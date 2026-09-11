from dataclasses import is_dataclass

import pytest
import torch
from rdkit import Chem
from torch_geometric.data import Batch

from rxnresid.data.collate import collate_reaction_groups, collate_reaction_paths
from rxnresid.data.dataset import ReactionGroupDataset, TargetStatistics
from rxnresid.data.featurizer import molecules_to_graph
from rxnresid.models.encoders import EncoderConfig
from rxnresid.models.heads import HeadConfig
from rxnresid.models.rxnresid import (
    MeanCenteredRouteConfig,
    MeanPairSurface,
    MeanPairSurfaceConfig,
    RxnResidConfig,
    RxnResidModel,
    RxnResidModelOutput,
)
from tests.helpers import sample_of_size, tiny_rxnresid_model


def _batch():  # type: ignore[no-untyped-def]
    return collate_reaction_groups([sample_of_size(size) for size in (3, 2, 1)])


def test_rxnresid_decomposes_every_path_and_emits_evidential_uncertainty() -> None:
    torch.manual_seed(3)
    batch = _batch()
    model = tiny_rxnresid_model()
    output = model(batch)

    assert is_dataclass(output)
    assert isinstance(output, RxnResidModelOutput)
    assert output.prediction.shape == (batch.num_paths,)
    assert torch.equal(output.prediction, output.baseline + output.residual)
    assert output.mapping_embedding.shape == (batch.num_paths, 8)
    assert output.product_group_correction.shape == (batch.num_paths,)
    assert torch.all(output.evidence_nu > 0.0)
    assert torch.all(output.evidence_alpha > 1.0)
    assert torch.all(output.evidence_beta > 0.0)
    assert torch.all(output.aleatoric_variance > 0.0)
    assert torch.all(output.epistemic_variance > 0.0)
    assert torch.allclose(
        output.predictive_variance,
        output.aleatoric_variance + output.epistemic_variance,
    )


def test_rxnresid_route_and_pair_branches_receive_gradients() -> None:
    torch.manual_seed(4)
    batch = _batch()
    model = tiny_rxnresid_model()
    output = model(batch)
    weights = torch.arange(1, batch.num_paths + 1, dtype=torch.float32)
    (output.prediction * weights).sum().backward()

    assert model.baseline_predictor.encoder.input.weight.grad is not None  # type: ignore[attr-defined]
    assert model.route_predictor.path_encoder.input.weight.grad is not None  # type: ignore[attr-defined]
    assert model.route_predictor.delta_encoder.input.weight.grad is not None  # type: ignore[attr-defined]
    assert model.route_predictor.product_encoder.input.weight.grad is not None  # type: ignore[attr-defined]
    assert model.route_predictor.route_head[-1].weight.grad is not None
    assert model.route_predictor.mapping.latent.projection[0].weight.grad is not None


def test_rxnresid_can_share_path_and_delta_encoder_weights() -> None:
    encoder = EncoderConfig(type="gine", num_layers=1, dropout=0.0, pooling="sum")
    model = RxnResidModel(
        RxnResidConfig(
            hidden_dim=16,
            pair=MeanPairSurfaceConfig(encoder=encoder, rank=4),
            route=MeanCenteredRouteConfig(
                path_encoder=encoder,
                product_encoder=encoder,
                route_count=8,
                route_embedding_dim=4,
                share_path_delta_encoder=True,
                mapping_hidden_dim=8,
                mapping_dropout=0.0,
                product_group_head=HeadConfig((8,)),
                route_head=HeadConfig((8,)),
            ),
        )
    )

    assert model.route_predictor.path_encoder is model.route_predictor.delta_encoder
    output = model(_batch())
    output.prediction.sum().backward()
    assert model.route_predictor.path_encoder.input.weight.grad is not None  # type: ignore[attr-defined]


def test_rxnresid_target_scaling_preserves_physical_decomposition() -> None:
    batch = _batch()
    model = tiny_rxnresid_model()
    model.set_target_statistics(
        TargetStatistics(
            target_mean=25.0,
            target_std=5.0,
            baseline_mean=20.0,
            baseline_std=2.0,
            residual_mean=0.0,
            residual_std=1.5,
        )
    )
    output = model(batch)

    assert torch.allclose(
        output.baseline,
        20.0 + 2.0 * output.baseline_standardized,
    )
    assert torch.allclose(
        output.residual,
        1.5 * output.residual_standardized,
    )
    assert torch.allclose(
        output.prediction_standardized,
        (output.prediction - 25.0) / 5.0,
    )
    assert torch.equal(output.prediction, output.baseline + output.residual)


