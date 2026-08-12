from dataclasses import fields, replace

import pytest

from rxnresid.config import EarlyStoppingConfig, SchedulerConfig, load_project_config
from scripts.run_cross_validation import (
    CrossValidationConfig,
    ExperimentSpec,
    _module_directory,
    _parser,
    _resolve_encoder_selection,
)


def _config(**encoder_overrides: str) -> CrossValidationConfig:
    return CrossValidationConfig(
        data="data/full_df.xlsx",
        project_config="configs/rxnresid.yaml",
        split_manifest="data/splits/manifest.json",
        output_root="runs/test",
        substrate_encoder=encoder_overrides.get("substrate_encoder", "gine"),
        path_encoder=encoder_overrides.get("path_encoder", "gine_gatv2"),
        product_encoder=encoder_overrides.get("product_encoder", "gine"),
        epochs=1000,
        nproc_per_node=2,
        seed=42,
        num_folds=10,
        experiments=("seed42",),
        fold_indices=(0,),
        scheduler=SchedulerConfig(),
        early_stopping=EarlyStoppingConfig(),
        tasks_per_gpu=1,
        gpu_indices=(),
        stop_mae_ge=None,
        refit_epochs=0,
        refit_learning_rate_factor=0.2,
        train_on_train_valid_from_scratch=False,
        two_stage_train_valid_from_scratch=False,
        selection_refit_from_scratch=False,
        stage1_epochs=None,
        stage2_epochs=None,
        stage2_learning_rate_factor=0.2,
        stage2_auxiliary_weight_factor=1.0,
    )


def test_experiment_specs_do_not_select_encoder_combinations() -> None:
    assert {field.name for field in fields(ExperimentSpec)} == {
        "name",
        "model_variant",
        "mapping_mode",
        "seed",
    }


@pytest.mark.parametrize(
    ("option", "attribute", "encoder"),
    (
        ("--substrate-encoder", "substrate_encoder", "dmpnn"),
        ("--path-encoder", "path_encoder", "transformer"),
        ("--product-encoder", "product_encoder", "gin"),
    ),
)
def test_parser_accepts_independent_module_encoder_override(
    option: str, attribute: str, encoder: str
) -> None:
    args = _parser().parse_args([option, encoder])

    assert getattr(args, attribute) == encoder


def test_scheduler_targets_one_module_at_a_time() -> None:
    project = load_project_config("configs/rxnresid.yaml")
    args = _parser().parse_args(["--module", "substrate", "--encoder", "genconv"])

    assert _resolve_encoder_selection(args, project) == (
        "genconv",
        "gine_gatv2",
        "gine",
        "substrate",
    )


def test_scheduler_keeps_baseline_without_an_encoder_override() -> None:
    project = load_project_config("configs/rxnresid.yaml")
    args = _parser().parse_args([])

    assert _resolve_encoder_selection(args, project) == (
        "gine",
        "gine_gatv2",
        "gine",
        None,
    )


def test_scheduler_rejects_multi_module_encoder_selection() -> None:
    project = load_project_config("configs/rxnresid.yaml")
    args = _parser().parse_args(["--substrate-encoder", "gin", "--path-encoder", "transformer"])

    with pytest.raises(ValueError, match="one encoder module at a time"):
        _resolve_encoder_selection(args, project)


def test_scheduler_requires_module_for_generic_encoder_flag() -> None:
    project = load_project_config("configs/rxnresid.yaml")
    args = _parser().parse_args(["--encoder", "gin"])

    with pytest.raises(ValueError, match="provided together"):
        _resolve_encoder_selection(args, project)


def test_module_directory_tracks_each_module_and_preserves_baseline_path() -> None:
    baseline = _config()
    assert _module_directory(baseline) == "gine"

    substrate_only = replace(baseline, substrate_encoder="dmpnn")
    assert _module_directory(substrate_only) == ("substrate-dmpnn__path-gine_gatv2__product-gine")

    path_only = replace(baseline, path_encoder="transformer")
    assert _module_directory(path_only) == ("substrate-gine__path-transformer__product-gine")
