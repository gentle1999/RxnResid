"""Strict parsing and reaction-center extraction for mapped RXN SMILES."""

from __future__ import annotations

from dataclasses import dataclass

from rdkit import Chem


class ReactionParseError(ValueError):
    """Raised when a mapped reaction cannot be represented safely."""


EDIT_FEATURE_NAMES = (
    "formed_bonds",
    "broken_bonds",
    "bond_order_changes",
    "single_to_double",
    "double_to_single",
    "aromatic_bond_changes",
    "degree_changes",
    "formal_charge_changes",
    "hybridization_changes",
    "reaction_center_atoms",
    "tetrahedral_created",
    "tetrahedral_removed",
    "tetrahedral_inversion",
    "ez_created",
    "ez_changed",
)


@dataclass(frozen=True)
class ReactionEdits:
    """Fixed-size reaction-change summary and reaction-center map numbers."""

    formed_bonds: int
    broken_bonds: int
    bond_order_changes: int
    single_to_double: int
    double_to_single: int
    aromatic_bond_changes: int
    degree_changes: int
    formal_charge_changes: int
    hybridization_changes: int
    reaction_center_atoms: int
    tetrahedral_created: int
    tetrahedral_removed: int
    tetrahedral_inversion: int
    ez_created: int
    ez_changed: int
    reaction_center_maps: tuple[int, ...]

    def as_tuple(self) -> tuple[float, ...]:
        return tuple(float(getattr(self, name)) for name in EDIT_FEATURE_NAMES)


@dataclass(frozen=True)
class ParsedReaction:
    """Parsed reaction and map-number correspondence between both sides."""

    mapped_reactants: str
    mapped_products: str
    reactant_mols: tuple[Chem.Mol, ...]
    product_mols: tuple[Chem.Mol, ...]
    atom_mapping: dict[int, tuple[int, int]]
    edits: ReactionEdits


def _parse_side(side: str, label: str) -> tuple[tuple[Chem.Mol, ...], dict[int, int]]:
    if not side:
        raise ReactionParseError(f"{label} side is empty")
    molecules: list[Chem.Mol] = []
    map_to_index: dict[int, int] = {}
    atom_offset = 0
    for component in side.split("."):
        mol = Chem.MolFromSmiles(component)
        if mol is None:
            raise ReactionParseError(f"Could not parse {label} component: {component!r}")
        molecules.append(mol)
        for atom in mol.GetAtoms():
            map_number = atom.GetAtomMapNum()
            if map_number <= 0:
                continue
            if map_number in map_to_index:
                raise ReactionParseError(f"Duplicate atom map number {map_number} on {label} side")
            map_to_index[map_number] = atom_offset + atom.GetIdx()
        atom_offset += mol.GetNumAtoms()
    return tuple(molecules), map_to_index


def _atom_properties(mols: tuple[Chem.Mol, ...]) -> dict[int, tuple[int, int, str, str]]:
    properties: dict[int, tuple[int, int, str, str]] = {}
    for mol in mols:
        for atom in mol.GetAtoms():
            map_number = atom.GetAtomMapNum()
            if map_number <= 0:
                continue
            properties[map_number] = (
                atom.GetDegree(),
                atom.GetFormalCharge(),
                str(atom.GetHybridization()),
                atom.GetProp("_CIPCode") if atom.HasProp("_CIPCode") else "",
            )
    return properties


def _bond_table(mols: tuple[Chem.Mol, ...]) -> dict[tuple[int, int], tuple[float, bool, str]]:
    table: dict[tuple[int, int], tuple[float, bool, str]] = {}
    for mol in mols:
        for bond in mol.GetBonds():
            begin = mol.GetAtomWithIdx(bond.GetBeginAtomIdx()).GetAtomMapNum()
            end = mol.GetAtomWithIdx(bond.GetEndAtomIdx()).GetAtomMapNum()
            if begin <= 0 or end <= 0:
                continue
            key = (min(begin, end), max(begin, end))
            table[key] = (
                bond.GetBondTypeAsDouble(),
                bond.GetIsAromatic(),
                str(bond.GetStereo()),
            )
    return table


