"""Leakage-resistant equal-weight OOF ensemble analysis."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pandas as pd


REQUIRED_COLUMNS = {"path_id", "group_id", "prediction", "target", "baseline", "residual"}


def _mean_as_float(series: pd.Series) -> float:
    return float(series.to_numpy(dtype="float64").mean())


def _std_as_float(series: pd.Series) -> float:
    return float(series.to_numpy(dtype="float64").std())


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    return cast(pd.Series, frame[name])


def _component_id_columns(frame: pd.DataFrame) -> list[str]:
    """Recover component columns emitted before ``substrate_group``."""
    non_component_columns = {
        "fold_index",
        "path_id",
        "group_id",
        "target",
        "prediction",
        "baseline",
        "residual",
        "baseline_target",
        "residual_target",
        "absolute_error",
    }
    if "substrate_group" in frame.columns:
        boundary = frame.columns.get_loc("substrate_group")
        return [
            str(column)
            for column in frame.columns[:boundary]
            if column not in non_component_columns
        ]
    return [
        str(column)
        for column in frame.columns
        if str(column).endswith("_id") and column not in {"path_id", "group_id"}
    ]


@dataclass(frozen=True)
class EnsembleResult:
    predictions: pd.DataFrame
    fold_metrics: pd.DataFrame
    summary: dict[str, object]

    def write(self, output_dir: str | Path) -> None:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        self.predictions.to_csv(output / "oof_predictions.csv", index=False)
        self.fold_metrics.to_csv(output / "fold_metrics.csv", index=False)
        (output / "summary.json").write_text(
            json.dumps(self.summary, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )


def _load_prediction_directory(fold_dir: Path) -> pd.DataFrame:
    refit_path = fold_dir / "refit" / "test_predictions.csv"
    if refit_path.exists():
        fold_dir = fold_dir / "refit"
        test_path = refit_path
    else:
        test_path = fold_dir / "test_predictions.csv"
    if test_path.exists():
        frame = pd.read_csv(test_path, dtype={"path_id": str})
    else:
        prediction_path = fold_dir / "predictions.csv"
        preprocessing_path = fold_dir / "preprocessed.csv"
        if not prediction_path.exists() or not preprocessing_path.exists():
            raise FileNotFoundError(
                f"Missing test_predictions.csv or predictions/preprocessed pair under {fold_dir}"
            )
        frame = pd.read_csv(prediction_path, dtype={"path_id": str})
        splits = pd.read_csv(
            preprocessing_path,
            dtype={"path_id": str},
            usecols=["path_id", "split"],
        )
        frame = frame.merge(splits, on="path_id", validate="one_to_one")
        frame = frame.loc[frame["split"] == "test"].drop(columns="split")
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Missing prediction columns in {fold_dir}: {sorted(missing)}")
    if frame["path_id"].duplicated().any():
        raise ValueError(f"Duplicate path ids in {fold_dir}")
    decomposition_error = (frame["prediction"] - frame["baseline"] - frame["residual"]).abs()
    if float(decomposition_error.max()) > 1e-5:
        raise ValueError(f"prediction != baseline + residual in {fold_dir}")
    return frame.reset_index(drop=True)


def _load_test_predictions(root: Path, fold_index: int) -> pd.DataFrame:
    return _load_prediction_directory(root / f"fold_{fold_index:02d}")


def build_equal_weight_ensemble(
    members: dict[str, str | Path],
    fold_indices: tuple[int, ...] = tuple(range(10)),
    *,
    fold_directories: Mapping[str, Mapping[int, str | Path]] | None = None,
) -> EnsembleResult:
    """Average fixed members on each test fold and concatenate the OOF rows."""
    if len(members) < 2:
        raise ValueError("An ensemble requires at least two members")
    if not fold_indices or len(set(fold_indices)) != len(fold_indices):
        raise ValueError("fold_indices must be non-empty and unique")

    oof_frames: list[pd.DataFrame] = []
    fold_records: list[dict[str, float | int]] = []
    for fold_index in fold_indices:
        aligned: pd.DataFrame | None = None
        prediction_columns: list[str] = []
        baseline_columns: list[str] = []
        residual_columns: list[str] = []
        expected_paths: int | None = None
        for member_name, member_root in members.items():
            override = (fold_directories or {}).get(member_name, {}).get(fold_index)
            frame = (
                _load_prediction_directory(Path(override))
                if override is not None
                else _load_test_predictions(Path(member_root), fold_index)
            )
            if expected_paths is None:
                expected_paths = len(frame)
            member_column = f"prediction_{member_name}"
            baseline_column = f"baseline_{member_name}"
            residual_column = f"residual_{member_name}"
            keys = ["path_id", "group_id"]
            if aligned is None:
                component_columns = _component_id_columns(frame)
                metadata_columns = [
                    column
                    for column in (
                        *component_columns,
                        "substrate_group",
                        "baseline_target",
                        "residual_target",
                    )
                    if column in frame.columns
                ]
                aligned = frame.reindex(
                    columns=keys
                    + ["target"]
                    + metadata_columns
                    + ["prediction", "baseline", "residual"]
                ).copy()
                aligned[member_column] = _column(aligned, "prediction")
                aligned[baseline_column] = _column(aligned, "baseline")
                aligned[residual_column] = _column(aligned, "residual")
                aligned = aligned.drop(columns=["prediction", "baseline", "residual"])
            else:
                member_target = f"target_{member_name}"
                selected = frame.reindex(
                    columns=keys + ["target", "prediction", "baseline", "residual"]
                ).copy()
                selected[member_target] = _column(selected, "target")
                selected[member_column] = _column(selected, "prediction")
                selected[baseline_column] = _column(selected, "baseline")
                selected[residual_column] = _column(selected, "residual")
                selected = selected.drop(columns=["target", "prediction", "baseline", "residual"])
                aligned = aligned.merge(
                    selected,
                    on=keys,
                    how="inner",
                    validate="one_to_one",
                )
                target_error = (aligned[member_target] - aligned["target"]).abs()
                if float(target_error.max()) > 1e-5:
                    raise ValueError(f"Member path or target mismatch in fold {fold_index}")
                aligned = aligned.drop(columns=member_target)
            prediction_columns.append(member_column)
            baseline_columns.append(baseline_column)
            residual_columns.append(residual_column)
        if aligned is None:
            raise RuntimeError("No ensemble members were loaded")
        if len(aligned) != expected_paths:
            raise ValueError(f"Member path or target mismatch in fold {fold_index}")
        aligned["baseline"] = aligned[baseline_columns].mean(axis=1)
        aligned["residual"] = aligned[residual_columns].mean(axis=1)
        aligned["prediction"] = aligned["baseline"] + aligned["residual"]
        averaged_prediction = aligned[prediction_columns].mean(axis=1)
        if float((aligned["prediction"] - averaged_prediction).abs().max()) > 1e-5:
            raise ValueError(f"Ensemble decomposition mismatch in fold {fold_index}")
        aligned["absolute_error"] = (aligned["prediction"] - aligned["target"]).abs()
        aligned.insert(0, "fold_index", fold_index)
        fold_records.append(
            {
                "fold_index": fold_index,
                "paths": len(aligned),
                "mae": _mean_as_float(_column(aligned, "absolute_error")),
            }
        )
        oof_frames.append(aligned)

    predictions = pd.concat(oof_frames, ignore_index=True)
    if predictions["path_id"].duplicated().any():
        raise ValueError("OOF path ids overlap across folds")
    fold_metrics = pd.DataFrame(fold_records).sort_values("fold_index").reset_index(drop=True)
    sort_columns = [*_component_id_columns(predictions), "path_id"]
    if sort_columns:
        predictions = predictions.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    summary: dict[str, object] = {
        "members": list(members),
        "weights": {name: 1.0 / len(members) for name in members},
        "folds": list(fold_indices),
        "num_paths": len(predictions),
        "path_weighted_mae": _mean_as_float(_column(predictions, "absolute_error")),
        "fold_mean_mae": _mean_as_float(_column(fold_metrics, "mae")),
        "fold_std_mae": _std_as_float(_column(fold_metrics, "mae")),
    }
    if "baseline_target" in predictions:
        summary["baseline_mae"] = float(
            _mean_as_float((predictions["baseline"] - predictions["baseline_target"]).abs())
        )
    if "residual_target" in predictions:
        summary["residual_mae"] = float(
            _mean_as_float((predictions["residual"] - predictions["residual_target"]).abs())
        )
    return EnsembleResult(predictions=predictions, fold_metrics=fold_metrics, summary=summary)


__all__ = ["EnsembleResult", "build_equal_weight_ensemble"]
