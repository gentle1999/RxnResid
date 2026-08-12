from dataclasses import is_dataclass

import pytest

from rxnresid.config import ProjectConfig, ResolvedRunConfig, load_project_config
from rxnresid.data.collate import collate_reaction_groups
from rxnresid.models.build import build_model
from rxnresid.models.rxnresid import RxnResidModel
from tests.helpers import sample_of_size


CONFIG = "configs/rxnresid.yaml"


def test_rxnresid_configuration_and_data_protocol_use_explicit_dataclasses() -> None:
    config = load_project_config(CONFIG)
    batch = collate_reaction_groups([sample_of_size(2)])

    for value in (
        config,
        config.data,
        config.model,
        config.model.substrate_encoder,
        config.model.path_encoder,
        config.model.product_encoder,
        config.model.mapping,
        config.loss,
        config.training,
        config.training.scheduler,
        config.training.early_stopping,
        batch,
        batch.mapping,
    ):
        assert is_dataclass(value)
    assert config.model.variant == "rxnresid"
    assert not config.model.share_path_delta_encoder
    assert config.data.baseline_reduction == "mean"
    assert config.data.cache_enabled
    assert config.data.cache_dir == ".cache/rxnresid"
    assert config.training.group_complete_batches
    assert not config.training.split_batches
    assert config.training.batch_size_paths == 512
    assert config.training.mixed_precision == "no"
    assert config.training.fused_optimizer
    assert batch.baseline_targets.shape == (2,)
    assert batch.residual_targets.shape == (2,)


def test_rxnresid_project_and_resolved_configuration_round_trip() -> None:
    project = load_project_config(CONFIG)
    assert ProjectConfig.from_mapping(project.to_dict()) == project
    resolved = ResolvedRunConfig.from_mapping(
        {
            "model_variant": "rxnresid",
            "mapping_mode": "latent_diff",
            "hidden_dim": 192,
            "group_encoder": "gine",
            "path_encoder": "gine_gatv2",
            "substrate_encoder": "gine",
            "product_encoder": "gine",
            "epochs": 1000,
            "batch_size_paths": 512,
            "gradient_accumulation_steps": 1,
            "split_batches": False,
            "mixed_precision": "no",
            "seed": 42,
            "huber_beta": 1.0,
            "split_groups": {"train": 1280, "valid": 160, "test": 160},
            "split_paths": {"train": 2374, "valid": 297, "test": 297},
            "distributed": {"world_size": 2, "backend": "MULTI_GPU"},
            "group_complete_batches": True,
        }
    )
    assert ResolvedRunConfig.from_mapping(resolved.to_dict()) == resolved


def test_build_model_only_exposes_rxnresid_but_keeps_encoder_overrides() -> None:
    config = load_project_config(CONFIG)
    model, resolved = build_model(config.model)
    assert isinstance(model, RxnResidModel)
    assert resolved.variant == "rxnresid"
    assert resolved.group_encoder == "gine"
    assert resolved.path_encoder == "gine_gatv2"
    assert resolved.substrate_encoder == "gine"
    assert resolved.product_encoder == "gine"

    _, overridden = build_model(config.model, encoder_override="graphsage")
    assert overridden.path_encoder == "graphsage"
    assert overridden.substrate_encoder == "graphsage"
    assert overridden.product_encoder == "graphsage"
    with pytest.raises(ValueError, match="Only the production"):
        build_model(config.model, variant_override="rxnresid_v8")

    shared = ProjectConfig.from_mapping({"model": {"share_path_delta_encoder": True}})
    shared_model, _ = build_model(shared.model)
    assert isinstance(shared_model, RxnResidModel)
    assert shared_model.route_predictor.path_encoder is shared_model.route_predictor.delta_encoder


def test_historical_variant_tag_is_normalized() -> None:
    project = ProjectConfig.from_mapping({"model": {"variant": "rxnresid_v5"}})
    assert project.model.variant == "rxnresid"

    resolved = ResolvedRunConfig.from_mapping(
        {
            "model_variant": "rxnresid_v5",
            "mapping_mode": "latent_diff",
            "hidden_dim": 192,
            "substrate_encoder": "gine",
            "product_encoder": "gine",
            "epochs": 1,
            "batch_size_paths": 1,
            "mixed_precision": "no",
            "seed": 42,
            "huber_beta": 0.1,
            "split_groups": {"train": 1, "valid": 1, "test": 1},
            "distributed": {"world_size": 1, "backend": "NO"},
        }
    )
    assert resolved.model_variant == "rxnresid"


def test_rxnresid_rejects_incompatible_data_and_batch_configuration() -> None:
    with pytest.raises(ValueError, match="baseline_reduction=mean"):
        ProjectConfig.from_mapping({"data": {"baseline_reduction": "minimum"}})
    with pytest.raises(ValueError, match="cache_dir"):
        ProjectConfig.from_mapping({"data": {"cache_dir": ""}})
    with pytest.raises(ValueError, match="group_complete_batches=true"):
        ProjectConfig.from_mapping({"training": {"group_complete_batches": False}})
    with pytest.raises(ValueError, match="split_batches=false"):
        ProjectConfig.from_mapping(
            {"training": {"group_complete_batches": True, "split_batches": True}}
        )
    with pytest.raises(ValueError, match="model.variant"):
        ProjectConfig.from_mapping({"model": {"variant": "rxnresid_v10"}})
