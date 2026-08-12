"""Group-level train/validation/test splitting."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rxnresid.data.dataset import ReactionGroupDataset, ReactionPathDataset


@dataclass(frozen=True)
class GroupSplit:
    """Indices and group ids for a leakage-free split."""

    train: list[int]
    valid: list[int]
    test: list[int]


@dataclass(frozen=True)
class FoldAssignment:
    fold_index: int
    train_group_ids: tuple[str, ...]
    valid_group_ids: tuple[str, ...]
    test_group_ids: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Any) -> FoldAssignment:
        if not isinstance(value, dict):
            raise ValueError("fold assignment must be a mapping")
        return cls(
            fold_index=int(value["fold_index"]),
            train_group_ids=tuple(str(item) for item in value["train_group_ids"]),
            valid_group_ids=tuple(str(item) for item in value["valid_group_ids"]),
            test_group_ids=tuple(str(item) for item in value["test_group_ids"]),
        )


@dataclass(frozen=True)
class SplitManifest:
    schema_version: int
    strategy: str
    seed: int
    num_folds: int
    dataset_group_count: int
    dataset_fingerprint: str
    folds: tuple[FoldAssignment, ...]

    @classmethod
    def from_mapping(cls, value: Any) -> SplitManifest:
        if not isinstance(value, dict):
            raise ValueError("split manifest must be a mapping")
        folds = value.get("folds")
        if not isinstance(folds, list):
            raise ValueError("split manifest folds must be a list")
        return cls(
            schema_version=int(value["schema_version"]),
            strategy=str(value["strategy"]),
            seed=int(value["seed"]),
            num_folds=int(value["num_folds"]),
            dataset_group_count=int(value["dataset_group_count"]),
            dataset_fingerprint=str(value["dataset_fingerprint"]),
            folds=tuple(FoldAssignment.from_mapping(fold) for fold in folds),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def resolve(self, dataset: ReactionGroupDataset, fold_index: int) -> GroupSplit:
        if self.schema_version != 1:
            raise ValueError(f"Unsupported split manifest schema: {self.schema_version}")
        if self.dataset_group_count != len(dataset):
            raise ValueError("split manifest group count does not match dataset")
        if self.dataset_fingerprint != dataset_group_fingerprint(dataset):
            raise ValueError("split manifest fingerprint does not match dataset")
        try:
            fold = next(fold for fold in self.folds if fold.fold_index == fold_index)
        except StopIteration as exc:
            raise ValueError(f"Fold {fold_index} is not present in split manifest") from exc
        group_index = dataset.group_index
        train_ids = set(fold.train_group_ids)
        valid_ids = set(fold.valid_group_ids)
        test_ids = set(fold.test_group_ids)
        if train_ids & valid_ids or train_ids & test_ids or valid_ids & test_ids:
            raise ValueError("split manifest contains overlapping group assignments")
        if train_ids | valid_ids | test_ids != set(dataset.group_ids):
            raise ValueError("split manifest fold does not cover the dataset exactly")
        return GroupSplit(
            train=[group_index[group_id] for group_id in fold.train_group_ids],
            valid=[group_index[group_id] for group_id in fold.valid_group_ids],
            test=[group_index[group_id] for group_id in fold.test_group_ids],
        )


def random_group_split(
    dataset: ReactionGroupDataset,
    fractions: tuple[float, float, float] = (0.8, 0.1, 0.1),
    seed: int = 42,
) -> GroupSplit:
    """Randomly split complete groups, never individual paths."""
    if len(fractions) != 3 or any(value <= 0 for value in fractions):
        raise ValueError("fractions must contain three positive values")
    total = sum(fractions)
    if abs(total - 1.0) > 1e-6:
        raise ValueError("split fractions must sum to one")
    indices = list(range(len(dataset)))
    random.Random(seed).shuffle(indices)
    train_end = round(len(indices) * fractions[0])
    valid_end = train_end + round(len(indices) * fractions[1])
    train = indices[:train_end]
    valid = indices[train_end:valid_end]
    test = indices[valid_end:]
    if not train or not valid or not test:
        raise ValueError("dataset is too small for the requested split")
    return GroupSplit(train=train, valid=valid, test=test)


def group_kfold_splits(
    dataset: ReactionGroupDataset,
    num_folds: int = 10,
    seed: int = 42,
) -> list[GroupSplit]:
    """Create rotating group-level train/valid/test folds without leakage."""
    if num_folds < 3:
        raise ValueError("num_folds must be at least three to reserve validation and test folds")
    if num_folds > len(dataset):
        raise ValueError("num_folds cannot exceed the number of reaction groups")
    indices = list(range(len(dataset)))
    random.Random(seed).shuffle(indices)
    base_size, remainder = divmod(len(indices), num_folds)
    partitions: list[list[int]] = []
    start = 0
    for fold_index in range(num_folds):
        fold_size = base_size + (1 if fold_index < remainder else 0)
        partitions.append(indices[start : start + fold_size])
        start += fold_size
    splits: list[GroupSplit] = []
    for test_index in range(num_folds):
        valid_index = (test_index + 1) % num_folds
        train = [
            index
            for fold_index, partition in enumerate(partitions)
            if fold_index not in {test_index, valid_index}
            for index in partition
        ]
        splits.append(
            GroupSplit(
                train=train,
                valid=list(partitions[valid_index]),
                test=list(partitions[test_index]),
            )
        )
    return splits


def dataset_group_fingerprint(dataset: ReactionGroupDataset) -> str:
    payload = "\n".join(sorted(dataset.group_ids)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_group_kfold_manifest(
    dataset: ReactionGroupDataset,
    num_folds: int = 10,
    seed: int = 42,
) -> SplitManifest:
    splits = group_kfold_splits(dataset, num_folds=num_folds, seed=seed)
    folds = tuple(
        FoldAssignment(
            fold_index=fold_index,
            train_group_ids=tuple(dataset.group_ids[index] for index in split.train),
            valid_group_ids=tuple(dataset.group_ids[index] for index in split.valid),
            test_group_ids=tuple(dataset.group_ids[index] for index in split.test),
        )
        for fold_index, split in enumerate(splits)
    )
    return SplitManifest(
        schema_version=1,
        strategy="group_kfold",
        seed=seed,
        num_folds=num_folds,
        dataset_group_count=len(dataset),
        dataset_fingerprint=dataset_group_fingerprint(dataset),
        folds=folds,
    )


def save_split_manifest(manifest: SplitManifest, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_split_manifest(path: str | Path) -> SplitManifest:
    return SplitManifest.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))


def split_datasets(
    dataset: ReactionGroupDataset, split: GroupSplit
) -> dict[str, ReactionPathDataset]:
    return {
        "train": ReactionPathDataset(dataset, split.train),
        "valid": ReactionPathDataset(dataset, split.valid),
        "test": ReactionPathDataset(dataset, split.test),
    }


def split_group_labels(dataset: ReactionGroupDataset, split: GroupSplit) -> dict[str, str]:
    labels: dict[str, str] = {}
    for name, indices in (("train", split.train), ("valid", split.valid), ("test", split.test)):
        for index in indices:
            labels[dataset.group_ids[index]] = name
    return labels
