"""Preprocess a raw path-wise table and attach group ids and split labels."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from rxnresid.data.dataset import ReactionGroupDataset
from rxnresid.data.split import GroupSplit, random_group_split, split_group_labels


def prepare_table(
    input_path: str | Path,
    output_path: str | Path,
    seed: int = 42,
    split_fractions: tuple[float, float, float] = (0.8, 0.1, 0.1),
    report_path: str | Path | None = None,
    anomalies_path: str | Path | None = None,
    target_column: str = "G_T_activate",
    reaction_column: str = "rxn_smiles",
    condition_columns: Sequence[str] = (),
    route_id_column: str | None = None,
    baseline_reduction: Literal["mean"] = "mean",
    group_split: GroupSplit | None = None,
) -> dict[str, int]:
    dataset = ReactionGroupDataset(
        input_path,
        target_column=target_column,
        reaction_column=reaction_column,
        condition_columns=condition_columns,
        route_id_column=route_id_column,
        baseline_reduction=baseline_reduction,
        on_error="record",
    )
    return write_prepared_dataset(
        dataset,
        output_path,
        seed=seed,
        split_fractions=split_fractions,
        report_path=report_path,
        anomalies_path=anomalies_path,
        group_split=group_split,
    )


def write_prepared_dataset(
    dataset: ReactionGroupDataset,
    output_path: str | Path,
    *,
    seed: int = 42,
    split_fractions: tuple[float, float, float] = (0.8, 0.1, 0.1),
    report_path: str | Path | None = None,
    anomalies_path: str | Path | None = None,
    group_split: GroupSplit | None = None,
) -> dict[str, int]:
    """Write audit artifacts from an already parsed and featurized dataset."""
    output = Path(output_path)
    split = group_split or random_group_split(dataset, fractions=split_fractions, seed=seed)
    labels = split_group_labels(dataset, split)
    rows = dataset.processed_rows(labels)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "rows": len(dataset.rows),
        "groups": len(dataset),
        "train_groups": len(split.train),
        "valid_groups": len(split.valid),
        "test_groups": len(split.test),
        "anomalies": len(dataset.anomalies),
    }
    anomaly_output = (
        Path(anomalies_path)
        if anomalies_path is not None
        else output.with_name(f"{output.stem}.anomalies.csv")
    )
    anomaly_output.parent.mkdir(parents=True, exist_ok=True)
    with anomaly_output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["row_index", "path_id", "error_type", "message"],
        )
        writer.writeheader()
        writer.writerows(
            {
                "row_index": anomaly.row_index,
                "path_id": anomaly.path_id,
                "error_type": anomaly.error_type,
                "message": anomaly.message,
            }
            for anomaly in dataset.anomalies
        )
    if report_path is not None:
        Path(report_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


__all__ = ["prepare_table", "write_prepared_dataset"]
