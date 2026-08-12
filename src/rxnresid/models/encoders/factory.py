"""Registry and factory for built-in and project-specific encoder backends."""

from __future__ import annotations

from collections.abc import Callable

from rxnresid.data.featurizer import ATOM_FEATURE_DIM, EDGE_FEATURE_DIM
from rxnresid.models.encoders.base import EncoderConfig, MolecularEncoder
from rxnresid.models.encoders.dmpnn import DMPNNEncoder
from rxnresid.models.encoders.gatv2 import GATv2Encoder
from rxnresid.models.encoders.gine import GINEEncoder
from rxnresid.models.encoders.gine_gatv2 import GINEGATv2Encoder
from rxnresid.models.encoders.gps import GPSEncoder
from rxnresid.models.encoders.graphsage import GraphSAGEEncoder
from rxnresid.models.encoders.pyg_layers import (
    GCNEncoder,
    GENEncoder,
    GINEncoder,
    TransformerEncoder,
)
from rxnresid.models.encoders.relation_gine_gatv2 import RelationGINEGATv2Encoder


EncoderBuilder = Callable[[EncoderConfig, int, int, int], MolecularEncoder]
_ENCODER_BUILDERS: dict[str, EncoderBuilder] = {}


def register_encoder(name: str, builder: EncoderBuilder, *, replace: bool = False) -> None:
    """Register a backend without changing RxnResid model code."""
    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("encoder name cannot be empty")
    if normalized in _ENCODER_BUILDERS and not replace:
        raise ValueError(f"Encoder is already registered: {normalized}")
    _ENCODER_BUILDERS[normalized] = builder


def available_encoders() -> tuple[str, ...]:
    return tuple(sorted(_ENCODER_BUILDERS))


def build_molecular_encoder(
    config: EncoderConfig,
    hidden_dim: int,
    *,
    atom_dim: int = ATOM_FEATURE_DIM,
    edge_dim: int = EDGE_FEATURE_DIM,
) -> MolecularEncoder:
    encoder_type = config.type.strip().lower()
    try:
        builder = _ENCODER_BUILDERS[encoder_type]
    except KeyError as exc:
        choices = ", ".join(available_encoders())
        raise ValueError(f"Unknown encoder type {config.type!r}; available: {choices}") from exc
    encoder = builder(config, hidden_dim, atom_dim, edge_dim)
    if encoder.output_dim != hidden_dim:
        raise ValueError(
            f"Encoder {encoder_type!r} outputs {encoder.output_dim}, expected {hidden_dim}"
        )
    return encoder


def _build_gine(
    config: EncoderConfig, hidden_dim: int, atom_dim: int, edge_dim: int
) -> MolecularEncoder:
    return GINEEncoder(
        hidden_dim=hidden_dim,
        num_layers=config.num_layers,
        dropout=config.dropout,
        pooling=config.pooling,
        train_eps=bool(config.options.get("train_eps", True)),
        residual=bool(config.options.get("residual", False)),
        atom_dim=atom_dim,
        edge_dim=edge_dim,
    )


def _build_dmpnn(
    config: EncoderConfig, hidden_dim: int, atom_dim: int, edge_dim: int
) -> MolecularEncoder:
    return DMPNNEncoder(
        hidden_dim=hidden_dim,
        num_layers=config.num_layers,
        dropout=config.dropout,
        pooling=config.pooling,
        center_global_weight=float(config.options.get("center_global_weight", 0.1)),
        atom_dim=atom_dim,
        edge_dim=edge_dim,
    )


def _build_graphsage(
    config: EncoderConfig, hidden_dim: int, atom_dim: int, edge_dim: int
) -> MolecularEncoder:
    return GraphSAGEEncoder(
        hidden_dim=hidden_dim,
        num_layers=config.num_layers,
        dropout=config.dropout,
        pooling=config.pooling,
        aggregation=str(config.options.get("aggregation", "mean")),
        atom_dim=atom_dim,
    )


def _build_gps(
    config: EncoderConfig, hidden_dim: int, atom_dim: int, edge_dim: int
) -> MolecularEncoder:
    return GPSEncoder(
        hidden_dim=hidden_dim,
        num_layers=config.num_layers,
        dropout=config.dropout,
        pooling=config.pooling,
        heads=int(config.options.get("heads", 4)),
        train_eps=bool(config.options.get("train_eps", True)),
        atom_dim=atom_dim,
        edge_dim=edge_dim,
    )


