"""Regression tests for identity, alignment, and source-record validation."""

import json
from dataclasses import replace

import pytest
import torch

from rxnresid.data.change_graphs import ALIGNMENT_VERSION, reaction_change_graphs
from rxnresid.data.dataset import ReactionGroupDataset
from rxnresid.data.grouping import canonical_reactant_key, group_id_from_reaction
from rxnresid.data.reaction_parser import parse_mapped_reaction
from rxnresid.data.split import create_group_kfold_manifest


REACTION = "[CH3:1][CH2:2][OH:3]>>[CH3:1][CH:2]=[O:3]"
REMAPPED = "[OH:30][CH2:20][CH3:10]>>[O:30]=[CH:20][CH3:10]"


def _row(path_id: str, reaction: str = REACTION, **extra: str) -> dict[str, str]:
    return {"path_id": path_id, "rxn_smiles": reaction, "G_T_activate": "1.5", **extra}


def test_substrate_key_uses_unmapped_canonical_smiles() -> None:
    first = "[CH3:1][OH:2].[CH3:3][CH2:4][OH:5]"
    second = "[OH:50][CH2:40][CH3:30].[OH:20][CH3:10]"
    key = canonical_reactant_key(first)
    assert key == canonical_reactant_key(second)
    assert ":" not in key
    assert group_id_from_reaction(first + ">>" + first) == group_id_from_reaction(
        second + ">>" + second
    )


def test_product_and_delta_use_the_same_aligned_coordinates() -> None:
    dataset = ReactionGroupDataset([_row("a", REACTION), _row("b", REMAPPED)])
    sample = dataset[0]
    assert sample.path_source_map_to_coordinate[1] == {10: 1, 20: 2, 30: 3}
    assert torch.equal(sample.path_cgrs[0].x, sample.path_cgrs[1].x)
    assert torch.equal(sample.path_delta_cgrs[0].x, sample.path_delta_cgrs[1].x)
    assert torch.equal(sample.products[0].atom_map_numbers, sample.products[1].atom_map_numbers)
    assert torch.equal(sample.products[0].x, sample.products[1].x)
    assert torch.equal(sample.products[0].edge_index, sample.products[1].edge_index)
    assert torch.equal(sample.path_cgrs[0].edge_attr, sample.path_cgrs[1].edge_attr)
    assert torch.count_nonzero(sample.path_delta_cgrs[0].x) == 0
    assert torch.count_nonzero(sample.path_delta_cgrs[0].edge_attr) == 0
    assert dataset.rows[1].raw_rxn_smiles == REMAPPED
    assert json.loads(dataset.processed_rows()[1]["source_map_to_coordinate"]) == {
        "10": 1,
        "20": 2,
        "30": 3,
    }
    assert dataset.rows[1].alignment_hash
    assert dataset.processed_rows()[1]["alignment_version"] == ALIGNMENT_VERSION


def test_stereo_grouping_is_explicit_and_alignment_accepts_the_policy() -> None:
    left = "[F:1][C@:2]([Cl:3])([Br:4])[I:5]"
    right = "[F:11][C@@:12]([Cl:13])([Br:14])[I:15]"
    left_reaction = left + ">>" + left
    right_reaction = right + ">>" + right
    assert group_id_from_reaction(left_reaction) != group_id_from_reaction(right_reaction)
    assert group_id_from_reaction(left_reaction, include_stereo=False) == group_id_from_reaction(
        right_reaction, include_stereo=False
    )
    dataset = ReactionGroupDataset(
        [_row("left", left_reaction), _row("right", right_reaction)],
        include_stereo=False,
    )
    assert len(dataset) == 1
    graphs = reaction_change_graphs(
        [parse_mapped_reaction(left_reaction), parse_mapped_reaction(right_reaction)],
        include_stereo=False,
    )
    assert len(graphs.paths) == 2


