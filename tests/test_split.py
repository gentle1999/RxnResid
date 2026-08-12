from collections import Counter

from rxnresid.data.split import (
    create_group_kfold_manifest,
    group_kfold_splits,
    load_split_manifest,
    random_group_split,
    save_split_manifest,
    split_datasets,
    split_group_labels,
)
from tests.helpers import dataset


def test_split_is_group_level() -> None:
    data = dataset()
    split = random_group_split(data, seed=7)
    assert not set(split.train) & set(split.valid)
    assert not set(split.train) & set(split.test)
    assert not set(split.valid) & set(split.test)
    labels = split_group_labels(data, split)
    assert len(labels) == len(data)
    path_splits = split_datasets(data, split)
    assert sum(len(subset) for subset in path_splits.values()) == 2968
    assert not set(path_splits["train"].group_ids) & set(path_splits["valid"].group_ids)
    statistics = path_splits["train"].target_statistics()
    assert statistics.target_std > statistics.residual_std > 0.0
    assert abs(statistics.residual_mean) < 1e-6


def test_ten_fold_split_covers_each_group_once_as_test() -> None:
    data = dataset()
    splits = group_kfold_splits(data, num_folds=10, seed=42)
    assert len(splits) == 10
    assert all(
        (len(split.train), len(split.valid), len(split.test)) == (1280, 160, 160)
        for split in splits
    )
    for split in splits:
        assert not set(split.train) & set(split.valid)
        assert not set(split.train) & set(split.test)
        assert not set(split.valid) & set(split.test)
    assert Counter(index for split in splits for index in split.test) == Counter(
        dict.fromkeys(range(len(data)), 1)
    )
    assert Counter(index for split in splits for index in split.valid) == Counter(
        dict.fromkeys(range(len(data)), 1)
    )


def test_split_manifest_round_trip_and_dataset_validation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = dataset()
    manifest = create_group_kfold_manifest(data, num_folds=10, seed=42)
    path = tmp_path / "folds.json"
    save_split_manifest(manifest, path)
    loaded = load_split_manifest(path)
    assert loaded == manifest
    split = loaded.resolve(data, fold_index=3)
    assert (len(split.train), len(split.valid), len(split.test)) == (1280, 160, 160)