def _build_gatv2(
    config: EncoderConfig, hidden_dim: int, atom_dim: int, edge_dim: int
) -> MolecularEncoder:
    return GATv2Encoder(
        hidden_dim=hidden_dim,
        num_layers=config.num_layers,
        dropout=config.dropout,
        pooling=config.pooling,
        heads=int(config.options.get("heads", 4)),
        share_weights=bool(config.options.get("share_weights", False)),
        residual=bool(config.options.get("residual", True)),
        atom_dim=atom_dim,
        edge_dim=edge_dim,
    )


def _build_gine_gatv2(
    config: EncoderConfig, hidden_dim: int, atom_dim: int, edge_dim: int
) -> MolecularEncoder:
    return GINEGATv2Encoder(
        hidden_dim=hidden_dim,
        num_layers=config.num_layers,
        gine_layers=int(config.options.get("gine_layers", max(1, config.num_layers // 2))),
        dropout=config.dropout,
        pooling=config.pooling,
        heads=int(config.options.get("heads", 4)),
        train_eps=bool(config.options.get("train_eps", True)),
        residual=bool(config.options.get("residual", True)),
        atom_dim=atom_dim,
        edge_dim=edge_dim,
    )


def _build_relation_gine_gatv2(
    config: EncoderConfig, hidden_dim: int, atom_dim: int, edge_dim: int
) -> MolecularEncoder:
    return RelationGINEGATv2Encoder(
        hidden_dim=hidden_dim,
        num_layers=config.num_layers,
        gine_layers=int(config.options.get("gine_layers", max(1, config.num_layers // 2))),
        dropout=config.dropout,
        pooling=config.pooling,
        heads=int(config.options.get("heads", 4)),
        train_eps=bool(config.options.get("train_eps", True)),
        residual=bool(config.options.get("residual", True)),
        atom_dim=atom_dim,
        edge_dim=edge_dim,
    )


def _build_gcn(
    config: EncoderConfig, hidden_dim: int, atom_dim: int, edge_dim: int
) -> MolecularEncoder:
    del edge_dim
    return GCNEncoder(
        hidden_dim=hidden_dim,
        num_layers=config.num_layers,
        dropout=config.dropout,
        pooling=config.pooling,
        improved=bool(config.options.get("improved", False)),
        normalize=bool(config.options.get("normalize", True)),
        residual=bool(config.options.get("residual", True)),
        atom_dim=atom_dim,
    )


def _build_gin(
    config: EncoderConfig, hidden_dim: int, atom_dim: int, edge_dim: int
) -> MolecularEncoder:
    del edge_dim
    return GINEncoder(
        hidden_dim=hidden_dim,
        num_layers=config.num_layers,
        dropout=config.dropout,
        pooling=config.pooling,
        train_eps=bool(config.options.get("train_eps", True)),
        residual=bool(config.options.get("residual", True)),
        atom_dim=atom_dim,
    )


def _build_transformer(
    config: EncoderConfig, hidden_dim: int, atom_dim: int, edge_dim: int
) -> MolecularEncoder:
    return TransformerEncoder(
        hidden_dim=hidden_dim,
        num_layers=config.num_layers,
        dropout=config.dropout,
        pooling=config.pooling,
        heads=int(config.options.get("heads", 4)),
        beta=bool(config.options.get("beta", True)),
        root_weight=bool(config.options.get("root_weight", True)),
        residual=bool(config.options.get("residual", True)),
        atom_dim=atom_dim,
        edge_dim=edge_dim,
    )


def _build_genconv(
    config: EncoderConfig, hidden_dim: int, atom_dim: int, edge_dim: int
) -> MolecularEncoder:
    return GENEncoder(
        hidden_dim=hidden_dim,
        num_layers=config.num_layers,
        dropout=config.dropout,
        pooling=config.pooling,
        aggregation=str(config.options.get("aggregation", "softmax")),
        learn_t=bool(config.options.get("learn_t", True)),
        message_norm=bool(config.options.get("message_norm", True)),
        learn_message_scale=bool(config.options.get("learn_message_scale", True)),
        residual=bool(config.options.get("residual", True)),
        atom_dim=atom_dim,
        edge_dim=edge_dim,
    )


register_encoder("dmpnn", _build_dmpnn)
register_encoder("gatv2", _build_gatv2)
register_encoder("gcn", _build_gcn)
register_encoder("genconv", _build_genconv)
register_encoder("gin", _build_gin)
register_encoder("gine", _build_gine)
register_encoder("gine_gatv2", _build_gine_gatv2)
register_encoder("gps", _build_gps)
register_encoder("graphsage", _build_graphsage)
register_encoder("relation_gine_gatv2", _build_relation_gine_gatv2)
register_encoder("transformer", _build_transformer)
