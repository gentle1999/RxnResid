"""End-to-end low-rank pair surface with mean-centered route potentials."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import cast

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor

from rxnresid.data.change_graphs import CHANGE_ATOM_FEATURE_DIM, CHANGE_EDGE_FEATURE_DIM
from rxnresid.data.collate import RxnResidBatch
from rxnresid.data.dataset import TargetStatistics
from rxnresid.data.protocols import PyGBatchStub
from rxnresid.models.encoders import EncoderConfig, build_molecular_encoder
from rxnresid.models.heads import HeadConfig
from rxnresid.models.mapping.module import MappingMode, MappingModule
from rxnresid.utils.scatter import scatter_max, scatter_mean, scatter_min, scatter_sum


@dataclass(frozen=True)
class MeanPairSurfaceConfig:
    """Role-aware graph surface used for the substrate-group mean barrier.

    ``component_roles`` follows the component order in the disconnected mapped
    reactant graph.  The default keeps the historical ene/diene RxnResid contract;
    additional roles use the generalized all-component surface.
    """

    encoder: EncoderConfig = field(default_factory=EncoderConfig)
    rank: int = 48
    graph_contribution: bool = True
    identity_factors: bool = True
    component_hash_buckets: int = 4096
    component_roles: tuple[str, ...] = ("ene", "diene")


@dataclass(frozen=True)
class MeanCenteredRouteConfig:
    """Mapped path topology used to rank routes within a substrate pair."""

    path_encoder: EncoderConfig = field(
        default_factory=lambda: EncoderConfig(type="gine_gatv2", pooling="sum")
    )
    product_encoder: EncoderConfig = field(default_factory=EncoderConfig)
    route_count: int = 8
    route_embedding_dim: int = 8
    share_path_delta_encoder: bool = False
    product_group_correction: bool = True
    mapping_mode: MappingMode = "latent_diff"
    mapping_hidden_dim: int = 64
    mapping_dropout: float = 0.05
    product_group_head: HeadConfig = field(default_factory=lambda: HeadConfig((96,)))
    route_head: HeadConfig = field(default_factory=lambda: HeadConfig((96,)))


@dataclass(frozen=True)
class RxnResidConfig:
    """Explicit configuration for the graph analogue of the pair reranker."""

    hidden_dim: int = 192
    pair: MeanPairSurfaceConfig = field(default_factory=MeanPairSurfaceConfig)
    route: MeanCenteredRouteConfig = field(default_factory=MeanCenteredRouteConfig)


@dataclass(frozen=True)
class MeanPairSurfaceOutput:
    standardized: Tensor
    node: Tensor
    component_states: Tensor
    component_tokens: Tensor
    component_mask: Tensor
    component_factors: Tensor
    component_bias: Tensor

    @property
    def ene_state(self) -> Tensor:
        return self.component_states[:, 0]

    @property
    def diene_state(self) -> Tensor:
        return self.component_states[:, 1]

    @property
    def ene_factor(self) -> Tensor:
        return self.component_factors[:, 0]

    @property
    def diene_factor(self) -> Tensor:
        return self.component_factors[:, 1]


@dataclass(frozen=True)
class MeanCenteredRouteOutput:
    standardized: Tensor
    potential: Tensor
    group_correction: Tensor
    product_factor: Tensor
    path: Tensor
    path_node: Tensor
    delta: Tensor
    mapped: Tensor


@dataclass(frozen=True)
class RxnResidOutput:
    """Stable baseline-residual contract consumed by training and inference."""

    prediction: Tensor
    prediction_standardized: Tensor
    baseline: Tensor
    baseline_standardized: Tensor
    residual: Tensor
    residual_standardized: Tensor
    target_mean: Tensor
    target_scale: Tensor
    baseline_mean: Tensor
    baseline_scale: Tensor
    residual_mean: Tensor
    residual_scale: Tensor

    @property
    def raw_residual(self) -> Tensor:
        return self.residual


@dataclass(frozen=True)
class RxnResidModelOutput(RxnResidOutput):
    """RxnResid prediction contract plus inspectable intermediate representations."""

    pair_surface_standardized: Tensor
    neural_baseline_standardized: Tensor
    product_group_correction: Tensor
    route_potential: Tensor
    component_states: Tensor
    component_tokens: Tensor
    component_mask: Tensor
    component_factors: Tensor
    path_embedding: Tensor
    delta_embedding: Tensor
    product_factor: Tensor
    mapping_embedding: Tensor

    @property
    def ene_state(self) -> Tensor:
        return self.component_states[:, 0]

    @property
    def diene_state(self) -> Tensor:
        return self.component_states[:, 1]

    @property
    def ene_factor(self) -> Tensor:
        return self.component_factors[:, 0]

    @property
    def diene_factor(self) -> Tensor:
        return self.component_factors[:, 1]


def _normalized_projection(
    input_dim: int,
    output_dim: int,
    hidden_dim: int,
    dropout: float,
) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim),
        nn.LayerNorm(hidden_dim),
        nn.SiLU(),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim, output_dim),
    )


def _normalized_regression_head(
    input_dim: int,
    hidden_dims: tuple[int, ...],
    dropout: float,
) -> nn.Sequential:
    layers: list[nn.Module] = []
    current_dim = input_dim
    for hidden_dim in hidden_dims:
        layers.extend(
            (
                nn.Linear(current_dim, hidden_dim),
                nn.LayerNorm(hidden_dim),
                nn.SiLU(),
                nn.Dropout(dropout),
            )
        )
        current_dim = hidden_dim
    layers.append(nn.Linear(current_dim, 1))
    return nn.Sequential(*layers)


def _component_states(
    node: Tensor,
    graph: PyGBatchStub,
    *,
    expected_components: int,
) -> tuple[Tensor, Tensor, Tensor]:
    if expected_components < 1:
        raise ValueError("expected_components must be positive")
    component_id = graph.component_id.to(torch.long)
    if component_id.numel() == 0:
        raise ValueError("A substrate graph must contain at least one component atom")
    component_key = graph.batch * expected_components + component_id
    component_count = graph.num_graphs * expected_components
    states = scatter_mean(node, component_key, dim_size=component_count)
    tokens = scatter_mean(
        graph.component_token_id.to(node.dtype),
        component_key,
        dim_size=component_count,
    ).to(torch.long)
    counts = scatter_sum(
        torch.ones_like(component_id, dtype=node.dtype),
        component_key,
        dim_size=component_count,
    )
    return (
        states.reshape(graph.num_graphs, expected_components, -1),
        tokens.reshape(graph.num_graphs, expected_components),
        counts.reshape(graph.num_graphs, expected_components) > 0,
    )


def _indexed_component_states(
    node: Tensor,
    graph: PyGBatchStub,
    group_component_index: Tensor,
    *,
    expected_components: int,
) -> tuple[Tensor, Tensor, Tensor]:
    """Gather deduplicated molecular states into ordered group role slots."""
    if group_component_index.ndim != 2:
        raise ValueError("group_component_index must be a rank-two tensor")
    if group_component_index.shape[1] > expected_components:
        raise ValueError(
            "A substrate group contains more components than configured component roles"
        )
    if group_component_index.shape[1] < expected_components:
        group_component_index = F.pad(
            group_component_index,
            (0, expected_components - group_component_index.shape[1]),
            value=-1,
        )
    mask = group_component_index >= 0
    if torch.any(group_component_index[mask] >= graph.num_graphs):
        raise ValueError("group_component_index references a missing component graph")
    safe_index = group_component_index.clamp_min(0)
    component_states = scatter_mean(
        node,
        graph.batch,
        dim_size=graph.num_graphs,
    )
    component_tokens = scatter_mean(
        graph.component_token_id.to(node.dtype),
        graph.batch,
        dim_size=graph.num_graphs,
    ).to(torch.long)
    return (
        component_states[safe_index] * mask.unsqueeze(-1),
        component_tokens[safe_index] * mask,
        mask,
    )


def _masked_component_summaries(
    values: Tensor,
    mask: Tensor,
) -> tuple[Tensor, Tensor, Tensor, Tensor]:
    """Return sum, mean, minimum, and maximum over the valid role slots."""
    valid = mask.unsqueeze(-1)
    count = mask.sum(dim=1, keepdim=True).clamp_min(1).to(values.dtype)
    masked = values.masked_fill(~valid, 0.0)
    summed = masked.sum(dim=1)
    mean = summed / count
    minimum = values.masked_fill(~valid, float("inf")).min(dim=1).values
    maximum = values.masked_fill(~valid, float("-inf")).max(dim=1).values
    return summed, mean, minimum, maximum


class MeanPairSurface(nn.Module):
    """Learn additive and pairwise low-rank effects from component graphs."""

    def __init__(self, config: MeanPairSurfaceConfig, hidden_dim: int) -> None:
        super().__init__()
        if config.rank < 1:
            raise ValueError("pair rank must be positive")
        if not config.graph_contribution and not config.identity_factors:
            raise ValueError("The pair surface needs graph or identity factors")
        if not config.component_roles:
            raise ValueError("component_roles must contain at least one role")
        if len(set(config.component_roles)) != len(config.component_roles):
            raise ValueError("component_roles must be unique")
        self.config = config
        self.component_count = len(config.component_roles)
        self.encoder = build_molecular_encoder(config.encoder, hidden_dim)
        dropout = config.encoder.dropout
        self._legacy_pair = self.component_count == 2
        if self._legacy_pair:
            # Keep these names and module shapes for loading existing RxnResid runs.
            self.ene_factor = _normalized_projection(hidden_dim, config.rank, hidden_dim, dropout)
            self.diene_factor = _normalized_projection(hidden_dim, config.rank, hidden_dim, dropout)
            self.ene_bias = nn.Linear(hidden_dim, 1)
            self.diene_bias = nn.Linear(hidden_dim, 1)
        else:
            self.component_factor = nn.ModuleList(
                _normalized_projection(hidden_dim, config.rank, hidden_dim, dropout)
                for _ in config.component_roles
            )
            self.component_bias = nn.ModuleList(
                nn.Linear(hidden_dim, 1) for _ in config.component_roles
            )
        self.intercept = nn.Parameter(torch.zeros((), dtype=torch.float32))
        if self._legacy_pair:
            self.ene_identity_factor = (
                nn.Embedding(config.component_hash_buckets, config.rank)
                if config.identity_factors
                else None
            )
            self.diene_identity_factor = (
                nn.Embedding(config.component_hash_buckets, config.rank)
                if config.identity_factors
                else None
            )
            self.ene_identity_bias = (
                nn.Embedding(config.component_hash_buckets, 1) if config.identity_factors else None
            )
            self.diene_identity_bias = (
                nn.Embedding(config.component_hash_buckets, 1) if config.identity_factors else None
            )
        else:
            self.component_identity_factor = (
                nn.ModuleList(
                    nn.Embedding(config.component_hash_buckets, config.rank)
                    for _ in config.component_roles
                )
                if config.identity_factors
                else None
            )
            self.component_identity_bias = (
                nn.ModuleList(
                    nn.Embedding(config.component_hash_buckets, 1) for _ in config.component_roles
                )
                if config.identity_factors
                else None
            )
        if self._legacy_pair:
            for embedding in (self.ene_identity_factor, self.diene_identity_factor):
                if embedding is not None:
                    nn.init.normal_(embedding.weight, mean=0.0, std=0.02)
            for bias in (self.ene_identity_bias, self.diene_identity_bias):
                if bias is not None:
                    nn.init.zeros_(bias.weight)
        else:
            if self.component_identity_factor is not None:
                for component_embedding in self.component_identity_factor:
                    nn.init.normal_(
                        cast(nn.Embedding, component_embedding).weight,
                        mean=0.0,
                        std=0.02,
                    )
            if self.component_identity_bias is not None:
                for component_bias_embedding in self.component_identity_bias:
                    nn.init.zeros_(cast(nn.Embedding, component_bias_embedding).weight)

    def forward(
        self,
        graph: PyGBatchStub,
        group_component_index: Tensor | None = None,
    ) -> MeanPairSurfaceOutput:
        encoded = self.encoder(graph)
        if group_component_index is None:
            states, tokens, mask = _component_states(
                encoded.node,
                graph,
                expected_components=self.component_count,
            )
        else:
            states, tokens, mask = _indexed_component_states(
                encoded.node,
                graph,
                group_component_index,
                expected_components=self.component_count,
            )
        if self._legacy_pair:
            ene_state, diene_state = states.unbind(dim=1)
            ene_factor = self.ene_factor(ene_state)
            diene_factor = self.diene_factor(diene_state)
            component_factors = torch.stack((ene_factor, diene_factor), dim=1)
            ene_bias = self.ene_bias(ene_state).squeeze(-1)
            diene_bias = self.diene_bias(diene_state).squeeze(-1)
            component_bias = torch.stack((ene_bias, diene_bias), dim=1)
        else:
            component_factors = torch.stack(
                [
                    projector(states[:, index])
                    for index, projector in enumerate(self.component_factor)
                ],
                dim=1,
            )
            component_bias = torch.stack(
                [
                    projector(states[:, index]).squeeze(-1)
                    for index, projector in enumerate(self.component_bias)
                ],
                dim=1,
            )
        if not self.config.graph_contribution:
            component_factors = torch.zeros_like(component_factors)
            component_bias = torch.zeros_like(component_bias)
        if self._legacy_pair:
            if self.ene_identity_factor is not None:
                if (
                    self.diene_identity_factor is None
                    or self.ene_identity_bias is None
                    or self.diene_identity_bias is None
                ):
                    raise RuntimeError("Ene/diene identity adapters must be configured together")
                component_factors = component_factors + torch.stack(
                    (
                        self.ene_identity_factor(tokens[:, 0]),
                        self.diene_identity_factor(tokens[:, 1]),
                    ),
                    dim=1,
                )
                component_bias = component_bias + torch.stack(
                    (
                        self.ene_identity_bias(tokens[:, 0]).squeeze(-1),
                        self.diene_identity_bias(tokens[:, 1]).squeeze(-1),
                    ),
                    dim=1,
                )
        elif self.component_identity_factor is not None:
            if self.component_identity_bias is None:
                raise RuntimeError("Component identity factor and bias adapters must be paired")
            component_factors = component_factors + torch.stack(
                [
                    embedding(tokens[:, index])
                    for index, embedding in enumerate(self.component_identity_factor)
                ],
                dim=1,
            )
            component_bias = component_bias + torch.stack(
                [
                    embedding(tokens[:, index]).squeeze(-1)
                    for index, embedding in enumerate(self.component_identity_bias)
                ],
                dim=1,
            )
        component_factors = component_factors * mask.unsqueeze(-1)
        component_bias = component_bias * mask
        pair_mask = torch.triu(mask.unsqueeze(2) & mask.unsqueeze(1), diagonal=1)
        pairwise = (component_factors.unsqueeze(2) * component_factors.unsqueeze(1)).sum(dim=-1)
        low_rank_interaction = (pairwise * pair_mask).sum(dim=(1, 2)) / math.sqrt(
            float(self.config.rank)
        )
        standardized = self.intercept + component_bias.sum(dim=1) + low_rank_interaction
        return MeanPairSurfaceOutput(
            standardized=standardized,
            node=encoded.node,
            component_states=states,
            component_tokens=tokens,
            component_mask=mask,
            component_factors=component_factors,
            component_bias=component_bias,
        )


class MeanCenteredRouteModel(nn.Module):
    """Predict path potentials and remove their substrate-group mean."""

    def __init__(
        self,
        config: MeanCenteredRouteConfig,
        *,
        hidden_dim: int,
        rank: int,
    ) -> None:
        super().__init__()
        if config.route_count < 1:
            raise ValueError("route_count must be positive")
        if config.route_embedding_dim < 1:
            raise ValueError("route_embedding_dim must be positive")
        self.config = config
        self.path_encoder = build_molecular_encoder(
            config.path_encoder,
            hidden_dim,
            atom_dim=CHANGE_ATOM_FEATURE_DIM,
            edge_dim=CHANGE_EDGE_FEATURE_DIM,
        )
        self.delta_encoder = (
            self.path_encoder
            if config.share_path_delta_encoder
            else build_molecular_encoder(
                config.path_encoder,
                hidden_dim,
                atom_dim=CHANGE_ATOM_FEATURE_DIM,
                edge_dim=CHANGE_EDGE_FEATURE_DIM,
            )
        )
        self.product_encoder = build_molecular_encoder(config.product_encoder, hidden_dim)
        self.mapping = MappingModule(
            mode=config.mapping_mode,
            encoder_dim=hidden_dim,
            hidden_dim=config.mapping_hidden_dim,
            dropout=config.mapping_dropout,
        )
        dropout = config.path_encoder.dropout
        self.path_projector = _normalized_projection(hidden_dim, rank, hidden_dim, dropout)
        self.delta_projector = _normalized_projection(hidden_dim, rank, hidden_dim, dropout)
        self.product_projector = _normalized_projection(hidden_dim, rank, hidden_dim, dropout)
        self.mapping_projector = (
            _normalized_projection(config.mapping_hidden_dim, rank, hidden_dim, dropout)
            if config.mapping_mode != "none"
            else None
        )
        self.route_embedding = nn.Embedding(config.route_count, config.route_embedding_dim)
        route_width = rank * 8 + config.route_embedding_dim
        self.route_head = _normalized_regression_head(
            route_width,
            config.route_head.hidden_dims,
            dropout,
        )
        self.product_group_head = (
            _normalized_regression_head(
                rank * 4,
                config.product_group_head.hidden_dims,
                config.product_encoder.dropout,
            )
            if config.product_group_correction
            else None
        )

    def forward(
        self,
        batch: RxnResidBatch,
        pair: MeanPairSurfaceOutput,
        substrate_node: Tensor,
    ) -> MeanCenteredRouteOutput:
        path_encoded = self.path_encoder(batch.path_cgrs)
        delta_encoded = self.delta_encoder(batch.path_delta_cgrs)
        product_encoded = self.product_encoder(batch.products)
        mapping_output = self.mapping(
            batch.mapping,
            substrate_node,
            product_encoded.node,
            batch.num_paths,
        )
        path_factor = self.path_projector(path_encoded.graph)
        delta_factor = self.delta_projector(delta_encoded.graph)
        product_factor = self.product_projector(product_encoded.graph)
        mapped = (
            mapping_output.embedding
            if mapping_output.embedding is not None
            else product_factor.new_zeros((batch.num_paths, 0))
        )
        mapped_factor = (
            self.mapping_projector(mapped)
            if self.mapping_projector is not None
            else product_factor.new_zeros(product_factor.shape)
        )
        component_factors = pair.component_factors[batch.path_to_group]
        component_mask = pair.component_mask[batch.path_to_group]
        component_sum, component_mean, component_min, component_max = _masked_component_summaries(
            component_factors,
            component_mask,
        )
        component_range = component_max - component_min
        if component_factors.shape[1] == 2:
            ene_factor, diene_factor = component_factors.unbind(dim=1)
            pair_context = ene_factor + diene_factor
            route_components = (
                ene_factor,
                diene_factor,
                product_factor,
                torch.abs(ene_factor - diene_factor),
                product_factor * pair_context,
            )
        else:
            route_components = (
                component_sum,
                component_mean,
                component_range,
                product_factor,
                product_factor * component_mean,
            )
        route_input = torch.cat(
            (
                *route_components,
                path_factor,
                delta_factor,
                mapped_factor,
                self.route_embedding(batch.route_ids),
            ),
            dim=-1,
        )
        potential = F.softplus(self.route_head(route_input).squeeze(-1))
        route_center = scatter_mean(
            potential,
            batch.path_to_group,
            dim_size=batch.num_groups,
        )
        standardized = potential - route_center[batch.path_to_group]
        if self.product_group_head is None:
            group_correction = pair.standardized.new_zeros((batch.num_groups,))
        else:
            product_mean = scatter_mean(
                product_factor,
                batch.path_to_group,
                dim_size=batch.num_groups,
            )
            product_min = scatter_min(
                product_factor,
                batch.path_to_group,
                dim_size=batch.num_groups,
            )
            product_max = scatter_max(
                product_factor,
                batch.path_to_group,
                dim_size=batch.num_groups,
            )
            substrate_context = pair.component_factors.sum(dim=1)
            group_correction = self.product_group_head(
                torch.cat(
                    (product_mean, product_min, product_max, substrate_context),
                    dim=-1,
                )
            ).squeeze(-1)
        return MeanCenteredRouteOutput(
            standardized=standardized,
            potential=potential,
            group_correction=group_correction,
            product_factor=product_factor,
            path=path_encoded.graph,
            path_node=path_encoded.node,
            delta=delta_encoded.graph,
            mapped=mapped,
        )


class RxnResidModel(nn.Module):
    """Low-rank pair mean plus a learned, mean-centered route correction."""

    target_mean: Tensor
    target_scale: Tensor
    baseline_mean: Tensor
    baseline_scale: Tensor
    residual_mean: Tensor
    residual_scale: Tensor

    def __init__(self, config: RxnResidConfig | None = None) -> None:
        super().__init__()
        self.config = config or RxnResidConfig()
        self.baseline_predictor = MeanPairSurface(self.config.pair, self.config.hidden_dim)
        self.route_predictor = MeanCenteredRouteModel(
            self.config.route,
            hidden_dim=self.config.hidden_dim,
            rank=self.config.pair.rank,
        )
        self.register_buffer("target_mean", torch.tensor(0.0))
        self.register_buffer("target_scale", torch.tensor(1.0))
        self.register_buffer("baseline_mean", torch.tensor(0.0))
        self.register_buffer("baseline_scale", torch.tensor(1.0))
        self.register_buffer("residual_mean", torch.tensor(0.0))
        self.register_buffer("residual_scale", torch.tensor(1.0))

    @torch.no_grad()
    def set_target_statistics(self, statistics: TargetStatistics) -> None:
        device = self.target_mean.device
        self.target_mean = torch.tensor(statistics.target_mean, device=device)
        self.target_scale = torch.tensor(max(statistics.target_std, 1e-6), device=device)
        self.baseline_mean = torch.tensor(statistics.baseline_mean, device=device)
        self.baseline_scale = torch.tensor(max(statistics.baseline_std, 1e-6), device=device)
        self.residual_mean = torch.tensor(statistics.residual_mean, device=device)
        self.residual_scale = torch.tensor(max(statistics.residual_std, 1e-6), device=device)

    @torch.no_grad()
    def set_residual_statistics(self, statistics: TargetStatistics) -> None:
        device = self.target_mean.device
        self.residual_mean = torch.tensor(statistics.residual_mean, device=device)
        self.residual_scale = torch.tensor(max(statistics.residual_std, 1e-6), device=device)

    def set_training_phase(self, phase: str) -> None:
        if phase not in {"baseline", "residual", "joint"}:
            raise ValueError(f"Unknown training phase: {phase}")
        for parameter in self.baseline_predictor.parameters():
            parameter.requires_grad = phase in {"baseline", "joint"}
        for name, parameter in self.route_predictor.named_parameters():
            belongs_to_baseline = name.startswith(("product_encoder.", "product_projector."))
            if phase == "joint":
                parameter.requires_grad = True
            elif phase == "baseline":
                parameter.requires_grad = belongs_to_baseline or name.startswith(
                    "product_group_head."
                )
            else:
                parameter.requires_grad = not name.startswith("product_group_head.")

    def forward(self, batch: RxnResidBatch) -> RxnResidModelOutput:
        pair_output = self.baseline_predictor(
            batch.unique_components,
            batch.group_component_index,
        )
        route_output = self.route_predictor(
            batch,
            pair_output,
            pair_output.node,
        )
        neural_baseline_standardized = pair_output.standardized + route_output.group_correction
        baseline_standardized = neural_baseline_standardized[batch.path_to_group]
        baseline = self.baseline_mean + self.baseline_scale * baseline_standardized
        residual_standardized = route_output.standardized
        residual = self.residual_mean + self.residual_scale * residual_standardized
        prediction = baseline + residual
        prediction_standardized = (prediction - self.target_mean) / self.target_scale
        return RxnResidModelOutput(
            prediction=prediction,
            prediction_standardized=prediction_standardized,
            baseline=baseline,
            baseline_standardized=baseline_standardized,
            residual=residual,
            residual_standardized=residual_standardized,
            target_mean=self.target_mean,
            target_scale=self.target_scale,
            baseline_mean=self.baseline_mean,
            baseline_scale=self.baseline_scale,
            residual_mean=self.residual_mean,
            residual_scale=self.residual_scale,
            pair_surface_standardized=pair_output.standardized,
            neural_baseline_standardized=neural_baseline_standardized,
            product_group_correction=route_output.group_correction,
            route_potential=route_output.potential,
            component_states=pair_output.component_states,
            component_tokens=pair_output.component_tokens,
            component_mask=pair_output.component_mask,
            component_factors=pair_output.component_factors,
            path_embedding=route_output.path,
            delta_embedding=route_output.delta,
            product_factor=route_output.product_factor,
            mapping_embedding=route_output.mapped,
        )


__all__ = [
    "MeanCenteredRouteConfig",
    "MeanCenteredRouteModel",
    "MeanCenteredRouteOutput",
    "MeanPairSurface",
    "MeanPairSurfaceConfig",
    "MeanPairSurfaceOutput",
    "RxnResidConfig",
    "RxnResidModel",
    "RxnResidOutput",
    "RxnResidModelOutput",
]
