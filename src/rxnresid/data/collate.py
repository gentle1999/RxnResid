"""Path-level batches with repeated group context and exact path CGRs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self, cast

import torch
from torch import Tensor
from torch_geometric.data import Batch
from torch_geometric.data.data import BaseData

from rxnresid.data.dataset import ReactionGroupSample, ReactionPathSample
from rxnresid.data.mapping_features import (
    reaction_edit_features,
    reaction_stereo_signature_token,
)
from rxnresid.data.protocols import PyGBatchStub


@dataclass
class MappingBatch:
    """Flattened mapping/edit information aligned one-to-one with paths."""

    edit_features: Tensor
    stereo_signature_token: Tensor
    mapping_present: Tensor
    mapped_substrate_node: Tensor
    mapped_product_node: Tensor
    mapping_to_path: Tensor

    def to(self, device: torch.device | str, *, non_blocking: bool = False) -> Self:
        self.edit_features = self.edit_features.to(device, non_blocking=non_blocking)
        self.stereo_signature_token = self.stereo_signature_token.to(
            device, non_blocking=non_blocking
        )
        self.mapping_present = self.mapping_present.to(device, non_blocking=non_blocking)
        self.mapped_substrate_node = self.mapped_substrate_node.to(
            device, non_blocking=non_blocking
        )
        self.mapped_product_node = self.mapped_product_node.to(device, non_blocking=non_blocking)
        self.mapping_to_path = self.mapping_to_path.to(device, non_blocking=non_blocking)
        return self

    def pin_memory(self) -> Self:
        for name in (
            "edit_features",
            "stereo_signature_token",
            "mapping_present",
            "mapped_substrate_node",
            "mapped_product_node",
            "mapping_to_path",
        ):
            tensor = getattr(self, name)
            if tensor.device.type == "cpu" and not tensor.is_pinned():
                setattr(self, name, tensor.pin_memory())
        return self


@dataclass
class RxnResidBatch:
    """The graph and target tensors consumed by the production RxnResid model."""

    unique_components: PyGBatchStub
    path_cgrs: PyGBatchStub
    path_delta_cgrs: PyGBatchStub
    products: PyGBatchStub
    group_component_index: Tensor
    path_to_group: Tensor
    energies: Tensor
    baseline_targets: Tensor
    residual_targets: Tensor
    route_ids: Tensor
    group_sizes: Tensor
    component_counts: Tensor
    group_ids: list[str]
    substrate_groups: list[str]
    path_ids: list[str]
    mapping: MappingBatch

    @property
    def num_groups(self) -> int:
        return len(self.group_ids)

    @property
    def num_paths(self) -> int:
        return len(self.path_ids)

    def to(self, device: torch.device | str, *, non_blocking: bool = False) -> Self:
        for name in (
            "unique_components",
            "path_cgrs",
            "path_delta_cgrs",
            "products",
        ):
            setattr(self, name, getattr(self, name).to(device, non_blocking=non_blocking))
        for name in (
            "group_component_index",
            "path_to_group",
            "energies",
            "baseline_targets",
            "residual_targets",
            "route_ids",
            "group_sizes",
            "component_counts",
        ):
            setattr(self, name, getattr(self, name).to(device, non_blocking=non_blocking))
        self.mapping.to(device, non_blocking=non_blocking)
        return self

    def pin_memory(self) -> Self:
        for name in (
            "unique_components",
            "path_cgrs",
            "path_delta_cgrs",
            "products",
        ):
            graph = getattr(self, name)
            if graph.x.device.type == "cpu" and not graph.x.is_pinned():
                setattr(self, name, graph.pin_memory())
        for name in (
            "group_component_index",
            "path_to_group",
            "energies",
            "baseline_targets",
            "residual_targets",
            "route_ids",
            "group_sizes",
            "component_counts",
        ):
            tensor = getattr(self, name)
            if tensor.device.type == "cpu" and not tensor.is_pinned():
                setattr(self, name, tensor.pin_memory())
        self.mapping.pin_memory()
        return self


@dataclass
class CachedPathCollator:
    """Reuse immutable complete-group batches across training epochs."""

    _cache: dict[tuple[str, ...], RxnResidBatch] = field(default_factory=dict, init=False)

    def __call__(self, samples: list[ReactionPathSample]) -> RxnResidBatch:
        key = tuple(sample.path_id for sample in samples)
        batch = self._cache.get(key)
        if batch is None:
            batch = collate_reaction_paths(samples)
            self._cache[key] = batch
        return batch

    @property
    def cached_batches(self) -> int:
        return len(self._cache)


def _same_component_graph(left: BaseData, right: BaseData) -> bool:
    """Require exact cached graph semantics before sharing an encoding."""
    return all(
        torch.equal(cast(Tensor, left[name]), cast(Tensor, right[name]))
        for name in ("x", "edge_index", "edge_attr", "atom_map_numbers", "component_token_id")
    )


def collate_reaction_paths(samples: list[ReactionPathSample]) -> RxnResidBatch:
    """Collate one graph context and one exact CGR for every path row."""
    if not samples:
        raise ValueError("Cannot collate an empty path batch")
    group_index: dict[str, int] = {}
    group_ids: list[str] = []
    substrate_groups: list[str] = []
    path_to_group: list[int] = []
    group_representatives: list[ReactionPathSample] = []
    for sample in samples:
        if sample.group_id not in group_index:
            group_index[sample.group_id] = len(group_ids)
            group_ids.append(sample.group_id)
            substrate_groups.append(sample.substrate_group)
            group_representatives.append(sample)
        path_to_group.append(group_index[sample.group_id])

    for group_id, representative in zip(group_ids, group_representatives, strict=True):
        if representative.group_size < 1:
            raise ValueError(f"Path group {group_id} has a non-positive group size")
        if any(
            sample.group_size != representative.group_size
            for sample in samples
            if sample.group_id == group_id
        ):
            raise ValueError(f"Path group {group_id} has inconsistent group sizes")

    unique_component_graphs: list[BaseData] = []
    unique_component_candidates: dict[str, list[int]] = {}
    group_components: list[list[int]] = []
    for group_id, sample in zip(group_ids, group_representatives, strict=True):
        component_ids = set(sample.reactant.component_id.tolist())
        if not component_ids:
            raise ValueError(f"Group {group_id} must contain at least one component")
        expected_ids = set(range(max(component_ids) + 1))
        if component_ids != expected_ids:
            raise ValueError(
                f"Group {group_id} component ids must be contiguous from zero, got {sorted(component_ids)}"
            )
        if len(sample.components) != len(component_ids) or len(sample.component_keys) != len(
            component_ids
        ):
            raise ValueError(f"Group {group_id} parsed components do not match its reactant graph")
        component_indices: list[int] = []
        for key, component_graph in zip(
            sample.component_keys,
            sample.components,
            strict=True,
        ):
            candidates = unique_component_candidates.setdefault(key, [])
            component_index = next(
                (
                    candidate
                    for candidate in candidates
                    if _same_component_graph(unique_component_graphs[candidate], component_graph)
                ),
                None,
            )
            if component_index is None:
                component_index = len(unique_component_graphs)
                candidates.append(component_index)
                unique_component_graphs.append(component_graph)
            component_indices.append(component_index)
        group_components.append(component_indices)
    unique_components = cast(
        PyGBatchStub,
        Batch.from_data_list(unique_component_graphs),
    )
    max_components = max(len(indices) for indices in group_components)
    group_component_index = torch.full(
        (len(group_components), max_components),
        -1,
        dtype=torch.long,
    )
    for group_position, indices in enumerate(group_components):
        group_component_index[group_position, : len(indices)] = torch.tensor(
            indices,
            dtype=torch.long,
        )
    path_cgrs = cast(PyGBatchStub, Batch.from_data_list([sample.path_cgr for sample in samples]))
    path_delta_cgrs = cast(
        PyGBatchStub,
        Batch.from_data_list([sample.path_delta_cgr for sample in samples]),
    )
    products = cast(PyGBatchStub, Batch.from_data_list([sample.product for sample in samples]))
    path_to_group_tensor = torch.tensor(path_to_group, dtype=torch.long)
    group_sizes = torch.tensor(
        [sample.group_size for sample in group_representatives],
        dtype=torch.long,
    )
    component_counts = torch.tensor(
        [len(indices) for indices in group_components],
        dtype=torch.long,
    )

    edit_features = torch.stack([reaction_edit_features(sample.mapping) for sample in samples])
    present: list[float] = []
    substrate_nodes: list[int] = []
    product_nodes: list[int] = []
    mapping_paths: list[int] = []
    group_substrate_maps: list[dict[int, int]] = []
    for component_indices in group_components:
        group_maps: dict[int, int] = {}
        for component_index in component_indices:
            component_start = int(unique_components.ptr[component_index].item())
            component_maps = unique_components.atom_map_numbers[
                unique_components.ptr[component_index] : unique_components.ptr[component_index + 1]
            ]
            for node_index, map_number in enumerate(component_maps.tolist()):
                if map_number <= 0:
                    continue
                if map_number in group_maps:
                    raise ValueError(f"Duplicate substrate atom map number {map_number}")
                group_maps[map_number] = component_start + node_index
        group_substrate_maps.append(group_maps)
    for path_index, sample in enumerate(samples):
        product_offset = int(products.ptr[path_index].item())
        product_map_to_node = {
            int(map_number): node_index
            for node_index, map_number in enumerate(sample.product.atom_map_numbers.tolist())
            if map_number > 0
        }
        source_map_to_coordinate = sample.source_map_to_coordinate or {
            int(map_number): int(map_number) for map_number in sample.mapping.atom_mapping
        }
        source_to_product_node: dict[int, int] = {}
        for source_map in sample.mapping.atom_mapping:
            coordinate_map = source_map_to_coordinate.get(source_map)
            if coordinate_map is not None and coordinate_map in product_map_to_node:
                source_to_product_node[source_map] = product_map_to_node[coordinate_map]
        common_source_maps = set(source_to_product_node)
        coordinate_maps: dict[int, int] = {}
        for source_map in common_source_maps:
            if source_map not in source_map_to_coordinate:
                raise ValueError(f"Path {sample.path_id} has no normalized atom map {source_map}")
            coordinate_map = source_map_to_coordinate[source_map]
            if coordinate_map not in group_substrate_maps[path_to_group[path_index]]:
                raise ValueError(
                    f"Path {sample.path_id} normalized atom map {coordinate_map} is absent "
                    "from its group substrate"
                )
            coordinate_maps[source_map] = coordinate_map
        present.append(float(bool(coordinate_maps)))
        for source_map in sorted(
            set(coordinate_maps) & set(sample.mapping.edits.reaction_center_maps)
        ):
            substrate_nodes.append(
                group_substrate_maps[path_to_group[path_index]][coordinate_maps[source_map]]
            )
            product_nodes.append(product_offset + source_to_product_node[source_map])
            mapping_paths.append(path_index)

    mapping = MappingBatch(
        edit_features=edit_features,
        stereo_signature_token=torch.tensor(
            [reaction_stereo_signature_token(sample.mapping) for sample in samples],
            dtype=torch.long,
        ),
        mapping_present=torch.tensor(present, dtype=torch.float32),
        mapped_substrate_node=torch.tensor(substrate_nodes, dtype=torch.long),
        mapped_product_node=torch.tensor(product_nodes, dtype=torch.long),
        mapping_to_path=torch.tensor(mapping_paths, dtype=torch.long),
    )
    return RxnResidBatch(
        unique_components=unique_components,
        path_cgrs=path_cgrs,
        path_delta_cgrs=path_delta_cgrs,
        products=products,
        group_component_index=group_component_index,
        path_to_group=path_to_group_tensor,
        energies=torch.tensor([sample.energy for sample in samples], dtype=torch.float32),
        baseline_targets=torch.tensor(
            [sample.baseline_target for sample in samples], dtype=torch.float32
        ),
        residual_targets=torch.tensor(
            [sample.residual_target for sample in samples], dtype=torch.float32
        ),
        route_ids=torch.tensor([sample.route_id for sample in samples], dtype=torch.long),
        group_sizes=group_sizes,
        component_counts=component_counts,
        group_ids=group_ids,
        substrate_groups=substrate_groups,
        path_ids=[sample.path_id for sample in samples],
        mapping=mapping,
    )


def collate_reaction_groups(samples: list[ReactionGroupSample]) -> RxnResidBatch:
    """Compatibility wrapper that expands groups before path-level collation."""
    paths = [path for sample in samples for path in sample.path_samples()]
    return collate_reaction_paths(paths)


__all__ = [
    "CachedPathCollator",
    "MappingBatch",
    "RxnResidBatch",
    "collate_reaction_groups",
    "collate_reaction_paths",
]
