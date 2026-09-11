"""Build the production RxnResid model from the project configuration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

import torch.nn as nn

from rxnresid.config import ModelConfig
from rxnresid.models.mapping.module import MappingMode
from rxnresid.models.rxnresid import (
    MeanCenteredRouteConfig,
    MeanPairSurfaceConfig,
    RxnResidConfig,
    RxnResidModel,
)


@dataclass(frozen=True)
class ResolvedModel:
    variant: str
    mapping_mode: str
    hidden_dim: int
    group_encoder: str
    path_encoder: str
    substrate_encoder: str
    product_encoder: str


def build_model(
    model_config: ModelConfig,
    *,
    variant_override: str | None = None,
    mapping_mode_override: str | None = None,
    encoder_override: str | None = None,
    group_encoder_override: str | None = None,
    path_encoder_override: str | None = None,
    substrate_encoder_override: str | None = None,
    product_encoder_override: str | None = None,
) -> tuple[nn.Module, ResolvedModel]:
    """Build RxnResid while accepting the historical checkpoint variant tag."""
    variant = variant_override or model_config.variant
    if variant == "rxnresid_v5":
        variant = "rxnresid"
    if variant != "rxnresid":
        raise ValueError("Only the production 'rxnresid' variant is supported")

    path_encoder = model_config.path_encoder
    substrate_encoder = model_config.substrate_encoder
    product_encoder = model_config.product_encoder
    if encoder_override is not None:
        path_encoder = replace(path_encoder, type=encoder_override)
        substrate_encoder = replace(substrate_encoder, type=encoder_override)
        product_encoder = replace(product_encoder, type=encoder_override)
    if path_encoder_override is not None:
        path_encoder = replace(path_encoder, type=path_encoder_override)
    if substrate_encoder_override is not None:
        substrate_encoder = replace(substrate_encoder, type=substrate_encoder_override)
    if product_encoder_override is not None:
        product_encoder = replace(product_encoder, type=product_encoder_override)

    mapping_mode_value = mapping_mode_override or model_config.mapping.mode
    if mapping_mode_value not in {"none", "edit_features", "latent_diff", "combined"}:
        raise ValueError(f"Unknown mapping mode: {mapping_mode_value}")
    mapping_mode = cast(MappingMode, mapping_mode_value)

    model = RxnResidModel(
        RxnResidConfig(
            hidden_dim=model_config.hidden_dim,
            pair=MeanPairSurfaceConfig(
                encoder=substrate_encoder,
                rank=model_config.baseline_factor_rank,
                graph_contribution=model_config.baseline_graph_contribution,
                identity_factors=model_config.baseline_identity_factors,
                component_hash_buckets=model_config.component_hash_buckets,
                component_roles=model_config.component_roles,
            ),
            route=MeanCenteredRouteConfig(
                path_encoder=path_encoder,
                product_encoder=product_encoder,
                route_count=model_config.route_id_count,
                route_embedding_dim=model_config.route_embedding_dim,
                share_path_delta_encoder=model_config.share_path_delta_encoder,
                product_group_correction=model_config.baseline_product_group_correction,
                mapping_mode=mapping_mode,
                mapping_hidden_dim=model_config.mapping.hidden_dim,
                mapping_dropout=model_config.mapping.dropout,
                product_group_head=model_config.baseline_head,
                route_head=model_config.residual_head,
                evidence_head=model_config.evidence_head,
            ),
        )
    )
    group_encoder = group_encoder_override or encoder_override or substrate_encoder.type
    return model, ResolvedModel(
        variant="rxnresid",
        mapping_mode=mapping_mode,
        hidden_dim=model_config.hidden_dim,
        group_encoder=group_encoder,
        path_encoder=path_encoder.type,
        substrate_encoder=substrate_encoder.type,
        product_encoder=product_encoder.type,
    )


__all__ = ["ResolvedModel", "build_model"]
