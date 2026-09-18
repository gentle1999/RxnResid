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
    ATOM_STEREO_FEATURE_DIM,
    BOND_STEREO_FEATURE_DIM,
    BOND_TYPE_FEATURE_DIM,
    EDGE_FEATURE_DIM,
    atom_feature,
    bond_feature,
    component_token_id,
)
from rxnresid.data.grouping import canonical_reactant_key
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
    path_source_map_to_coordinate: tuple[dict[int, int], ...]
    reference_path_index: int


@dataclass(frozen=True)
class _ReactantFeatures:
    """Features for one mapped reactant schema, indexed independently of SMILES order."""

    atom_features: dict[int, list[float]]
    atom_core_features: dict[int, tuple[float, ...]]
    bonds: dict[tuple[int, int], list[float]]
    component_tokens: dict[int, int]
    group_component_tokens: dict[int, int]
    component_maps: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class _ReactantAlignment:
    """Canonical node/edge coordinates shared by a complete reaction group."""

    atom_maps: tuple[int, ...]
    map_to_node: dict[int, int]
    edge_maps: tuple[tuple[int, int], ...]
    component_id_by_map: dict[int, int]
    group_component_tokens: dict[int, int]
    source_map_to_coordinate: tuple[dict[int, int], ...]
    reference_path_index: int


_SCHEMA_ERROR = "All paths in a group must use one consistent mapped reactant schema"


def _atom_features_by_map(
    mols: Sequence[Chem.Mol],
    *,
    side: str = "product",
) -> dict[int, list[float]]:
    features: dict[int, list[float]] = {}
    for mol in mols:
        for atom in mol.GetAtoms():
            map_number = atom.GetAtomMapNum()
            if map_number <= 0:
                raise ValueError(f"Change graphs require every {side} atom to be mapped")
            if map_number in features:
                raise ValueError(f"Duplicate {side} atom map number: {map_number}")
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
    if len(set(reactant_maps)) != len(reactant_maps):
        raise ValueError("Change graphs require unique reactant atom maps")
    if len(set(product_maps)) != len(product_maps):
        raise ValueError("Change graphs require unique product atom maps")
    if set(reactant_maps) != set(product_maps):
        raise ValueError("Change graphs require identical atom maps on both reaction sides")


def _mapped_bonds(
    mols: Sequence[Chem.Mol],
    *,
    side: str,
) -> dict[tuple[int, int], list[float]]:
    bonds: dict[tuple[int, int], list[float]] = {}
    for mol in mols:
        for bond in mol.GetBonds():
            left = mol.GetAtomWithIdx(bond.GetBeginAtomIdx()).GetAtomMapNum()
            right = mol.GetAtomWithIdx(bond.GetEndAtomIdx()).GetAtomMapNum()
            if left <= 0 or right <= 0:
                raise ValueError(f"Change graphs require every {side} atom to be mapped")
            key = (min(left, right), max(left, right))
            if key in bonds:
                raise ValueError(f"Duplicate mapped {side} bond for atom pair {key}")
            bonds[key] = bond_feature(bond)
    return bonds


def _component_maps(mols: Sequence[Chem.Mol]) -> tuple[tuple[int, ...], ...]:
    return tuple(
        sorted(tuple(sorted(atom.GetAtomMapNum() for atom in mol.GetAtoms())) for mol in mols)
    )


def _component_key(mol: Chem.Mol, *, isomeric: bool) -> str:
    canonical = Chem.Mol(mol)
    for atom in canonical.GetAtoms():
        atom.SetAtomMapNum(0)
    if not isomeric:
        Chem.RemoveStereochemistry(canonical)
    return Chem.MolToSmiles(canonical, canonical=True, isomericSmiles=isomeric)


def _reactant_structure_key(mols: Sequence[Chem.Mol], *, isomeric: bool) -> str:
    return ".".join(sorted(_component_key(mol, isomeric=isomeric) for mol in mols))


