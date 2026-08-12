from collections import defaultdict

from rxnresid.data.dataset import ReactionPathDataset
from rxnresid.data.samplers import CompleteGroupBatchSampler
from tests.helpers import dataset


def _varied_path_dataset() -> ReactionPathDataset:
    source = dataset()
    indices = [
        next(index for index, sample in enumerate(source) if len(sample) == size)
        for size in (1, 2, 4)
    ]
    return ReactionPathDataset(source, indices)


def test_complete_group_sampler_never_splits_a_group() -> None:
    paths = _varied_path_dataset()
    sampler = CompleteGroupBatchSampler(paths, 3, shuffle=False)
    batches = list(sampler)
    assert sorted(path for batch in batches for path in batch) == list(range(len(paths)))
    group_batches: dict[str, set[int]] = defaultdict(set)
    for batch_index, batch in enumerate(batches):
        for path_index in batch:
            group_batches[paths[path_index].group_id].add(batch_index)
    assert all(len(batch_indices) == 1 for batch_indices in group_batches.values())
    assert max(len(batch) for batch in batches) == 4


def test_complete_group_sampler_has_stable_epoch_length() -> None:
    paths = _varied_path_dataset()
    sampler = CompleteGroupBatchSampler(paths, 4, shuffle=True, seed=42)
    first = list(sampler)
    second = list(sampler)
    assert len(first) == len(second) == len(sampler)
    assert {tuple(sorted(batch)) for batch in first} == {tuple(sorted(batch)) for batch in second}
