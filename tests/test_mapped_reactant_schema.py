import csv
from pathlib import Path

import pytest
import torch

from rxnresid.data.change_graphs import reaction_change_graphs
from rxnresid.data.collate import collate_reaction_paths
from rxnresid.data.dataset import ReactionGroupDataset
from rxnresid.data.featurizer import (
    BOND_STEREO_FEATURE_DIM,
    EDGE_FEATURE_DIM,
    bond_feature,
)
from rxnresid.data.reaction_parser import parse_mapped_reaction


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "rxnresid-mapped-reactant-schema"
CASES = (
    ("autode.csv", (40.13989853, 40.1317409)),
    ("dpa-fined-rits-da.csv", (36.43508259, 36.4357101)),
    ("rits-zero-shot-da.csv", (47.1592195, 41.74946033)),
)


def _rows_and_mappings(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    mappings = [parse_mapped_reaction(row["rxn_smiles"]) for row in rows]
    return rows, mappings


@pytest.mark.parametrize(("filename", "expected_energies"), CASES)
def test_mapped_reactant_schema_fixture_keeps_one_complete_group(
    filename: str,
    expected_energies: tuple[float, float],
) -> None:
    path = FIXTURE_ROOT / filename
    rows, mappings = _rows_and_mappings(path)
    dataset = ReactionGroupDataset(
        path,
        target_column="G_T_activate",
        reaction_column="rxn_smiles",
        route_id_column="prod_id",
    )

    assert len(dataset.rows) == 2
    assert len(dataset) == 1
    assert len(dataset[0].mappings) == 2
    assert len(dataset[0].path_ids) == 2
    assert len(dataset[0].energies) == 2
    assert dataset.anomalies == []
    assert dataset[0].energies.tolist() == pytest.approx(expected_energies)
    assert dataset[0].path_ids == [row["path_id"] for row in rows]
    assert dataset[0].route_ids.tolist() == [int(row["prod_id"]) for row in rows]
    assert [mapping.mapped_products for mapping in dataset[0].mappings] == [
        mapping.mapped_products for mapping in mappings
    ]
    assert [product.atom_map_numbers.tolist() for product in dataset[0].products] == [
        [atom.GetAtomMapNum() for molecule in mapping.product_mols for atom in molecule.GetAtoms()]
        for mapping in mappings
    ]


def _edge_feature_by_maps(graph, left_map: int, right_map: int) -> torch.Tensor:
    nodes = {
        int(map_number): index for index, map_number in enumerate(graph.atom_map_numbers.tolist())
    }
    left = nodes[left_map]
    right = nodes[right_map]
    matches = (graph.edge_index[0] == left) & (graph.edge_index[1] == right)
    indices = matches.nonzero(as_tuple=False).flatten()
    assert indices.numel() == 1
    return graph.edge_attr[indices.item()]


@pytest.mark.parametrize("filename", [case[0] for case in CASES])
def test_group_graph_is_order_invariant_and_paths_keep_reactant_schema(filename: str) -> None:
    _, mappings = _rows_and_mappings(FIXTURE_ROOT / filename)
    forward = reaction_change_graphs(mappings)
    reverse = reaction_change_graphs(list(reversed(mappings)))

    assert torch.equal(forward.group.atom_map_numbers, reverse.group.atom_map_numbers)
    assert torch.equal(forward.group.edge_index, reverse.group.edge_index)
    assert torch.equal(forward.group.component_id, reverse.group.component_id)
    assert torch.equal(forward.group.component_token_id, reverse.group.component_token_id)
    assert torch.allclose(forward.group.x, reverse.group.x)
    assert torch.allclose(forward.group.edge_attr, reverse.group.edge_attr)
    for path, delta in zip(forward.paths, forward.deltas, strict=True):
        assert torch.equal(path.atom_map_numbers, forward.group.atom_map_numbers)
        assert torch.equal(path.component_id, forward.group.component_id)
        assert torch.equal(delta.atom_map_numbers, forward.group.atom_map_numbers)
        assert torch.equal(delta.component_id, forward.group.component_id)
        assert torch.equal(delta.edge_index, forward.group.edge_index)

    # These are equivalent symmetry-related mapped representations, not
    # incompatible substrates.  The group substrate block still covers every
    # path-level stereo encoding rather than silently keeping only path zero.
    stereo_features: dict[tuple[int, int], list[list[float]]] = {}
    for mapping in mappings:
        for molecule in mapping.reactant_mols:
            for bond in molecule.GetBonds():
                if bond.GetBondTypeAsDouble() != 2.0 or str(bond.GetStereo()) == "STEREONONE":
                    continue
                left = molecule.GetAtomWithIdx(bond.GetBeginAtomIdx()).GetAtomMapNum()
                right = molecule.GetAtomWithIdx(bond.GetEndAtomIdx()).GetAtomMapNum()
                pair = (min(left, right), max(left, right))
                stereo_features.setdefault(pair, []).append(bond_feature(bond))

    assert stereo_features
    for pair, expected_features in stereo_features.items():
        if len({tuple(feature[-BOND_STEREO_FEATURE_DIM:]) for feature in expected_features}) < 2:
            continue
        group_feature = _edge_feature_by_maps(forward.group, *pair)[:EDGE_FEATURE_DIM]
        path_features = [
            _edge_feature_by_maps(path, *pair)[:EDGE_FEATURE_DIM] for path in forward.paths
        ]
        for path_feature, expected in zip(path_features, expected_features, strict=True):
            assert path_feature[-BOND_STEREO_FEATURE_DIM:].tolist() == pytest.approx(
                expected[-BOND_STEREO_FEATURE_DIM:]
            )
        assert group_feature[-BOND_STEREO_FEATURE_DIM:].tolist() == pytest.approx(
            [
                max(feature[-BOND_STEREO_FEATURE_DIM + index] for feature in expected_features)
                for index in range(BOND_STEREO_FEATURE_DIM)
            ]
        )
        return
    raise AssertionError("fixture does not contain a mapped reactant stereo difference")


def test_alignment_does_not_depend_on_reactant_component_or_atom_order() -> None:
    first = parse_mapped_reaction("[CH3:2][CH2:1].[OH:4][CH3:3]>>[CH3:2][CH2:1].[OH:4][CH3:3]")
    second = parse_mapped_reaction("[CH3:3][OH:4].[CH2:1][CH3:2]>>[CH3:3][OH:4].[CH2:1][CH3:2]")
    graphs = reaction_change_graphs([first, second])

    assert graphs.group.atom_map_numbers.tolist() == [1, 2, 3, 4]
    assert all(
        graph.atom_map_numbers.tolist() == [1, 2, 3, 4] for graph in (*graphs.paths, *graphs.deltas)
    )
    assert torch.equal(graphs.paths[0].edge_index, graphs.paths[1].edge_index)
    assert torch.equal(graphs.paths[0].component_id, graphs.paths[1].component_id)


def test_equivalent_atom_map_assignments_are_normalized_without_mutating_inputs() -> None:
    first_smiles = "[CH3:1][CH2:2][OH:3]>>[CH3:1][CH2:2][OH:3]"
    second_smiles = "[CH3:1][CH2:3][OH:2]>>[CH3:1][CH2:3][OH:2]"
    first = parse_mapped_reaction(first_smiles)
    second = parse_mapped_reaction(second_smiles)

    graphs = reaction_change_graphs([first, second])
    reversed_graphs = reaction_change_graphs([second, first])

    assert first.mapped_reactants == first_smiles.split(">>")[0]
    assert second.mapped_reactants == second_smiles.split(">>")[0]
    assert torch.equal(graphs.group.atom_map_numbers, reversed_graphs.group.atom_map_numbers)
    assert torch.equal(graphs.group.edge_index, reversed_graphs.group.edge_index)
    assert torch.allclose(graphs.group.x, reversed_graphs.group.x)
    assert torch.allclose(graphs.group.edge_attr, reversed_graphs.group.edge_attr)
    assert torch.equal(graphs.paths[0].atom_map_numbers, graphs.paths[1].atom_map_numbers)
    assert torch.equal(graphs.paths[0].edge_index, graphs.paths[1].edge_index)
    assert torch.allclose(graphs.paths[0].x, graphs.paths[1].x)
    assert torch.allclose(graphs.paths[0].edge_attr, graphs.paths[1].edge_attr)


def test_dataset_and_collator_use_normalized_maps_for_independent_path_mappings() -> None:
    first_smiles = "[CH3:1][CH2:2][OH:3]>>[CH3:1][CH:2]=[O:3]"
    second_smiles = "[CH3:1][CH2:3][OH:2]>>[CH3:1][CH:3]=[O:2]"
    dataset = ReactionGroupDataset(
        [
            {
                "path_id": "first",
                "rxn_smiles": first_smiles,
                "G_T_activate": "1.0",
                "prod_id": "0",
            },
            {
                "path_id": "second",
                "rxn_smiles": second_smiles,
                "G_T_activate": "2.0",
                "prod_id": "1",
            },
        ],
        target_column="G_T_activate",
        reaction_column="rxn_smiles",
        route_id_column="prod_id",
    )

    assert len(dataset) == 1
    sample = dataset[0]
    assert sample.path_source_map_to_coordinate[1] == {1: 1, 3: 2, 2: 3}
    batch = collate_reaction_paths(list(sample.path_samples()))
    assert torch.equal(
        batch.unique_components.atom_map_numbers[batch.mapping.mapped_substrate_node],
        batch.products.atom_map_numbers[batch.mapping.mapped_product_node],
    )
