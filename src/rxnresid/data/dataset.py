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
from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

import torch
from filelock import FileLock
from torch import Tensor
from torch.utils.data import Dataset
from torch_geometric.data import Data

from rxnresid.data.change_graphs import (
    ALIGNMENT_VERSION,
    align_mapped_reaction,
    reaction_change_graphs,
)
from rxnresid.data.featurizer import (
    COMPONENT_HASH_BUCKETS,
    mapped_component_key,
    reaction_graphs,
    split_component_graphs,
)
from rxnresid.data.grouping import canonical_reactant_key, group_id_from_parsed, reaction_group_key
from rxnresid.data.reaction_parser import ParsedReaction, parse_mapped_reaction


DATASET_CACHE_SCHEMA_VERSION = 9
ADAPTATION_VERSION = "rxnresid-data-contract-v2"


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
    route_label: str = "0"
    raw_rxn_smiles: str = ""
    source_map_to_coordinate: dict[int, int] | None = None
    alignment_hash: str = ""
    aligned_rxn_smiles: str = ""
    reference_path_id: str = ""
    csv_line_number: int | None = None
    adaptation_version: str = ADAPTATION_VERSION


class RecordValidationError(ValueError):
    """A source-record failure with a stable rule for audit reports."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule


@dataclass(frozen=True)
class PreprocessingAnomaly:
    """One invalid source row retained for a machine-readable audit report."""

    row_index: int
    path_id: str
    error_type: str
    message: str
    rule: str = "record_validation"
    csv_line_number: int | None = None


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
    path_source_map_to_coordinate: tuple[dict[int, int], ...] = ()
    route_labels: tuple[str, ...] = ()
    path_aligned_mappings: tuple[ParsedReaction, ...] = ()

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
                route_label=(
                    self.route_labels[path_index]
                    if self.route_labels
                    else str(self.route_ids[path_index].item())
                ),
                path_id=self.path_ids[path_index],
                mapping=self.mappings[path_index],
                aligned_mapping=(
                    self.path_aligned_mappings[path_index] if self.path_aligned_mappings else None
                ),
                source_map_to_coordinate=(
                    self.path_source_map_to_coordinate[path_index]
                    if self.path_source_map_to_coordinate
                    else None
                ),
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
    source_map_to_coordinate: dict[int, int] | None = None
    route_label: str = "0"
    aligned_mapping: ParsedReaction | None = None


@dataclass
class _DatasetCachePayload:
    schema_version: int
    cache_key: str
    rows: list[ReactionRow]
    anomalies: list[PreprocessingAnomaly]
    group_to_rows: dict[str, list[int]]
    group_to_source_rows: dict[str, list[int]]
    route_id_vocabulary: dict[str, int]
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
        route_id_vocabulary: dict[str, int] | None = None,
        include_stereo: bool = True,
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
        self._specified_route_id_vocabulary = (
            dict(route_id_vocabulary) if route_id_vocabulary is not None else None
        )
        self.include_stereo = include_stereo
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
        rows, csv_lines = self._read_rows(source)
        if not rows:
            raise ValueError("Input CSV contains no rows")
        self.anomalies: list[PreprocessingAnomaly] = []
        self.rows: list[ReactionRow] = []
        self.group_to_rows: dict[str, list[int]] = {}
        self.group_to_source_rows: dict[str, list[int]] = {}
        group_parsed: dict[str, list[ParsedReaction]] = {}
        group_paths: dict[str, list[str]] = {}
        group_targets: dict[str, list[float]] = {}
        group_route_labels: dict[str, list[str]] = {}
        group_keys: dict[str, str] = {}
        seen_path_ids: set[str] = set()

        for row_index, row in enumerate(rows):
            path_id = self._path_id(row, path_id_column)
            try:
                if any(key is None or value is None for key, value in row.items()):
                    raise RecordValidationError(
                        "complete_csv_record", "CSV record has missing or extra fields"
                    )
                row = {key: str(value) for key, value in row.items()}
                if not path_id.strip():
                    raise RecordValidationError("nonempty_path_id", "empty path_id")
                if path_id in seen_path_ids:
                    raise RecordValidationError("unique_path_id", f"duplicate path id: {path_id}")
                seen_path_ids.add(path_id)
                raw_reaction = row.get(reaction_column, "")
                reaction = raw_reaction.strip()
                if not reaction:
                    raise RecordValidationError("nonempty_reaction", f"empty {reaction_column!r}")
                raw_target = row.get(target_column, "").strip()
                if not raw_target:
                    raise RecordValidationError("finite_target", f"empty {target_column!r}")
                try:
                    target = float(raw_target)
                except ValueError as exc:
                    raise RecordValidationError(
                        "finite_target", f"non-numeric target: {raw_target!r}"
                    ) from exc
                if not math.isfinite(target):
                    raise RecordValidationError("finite_target", "non-finite target")
                conditions: dict[str, str] = {}
                for column in self.condition_columns:
                    if column not in row or not row[column].strip():
                        raise RecordValidationError(
                            "configured_condition", f"missing configured condition {column!r}"
                        )
                    conditions[column] = row[column].strip()
                route_label = "0"
                if self.route_id_column is not None:
                    route_label = row.get(self.route_id_column, "")
                    if not route_label.strip():
                        raise RecordValidationError(
                            "configured_route_id",
                            f"missing configured route id {self.route_id_column!r}",
                        )
                parsed = parse_mapped_reaction(reaction, require_complete_mapping=True)
                group_key = reaction_group_key(
                    parsed, conditions, include_stereo=self.include_stereo
                )
                group_id = group_id_from_parsed(
                    parsed, conditions, include_stereo=self.include_stereo
                )
            except ValueError as exc:
                rule = getattr(exc, "rule", "graph_features")
                line = (
                    f" (CSV line {csv_lines[row_index]})"
                    if csv_lines[row_index] is not None
                    else ""
                )
                message = f"Row {row_index} path_id {path_id!r}: [{rule}]{line} {exc}"
                if on_error == "raise":
                    raise ValueError(message) from exc
                self.anomalies.append(
                    PreprocessingAnomaly(
                        row_index=row_index,
                        path_id=path_id,
                        error_type=type(exc).__name__,
                        message=message,
                        rule=rule,
                        csv_line_number=csv_lines[row_index],
                    )
                )
                continue
            if group_id not in group_keys:
                group_keys[group_id] = group_key
                group_parsed[group_id] = []
                group_paths[group_id] = []
                group_targets[group_id] = []
                group_route_labels[group_id] = []
                self.group_to_rows[group_id] = []
                self.group_to_source_rows[group_id] = []
            elif group_keys[group_id] != group_key:
                raise RuntimeError(f"Group hash collision detected for {group_id}")
            record = ReactionRow(
                row_index=row_index,
                path_id=path_id,
                group_id=group_id,
                mapped_rxn_smiles=reaction,
                activation_energy=target,
                route_id=0,
                parsed=parsed,
                metadata=dict(row),
                route_label=route_label,
                raw_rxn_smiles=raw_reaction,
                csv_line_number=csv_lines[row_index],
            )
            self.rows.append(record)
            self.group_to_rows[group_id].append(len(self.rows) - 1)
            self.group_to_source_rows[group_id].append(row_index)
            group_parsed[group_id].append(parsed)
            group_paths[group_id].append(path_id)
            group_targets[group_id].append(target)
            group_route_labels[group_id].append(route_label)

        if not self.group_to_rows:
            details = "; ".join(anomaly.message for anomaly in self.anomalies[:3])
            raise ValueError(f"Input contains no valid reaction rows: {details}")
        labels = sorted({row.route_label for row in self.rows})
        if self._specified_route_id_vocabulary is None:
            self.route_id_vocabulary = {label: index for index, label in enumerate(labels)}
        else:
            self.route_id_vocabulary = self._specified_route_id_vocabulary
            missing = set(labels) - set(self.route_id_vocabulary)
            if missing:
                raise ValueError(f"Route ID vocabulary is missing labels: {sorted(missing)}")
            indices = list(self.route_id_vocabulary.values())
            if any(not isinstance(index, int) or index < 0 for index in indices):
                raise ValueError("Route ID vocabulary indices must be non-negative integers")
            if len(set(indices)) != len(indices):
                raise ValueError("Route ID vocabulary indices must be unique")
        self.rows = [
            replace(row, route_id=self.route_id_vocabulary[row.route_label]) for row in self.rows
        ]
        self.group_ids = list(self.group_to_rows)
        self._samples: list[ReactionGroupSample] = []
        for group_id in self.group_ids:
            change_graphs = reaction_change_graphs(
                group_parsed[group_id], include_stereo=self.include_stereo
            )
            reference_index = change_graphs.reference_path_index
            reference_path_id = group_paths[group_id][reference_index]
            aligned_mappings = [
                align_mapped_reaction(mapping, change_graphs.path_source_map_to_coordinate[index])
                for index, mapping in enumerate(group_parsed[group_id])
            ]
            for path_index, row_index in enumerate(self.group_to_rows[group_id]):
                correspondence = change_graphs.path_source_map_to_coordinate[path_index]
                aligned_row = self.rows[row_index]
                audit = json.dumps(
                    {
                        "version": ALIGNMENT_VERSION,
                        "adaptation_version": ADAPTATION_VERSION,
                        "reaction": aligned_row.raw_rxn_smiles,
                        "reference_path_id": reference_path_id,
                        "reference_reactants": aligned_mappings[reference_index].mapped_reactants,
                        "correspondence": correspondence,
                        "include_stereo": self.include_stereo,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                self.rows[row_index] = replace(
                    aligned_row,
                    source_map_to_coordinate=correspondence,
                    alignment_hash=hashlib.sha256(audit.encode("utf-8")).hexdigest(),
                    aligned_rxn_smiles=(
                        aligned_mappings[path_index].mapped_reactants
                        + ">>"
                        + aligned_mappings[path_index].mapped_products
                    ),
                    reference_path_id=reference_path_id,
                )
            reference_mapping = aligned_mappings[reference_index]
            reference_reactant, _ = reaction_graphs(
                reference_mapping,
                component_hash_buckets=self.component_hash_buckets,
            )
            reference_components = split_component_graphs(reference_reactant)
            reference_component_keys = tuple(
                mapped_component_key(molecule) for molecule in reference_mapping.reactant_mols
            )
            normalized_products = [
                reaction_graphs(mapping, component_hash_buckets=self.component_hash_buckets)[1]
                for mapping in aligned_mappings
            ]
            energies = torch.tensor(group_targets[group_id], dtype=torch.float32)
            baseline_target = float(energies.mean().item())
            self._samples.append(
                ReactionGroupSample(
                    group_id=group_id,
                    substrate_group=canonical_reactant_key(
                        group_parsed[group_id][0].mapped_reactants,
                        include_stereo=self.include_stereo,
                    ),
                    path_cgrs=change_graphs.paths,
                    path_delta_cgrs=change_graphs.deltas,
                    reactant=reference_reactant,
                    components=reference_components,
                    component_keys=reference_component_keys,
                    products=normalized_products,
                    energies=energies,
                    baseline_target=baseline_target,
                    residual_targets=energies - baseline_target,
                    route_ids=torch.tensor(
                        [self.route_id_vocabulary[label] for label in group_route_labels[group_id]],
                        dtype=torch.long,
                    ),
                    route_labels=tuple(group_route_labels[group_id]),
                    path_ids=group_paths[group_id],
                    mappings=group_parsed[group_id],
                    path_aligned_mappings=tuple(aligned_mappings),
                    path_source_map_to_coordinate=change_graphs.path_source_map_to_coordinate,
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
            "alignment_version": ALIGNMENT_VERSION,
            "adaptation_version": ADAPTATION_VERSION,
            "include_stereo": self.include_stereo,
            "target_column": self.target_column,
            "reaction_column": self.reaction_column,
            "path_id_column": path_id_column,
            "condition_columns": self.condition_columns,
            "route_id_column": self.route_id_column,
            "route_id_vocabulary": self._specified_route_id_vocabulary,
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
            group_to_source_rows=self.group_to_source_rows,
            route_id_vocabulary=self.route_id_vocabulary,
            group_ids=self.group_ids,
            samples=self._samples,
            group_index=self.group_index,
            path_targets=self.path_targets,
        )

    def _restore_cache_payload(self, payload: _DatasetCachePayload) -> None:
        self.rows = payload.rows
        self.anomalies = payload.anomalies
        self.group_to_rows = payload.group_to_rows
        self.group_to_source_rows = payload.group_to_source_rows
        self.route_id_vocabulary = payload.route_id_vocabulary
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
                        route_id_vocabulary=self._specified_route_id_vocabulary,
                        include_stereo=self.include_stereo,
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
    def _read_rows(
        source: str | Path | list[dict[str, str]],
    ) -> tuple[list[dict[str, str]], list[int | None]]:
        if isinstance(source, list):
            return source, [None] * len(source)
        rows: list[dict[str, str]] = []
        lines: list[int | None] = []
        with Path(source).open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            if len(header) != len(set(header)):
                raise ValueError("CSV header contains duplicate columns")
            while True:
                first_line = reader.line_num + 1
                try:
                    fields = next(reader)
                except StopIteration:
                    break
                if not fields:
                    continue
                # DictReader represents ragged records with None values/keys;
                # retain that behavior so the per-record validator reports them.
                row: dict[Any, Any] = dict(zip(header, fields, strict=False))
                for missing in header[len(fields) :]:
                    row[missing] = None
                if len(fields) > len(header):
                    row[None] = fields[len(header) :]
                rows.append(row)
                lines.append(first_line)
        return rows, lines

    @staticmethod
    def _path_id(row: dict[str, str], column: str | None) -> str:
        candidates = (
            [column]
            if column
            else ["path_id", "source_row_index", "reaction_id", "mapped_reaction_id"]
        )
        for candidate in candidates:
            if candidate and candidate in row:
                value = row[candidate]
                return str(value) if value is not None else ""
        return ""

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
                **row.metadata,
                "csv_row_index": str(row.row_index),
                "csv_line_number": str(row.csv_line_number)
                if row.csv_line_number is not None
                else "",
                "path_id": row.path_id,
                "group_id": row.group_id,
                "mapped_rxn_smiles": row.mapped_rxn_smiles,
                "raw_rxn_smiles": row.raw_rxn_smiles,
                "source_map_to_coordinate": json.dumps(
                    row.source_map_to_coordinate, sort_keys=True, separators=(",", ":")
                ),
                "alignment_version": ALIGNMENT_VERSION,
                "adaptation_version": row.adaptation_version,
                "aligned_rxn_smiles": row.aligned_rxn_smiles,
                "reference_path_id": row.reference_path_id,
                "route_label": row.route_label,
                "route_index": str(row.route_id),
                "alignment_hash": row.alignment_hash,
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