@pytest.mark.parametrize(
    ("bad", "rule"),
    [
        (_row("", REACTION), "empty path_id"),
        (_row("bad", REACTION, G_T_activate="nan"), "non-finite target"),
        (_row("bad", "[CH3:1].[OH:2]>>[CH3:1]O"), "positive atom map"),
        (_row("bad", "[CH3:1].[OH:1]>>[CH3:1].[OH:2]"), "Duplicate atom map"),
        (_row("bad", "[CH3:1]>>[OH:1]"), "changes element or isotope"),
        (_row("bad", "[13CH4:1]>>[CH4:1]"), "changes element or isotope"),
    ],
)
def test_bad_records_report_source_row_path_and_rule(bad: dict[str, str], rule: str) -> None:
    dataset = ReactionGroupDataset([_row("good"), bad, _row("last")], on_error="record")
    assert len(dataset.rows) == 2
    group = dataset.group_ids[0]
    assert dataset.group_to_rows[group] == [0, 1]
    assert dataset.group_to_source_rows[group] == [0, 2]
    anomaly = dataset.anomalies[0]
    assert anomaly.row_index == 1
    assert "Row 1" in anomaly.message
    assert "path_id" in anomaly.message
    assert rule in anomaly.message


def test_duplicate_path_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="Row 1 path_id 'same': .*duplicate path id"):
        ReactionGroupDataset([_row("same"), _row("same")])


def test_external_ids_are_preserved_and_encoded_separately() -> None:
    large = "900719925474099312345678901"
    dataset = ReactionGroupDataset(
        [_row("000123", prod_id=large), _row("000124", prod_id="000000001")],
        route_id_column="prod_id",
    )
    assert [row.path_id for row in dataset.rows] == ["000123", "000124"]
    assert [row.route_label for row in dataset.rows] == [large, "000000001"]
    assert dataset.route_id_vocabulary == {"000000001": 0, large: 1}
    assert dataset[0].route_ids.tolist() == [1, 0]
    assert dataset[0].route_labels == (large, "000000001")


@pytest.mark.parametrize("count", [1, 7, 27])
def test_actual_record_count_drives_loading(count: int) -> None:
    dataset = ReactionGroupDataset([_row(f"path-{i}") for i in range(count)])
    assert len(dataset.rows) == count
    assert len(dataset[0]) == count


def test_fold_ids_cover_actual_groups_and_row_count_is_snapshot_only() -> None:
    rows = [_row(f"path-{i}", condition=str(i)) for i in range(5)]
    dataset = ReactionGroupDataset(rows, condition_columns=["condition"])
    manifest = create_group_kfold_manifest(dataset, num_folds=3)
    assert manifest.dataset_row_count == 5
    for fold in manifest.folds:
        assigned = set(fold.train_group_ids + fold.valid_group_ids + fold.test_group_ids)
        assert assigned == set(dataset.group_ids)
        manifest.resolve(dataset, fold.fold_index)
    changed = ReactionGroupDataset(
        rows + [_row("extra", condition="0")], condition_columns=["condition"]
    )
    with pytest.raises(ValueError, match="row count"):
        manifest.resolve(changed, 0)
    duplicate = replace(
        manifest,
        folds=(
            replace(
                manifest.folds[0],
                train_group_ids=manifest.folds[0].train_group_ids * 2,
            ),
            *manifest.folds[1:],
        ),
    )
    with pytest.raises(ValueError, match="duplicate group"):
        duplicate.resolve(dataset, 0)


def test_isotopes_remain_distinct_when_stereo_is_ignored() -> None:
    labeled = "[13CH3:1][OH:2]"
    unlabeled = "[CH3:10][OH:20]"
    assert canonical_reactant_key(labeled, include_stereo=False) != canonical_reactant_key(
        unlabeled, include_stereo=False
    )


def test_explicit_hydrogens_are_validated_and_preserved() -> None:
    reaction = "[H:2][CH3:1]>>[H:2][CH3:1]"
    parsed = parse_mapped_reaction(reaction, require_complete_mapping=True)
    assert set(parsed.atom_mapping) == {1, 2}
    dataset = ReactionGroupDataset([_row("hydrogen", reaction)])
    assert set(dataset[0].reactant.atom_map_numbers.tolist()) == {1, 2}
    for bad in ["[H][CH3:1]>>[H][CH3:1]", "[H:2][CH3:1]>>[H:3][CH3:1]"]:
        with pytest.raises(ValueError, match="atom map"):
            ReactionGroupDataset([_row("bad", bad)])


def test_missing_path_id_is_not_synthesized() -> None:
    with pytest.raises(ValueError, match="empty path_id"):
        ReactionGroupDataset([{"rxn_smiles": REACTION, "G_T_activate": "1"}])