def test_rxnresid_single_reaction_output_is_independent_of_group_context() -> None:
    sample = sample_of_size(3)
    full_batch = collate_reaction_groups([sample])
    single_batch = collate_reaction_paths([sample.path_samples()[0]])
    model = tiny_rxnresid_model().eval()

    full = model(full_batch)
    single = model(single_batch)

    for name in (
        "prediction",
        "baseline",
        "residual",
        "aleatoric_variance",
        "epistemic_variance",
        "predictive_variance",
    ):
        assert torch.allclose(getattr(full, name)[0], getattr(single, name)[0], atol=1e-6)


def test_uncertainty_variances_are_reported_in_physical_target_units() -> None:
    batch = collate_reaction_groups([sample_of_size(1)])
    model = tiny_rxnresid_model()
    output_unit_scale = model(batch)
    model.set_target_statistics(
        TargetStatistics(
            target_mean=25.0,
            target_std=5.0,
            baseline_mean=20.0,
            baseline_std=2.0,
            residual_mean=0.0,
            residual_std=1.5,
        )
    )
    output_scaled = model(batch)

    assert torch.allclose(
        output_scaled.predictive_variance,
        25.0 * output_unit_scale.predictive_variance,
    )


def test_rxnresid_rejects_route_id_outside_configured_vocabulary() -> None:
    batch = _batch()
    batch.route_ids[-1] = 8
    with pytest.raises((ValueError, IndexError, RuntimeError)):
        tiny_rxnresid_model(route_count=8)(batch)


def test_rxnresid_training_phase_is_explicit() -> None:
    model = tiny_rxnresid_model()
    model.set_training_phase("residual")
    assert all(not parameter.requires_grad for parameter in model.baseline_predictor.parameters())
    assert any(parameter.requires_grad for parameter in model.route_predictor.parameters())
    model.set_training_phase("joint")
    assert all(parameter.requires_grad for parameter in model.parameters())
    with pytest.raises(ValueError, match="Unknown training phase"):
        model.set_training_phase("unknown")


def test_component_surface_supports_variable_component_counts() -> None:
    def molecule(smiles: str) -> Chem.Mol:
        parsed = Chem.MolFromSmiles(smiles)
        assert parsed is not None
        return parsed

    graph = Batch.from_data_list(
        [
            molecules_to_graph([molecule("C"), molecule("N")]),
            molecules_to_graph([molecule("C"), molecule("N"), molecule("O")]),
        ]
    )
    encoder = EncoderConfig(type="gine", num_layers=1, dropout=0.0, pooling="sum")
    surface = MeanPairSurface(
        MeanPairSurfaceConfig(
            encoder=encoder,
            rank=4,
            component_roles=("substrate", "partner", "catalyst"),
        ),
        hidden_dim=16,
    )
    output = surface(graph)

    assert output.component_states.shape == (2, 3, 16)
    assert output.component_factors.shape == (2, 3, 4)
    assert output.component_mask.tolist() == [[True, True, False], [True, True, True]]
    assert torch.isfinite(output.standardized).all()


def test_rxnresid_component_roles_flow_through_path_forward() -> None:
    rows = [
        {
            "path_id": "p0",
            "rxn_smiles": "[CH4:1].[NH3:2].[OH2:3]>>[CH4:1].[NH3:2].[OH2:3]",
            "G_T_activate": "1.0",
            "prod_id": "0",
        },
        {
            "path_id": "p1",
            "rxn_smiles": "[CH4:1].[NH3:2].[OH2:3]>>[CH4:1].[NH3:2].[OH2:3]",
            "G_T_activate": "2.0",
            "prod_id": "1",
        },
    ]
    dataset = ReactionGroupDataset(rows, route_id_column="prod_id")
    batch = collate_reaction_groups([dataset[0]])
    encoder = EncoderConfig(type="gine", num_layers=1, dropout=0.0, pooling="sum")
    model = RxnResidModel(
        RxnResidConfig(
            hidden_dim=16,
            pair=MeanPairSurfaceConfig(
                encoder=encoder,
                rank=4,
                component_roles=("substrate", "partner", "catalyst"),
            ),
            route=MeanCenteredRouteConfig(
                path_encoder=encoder,
                product_encoder=encoder,
                route_count=8,
                route_embedding_dim=4,
                mapping_hidden_dim=8,
                mapping_dropout=0.0,
                product_group_head=HeadConfig((8,)),
                route_head=HeadConfig((8,)),
            ),
        )
    )
    output = model(batch)

    assert output.component_factors.shape == (1, 3, 4)
    assert output.prediction.shape == (2,)
    assert torch.equal(output.prediction, output.baseline + output.residual)
