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
    assert set(processed[0]) == {
        "path_id",
        "group_id",
        "mapped_rxn_smiles",
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
