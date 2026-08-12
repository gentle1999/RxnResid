"""Path-wise CSV loading with reaction-group samples as the dataset unit."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import pickle
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal, cast

import torch
from filelock import FileLock
from torch import Tensor
from torch.utils.data import Dataset
from torch_geometric.data import Data

from rxnresid.data.change_graphs import reaction_change_graphs
from rxnresid.data.featurizer import (
    COMPONENT_HASH_BUCKETS,
    mapped_component_key,
    reaction_graphs,
    split_component_graphs,
)
from rxnresid.data.grouping import canonical_reactant_key, group_id_from_parsed, reaction_group_key
from rxnresid.data.protocols import PyGDataStub
from rxnresid.data.reaction_parser import ParsedReaction, parse_mapped_reaction


DATASET_CACHE_SCHEMA_VERSION = 4


@dataclass(frozen=True)
class DatasetCacheInfo:
    """Persistent preprocessing cache state for one dataset instance."""

    enabled: bool
    hit: bool
    path: str | None
    cache_key: str | None


@dataclass(frozen=True)
class ReactionRow:
    """One original path row retained for preprocessing and audit output."""

    row_index: int
    path_id: str
    group_id: str
    mapped_rxn_smiles: str
    activation_energy: float
    route_id: int
    parsed: ParsedReaction
    metadata: dict[str, str]


@dataclass(frozen=True)
class PreprocessingAnomaly:
    """One invalid source row retained for a machine-readable audit report."""

    row_index: int
    path_id: str
    error_type: str
    message: str


@dataclass(frozen=True)
class TargetStatistics:
    """Train-split target moments used to scale regression heads."""

    target_mean: float
    target_std: float
    baseline_mean: float
    baseline_std: float
    residual_mean: float
    residual_std: float

    @classmethod
    def from_mapping(cls, value: dict[str, float]) -> TargetStatistics:
        return cls(
            target_mean=float(value["target_mean"]),
            target_std=float(value["target_std"]),
            baseline_mean=float(value["baseline_mean"]),
            baseline_std=float(value["baseline_std"]),
            residual_mean=float(value["residual_mean"]),
            residual_std=float(value["residual_std"]),
        )


@dataclass
class ReactionGroupSample:
    """All candidate paths belonging to one reaction group."""

    group_id: str
    substrate_group: str
    path_cgrs: tuple[Data, ...]
    path_delta_cgrs: tuple[Data, ...]
    reactant: Data
    components: tuple[Data, ...]
    component_keys: tuple[str, ...]
    products: list[Data]
    energies: Tensor
    baseline_target: float
    residual_targets: Tensor
    route_ids: Tensor
    path_ids: list[str]
    mappings: list[ParsedReaction]

    def __len__(self) -> int:
        return len(self.products)

    def path_samples(self) -> tuple[ReactionPathSample, ...]:
        """Expand this group into path rows sharing the same group graph."""
        return tuple(
            ReactionPathSample(
                group_id=self.group_id,
                substrate_group=self.substrate_group,
                path_cgr=self.path_cgrs[path_index],
                path_delta_cgr=self.path_delta_cgrs[path_index],
                reactant=self.reactant,
                components=self.components,
                component_keys=self.component_keys,
                product=self.products[path_index],
                energy=float(self.energies[path_index].item()),
                baseline_target=self.baseline_target,
                residual_target=float(self.residual_targets[path_index].item()),
                group_size=len(self),
                route_id=int(self.route_ids[path_index].item()),
                path_id=self.path_ids[path_index],
                mapping=self.mappings[path_index],
            )
            for path_index in range(len(self))
        )


@dataclass(frozen=True)
class ReactionPathSample:
    """One path row with its complete group context and precomputed targets."""

    group_id: str
    substrate_group: str
    path_cgr: Data
    path_delta_cgr: Data
    reactant: Data
    components: tuple[Data, ...]
    component_keys: tuple[str, ...]
    product: Data
    energy: float
    baseline_target: float
    residual_target: float
    group_size: int
    route_id: int
    path_id: str
    mapping: ParsedReaction


@dataclass
class _DatasetCachePayload:
    schema_version: int
    cache_key: str
    rows: list[ReactionRow]
    anomalies: list[PreprocessingAnomaly]
    group_to_rows: dict[str, list[int]]
    group_ids: list[str]
    samples: list[ReactionGroupSample]
    group_index: dict[str, int]
    path_targets: dict[str, tuple[float, float]]


class ReactionGroupDataset(Dataset[ReactionGroupSample]):
    """Load a flat CSV while exposing complete groups through ``__getitem__``."""

    def __init__(
        self,
        source: str | Path | list[dict[str, str]],
        target_column: str = "G_T_activate",
        reaction_column: str = "rxn_smiles",
        path_id_column: str | None = None,
        condition_columns: Sequence[str] = (),
        route_id_column: str | None = None,
        baseline_reduction: Literal["mean"] = "mean",
        component_hash_buckets: int = COMPONENT_HASH_BUCKETS,
        on_error: Literal["raise", "record"] = "raise",
        cache_dir: str | Path | None = None,
    ) -> None:
        if on_error not in {"raise", "record"}:
            raise ValueError("on_error must be 'raise' or 'record'")
        if baseline_reduction != "mean":
            raise ValueError("RxnResid requires baseline_reduction='mean'")
        if component_hash_buckets < 2:
            raise ValueError("component_hash_buckets must be at least two")
        self.target_column = target_column
        self.reaction_column = reaction_column
        self.condition_columns = tuple(condition_columns)
        self.route_id_column = route_id_column
        self.baseline_reduction: Literal["mean"] = baseline_reduction
        self.component_hash_buckets = component_hash_buckets
        if not isinstance(source, list) and cache_dir is not None:
            self._initialize_from_cache(
                Path(source),
                cache_dir=Path(cache_dir),
                path_id_column=path_id_column,
                on_error=on_error,
            )
            return
        rows = self._read_rows(source)
        if not rows:
            raise ValueError("Input CSV contains no rows")
        self.anomalies: list[PreprocessingAnomaly] = []
        self.rows: list[ReactionRow] = []
        self.group_to_rows: dict[str, list[int]] = {}
        group_parsed: dict[str, list[ParsedReaction]] = {}
        group_products: dict[str, list[Data]] = {}
        group_paths: dict[str, list[str]] = {}
        group_targets: dict[str, list[float]] = {}
        group_route_ids: dict[str, list[int]] = {}
        group_reactants: dict[str, Data] = {}
        group_components: dict[str, tuple[Data, ...]] = {}
        group_component_keys: dict[str, tuple[str, ...]] = {}
        group_keys: dict[str, str] = {}
        seen_path_ids: set[str] = set()

        for row_index, row in enumerate(rows):
            path_id = self._path_id(row, row_index, path_id_column)
            try:
                reaction = row.get(reaction_column, "").strip()
                if not reaction:
                    raise ValueError(f"empty {reaction_column!r}")
                raw_target = row.get(target_column, "").strip()
                if not raw_target:
                    raise ValueError(f"empty {target_column!r}")
                try:
                    target = float(raw_target)
                except ValueError as exc:
                    raise ValueError(f"non-numeric target: {raw_target!r}") from exc
                if not math.isfinite(target):
                    raise ValueError("non-finite target")
                if path_id in seen_path_ids:
                    raise ValueError(f"duplicate path id: {path_id}")
                conditions: dict[str, str] = {}
                for column in self.condition_columns:
                    if column not in row or not row[column].strip():
                        raise ValueError(f"missing configured condition {column!r}")
                    conditions[column] = row[column].strip()
                route_id = 0
                if self.route_id_column is not None:
                    raw_route_id = row.get(self.route_id_column, "").strip()
                    if not raw_route_id:
                        raise ValueError(f"missing configured route id {self.route_id_column!r}")
                    try:
                        route_id_value = float(raw_route_id)
                    except ValueError as exc:
                        raise ValueError(f"non-numeric route id: {raw_route_id!r}") from exc
                    if not route_id_value.is_integer() or route_id_value < 0:
                        raise ValueError("route id must be a non-negative integer")
                    route_id = int(route_id_value)
                parsed = parse_mapped_reaction(reaction)
                group_key = reaction_group_key(parsed, conditions)
                group_id = group_id_from_parsed(parsed, conditions)
                reactant_graph, product_graph = reaction_graphs(
                    parsed,
                    component_hash_buckets=self.component_hash_buckets,
                )
            except ValueError as exc:
                if on_error == "raise":
                    raise ValueError(f"Row {row_index}: {exc}") from exc
                self.anomalies.append(
                    PreprocessingAnomaly(
                        row_index=row_index,
                        path_id=path_id,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
                continue
            seen_path_ids.add(path_id)
            if group_id not in group_reactants:
                group_reactants[group_id] = reactant_graph
                group_components[group_id] = split_component_graphs(reactant_graph)
                group_component_keys[group_id] = tuple(
                    mapped_component_key(molecule) for molecule in parsed.reactant_mols
                )
                group_keys[group_id] = group_key
                group_parsed[group_id] = []
                group_products[group_id] = []
                group_paths[group_id] = []
                group_targets[group_id] = []
                group_route_ids[group_id] = []
                self.group_to_rows[group_id] = []
            elif group_keys[group_id] != group_key:
                raise RuntimeError(f"Group hash collision detected for {group_id}")
            elif (
                cast(PyGDataStub, group_reactants[group_id]).x.shape
                != cast(PyGDataStub, reactant_graph).x.shape
            ):
                raise RuntimeError(f"Reactant graph mismatch inside group {group_id}")
            record = ReactionRow(
                row_index=row_index,
                path_id=path_id,
                group_id=group_id,
                mapped_rxn_smiles=reaction,
                activation_energy=target,
                route_id=route_id,
                parsed=parsed,
                metadata=dict(row),
            )
            self.rows.append(record)
            self.group_to_rows[group_id].append(row_index)
            group_parsed[group_id].append(parsed)
            group_products[group_id].append(product_graph)
            group_paths[group_id].append(path_id)
            group_targets[group_id].append(target)
            group_route_ids[group_id].append(route_id)

        if not self.group_to_rows:
            raise ValueError("Input contains no valid reaction rows")
        self.group_ids = list(self.group_to_rows)
        self._samples: list[ReactionGroupSample] = []
        for group_id in self.group_ids:
            change_graphs = reaction_change_graphs(group_parsed[group_id])
            energies = torch.tensor(group_targets[group_id], dtype=torch.float32)
            baseline_target = float(energies.mean().item())
            self._samples.append(
                ReactionGroupSample(
                    group_id=group_id,
                    substrate_group=canonical_reactant_key(
                        group_parsed[group_id][0].mapped_reactants
                    ),
                    path_cgrs=change_graphs.paths,
                    path_delta_cgrs=change_graphs.deltas,
                    reactant=group_reactants[group_id],
                    components=group_components[group_id],
                    component_keys=group_component_keys[group_id],
                    products=group_products[group_id],
                    energies=energies,
                    baseline_target=baseline_target,
                    residual_targets=energies - baseline_target,
                    route_ids=torch.tensor(group_route_ids[group_id], dtype=torch.long),
                    path_ids=group_paths[group_id],
                    mappings=group_parsed[group_id],
                )
            )
        self.group_index = {group_id: index for index, group_id in enumerate(self.group_ids)}
        self.path_targets = {
            path.path_id: (path.baseline_target, path.residual_target)
            for sample in self._samples
            for path in sample.path_samples()
        }
        self.cache_info = DatasetCacheInfo(
            enabled=False,
            hit=False,
            path=None,
            cache_key=None,
        )

    @staticmethod
    def _distribution_version(distribution: str) -> str:
        try:
            return version(distribution)
        except PackageNotFoundError:
            return "unavailable"

    def _cache_key(
        self,
        source: Path,
        *,
        path_id_column: str | None,
        on_error: Literal["raise", "record"],
    ) -> str:
        options = {
            "schema_version": DATASET_CACHE_SCHEMA_VERSION,
            "target_column": self.target_column,
            "reaction_column": self.reaction_column,
            "path_id_column": path_id_column,
            "condition_columns": self.condition_columns,
            "route_id_column": self.route_id_column,
            "baseline_reduction": self.baseline_reduction,
            "component_hash_buckets": self.component_hash_buckets,
            "on_error": on_error,
            "torch_version": torch.__version__,
            "pyg_version": self._distribution_version("torch-geometric"),
            "rdkit_version": self._distribution_version("rdkit"),
        }
        digest = hashlib.sha256(
            json.dumps(options, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _cache_payload(self, cache_key: str) -> _DatasetCachePayload:
        return _DatasetCachePayload(
            schema_version=DATASET_CACHE_SCHEMA_VERSION,
            cache_key=cache_key,
            rows=self.rows,
            anomalies=self.anomalies,
            group_to_rows=self.group_to_rows,
            group_ids=self.group_ids,
            samples=self._samples,
            group_index=self.group_index,
            path_targets=self.path_targets,
        )

    def _restore_cache_payload(self, payload: _DatasetCachePayload) -> None:
        self.rows = payload.rows
        self.anomalies = payload.anomalies
        self.group_to_rows = payload.group_to_rows
        self.group_ids = payload.group_ids
        self._samples = payload.samples
        self.group_index = payload.group_index
        self.path_targets = payload.path_targets

    @staticmethod
    def _load_cache(path: Path, cache_key: str) -> _DatasetCachePayload | None:
        if not path.is_file():
            return None
        try:
            loaded = torch.load(path, map_location="cpu", weights_only=False, mmap=True)
            if not isinstance(loaded, _DatasetCachePayload):
                raise TypeError("Unexpected dataset cache payload")
            if loaded.schema_version != DATASET_CACHE_SCHEMA_VERSION:
                raise ValueError("Dataset cache schema mismatch")
            if loaded.cache_key != cache_key:
                raise ValueError("Dataset cache key mismatch")
            return loaded
        except (
            AttributeError,
            EOFError,
            ImportError,
            OSError,
            pickle.UnpicklingError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return None

    @staticmethod
    def _write_cache(path: Path, payload: _DatasetCachePayload) -> None:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
        try:
            torch.save(payload, temporary_path)
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _initialize_from_cache(
        self,
        source: Path,
        *,
        cache_dir: Path,
        path_id_column: str | None,
        on_error: Literal["raise", "record"],
    ) -> None:
        cache_key = self._cache_key(
            source,
            path_id_column=path_id_column,
            on_error=on_error,
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{source.stem}-{cache_key}.pt"
        payload = self._load_cache(cache_path, cache_key)
        hit = payload is not None
        if payload is None:
            with FileLock(f"{cache_path}.lock"):
                payload = self._load_cache(cache_path, cache_key)
                hit = payload is not None
                if payload is None:
                    uncached = type(self)(
                        source,
                        target_column=self.target_column,
                        reaction_column=self.reaction_column,
                        path_id_column=path_id_column,
                        condition_columns=self.condition_columns,
                        route_id_column=self.route_id_column,
                        baseline_reduction=self.baseline_reduction,
                        component_hash_buckets=self.component_hash_buckets,
                        on_error=on_error,
                        cache_dir=None,
                    )
                    payload = uncached._cache_payload(cache_key)
                    self._write_cache(cache_path, payload)
        if payload is None:  # pragma: no cover - guarded by the build branch above.
            raise RuntimeError("Dataset cache initialization failed")
        self._restore_cache_payload(payload)
        self.cache_info = DatasetCacheInfo(
            enabled=True,
            hit=hit,
            path=str(cache_path),
            cache_key=cache_key,
        )

    @staticmethod
    def _read_rows(source: str | Path | list[dict[str, str]]) -> list[dict[str, str]]:
        if isinstance(source, list):
            return source
        with Path(source).open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    @staticmethod
    def _path_id(row: dict[str, str], row_index: int, column: str | None) -> str:
        candidates = [column] if column else ["path_id", "source_row_index", "reaction_id"]
        for candidate in candidates:
            if candidate and row.get(candidate, "").strip():
                return row[candidate].strip()
        return f"path_{row_index:08d}"

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> ReactionGroupSample:
        return self._samples[index]

    def processed_rows(self, split_by_group: dict[str, str] | None = None) -> list[dict[str, str]]:
        """Return the required path-wise preprocessed table rows."""
        output: list[dict[str, str]] = []
        for row in self.rows:
            baseline_target, residual_target = self.path_targets[row.path_id]
            item = {
                "path_id": row.path_id,
                "group_id": row.group_id,
                "mapped_rxn_smiles": row.mapped_rxn_smiles,
                "activation_energy": str(row.activation_energy),
                "baseline_target": str(baseline_target),
                "residual_target": str(residual_target),
            }
            if split_by_group is not None:
                item["split"] = split_by_group[row.group_id]
            output.append(item)
        return output


class ReactionGroupSubset(Dataset[ReactionGroupSample]):
    """A lightweight group-index subset that preserves group sampling semantics."""

    def __init__(self, dataset: ReactionGroupDataset, indices: list[int]) -> None:
        self.dataset = dataset
        self.indices = indices

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, index: int) -> ReactionGroupSample:
        return self.dataset[self.indices[index]]


class ReactionPathDataset(Dataset[ReactionPathSample]):
    """Path-level view over selected groups, retaining group-level split isolation."""

    def __init__(self, dataset: ReactionGroupDataset, group_indices: list[int]) -> None:
        self.group_dataset = dataset
        self.group_indices = list(group_indices)
        self.group_ids = [dataset.group_ids[index] for index in self.group_indices]
        self._samples = [
            path
            for group_index in self.group_indices
            for path in dataset[group_index].path_samples()
        ]

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> ReactionPathSample:
        return self._samples[index]

    @property
    def samples(self) -> tuple[ReactionPathSample, ...]:
        """Expose the immutable path ordering used by batch samplers."""
        return tuple(self._samples)

    def target_statistics(
        self,
        *,
        residual_multi_path_only: bool = False,
    ) -> TargetStatistics:
        """Compute split moments, optionally excluding singleton residual targets."""
        if not self._samples:
            raise ValueError("Cannot compute target statistics for an empty path dataset")

        def moments(values: list[float]) -> tuple[float, float]:
            tensor = torch.tensor(values, dtype=torch.float64)
            mean = float(tensor.mean().item())
            std = float(tensor.std(correction=0).clamp_min(1e-8).item())
            return mean, std

        target_mean, target_std = moments([sample.energy for sample in self._samples])
        baseline_mean, baseline_std = moments([sample.baseline_target for sample in self._samples])
        residual_samples = self._samples
        if residual_multi_path_only:
            multi_path_groups = {
                self.group_dataset[index].group_id
                for index in range(len(self.group_dataset))
                if len(self.group_dataset[index]) > 1
                and self.group_dataset[index].group_id in self.group_ids
            }
            residual_samples = [
                sample for sample in self._samples if sample.group_id in multi_path_groups
            ]
            if not residual_samples:
                raise ValueError("No multi-path groups available for residual statistics")
        residual_mean, residual_std = moments(
            [sample.residual_target for sample in residual_samples]
        )
        return TargetStatistics(
            target_mean=target_mean,
            target_std=target_std,
            baseline_mean=baseline_mean,
            baseline_std=baseline_std,
            residual_mean=residual_mean,
            residual_std=residual_std,
        )


__all__ = [
    "DatasetCacheInfo",
    "PreprocessingAnomaly",
    "ReactionGroupDataset",
    "ReactionGroupSample",
    "ReactionGroupSubset",
    "ReactionPathDataset",
    "ReactionPathSample",
    "ReactionRow",
    "TargetStatistics",
]
