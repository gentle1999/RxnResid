"""Batch samplers that preserve complete path groups."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterator

from torch.utils.data import Sampler

from rxnresid.data.dataset import ReactionPathDataset


class CompleteGroupBatchSampler(Sampler[list[int]]):
    """Pack complete reaction groups into path-bounded minibatches.

    Every path index appears exactly once per epoch. Shuffling changes only the
    minibatch order, so batch count and scheduler length remain stable.
    """

    def __init__(
        self,
        dataset: ReactionPathDataset,
        max_paths_per_batch: int,
        *,
        shuffle: bool,
        seed: int = 0,
    ) -> None:
        if max_paths_per_batch < 1:
            raise ValueError("max_paths_per_batch must be at least one")
        self.shuffle = shuffle
        self.seed = seed
        self.epoch = 0

        group_paths: dict[str, list[int]] = defaultdict(list)
        for path_index, sample in enumerate(dataset.samples):
            group_paths[sample.group_id].append(path_index)
        self._batches = self._pack(tuple(group_paths.values()), max_paths_per_batch)

    @staticmethod
    def _pack(
        groups: tuple[list[int], ...],
        max_paths_per_batch: int,
    ) -> tuple[tuple[int, ...], ...]:
        batches: list[tuple[int, ...]] = []
        current: list[int] = []
        for group in groups:
            if current and len(current) + len(group) > max_paths_per_batch:
                batches.append(tuple(current))
                current = []
            current.extend(group)
            if len(current) >= max_paths_per_batch:
                batches.append(tuple(current))
                current = []
        if current:
            batches.append(tuple(current))
        return tuple(batches)

    def __iter__(self) -> Iterator[list[int]]:
        order = list(range(len(self._batches)))
        if self.shuffle:
            random.Random(self.seed + self.epoch).shuffle(order)
            self.epoch += 1
        for batch_index in order:
            yield list(self._batches[batch_index])

    def __len__(self) -> int:
        return len(self._batches)


__all__ = ["CompleteGroupBatchSampler"]
