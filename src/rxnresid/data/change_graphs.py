"""Group-level possible-change graphs and path-specific CGRs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import torch
from rdkit import Chem
from torch import Tensor
from torch_geometric.data import Data

from rxnresid.data.featurizer import (
    ATOM_FEATURE_DIM,
    BOND_STEREO_FEATURE_DIM,
    BOND_TYPE_FEATURE_DIM,
    EDGE_FEATURE_DIM,
    atom_feature,
    bond_feature,
    molecules_to_graph,
)
from rxnresid.data.protocols import PyGDataStub
from rxnresid.data.reaction_parser import ParsedReaction


ATOM_CHANGE_STAT_DIM = 2
EDGE_CHANGE_STAT_DIM = 5
CHANGE_ATOM_FEATURE_DIM = ATOM_FEATURE_DIM * 3 + ATOM_CHANGE_STAT_DIM
CHANGE_EDGE_FEATURE_DIM = EDGE_FEATURE_DIM * 3 + EDGE_CHANGE_STAT_DIM


@dataclass(frozen=True)
class ReactionChangeGraphs:
    """One temporary group union graph and aligned RxnResid path graphs."""

    group: Data
    paths: tuple[Data, ...]
    deltas: tuple[Data, ...]


def _atom_features_by_map(mols: Sequence[Chem.Mol]) -> dict[int, list[float]]:
    features: dict[int, list[float]] = {}
    for mol in mols:
        for atom in mol.GetAtoms():
            map_number = atom.GetAtomMapNum()
            if map_number <= 0:
                raise ValueError("Change graphs require every product atom to be mapped")
            if map_number in features:
                raise ValueError(f"Duplicate product atom map number: {map_number}")
            features[map_number] = atom_feature(atom)
    return features


def _validate_complete_mapping(mapping: ParsedReaction) -> None:
    reactant_maps = [
        atom.GetAtomMapNum() for mol in mapping.reactant_mols for atom in mol.GetAtoms()
    ]
    product_maps = [atom.GetAtomMapNum() for mol in mapping.product_mols for atom in mol.GetAtoms()]
    if any(map_number <= 0 for map_number in reactant_maps):
        raise ValueError("Change graphs require every reactant atom to be mapped")
    if any(map_number <= 0 for map_number in product_maps):
        raise ValueError("Change graphs require every product atom to be mapped")
    if set(reactant_maps) != set(product_maps):
        raise ValueError("Change graphs require identical atom maps on both reaction sides")


def _substrate_bonds(mols: Sequence[Chem.Mol]) -> dict[tuple[int, int], list[float]]:
    bonds: dict[tuple[int, int], list[float]] = {}
    offset = 0
    for mol in mols:
        for bond in mol.GetBonds():
            left = offset + bond.GetBeginAtomIdx()
            right = offset + bond.GetEndAtomIdx()
            bonds[(min(left, right), max(left, right))] = bond_feature(bond)
        offset += mol.GetNumAtoms()
    return bonds


def _product_bonds(
    mols: Sequence[Chem.Mol],
    substrate_map_to_node: dict[int, int],
) -> dict[tuple[int, int], list[float]]:
    bonds: dict[tuple[int, int], list[float]] = {}
    for mol in mols:
        for bond in mol.GetBonds():
            left_map = mol.GetAtomWithIdx(bond.GetBeginAtomIdx()).GetAtomMapNum()
            right_map = mol.GetAtomWithIdx(bond.GetEndAtomIdx()).GetAtomMapNum()
            if left_map <= 0 or right_map <= 0:
                continue
            if left_map not in substrate_map_to_node or right_map not in substrate_map_to_node:
                raise ValueError("Product bond references an atom absent from the group substrate")
            left = substrate_map_to_node[left_map]
            right = substrate_map_to_node[right_map]
            bonds[(min(left, right), max(left, right))] = bond_feature(bond)
    return bonds


def _mean_and_max(rows: list[list[float]], width: int) -> tuple[Tensor, Tensor]:
    if not rows:
        zeros = torch.zeros(width, dtype=torch.float32)
        return zeros, zeros.clone()
    columns = tuple(zip(*rows, strict=True))
    count = len(rows)
    return (
        torch.tensor([sum(column) / count for column in columns], dtype=torch.float32),
        torch.tensor([max(column) for column in columns], dtype=torch.float32),
    )


def _build_change_graph(mappings: Sequence[ParsedReaction]) -> Data:
    if not mappings:
        raise ValueError("At least one mapped reaction is required")
    mapped_reactants = mappings[0].mapped_reactants
    if any(mapping.mapped_reactants != mapped_reactants for mapping in mappings[1:]):
        raise ValueError("All paths in a group must use one consistent mapped reactant schema")
    for mapping in mappings:
        _validate_complete_mapping(mapping)

    substrate = cast(PyGDataStub, molecules_to_graph(mappings[0].reactant_mols))
    substrate_map_to_node = {
        int(map_number): node_index
        for node_index, map_number in enumerate(substrate.atom_map_numbers.tolist())
        if map_number > 0
    }
    product_atoms = [_atom_features_by_map(mapping.product_mols) for mapping in mappings]
    unknown_product_maps = set().union(*(set(table) for table in product_atoms)) - set(
        substrate_map_to_node
    )
    if unknown_product_maps:
        raise ValueError(
            "Product atoms are absent from the group substrate mapping: "
            f"{sorted(unknown_product_maps)}"
        )

    zero_atom = [0.0] * ATOM_FEATURE_DIM
    node_features: list[Tensor] = []
    path_count = len(mappings)
    for node_index, map_number_value in enumerate(substrate.atom_map_numbers.tolist()):
        map_number = int(map_number_value)
        rows = [table.get(map_number, zero_atom) for table in product_atoms]
        product_mean, product_union = _mean_and_max(rows, ATOM_FEATURE_DIM)
        present = sum(map_number in table for table in product_atoms)
        changed = sum(
            table[map_number] != substrate.x[node_index].tolist() for table in product_atoms
        )
        node_features.append(
            torch.cat(
                (
                    substrate.x[node_index],
                    product_mean,
                    product_union,
                    torch.tensor(
                        [present / path_count, changed / path_count],
                        dtype=torch.float32,
                    ),
                )
            )
        )

    substrate_bonds = _substrate_bonds(mappings[0].reactant_mols)
    product_bonds = [
        _product_bonds(mapping.product_mols, substrate_map_to_node) for mapping in mappings
    ]
    edge_keys = sorted(set(substrate_bonds).union(*(set(table) for table in product_bonds)))
    zero_edge = [0.0] * EDGE_FEATURE_DIM
    directed_edges: list[tuple[int, int]] = []
    directed_features: list[Tensor] = []
    for edge_key in edge_keys:
        substrate_feature = substrate_bonds.get(edge_key, zero_edge)
        product_rows = [table.get(edge_key, zero_edge) for table in product_bonds]
        product_mean, product_union = _mean_and_max(product_rows, EDGE_FEATURE_DIM)
        substrate_present = edge_key in substrate_bonds
        formed = broken = bond_type_changed = stereo_changed = changed = 0
        for table, product_feature in zip(product_bonds, product_rows, strict=True):
            product_present = edge_key in table
            formed += int(not substrate_present and product_present)
            broken += int(substrate_present and not product_present)
            if substrate_present and product_present:
                bond_type_changed += int(
                    substrate_feature[:BOND_TYPE_FEATURE_DIM]
                    != product_feature[:BOND_TYPE_FEATURE_DIM]
                )
                stereo_changed += int(
                    substrate_feature[-BOND_STEREO_FEATURE_DIM:]
                    != product_feature[-BOND_STEREO_FEATURE_DIM:]
                )
            changed += int(substrate_feature != product_feature)
        feature = torch.cat(
            (
                torch.tensor(substrate_feature, dtype=torch.float32),
                product_mean,
                product_union,
                torch.tensor(
                    [
                        formed / path_count,
                        broken / path_count,
                        bond_type_changed / path_count,
                        stereo_changed / path_count,
                        changed / path_count,
                    ],
                    dtype=torch.float32,
                ),
            )
        )
        left, right = edge_key
        directed_edges.extend(((left, right), (right, left)))
        directed_features.extend((feature, feature))

    edge_index = torch.tensor(directed_edges, dtype=torch.long).t().contiguous()
    if not directed_edges:
        edge_index = torch.empty((2, 0), dtype=torch.long)
    return Data(
        x=torch.stack(node_features),
        edge_index=edge_index,
        edge_attr=torch.stack(directed_features)
        if directed_features
        else torch.empty((0, CHANGE_EDGE_FEATURE_DIM), dtype=torch.float32),
        atom_map_numbers=substrate.atom_map_numbers.clone(),
        component_id=substrate.component_id.clone(),
        component_token_id=substrate.component_token_id.clone(),
    )


def reaction_change_graphs(mappings: Sequence[ParsedReaction]) -> ReactionChangeGraphs:
    """Build one permutation-invariant group graph and exact per-path CGRs."""
    mappings = tuple(mappings)
    group = _build_change_graph(mappings)
    paths = tuple(_build_change_graph((mapping,)) for mapping in mappings)

    def delta_graph(path: Data) -> Data:
        path_graph = cast(PyGDataStub, path)
        group_graph = cast(PyGDataStub, group)
        path_edges = {
            (int(left), int(right)): feature
            for (left, right), feature in zip(
                path_graph.edge_index.t().tolist(),
                path_graph.edge_attr,
                strict=True,
            )
        }
        edge_attr = (
            torch.stack(
                [
                    path_edges.get(
                        (int(left), int(right)), torch.zeros_like(group_graph.edge_attr[0])
                    )
                    - group_graph.edge_attr[edge_index]
                    for edge_index, (left, right) in enumerate(group_graph.edge_index.t().tolist())
                ]
            )
            if group_graph.edge_attr.shape[0]
            else group_graph.edge_attr.clone()
        )
        return Data(
            x=path_graph.x - group_graph.x,
            edge_index=group_graph.edge_index.clone(),
            edge_attr=edge_attr,
            atom_map_numbers=group_graph.atom_map_numbers.clone(),
            component_id=group_graph.component_id.clone(),
            component_token_id=group_graph.component_token_id.clone(),
        )

    return ReactionChangeGraphs(
        group=group,
        paths=paths,
        deltas=tuple(delta_graph(path) for path in paths),
    )


__all__ = [
    "CHANGE_ATOM_FEATURE_DIM",
    "CHANGE_EDGE_FEATURE_DIM",
    "ReactionChangeGraphs",
    "reaction_change_graphs",
]