@pytest.mark.parametrize("missing", ["rxn_smiles", "G_T_activate"])
def test_ragged_csv_is_reported_without_losing_valid_rows(tmp_path, missing) -> None:
    import csv

    path = tmp_path / "ragged.csv"
    columns = (
        ["path_id", "G_T_activate", "rxn_smiles"]
        if missing == "rxn_smiles"
        else ["path_id", "rxn_smiles", "G_T_activate"]
    )
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerow([_row("first")[name] for name in columns])
        writer.writerow([_row("bad")[name] for name in columns[:-1]])
        writer.writerow([_row("last")[name] for name in columns])
    dataset = ReactionGroupDataset(path, on_error="record")
    assert [row.path_id for row in dataset.rows] == ["first", "last"]
    assert dataset.group_to_rows[dataset.group_ids[0]] == [0, 1]
    assert dataset.anomalies[0].rule == "complete_csv_record"
    assert dataset.anomalies[0].csv_line_number == 3
    assert dataset.rows[-1].csv_line_number == 4


def test_csv_preserves_all_external_ids_and_original_reaction(tmp_path) -> None:
    import csv

    path = tmp_path / "source.csv"
    row = _row(
        "0000000123",
        "  " + REACTION + "  ",
        profile_id="900719925474099312345678901",
        source_row_index="000005",
        prod_id="000001",
    )
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    dataset = ReactionGroupDataset(path, route_id_column="prod_id")
    processed = dataset.processed_rows()[0]
    for name in ["path_id", "profile_id", "source_row_index", "prod_id"]:
        assert processed[name] == row[name]
    assert processed["raw_rxn_smiles"] == row["rxn_smiles"]
    assert processed["route_label"] == "000001"
    assert processed["route_index"] == "0"
    assert processed["csv_row_index"] == "0"
    assert processed["csv_line_number"] == "2"
    assert processed["adaptation_version"]
    assert processed["aligned_rxn_smiles"] == dataset.rows[0].aligned_rxn_smiles


@pytest.mark.parametrize(
    "reaction",
    [
        "[CH3:1][CH2:2][OH:3].[NH3:4]>>[CH3:1][CH:2]=[O:3].[NH3:4]",
        "[F:1][C@:2]([Cl:3])([Br:4])[I:5]>>[F:1][C@@:2]([Cl:3])([Br:4])[I:5]",
        r"[F:1]/[CH:2]=[CH:3]/[Cl:4]>>[F:1]/[CH:2]=[CH:3]\[Cl:4]",
        "[CH3:1][CH2:2][CH3:3]>>[CH3:1][CH2:2][CH3:3]",
        "[13CH3:1][12CH2:2][OH:3]>>[13CH3:1][12CH:2]=[O:3]",
    ],
)
def test_remapping_and_traversal_preserve_cgr_product_and_delta(reaction: str) -> None:
    from rdkit import Chem

    parsed = parse_mapped_reaction(reaction, require_complete_mapping=True)
    new_labels = {
        number: 1000 + i * 37 for i, number in enumerate(sorted(parsed.atom_mapping, reverse=True))
    }
    sides = []
    for molecules in (parsed.reactant_mols, parsed.product_mols):
        components = []
        for molecule in reversed(molecules):
            copy = Chem.RenumberAtoms(molecule, list(reversed(range(molecule.GetNumAtoms()))))
            for atom in copy.GetAtoms():
                atom.SetAtomMapNum(new_labels[atom.GetAtomMapNum()])
            components.append(Chem.MolToSmiles(copy, canonical=False, isomericSmiles=True))
        sides.append(".".join(components))
    changed = ">>".join(sides)
    dataset = ReactionGroupDataset([_row("first", reaction), _row("changed", changed)])
    assert len(dataset) == 1
    sample = dataset[0]
    for first, second in [
        (sample.path_cgrs[0], sample.path_cgrs[1]),
        (sample.products[0], sample.products[1]),
    ]:
        assert torch.equal(first.x, second.x)
        assert torch.equal(first.edge_index, second.edge_index)
        assert torch.equal(first.edge_attr, second.edge_attr)
    for delta in sample.path_delta_cgrs:
        assert torch.count_nonzero(delta.x) == 0
        assert torch.count_nonzero(delta.edge_attr) == 0
    assert dataset.rows[0].raw_rxn_smiles == reaction
    assert dataset.rows[1].raw_rxn_smiles == changed


