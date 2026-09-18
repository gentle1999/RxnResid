"""RDKit molecular graphs with stereochemical atom and bond features."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

import torch
from rdkit import Chem
from torch_geometric.data import Data

from rxnresid.data.reaction_parser import ParsedReaction


_ATOMIC_NUMBERS = (1, 5, 6, 7, 8, 9, 14, 15, 16, 17, 35, 53)
_DEGREES = (0, 1, 2, 3, 4, 5)
_FORMAL_CHARGES = (-2, -1, 0, 1, 2)
_HYDROGEN_COUNTS = (0, 1, 2, 3, 4)
_HYBRIDIZATIONS = (
    Chem.HybridizationType.S,
    Chem.HybridizationType.SP,
    Chem.HybridizationType.SP2,
    Chem.HybridizationType.SP3,
    Chem.HybridizationType.SP3D,
    Chem.HybridizationType.SP3D2,
)
_CHIRAL_TAGS = (
    Chem.ChiralType.CHI_UNSPECIFIED,
    Chem.ChiralType.CHI_TETRAHEDRAL_CW,
    Chem.ChiralType.CHI_TETRAHEDRAL_CCW,
)
_CIP_CODES = ("R", "S")
_BOND_TYPES = (
    Chem.BondType.SINGLE,
    Chem.BondType.DOUBLE,
    Chem.BondType.TRIPLE,
    Chem.BondType.AROMATIC,
)
_BOND_STEREO = (
    Chem.BondStereo.STEREONONE,
    Chem.BondStereo.STEREOANY,
    Chem.BondStereo.STEREOZ,
    Chem.BondStereo.STEREOE,
    Chem.BondStereo.STEREOCIS,
    Chem.BondStereo.STEREOTRANS,
)
COMPONENT_HASH_BUCKETS = 4096


def mapped_component_key(mol: Chem.Mol) -> str:
    """Return a collision-free key for one mapped component occurrence."""
    return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)


def split_component_graphs(graph: Data) -> tuple[Data, ...]:
    """Split a cached disconnected graph without recomputing atom features."""
    component_ids = set(graph.component_id.tolist())
    if not component_ids:
        raise ValueError("A molecular graph must contain at least one component")
    expected_ids = set(range(max(component_ids) + 1))
    if component_ids != expected_ids:
        raise ValueError(f"Component ids must be contiguous from zero, got {sorted(component_ids)}")
    components: list[Data] = []
    for component_id in range(len(component_ids)):
        node_index = (graph.component_id == component_id).nonzero(as_tuple=False).flatten()
        component = graph.subgraph(node_index)
        component.component_id = torch.zeros_like(component.component_id)
        components.append(component)
    return tuple(components)


def component_token_id(
    mol: Chem.Mol,
    num_buckets: int = COMPONENT_HASH_BUCKETS,
    *,
    isomeric_smiles: bool = True,
) -> int:
    """Return a stable structure token while reserving zero for unknowns."""
    if num_buckets < 2:
        raise ValueError("num_buckets must reserve at least one known-component bucket")
    canonical = Chem.Mol(mol)
    for atom in canonical.GetAtoms():
        atom.SetAtomMapNum(0)
    if not isomeric_smiles:
        Chem.RemoveStereochemistry(canonical)
    smiles = Chem.MolToSmiles(canonical, canonical=True, isomericSmiles=isomeric_smiles)
    digest = hashlib.sha1(smiles.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (num_buckets - 1) + 1


def _one_hot(value: object, choices: tuple[object, ...]) -> list[float]:
    return [1.0 if value == choice else 0.0 for choice in choices] + [
        1.0 if value not in choices else 0.0
    ]


def atom_feature(atom: Chem.Atom) -> list[float]:
    """Return the molecular atom feature vector, excluding atom-map number."""
    return (
        _one_hot(atom.GetAtomicNum(), _ATOMIC_NUMBERS)
        + _one_hot(atom.GetDegree(), _DEGREES)
        + _one_hot(atom.GetFormalCharge(), _FORMAL_CHARGES)
        + _one_hot(atom.GetTotalNumHs(includeNeighbors=True), _HYDROGEN_COUNTS)
        + _one_hot(atom.GetHybridization(), _HYBRIDIZATIONS)
        + [float(atom.GetIsAromatic()), float(atom.IsInRing())]
        + _one_hot(atom.GetChiralTag(), _CHIRAL_TAGS)
        + _one_hot(atom.GetProp("_CIPCode") if atom.HasProp("_CIPCode") else None, _CIP_CODES)
    )


def bond_feature(bond: Chem.Bond) -> list[float]:
    """Return bond order, aromaticity, ring, conjugation, and stereo features."""
    return (
        _one_hot(bond.GetBondType(), _BOND_TYPES)
        + [
            float(bond.GetIsConjugated()),
            float(bond.GetIsAromatic()),
            float(bond.IsInRing()),
        ]
        + _one_hot(bond.GetStereo(), _BOND_STEREO)
    )


ATOM_FEATURE_DIM = len(atom_feature(Chem.MolFromSmiles("C").GetAtomWithIdx(0)))
EDGE_FEATURE_DIM = len(bond_feature(Chem.MolFromSmiles("C=C").GetBondWithIdx(0)))
BOND_TYPE_FEATURE_DIM = len(_BOND_TYPES) + 1
BOND_STEREO_FEATURE_DIM = len(_BOND_STEREO) + 1
ATOM_STEREO_FEATURE_DIM = len(_CHIRAL_TAGS) + 1 + len(_CIP_CODES) + 1


def molecules_to_graph(
    molecules: Iterable[Chem.Mol],
    *,
    component_hash_buckets: int = COMPONENT_HASH_BUCKETS,
) -> Data:
    """Build one disconnected PyG graph from all supplied components."""
    molecules = tuple(molecules)
    if not molecules:
        raise ValueError("At least one molecule is required")
    node_features: list[list[float]] = []
    atom_maps: list[int] = []
    component_ids: list[int] = []
    component_tokens: list[int] = []
    edge_indices: list[tuple[int, int]] = []
    edge_features: list[list[float]] = []
    node_offset = 0
    for component_id, mol in enumerate(molecules):
        token_id = component_token_id(mol, component_hash_buckets)
        for atom in mol.GetAtoms():
            node_features.append(atom_feature(atom))
            atom_maps.append(atom.GetAtomMapNum())
            component_ids.append(component_id)
            component_tokens.append(token_id)
        for bond in mol.GetBonds():
            begin = node_offset + bond.GetBeginAtomIdx()
            end = node_offset + bond.GetEndAtomIdx()
            features = bond_feature(bond)
            edge_indices.extend(((begin, end), (end, begin)))
            edge_features.extend((features, features))
        node_offset += mol.GetNumAtoms()
    edge_index = torch.tensor(edge_indices, dtype=torch.long).t().contiguous()
    if not edge_indices:
        edge_index = torch.empty((2, 0), dtype=torch.long)
    return Data(
        x=torch.tensor(node_features, dtype=torch.float32),
        edge_index=edge_index,
        edge_attr=torch.tensor(edge_features, dtype=torch.float32).reshape(-1, EDGE_FEATURE_DIM),
        atom_map_numbers=torch.tensor(atom_maps, dtype=torch.long),
        component_id=torch.tensor(component_ids, dtype=torch.long),
        component_token_id=torch.tensor(component_tokens, dtype=torch.long),
    )


def reaction_graphs(
    parsed: ParsedReaction,
    *,
    component_hash_buckets: int = COMPONENT_HASH_BUCKETS,
) -> tuple[Data, Data]:
    """Build the substrate graph and one product graph for a parsed path."""
    return (
        molecules_to_graph(
            parsed.reactant_mols,
            component_hash_buckets=component_hash_buckets,
        ),
        molecules_to_graph(
            parsed.product_mols,
            component_hash_buckets=component_hash_buckets,
        ),
    )


__all__ = [
    "ATOM_FEATURE_DIM",
    "ATOM_STEREO_FEATURE_DIM",
    "BOND_STEREO_FEATURE_DIM",
    "BOND_TYPE_FEATURE_DIM",
    "COMPONENT_HASH_BUCKETS",
    "EDGE_FEATURE_DIM",
    "atom_feature",
    "bond_feature",
    "component_token_id",
    "mapped_component_key",
    "molecules_to_graph",
    "reaction_graphs",
    "split_component_graphs",
]