def _reactant_features(mols: Sequence[Chem.Mol]) -> _ReactantFeatures:
    atom_features: dict[int, list[float]] = {}
    atom_core_features: dict[int, tuple[float, ...]] = {}
    component_tokens: dict[int, int] = {}
    group_component_tokens: dict[int, int] = {}
    for mol in mols:
        path_token = component_token_id(mol)
        group_token = component_token_id(mol, isomeric_smiles=False)
        for atom in mol.GetAtoms():
            map_number = atom.GetAtomMapNum()
            if map_number <= 0:
                raise ValueError("Change graphs require every reactant atom to be mapped")
            if map_number in atom_features:
                raise ValueError(f"Duplicate reactant atom map number: {map_number}")
            features = atom_feature(atom)
            atom_features[map_number] = features
            atom_core_features[map_number] = (
                float(atom.GetIsotope()),
                float(atom.GetNumRadicalElectrons()),
                *features[:-ATOM_STEREO_FEATURE_DIM],
            )
            component_tokens[map_number] = path_token
            group_component_tokens[map_number] = group_token
    return _ReactantFeatures(
        atom_features=atom_features,
        atom_core_features=atom_core_features,
        bonds=_mapped_bonds(mols, side="reactant"),
        component_tokens=component_tokens,
        group_component_tokens=group_component_tokens,
        component_maps=_component_maps(mols),
    )


def _identity_alignment_is_safe(
    reference: _ReactantFeatures,
    candidate: _ReactantFeatures,
) -> bool:
    """Check whether existing map labels already define the same coordinates."""
    if set(candidate.atom_features) != set(reference.atom_features):
        return False
    if set(candidate.bonds) != set(reference.bonds):
        return False
    if set(candidate.component_maps) != set(reference.component_maps):
        return False
    for map_number in reference.atom_features:
        if candidate.atom_core_features[map_number] != reference.atom_core_features[map_number]:
            return False
    for pair in reference.bonds:
        reference_core = tuple(reference.bonds[pair][:-BOND_STEREO_FEATURE_DIM])
        candidate_core = tuple(candidate.bonds[pair][:-BOND_STEREO_FEATURE_DIM])
        if candidate_core != reference_core:
            return False
    return True


def _component_atom_alignment(
    reference: Chem.Mol,
    candidate: Chem.Mol,
    *,
    path_index: int,
) -> dict[int, int]:
    """Find a deterministic candidate-map to reference-map isomorphism."""
    reference_structure = Chem.Mol(reference)
    candidate_structure = Chem.Mol(candidate)
    for molecule in (reference_structure, candidate_structure):
        for atom in molecule.GetAtoms():
            atom.SetAtomMapNum(0)
        Chem.RemoveStereochemistry(molecule)

    matches = reference_structure.GetSubstructMatches(
        candidate_structure,
        uniquify=False,
        useChirality=False,
    )
    if not matches:
        raise ValueError(
            f"{_SCHEMA_ERROR}: path {path_index} has no safe atom correspondence "
            "for an equivalent reactant component"
        )

    reference_maps = tuple(atom.GetAtomMapNum() for atom in reference.GetAtoms())
    candidate_maps = tuple(atom.GetAtomMapNum() for atom in candidate.GetAtoms())
    candidate_order = sorted(
        range(len(candidate_maps)), key=lambda index: (candidate_maps[index], index)
    )
    selected = min(
        matches,
        key=lambda match: tuple(reference_maps[match[index]] for index in candidate_order),
    )
    alignment = {
        candidate_maps[candidate_index]: reference_maps[reference_index]
        for candidate_index, reference_index in enumerate(selected)
    }
    if any(map_number <= 0 for map_number in (*reference_maps, *candidate_maps)):
        raise ValueError(f"{_SCHEMA_ERROR}: path {path_index} has an unmapped aligned atom")
    if len(alignment) != len(candidate_maps) or len(set(alignment.values())) != len(reference_maps):
        raise ValueError(
            f"{_SCHEMA_ERROR}: path {path_index} has a non-bijective atom correspondence"
        )
    return alignment


