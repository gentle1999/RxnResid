from pathlib import Path

import pandas as pd
import pytest

from rxnresid.analysis.ensemble import build_equal_weight_ensemble


def _write_fold(
    root: Path,
    predictions: list[float],
    targets: list[float],
    *,
    refit: bool = False,
) -> None:
    fold = root / "fold_00"
    if refit:
        fold = fold / "refit"
    fold.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "path_id": [str(index) for index in range(len(targets))],
            "group_id": [f"group-{index}" for index in range(len(targets))],
            "prediction": predictions,
            "target": targets,
            "baseline": predictions,
            "residual": [0.0] * len(targets),
            "baseline_target": targets,
            "residual_target": [0.0] * len(targets),
        }
    )
    frame.to_csv(fold / "test_predictions.csv", index=False)


def test_equal_weight_ensemble_reports_path_and_fold_mae(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_fold(first, [1.0, 5.0], [2.0, 4.0])
    _write_fold(second, [3.0, 3.0], [2.0, 4.0])

    result = build_equal_weight_ensemble(
        {"first": first, "second": second},
        fold_indices=(0,),
    )

    assert result.predictions["prediction"].tolist() == [2.0, 4.0]
    assert result.summary["path_weighted_mae"] == 0.0
    assert result.summary["fold_mean_mae"] == 0.0
    assert result.summary["baseline_mae"] == 0.0
    assert result.summary["residual_mae"] == 0.0
    assert result.predictions["baseline"].tolist() == [2.0, 4.0]


def test_equal_weight_ensemble_supports_refit_and_fold_override(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    override = tmp_path / "hard-fold"
    _write_fold(first, [1.0], [2.0], refit=True)
    _write_fold(second, [3.0], [2.0], refit=True)
    _write_fold(override, [3.0], [2.0])

    result = build_equal_weight_ensemble(
        {"first": first, "second": second},
        fold_indices=(0,),
        fold_directories={"first": {0: override / "fold_00"}},
    )

    assert result.predictions["prediction"].tolist() == [3.0]


def test_equal_weight_ensemble_prefers_refit_predictions(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_fold(first, [10.0], [2.0])
    _write_fold(first, [1.0], [2.0], refit=True)
    _write_fold(second, [10.0], [2.0])
    _write_fold(second, [3.0], [2.0], refit=True)

    result = build_equal_weight_ensemble(
        {"first": first, "second": second},
        fold_indices=(0,),
    )

    assert result.predictions["prediction"].tolist() == [2.0]
    assert result.summary["path_weighted_mae"] == 0.0


def test_equal_weight_ensemble_rejects_target_mismatch(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_fold(first, [1.0], [2.0])
    _write_fold(second, [1.0], [3.0])

    with pytest.raises(ValueError, match="mismatch"):
        build_equal_weight_ensemble(
            {"first": first, "second": second},
            fold_indices=(0,),
        )


def test_equal_weight_ensemble_tolerates_csv_float_round_trip(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_fold(first, [1.0], [2.0])
    _write_fold(second, [3.0], [2.0 + 1e-12])

    result = build_equal_weight_ensemble(
        {"first": first, "second": second},
        fold_indices=(0,),
    )

    assert result.predictions["prediction"].tolist() == [2.0]


def test_equal_weight_ensemble_preserves_arbitrary_component_columns(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_fold(first, [1.0, 5.0], [2.0, 4.0])
    _write_fold(second, [3.0, 3.0], [2.0, 4.0])
    for root in (first, second):
        path = root / "fold_00" / "test_predictions.csv"
        frame = pd.read_csv(path)
        frame.insert(0, "catalyst_id", ["10", "2"])
        frame.insert(1, "solvent_id", ["3", "1"])
        frame.insert(2, "substrate_group", ["s10", "s2"])
        frame.to_csv(path, index=False)

    result = build_equal_weight_ensemble(
        {"first": first, "second": second},
        fold_indices=(0,),
    )

    assert result.predictions["catalyst_id"].tolist() == [2, 10]
    assert result.predictions["solvent_id"].tolist() == [1, 3]