def _extract_edits(
    reactant_mols: tuple[Chem.Mol, ...], product_mols: tuple[Chem.Mol, ...]
) -> ReactionEdits:
    reactant_bonds = _bond_table(reactant_mols)
    product_bonds = _bond_table(product_mols)
    formed = broken = order_changes = single_to_double = double_to_single = 0
    aromatic_changes = ez_created = ez_changed = 0
    reaction_center: set[int] = set()

    for key in sorted(set(reactant_bonds) | set(product_bonds)):
        reactant = reactant_bonds.get(key)
        product = product_bonds.get(key)
        if reactant is None:
            formed += 1
            reaction_center.update(key)
            if product and product[2] != "STEREONONE":
                ez_created += 1
            continue
        if product is None:
            broken += 1
            reaction_center.update(key)
            continue
        if reactant[0] != product[0]:
            order_changes += 1
            reaction_center.update(key)
            if reactant[0] == 1.0 and product[0] == 2.0:
                single_to_double += 1
            if reactant[0] == 2.0 and product[0] == 1.0:
                double_to_single += 1
        if reactant[1] != product[1]:
            aromatic_changes += 1
            reaction_center.update(key)
        if reactant[2] != product[2]:
            ez_changed += 1
            reaction_center.update(key)

    reactant_atom_props = _atom_properties(reactant_mols)
    product_atom_props = _atom_properties(product_mols)
    degree_changes = formal_charge_changes = hybridization_changes = 0
    tetrahedral_created = tetrahedral_removed = tetrahedral_inversion = 0
    for map_number in sorted(set(reactant_atom_props) & set(product_atom_props)):
        reactant_atom = reactant_atom_props[map_number]
        product_atom = product_atom_props[map_number]
        if reactant_atom[0] != product_atom[0]:
            degree_changes += 1
            reaction_center.add(map_number)
        if reactant_atom[1] != product_atom[1]:
            formal_charge_changes += 1
            reaction_center.add(map_number)
        if reactant_atom[2] != product_atom[2]:
            hybridization_changes += 1
            reaction_center.add(map_number)
        reactant_chiral = bool(reactant_atom[3])
        product_chiral = bool(product_atom[3])
        if not reactant_chiral and product_chiral:
            tetrahedral_created += 1
            reaction_center.add(map_number)
        elif reactant_chiral and not product_chiral:
            tetrahedral_removed += 1
            reaction_center.add(map_number)
        elif reactant_chiral and product_chiral and reactant_atom[3] != product_atom[3]:
            tetrahedral_inversion += 1
            reaction_center.add(map_number)

    return ReactionEdits(
        formed_bonds=formed,
        broken_bonds=broken,
        bond_order_changes=order_changes,
        single_to_double=single_to_double,
        double_to_single=double_to_single,
        aromatic_bond_changes=aromatic_changes,
        degree_changes=degree_changes,
        formal_charge_changes=formal_charge_changes,
        hybridization_changes=hybridization_changes,
        reaction_center_atoms=len(reaction_center),
        tetrahedral_created=tetrahedral_created,
        tetrahedral_removed=tetrahedral_removed,
        tetrahedral_inversion=tetrahedral_inversion,
        ez_created=ez_created,
        ez_changed=ez_changed,
        reaction_center_maps=tuple(sorted(reaction_center)),
    )


def parse_mapped_reaction(
    rxn_smiles: str, require_complete_mapping: bool = False
) -> ParsedReaction:
    """Parse ``reactants>>products`` and extract map correspondence and edits."""
    parts = rxn_smiles.split(">>")
    if len(parts) != 2:
        raise ReactionParseError("Reaction SMILES must contain exactly one '>>'")
    mapped_reactants, mapped_products = parts
    reactant_mols, reactant_maps = _parse_side(mapped_reactants, "reactant")
    product_mols, product_maps = _parse_side(mapped_products, "product")
    if require_complete_mapping and set(reactant_maps) != set(product_maps):
        raise ReactionParseError("Reactant and product atom maps are not identical")
    atom_mapping = {
        map_number: (reactant_maps[map_number], product_maps[map_number])
        for map_number in sorted(set(reactant_maps) & set(product_maps))
    }
    return ParsedReaction(
        mapped_reactants=mapped_reactants,
        mapped_products=mapped_products,
        reactant_mols=reactant_mols,
        product_mols=product_mols,
        atom_mapping=atom_mapping,
        edits=_extract_edits(reactant_mols, product_mols),
    )