def _structure_atom_alignment(
    reference_mols: Sequence[Chem.Mol],
    candidate_mols: Sequence[Chem.Mol],
    *,
    path_index: int,
) -> dict[int, int]:
    """Align all candidate components to a reference using map-free structure."""
    reference_components: dict[str, list[tuple[tuple[object, ...], int, Chem.Mol]]] = {}
    candidate_components: dict[str, list[tuple[tuple[object, ...], int, Chem.Mol]]] = {}
    for index, molecule in enumerate(reference_mols):
        key = _component_key(molecule, isomeric=True)
        sort_key = (
            Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True),
            tuple(atom.GetAtomMapNum() for atom in molecule.GetAtoms()),
            index,
        )
        reference_components.setdefault(key, []).append((sort_key, index, molecule))
    for index, molecule in enumerate(candidate_mols):
        key = _component_key(molecule, isomeric=True)
        sort_key = (
            Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True),
            tuple(atom.GetAtomMapNum() for atom in molecule.GetAtoms()),
            index,
        )
        candidate_components.setdefault(key, []).append((sort_key, index, molecule))

    if {key: len(value) for key, value in reference_components.items()} != {
        key: len(value) for key, value in candidate_components.items()
    }:
        raise ValueError(f"{_SCHEMA_ERROR}: path {path_index} has incompatible reactant components")

    alignment: dict[int, int] = {}
    for key in sorted(reference_components):
        references = sorted(reference_components[key])
        candidates = sorted(candidate_components[key])
        for (_, _, reference), (_, _, candidate) in zip(references, candidates, strict=True):
            component_alignment = _component_atom_alignment(
                reference,
                candidate,
                path_index=path_index,
            )
            for candidate_map, reference_map in component_alignment.items():
                if candidate_map in alignment or reference_map in alignment.values():
                    raise ValueError(
                        f"{_SCHEMA_ERROR}: path {path_index} has a non-bijective component alignment"
                    )
                alignment[candidate_map] = reference_map
    return alignment


def _remap_reactant_features(
    features: _ReactantFeatures,
    source_map_to_coordinate: dict[int, int],
    *,
    path_index: int,
) -> _ReactantFeatures:
    """Project one path's features into the group's coordinate map."""
    if set(source_map_to_coordinate) != set(features.atom_features):
        raise ValueError(
            f"{_SCHEMA_ERROR}: path {path_index} atom correspondence does not cover all atoms"
        )

    atom_features = {
        source_map_to_coordinate[source_map]: feature
        for source_map, feature in features.atom_features.items()
    }
    atom_core_features = {
        source_map_to_coordinate[source_map]: feature
        for source_map, feature in features.atom_core_features.items()
    }
    component_tokens = {
        source_map_to_coordinate[source_map]: token
        for source_map, token in features.component_tokens.items()
    }
    group_component_tokens = {
        source_map_to_coordinate[source_map]: token
        for source_map, token in features.group_component_tokens.items()
    }
    bonds: dict[tuple[int, int], list[float]] = {}
    for (left, right), feature in features.bonds.items():
        coordinate_left = source_map_to_coordinate[left]
        coordinate_right = source_map_to_coordinate[right]
        coordinate_pair = (
            min(coordinate_left, coordinate_right),
            max(coordinate_left, coordinate_right),
        )
        if coordinate_pair in bonds:
            raise ValueError(
                f"{_SCHEMA_ERROR}: path {path_index} maps multiple bonds to atom pair "
                f"{coordinate_pair}"
            )
        bonds[coordinate_pair] = feature
    component_maps = tuple(
        sorted(
            tuple(sorted(source_map_to_coordinate[map_number] for map_number in component))
            for component in features.component_maps
        )
    )
    return _ReactantFeatures(
        atom_features=atom_features,
        atom_core_features=atom_core_features,
        bonds=bonds,
        component_tokens=component_tokens,
        group_component_tokens=group_component_tokens,
        component_maps=component_maps,
    )


def _remap_atom_features(
    features: dict[int, list[float]],
    source_map_to_coordinate: dict[int, int],
    *,
    path_index: int,
    side: str,
) -> dict[int, list[float]]:
    if set(source_map_to_coordinate) != set(features):
        raise ValueError(
            f"{_SCHEMA_ERROR}: path {path_index} {side} maps do not match its reactants"
        )
    remapped = {
        source_map_to_coordinate[source_map]: feature for source_map, feature in features.items()
    }
    if len(remapped) != len(features):
        raise ValueError(
            f"{_SCHEMA_ERROR}: path {path_index} has a non-bijective {side} atom alignment"
        )
    return remapped


