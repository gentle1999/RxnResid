import torch

from rxnresid.data.change_graphs import reaction_change_graphs
from rxnresid.data.reaction_parser import parse_mapped_reaction
from rxnresid.models.encoders import (
    EncoderConfig,
    GATv2Encoder,
    GPSEncoder,
    GraphSAGEEncoder,
    RelationGINEGATv2Encoder,
    available_encoders,
    build_molecular_encoder,
    register_encoder,
)
from rxnresid.models.encoders.relation_gine_gatv2 import covalent_edge_view


def test_builtin_encoder_registry_is_not_gine_only() -> None:
    assert {
        "dmpnn",
        "gatv2",
        "gcn",
        "genconv",
        "gin",
        "gine",
        "gps",
        "graphsage",
        "relation_gine_gatv2",
        "transformer",
    }.issubset(available_encoders())
    for encoder_type in (
        "dmpnn",
        "gatv2",
        "gcn",
        "genconv",
        "gin",
        "gine",
        "gps",
        "graphsage",
        "transformer",
    ):
        encoder = build_molecular_encoder(
            EncoderConfig(type=encoder_type, num_layers=1, dropout=0.0),
            hidden_dim=12,
        )
        assert encoder.output_dim == 12


def test_additional_pyg_encoders_run_on_change_graphs() -> None:
    graph = reaction_change_graphs([parse_mapped_reaction("[CH2:1]=[CH2:2]>>[CH3:1][CH3:2]")]).group
    graph.batch = torch.zeros(graph.num_nodes, dtype=torch.long)

    for encoder_type in ("gcn", "gin", "transformer", "genconv"):
        encoder = build_molecular_encoder(
            EncoderConfig(
                type=encoder_type,
                num_layers=2,
                dropout=0.0,
                pooling="sum",
                options={"heads": 3},
            ),
            hidden_dim=12,
            atom_dim=graph.x.shape[1],
            edge_dim=graph.edge_attr.shape[1],
        )
        output = encoder(graph)
        assert output.graph.shape == (1, 12)
        assert output.node.shape == (2, 12)


def test_gps_options_are_forwarded() -> None:
    encoder = build_molecular_encoder(
        EncoderConfig(
            type="gps",
            num_layers=2,
            dropout=0.0,
            pooling="sum",
            options={"heads": 3, "train_eps": False},
        ),
        hidden_dim=12,
    )
    assert isinstance(encoder, GPSEncoder)
    assert len(encoder.layers) == 2
    assert encoder.heads == 3


def test_gatv2_options_are_forwarded() -> None:
    encoder = build_molecular_encoder(
        EncoderConfig(
            type="gatv2",
            num_layers=2,
            dropout=0.0,
            pooling="sum",
            options={"heads": 2, "share_weights": True, "residual": False},
        ),
        hidden_dim=12,
    )
    assert isinstance(encoder, GATv2Encoder)
    assert len(encoder.convs) == 2
    assert not encoder.residual


def test_project_specific_encoder_can_be_registered() -> None:
    def builder(
        config: EncoderConfig, hidden_dim: int, atom_dim: int, edge_dim: int
    ) -> GraphSAGEEncoder:
        return GraphSAGEEncoder(
            hidden_dim=hidden_dim,
            num_layers=config.num_layers,
            dropout=config.dropout,
            pooling=config.pooling,
            atom_dim=atom_dim,
        )

    register_encoder("test_custom", builder, replace=True)
    encoder = build_molecular_encoder(
        EncoderConfig(type="test_custom", num_layers=1, dropout=0.0),
        hidden_dim=10,
        atom_dim=7,
        edge_dim=11,
    )
    assert isinstance(encoder, GraphSAGEEncoder)


def test_relation_encoder_separates_forming_edges_from_covalent_edges() -> None:
    graph = reaction_change_graphs([parse_mapped_reaction("[CH3:1].[CH3:2]>>[CH3:1][CH3:2]")]).group

    covalent_index, covalent_attr = covalent_edge_view(graph.edge_index, graph.edge_attr)

    assert graph.edge_index.shape[1] == 2
    assert covalent_index.shape == (2, 0)
    assert covalent_attr.shape[0] == 0


def test_relation_encoder_runs_on_change_graphs() -> None:
    graph = reaction_change_graphs([parse_mapped_reaction("[CH2:1]=[CH2:2]>>[CH3:1][CH3:2]")]).group
    graph.batch = torch.zeros(graph.num_nodes, dtype=torch.long)
    encoder = build_molecular_encoder(
        EncoderConfig(
            type="relation_gine_gatv2",
            num_layers=3,
            dropout=0.0,
            pooling="sum",
            options={"heads": 2, "gine_layers": 1},
        ),
        hidden_dim=12,
        atom_dim=graph.x.shape[1],
        edge_dim=graph.edge_attr.shape[1],
    )

    output = encoder(graph)

    assert isinstance(encoder, RelationGINEGATv2Encoder)
    assert output.graph.shape == (1, 12)
    assert output.node.shape == (2, 12)
