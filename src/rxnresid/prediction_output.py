"""Stable CSV output for path-level predictions."""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from rxnresid.training.trainer import PredictionRecord


def _sort_token(value: str) -> tuple[int, int | str]:
    stripped = value.strip()
    try:
        return (0, int(stripped))
    except ValueError:
        return (1, stripped)


def prediction_rows(
    records: Sequence[PredictionRecord],
    metadata_by_path: Mapping[str, Mapping[str, str]],
    component_id_columns: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Attach substrate component identifiers and sort for chemical analysis."""
    rows: list[dict[str, Any]] = []
    for record in records:
        metadata = metadata_by_path[record.path_id]
        rows.append(
            {
                **{column: metadata[column] for column in component_id_columns},
                **asdict(record),
                "aleatoric_std": record.aleatoric_std,
                "epistemic_std": record.epistemic_std,
                "predictive_std": record.predictive_std,
                "lower_95": record.lower_95,
                "upper_95": record.upper_95,
            }
        )
    if component_id_columns:
        rows.sort(
            key=lambda row: tuple(
                _sort_token(str(row[column])) for column in (*component_id_columns, "path_id")
            )
        )
    return rows


def write_prediction_csv(
    path: str | Path,
    records: Sequence[PredictionRecord],
    metadata_by_path: Mapping[str, Mapping[str, str]],
    component_id_columns: tuple[str, ...],
) -> None:
    """Write predictions while preserving the baseline-plus-residual contract."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = prediction_rows(records, metadata_by_path, component_id_columns)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                *component_id_columns,
                "substrate_group",
                "path_id",
                "group_id",
                "prediction",
                "target",
                "baseline",
                "residual",
                "baseline_target",
                "residual_target",
                "aleatoric_variance",
                "epistemic_variance",
                "predictive_variance",
                "aleatoric_std",
                "epistemic_std",
                "predictive_std",
                "lower_95",
                "upper_95",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


__all__ = ["prediction_rows", "write_prediction_csv"]
