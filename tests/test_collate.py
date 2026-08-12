from dataclasses import replace

import torch

from rxnresid.data.collate import (
    CachedPathCollator,
    collate_reaction_groups,
    collate_reaction_paths,
)
from tests.helpers import sample_of_size


def test_flatten_collator_keeps_group_boundaries() -> None:
    samples = [sample_of_size(size) for size in [3, 2, 1]]
    batch = collate_reaction_groups(samples)
    assert batch.num_groups == 3
    assert batch.num_paths == 6
    assert batch.path_to_group.tolist() == [0, 0, 0, 1, 1, 2]
    assert batch.group_sizes.tolist() == [3, 2, 1]
    assert batch.substrate_groups == [sample.substrate_group for sample in samples]
    assert len(batch.substrate_groups) == batch.num_groups
    assert batch.unique_components.num_graphs < int(batch.component_counts.sum().item())
    assert batch.group_component_index.shape == (3, 2)
    assert torch.all(batch.group_component_index >= 0)
    assert batch.path_cgrs.num_graphs == 6
    assert batch.path_delta_cgrs.num_graphs == 6
    assert batch.products.num_graphs == 6
    assert batch.mapping.edit_features.shape[0] == 6
    assert batch.route_ids.shape == (6,)
    assert batch.route_ids.dtype == torch.long
    assert batch.component_counts.shape == (3,)
    assert torch.all(batch.component_counts >= 1)
    assert torch.equal(
        batch.unique_components.atom_map_numbers[batch.mapping.mapped_substrate_node],
        batch.products.atom_map_numbers[batch.mapping.mapped_product_node],
    )


def test_collator_does_not_pad_candidate_paths() -> None:
    sample = sample_of_size(8)
    batch = collate_reaction_groups([sample])
    assert batch.path_cgrs.num_graphs == 8
    assert batch.path_delta_cgrs.num_graphs == 8
    assert batch.products.num_graphs == 8
    assert batch.path_to_group.tolist() == [0] * 8
    assert batch.mapping.stereo_signature_token.shape == (8,)
    assert batch.mapping.stereo_signature_token.dtype == torch.long


def test_partial_path_batch_retains_precomputed_full_group_size() -> None:
    sample = sample_of_size(4)
    batch = collate_reaction_paths([sample.path_samples()[0]])
    assert batch.num_paths == 1
    assert batch.group_sizes.tolist() == [4]


def test_cached_collator_reuses_fixed_complete_group_batches() -> None:
    paths = sample_of_size(3).path_samples()
    collator = CachedPathCollator()
    first = collator(list(paths))
    second = collator(list(paths))
    assert first is second
    assert collator.cached_batches == 1


def test_collator_encodes_repeated_components_once_per_batch() -> None:
    source = sample_of_size(2)
    duplicate = replace(
        source,
        group_id=f"{source.group_id}_duplicate",
        path_ids=[f"{path_id}_duplicate" for path_id in source.path_ids],
    )

    batch = collate_reaction_groups([source, duplicate])

    assert batch.unique_components.num_graphs == int(batch.component_counts[0].item())
    assert torch.equal(batch.group_component_index[0], batch.group_component_index[1])