def _reactant_alignment(
    mappings: Sequence[ParsedReaction],
) -> tuple[_ReactantAlignment, tuple[_ReactantFeatures, ...]]:
    if not mappings:
        raise ValueError("At least one mapped reaction is required")
    for mapping in mappings:
        _validate_complete_mapping(mapping)
    raw_reactants = tuple(_reactant_features(mapping.reactant_mols) for mapping in mappings)
    reference_index = min(
        range(len(mappings)),
        key=lambda index: mappings[index].mapped_reactants,
    )
    reference = raw_reactants[reference_index]
    # Use the same map-free isomeric key as grouping.py.  This preserves
    # symmetry-equivalent mapped spellings while keeping real stereo changes
    # out of a single group.
    reference_reactant_key = canonical_reactant_key(mappings[reference_index].mapped_reactants)
    reference_structure_key = _reactant_structure_key(
        mappings[reference_index].reactant_mols,
        isomeric=False,
    )
    reference_maps = set(reference.atom_features)
    reference_components = set(reference.component_maps)
    reference_bonds: set[tuple[int, int]] = set(reference.bonds)
    source_map_to_coordinate: list[dict[int, int]] = []
    reactants: list[_ReactantFeatures] = []
    for path_index, (mapping, candidate) in enumerate(zip(mappings, raw_reactants, strict=True)):
        candidate_reactant_key = canonical_reactant_key(mapping.mapped_reactants)
        if candidate_reactant_key != reference_reactant_key:
            candidate_structure_key = _reactant_structure_key(mapping.reactant_mols, isomeric=False)
            if candidate_structure_key != reference_structure_key:
                raise ValueError(
                    f"{_SCHEMA_ERROR}: path {path_index} has incompatible unmapped "
                    "reactant structure/topology; it must be assigned to a different "
                    "reaction group"
                )
            raise ValueError(
                f"{_SCHEMA_ERROR}: path {path_index} has non-equivalent reactant stereo; "
                "it must be assigned to a different reaction group"
            )
        if path_index == reference_index or _identity_alignment_is_safe(reference, candidate):
            coordinate_alignment = {
                map_number: map_number for map_number in candidate.atom_features
            }
        else:
            coordinate_alignment = _structure_atom_alignment(
                mappings[reference_index].reactant_mols,
                mapping.reactant_mols,
                path_index=path_index,
            )
        normalized = _remap_reactant_features(
            candidate,
            coordinate_alignment,
            path_index=path_index,
        )
        if set(normalized.atom_features) != reference_maps:
            raise ValueError(
                f"{_SCHEMA_ERROR}: path {path_index} has an incompatible atom correspondence"
            )
        if set(normalized.bonds) != reference_bonds:
            raise ValueError(
                f"{_SCHEMA_ERROR}: path {path_index} has incompatible mapped bond topology "
                "after atom alignment"
            )
        if set(normalized.component_maps) != reference_components:
            raise ValueError(
                f"{_SCHEMA_ERROR}: path {path_index} has incompatible reactant component layout"
            )
        for map_number in sorted(reference_maps):
            if (
                normalized.atom_core_features[map_number]
                != reference.atom_core_features[map_number]
            ):
                raise ValueError(
                    f"{_SCHEMA_ERROR}: atom map {map_number} has incompatible non-stereo "
                    "reactant structure after alignment"
                )
        for pair in sorted(reference_bonds):
            reference_core = tuple(reference.bonds[pair][:-BOND_STEREO_FEATURE_DIM])
            candidate_core = tuple(normalized.bonds[pair][:-BOND_STEREO_FEATURE_DIM])
            if candidate_core != reference_core:
                raise ValueError(
                    f"{_SCHEMA_ERROR}: mapped bond {pair} has incompatible non-stereo "
                    "topology/features after alignment"
                )
        source_map_to_coordinate.append(coordinate_alignment)
        reactants.append(normalized)

    atom_maps = tuple(sorted(reference_maps))
    map_to_node = {map_number: node for node, map_number in enumerate(atom_maps)}
    component_id_by_map: dict[int, int] = {}
    for component_id, component in enumerate(sorted(reference_components)):
        for map_number in component:
            component_id_by_map[map_number] = component_id
    return (
        _ReactantAlignment(
            atom_maps=atom_maps,
            map_to_node=map_to_node,
            edge_maps=tuple(sorted(reference_bonds)),
            component_id_by_map=component_id_by_map,
            group_component_tokens={
                map_number: reference.group_component_tokens[map_number] for map_number in atom_maps
            },
            source_map_to_coordinate=tuple(source_map_to_coordinate),
            reference_path_index=reference_index,
        ),
        tuple(reactants),
    )