def test_many_identical_components_have_a_repeatable_bijection() -> None:
    first = ".".join(f"[CH4:{number}]" for number in range(1, 13))
    second = ".".join(f"[CH4:{number}]" for number in reversed(range(101, 113)))
    mappings = [parse_mapped_reaction(side + ">>" + side) for side in [first, second]]
    forward = reaction_change_graphs(mappings)
    reverse = reaction_change_graphs(list(reversed(mappings)))
    assert forward.path_source_map_to_coordinate == tuple(
        reversed(reverse.path_source_map_to_coordinate)
    )
    assert len(set(forward.path_source_map_to_coordinate[1].values())) == 12
    assert torch.equal(forward.paths[0].x, forward.paths[1].x)
    assert torch.count_nonzero(forward.deltas[1].x) == 0


@pytest.mark.parametrize("count", [3, 8, 19])
def test_folds_cover_actual_path_and_group_ids_at_different_scales(count: int) -> None:
    rows = [_row(f"path-{i}", condition=f"group-{i}") for i in range(count)]
    dataset = ReactionGroupDataset(rows, condition_columns=["condition"])
    manifest = create_group_kfold_manifest(dataset, num_folds=3)
    test_paths = []
    for fold in manifest.folds:
        split = manifest.resolve(dataset, fold.fold_index)
        sets = [
            {dataset.group_ids[index] for index in indices}
            for indices in [split.train, split.valid, split.test]
        ]
        assert sets[0] | sets[1] | sets[2] == set(dataset.group_ids)
        assert not sets[0] & sets[1] and not sets[0] & sets[2] and not sets[1] & sets[2]
        test_paths.extend(path for index in split.test for path in dataset[index].path_ids)
    assert set(test_paths) == {row.path_id for row in dataset.rows}
    assert len(test_paths) == len(dataset.rows)
    replaced = ReactionGroupDataset(
        [{**row, "path_id": "new-" + row["path_id"]} for row in rows],
        condition_columns=["condition"],
    )
    with pytest.raises(ValueError, match="record fingerprint"):
        manifest.resolve(replaced, 0)


def test_blank_lines_and_multiline_records_keep_actual_csv_line_numbers(tmp_path) -> None:
    import csv

    path = tmp_path / "lines.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["path_id", "rxn_smiles", "G_T_activate", "notes"]
        )
        writer.writeheader()
        handle.write("\n")
        writer.writerow(_row("first", notes="line one\nline two"))
        handle.write("\n")
        writer.writerow(_row("bad", G_T_activate="nan", notes=""))
        writer.writerow(_row("last", notes=""))
    dataset = ReactionGroupDataset(path, on_error="record")
    assert [row.csv_line_number for row in dataset.rows] == [3, 7]
    assert dataset.anomalies[0].csv_line_number == 6


def test_bad_mapping_sides_and_empty_components_are_rejected() -> None:
    for bad in [
        "[CH3:1][OH:2]>>[CH3:1][OH:3]",
        "[CH3:1][OH:2]>>[CH3:1][OH:1]",
        "[CH3:1][OH:2].>>[CH3:1][OH:2]",
    ]:
        with pytest.raises(ValueError):
            ReactionGroupDataset([_row("bad", bad)])


def test_record_mode_rejects_duplicate_ids_even_if_first_record_is_bad() -> None:
    dataset = ReactionGroupDataset(
        [_row("duplicate", G_T_activate="nan"), _row("duplicate"), _row("valid")], on_error="record"
    )
    assert [row.path_id for row in dataset.rows] == ["valid"]
    assert [anomaly.rule for anomaly in dataset.anomalies] == ["finite_target", "unique_path_id"]


def test_substrate_identity_does_not_validate_product_or_mapping() -> None:
    reference = group_id_from_reaction("[CH3:1][OH:2]>>[CH3:1][OH:2]")
    assert group_id_from_reaction("[OH:8][CH3:8]>>invalid-product") == reference
    with pytest.raises(ValueError, match="unique_atom_mapping"):
        ReactionGroupDataset([_row("bad", "[OH:8][CH3:8]>>invalid-product")])


def test_all_bad_records_retain_row_path_and_rule_in_error() -> None:
    with pytest.raises(ValueError, match=r"Row 0 path_id 'bad': \[finite_target\]"):
        ReactionGroupDataset([_row("bad", G_T_activate="nan")], on_error="record")
