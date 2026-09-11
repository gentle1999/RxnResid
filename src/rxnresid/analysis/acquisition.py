"""Path-wise acquisition rules for regression active learning."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from typing import Literal

from rxnresid.training.trainer import PredictionRecord


AcquisitionStrategy = Literal["predictive", "epistemic", "aleatoric", "random"]


def acquisition_score(record: PredictionRecord, strategy: AcquisitionStrategy) -> float:
    """Return the native variance used to rank one concrete reaction."""
    if strategy == "random":
        raise ValueError("random acquisition does not define an uncertainty score")
    if strategy not in {"predictive", "epistemic", "aleatoric"}:
        raise ValueError(f"Unknown acquisition strategy: {strategy}")
    value = getattr(record, f"{strategy}_variance")
    if value is None or not math.isfinite(value):
        raise ValueError(f"Prediction {record.path_id!r} has no finite {strategy} uncertainty")
    return value


def rank_acquisition(
    records: Sequence[PredictionRecord],
    strategy: AcquisitionStrategy,
    *,
    seed: int = 42,
) -> list[PredictionRecord]:
    """Rank individual reactions from most informative to least informative."""
    ranked = list(records)
    if strategy == "random":
        random.Random(seed).shuffle(ranked)
        return ranked
    ranked.sort(key=lambda record: (-acquisition_score(record, strategy), record.path_id))
    return ranked


def select_acquisition(
    records: Sequence[PredictionRecord],
    strategy: AcquisitionStrategy,
    count: int,
    *,
    seed: int = 42,
) -> list[PredictionRecord]:
    """Select a fixed number of individual reactions from an unlabeled pool."""
    if count < 0:
        raise ValueError("acquisition count must be non-negative")
    return rank_acquisition(records, strategy, seed=seed)[:count]


__all__ = [
    "AcquisitionStrategy",
    "acquisition_score",
    "rank_acquisition",
    "select_acquisition",
]
