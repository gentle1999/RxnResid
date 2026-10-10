import csv
from pathlib import Path

import pytest

import rxnresid.data.dataset as dataset_module
from rxnresid.data.dataset import ReactionGroupDataset
from rxnresid.data.prepare import prepare_table


REACTION = "[CH3:1][OH:2]>>[CH3:1][OH:2]"


def _write_cache_source(path: Path, *, target: float = 10.0) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["path_id", "rxn_smiles", "G_T_activate"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "path_id": "path_0",
                "rxn_smiles": REACTION,
                "G_T_activate": str(target),
            }
        )


def test_dataset_records_bad_rows_and_uses_conditions() -> None:
    rows = [
        {"rxn_smiles": REACTION, "G_T_activate": "10.0", "solvent": "a", "path_id": "a"},
        {"rxn_smiles": REACTION, "G_T_activate": "11.0", "solvent": "b", "path_id": "b"},
        {"rxn_smiles": "invalid", "G_T_activate": "12.0", "solvent": "c", "path_id": "c"},
    ]
    grouped = ReactionGroupDataset(
        rows,
        condition_columns=["solvent"],
        on_error="record",
    )
    assert len(grouped) == 2
    assert len(grouped.anomalies) == 1
    assert grouped.anomalies[0].path_id == "c"


def test_prepare_table_writes_required_columns_and_anomalies(tmp_path) -> None:  # type: ignore[no-untyped-def]
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "processed.csv"
    anomaly_path = tmp_path / "anomalies.csv"
    with input_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["path_id", "rxn_smiles", "G_T_activate", "solvent"],
        )
        writer.writeheader()
        for index in range(12):
            writer.writerow(
                {
                    "path_id": f"path_{index}",
                    "rxn_smiles": REACTION,
                    "G_T_activate": str(10 + index),
                    "solvent": f"solvent_{index}",
                }
            )
        writer.writerow(
            {
                "path_id": "bad",
                "rxn_smiles": "invalid",
                "G_T_activate": "20",
                "solvent": "bad",
            }
        )
    report = prepare_table(
        input_path,
        output_path,
        anomalies_path=anomaly_path,
        condition_columns=["solvent"],
    )
    with output_path.open(newline="", encoding="utf-8") as handle:
        processed = list(csv.DictReader(handle))
    with anomaly_path.open(newline="", encoding="utf-8") as handle:
        anomalies = list(csv.DictReader(handle))
    assert set(processed[0]) >= {
        "path_id",
        "group_id",
        "mapped_rxn_smiles",
        "raw_rxn_smiles",
        "source_map_to_coordinate",
        "alignment_version",
        "alignment_hash",
        "adaptation_version",
        "aligned_rxn_smiles",
        "reference_path_id",
        "csv_row_index",
        "csv_line_number",
        "route_label",
        "route_index",
        "activation_energy",
        "baseline_target",
        "residual_target",
        "split",
    }
    assert report == {
        "rows": 12,
        "groups": 12,
        "train_groups": 10,
        "valid_groups": 1,
        "test_groups": 1,
        "anomalies": 1,
    }
    assert anomalies[0]["path_id"] == "bad"
    assert anomalies[0]["rule"] == "reaction_syntax"
    assert anomalies[0]["csv_line_number"] == "14"
    assert processed[0]["solvent"] == "solvent_0"


def test_dataset_persistent_cache_skips_reprocessing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.csv"
    cache_dir = tmp_path / "cache"
    _write_cache_source(input_path)

    first = ReactionGroupDataset(input_path, cache_dir=cache_dir)
    assert first.cache_info.enabled
    assert not first.cache_info.hit
    assert first.cache_info.path is not None
    assert Path(first.cache_info.path).is_file()

    def fail_if_reparsed(*args: object, **kwargs: object) -> None:
        raise AssertionError("cache hit unexpectedly reparsed the reaction")

    monkeypatch.setattr(dataset_module, "parse_mapped_reaction", fail_if_reparsed)
    second = ReactionGroupDataset(input_path, cache_dir=cache_dir)
    assert second.cache_info.hit
    assert second.path_targets == first.path_targets


def test_dataset_cache_invalidates_changed_source_and_recovers_corruption(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    cache_dir = tmp_path / "cache"
    _write_cache_source(input_path, target=10.0)
    first = ReactionGroupDataset(input_path, cache_dir=cache_dir)
    first_cache_path = Path(first.cache_info.path or "")

    _write_cache_source(input_path, target=12.0)
    changed = ReactionGroupDataset(input_path, cache_dir=cache_dir)
    changed_cache_path = Path(changed.cache_info.path or "")
    assert not changed.cache_info.hit
    assert changed_cache_path != first_cache_path
    assert next(iter(changed.path_targets.values()))[0] == 12.0

    changed_cache_path.write_bytes(b"not a torch cache")
    recovered = ReactionGroupDataset(input_path, cache_dir=cache_dir)
    assert not recovered.cache_info.hit
    assert next(iter(recovered.path_targets.values()))[0] == 12.0


def test_cache_preserves_skipped_row_indices_and_alignment_audit(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    rows = [
        {"path_id": "first", "rxn_smiles": REACTION, "G_T_activate": "1", "profile_id": "000001"},
        {"path_id": "bad", "rxn_smiles": REACTION, "G_T_activate": "inf", "profile_id": "000002"},
        {"path_id": "last", "rxn_smiles": REACTION, "G_T_activate": "2", "profile_id": "000003"},
    ]
    with input_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    cache_dir = tmp_path / "cache"
    first = ReactionGroupDataset(input_path, on_error="record", cache_dir=cache_dir)
    cached = ReactionGroupDataset(input_path, on_error="record", cache_dir=cache_dir)
    assert cached.cache_info.hit
    assert cached.group_to_rows == first.group_to_rows == {first.group_ids[0]: [0, 1]}
    assert cached.group_to_source_rows == {first.group_ids[0]: [0, 2]}
    assert cached.processed_rows() == first.processed_rows()
    assert cached.anomalies == first.anomalies


def test_cache_invalidates_alignment_version_stereo_and_route_vocabulary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.csv"
    _write_cache_source(input_path)
    cache_dir = tmp_path / "cache"
    original = ReactionGroupDataset(input_path, cache_dir=cache_dir)
    no_stereo = ReactionGroupDataset(input_path, include_stereo=False, cache_dir=cache_dir)
    assert original.cache_info.cache_key != no_stereo.cache_info.cache_key
    monkeypatch.setattr(dataset_module, "ALIGNMENT_VERSION", "test-next-alignment")
    changed = ReactionGroupDataset(input_path, cache_dir=cache_dir)
    assert not changed.cache_info.hit
    assert changed.cache_info.cache_key != original.cache_info.cache_key
    vocabulary = ReactionGroupDataset(input_path, route_id_vocabulary={"0": 3}, cache_dir=cache_dir)
    assert vocabulary.cache_info.cache_key != changed.cache_info.cache_key
    assert vocabulary[0].route_ids.tolist() == [3]