def _product_bonds(
    mols: Sequence[Chem.Mol],
    substrate_map_to_node: dict[int, int],
    source_map_to_coordinate: dict[int, int],
) -> dict[tuple[int, int], list[float]]:
    bonds: dict[tuple[int, int], list[float]] = {}
    for mol in mols:
        for bond in mol.GetBonds():
            left_source_map = mol.GetAtomWithIdx(bond.GetBeginAtomIdx()).GetAtomMapNum()
            right_source_map = mol.GetAtomWithIdx(bond.GetEndAtomIdx()).GetAtomMapNum()
            if left_source_map <= 0 or right_source_map <= 0:
                continue
            if left_source_map not in source_map_to_coordinate:
                raise ValueError("Product bond references an atom absent from the path substrate")
            if right_source_map not in source_map_to_coordinate:
                raise ValueError("Product bond references an atom absent from the path substrate")
            left_map = source_map_to_coordinate[left_source_map]
            right_map = source_map_to_coordinate[right_source_map]
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


def _build_change_graph(
    mappings: Sequence[ParsedReaction],
    *,
    alignment: _ReactantAlignment | None = None,
    reactant_features: Sequence[_ReactantFeatures] | None = None,
    source_map_to_coordinate: Sequence[dict[int, int]] | None = None,
) -> Data:
    """Build a change graph in a map-keyed coordinate system.

    The first feature block in a group graph is the element-wise union of all
    compatible reactant schemas.  This keeps the fixed model width while
    retaining every possible mapped stereo feature; path graphs use their
    exact per-path reactant features.
    """
    mappings = tuple(mappings)
    if not mappings:
        raise ValueError("At least one mapped reaction is required")
    if alignment is None:
        alignment, built_reactants = _reactant_alignment(mappings)
        if reactant_features is None:
            reactant_features = built_reactants
        if source_map_to_coordinate is None:
            source_map_to_coordinate = alignment.source_map_to_coordinate
    elif reactant_features is None:
        for mapping in mappings:
            _validate_complete_mapping(mapping)
        raw_reactants = tuple(_reactant_features(mapping.reactant_mols) for mapping in mappings)
        if source_map_to_coordinate is None:
            raise ValueError("Reactant source-map coordinates are required with a shared alignment")
        reactant_features = tuple(
            _remap_reactant_features(
                features,
                source_map_to_coordinate[path_index],
                path_index=path_index,
            )
            for path_index, features in enumerate(raw_reactants)
        )
    if reactant_features is None or len(reactant_features) != len(mappings):
        raise ValueError("Reactant feature rows do not match the mapped reaction paths")
    if source_map_to_coordinate is None or len(source_map_to_coordinate) != len(mappings):
        raise ValueError("Reactant source-map coordinates do not match the mapped reaction paths")

    product_atoms = [
        _remap_atom_features(
            _atom_features_by_map(mapping.product_mols),
            source_map_to_coordinate[path_index],
            path_index=path_index,
            side="product",
        )
        for path_index, mapping in enumerate(mappings)
    ]
    unknown_product_maps = set().union(*(set(table) for table in product_atoms)) - set(
        alignment.map_to_node
    )
    if unknown_product_maps:
        raise ValueError(
            "Product atoms are absent from the group substrate mapping: "
            f"{sorted(unknown_product_maps)}"
        )

    zero_atom = [0.0] * ATOM_FEATURE_DIM
    node_features: list[Tensor] = []
    path_count = len(mappings)
    for map_number in alignment.atom_maps:
        reactant_rows = [features.atom_features[map_number] for features in reactant_features]
        reactant_union = _mean_and_max(reactant_rows, ATOM_FEATURE_DIM)[1]
        product_rows = [table.get(map_number, zero_atom) for table in product_atoms]
        product_mean, product_union = _mean_and_max(product_rows, ATOM_FEATURE_DIM)
        present = sum(map_number in table for table in product_atoms)
        changed = sum(
            features.atom_features[map_number] != table[map_number]
            for features, table in zip(reactant_features, product_atoms, strict=True)
        )
        node_features.append(
            torch.cat(
                (
                    reactant_union,
                    product_mean,
                    product_union,
                    torch.tensor(
                        [present / path_count, changed / path_count],
                        dtype=torch.float32,
                    ),
                )
            )
        )

    product_bonds = [
        _product_bonds(
            mapping.product_mols,
            alignment.map_to_node,
            source_map_to_coordinate[path_index],
        )
        for path_index, mapping in enumerate(mappings)
    ]
    edge_key_set = set(alignment.edge_maps)
    for table in product_bonds:
        edge_key_set.update(
            (alignment.atom_maps[left], alignment.atom_maps[right]) for left, right in table
        )
    edge_keys: list[tuple[int, int]] = sorted(edge_key_set)
    zero_edge = [0.0] * EDGE_FEATURE_DIM
    directed_edges: list[tuple[int, int]] = []
    directed_features: list[Tensor] = []
    for edge_map_key in edge_keys:
        edge_key: tuple[int, int] = (
            alignment.map_to_node[edge_map_key[0]],
            alignment.map_to_node[edge_map_key[1]],
        )
        reactant_rows = [
            features.bonds.get(edge_map_key, zero_edge) for features in reactant_features
        ]
        substrate_feature = _mean_and_max(reactant_rows, EDGE_FEATURE_DIM)[1]
        product_rows = [table.get(edge_key, zero_edge) for table in product_bonds]
        product_mean, product_union = _mean_and_max(product_rows, EDGE_FEATURE_DIM)
        substrate_present = edge_map_key in alignment.edge_maps
        formed = broken = bond_type_changed = stereo_changed = changed = 0
        for features, table, product_feature in zip(
            reactant_features,
            product_bonds,
            product_rows,
            strict=True,
        ):
            path_substrate = features.bonds.get(edge_map_key, zero_edge)
            product_present = edge_key in table
            formed += int(not substrate_present and product_present)
            broken += int(substrate_present and not product_present)
            if substrate_present and product_present:
                bond_type_changed += int(
                    path_substrate[:BOND_TYPE_FEATURE_DIM]
                    != product_feature[:BOND_TYPE_FEATURE_DIM]
                )
                stereo_changed += int(
                    path_substrate[-BOND_STEREO_FEATURE_DIM:]
                    != product_feature[-BOND_STEREO_FEATURE_DIM:]
                )
            changed += int(path_substrate != product_feature)
        feature = torch.cat(
            (
                substrate_feature,
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
    component_tokens = (
        alignment.group_component_tokens
        if len(mappings) > 1
        else reactant_features[0].component_tokens
    )
    atom_map_numbers = torch.tensor(alignment.atom_maps, dtype=torch.long)
    return Data(
        x=torch.stack(node_features),
        edge_index=edge_index,
        edge_attr=torch.stack(directed_features)
        if directed_features
        else torch.empty((0, CHANGE_EDGE_FEATURE_DIM), dtype=torch.float32),
        atom_map_numbers=atom_map_numbers,
        component_id=torch.tensor(
            [alignment.component_id_by_map[map_number] for map_number in alignment.atom_maps],
            dtype=torch.long,
        ),
        component_token_id=torch.tensor(
            [component_tokens[map_number] for map_number in alignment.atom_maps],
            dtype=torch.long,
        ),
    )


def reaction_change_graphs(mappings: Sequence[ParsedReaction]) -> ReactionChangeGraphs:
    """Build one permutation-invariant group graph and exact per-path CGRs."""
    mappings = tuple(mappings)
    alignment, reactant_features = _reactant_alignment(mappings)
    group = _build_change_graph(
        mappings,
        alignment=alignment,
        reactant_features=reactant_features,
        source_map_to_coordinate=alignment.source_map_to_coordinate,
    )
    paths = tuple(
        _build_change_graph(
            (mapping,),
            alignment=alignment,
            reactant_features=(reactant_features[path_index],),
            source_map_to_coordinate=(alignment.source_map_to_coordinate[path_index],),
        )
        for path_index, mapping in enumerate(mappings)
    )

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
        path_source_map_to_coordinate=alignment.source_map_to_coordinate,
        reference_path_index=alignment.reference_path_index,
    )


__all__ = [
    "CHANGE_ATOM_FEATURE_DIM",
    "CHANGE_EDGE_FEATURE_DIM",
    "ReactionChangeGraphs",
    "reaction_change_graphs",
]
