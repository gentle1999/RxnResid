"""Stable reaction-group keys derived from unmapped reactants."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from rdkit import Chem

from rxnresid.data.reaction_parser import ParsedReaction


def canonical_reactant_key(mapped_reactants: str, *, include_stereo: bool = True) -> str:
    """Canonicalize disconnected reactant components while removing map labels."""
    canonical_components: list[str] = []
    params: Any = Chem.SmilesParserParams()
    params.removeHs = False
    for component in mapped_reactants.split("."):
        mol = Chem.MolFromSmiles(component, params)
        if mol is None or mol.GetNumAtoms() == 0:
            raise ValueError(f"Could not parse reactant component: {component!r}")
        for atom in mol.GetAtoms():
            atom.SetAtomMapNum(0)
        if not include_stereo:
            Chem.RemoveStereochemistry(mol)
        canonical_components.append(Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True))
    return ".".join(sorted(canonical_components))


def reactant_group_key(
    mapped_reactants: str,
    conditions: Mapping[str, object] | None = None,
    *,
    include_stereo: bool = True,
) -> str:
    """Build the auditable canonical key before hashing."""
    reactant_key = canonical_reactant_key(mapped_reactants, include_stereo=include_stereo)
    if not conditions:
        return reactant_key
    normalized = {name: str(value).strip() for name, value in conditions.items()}
    condition_key = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return f"{reactant_key}||{condition_key}"


def reaction_group_key(
    parsed: ParsedReaction,
    conditions: Mapping[str, object] | None = None,
    *,
    include_stereo: bool = True,
) -> str:
    return reactant_group_key(parsed.mapped_reactants, conditions, include_stereo=include_stereo)


def _group_id(key: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"group_{digest}"


def group_id_from_parsed(
    parsed: ParsedReaction,
    conditions: Mapping[str, object] | None = None,
    *,
    include_stereo: bool = True,
) -> str:
    key = reaction_group_key(parsed, conditions, include_stereo=include_stereo)
    return _group_id(key)


def group_id_from_reaction(
    rxn_smiles: str,
    conditions: Mapping[str, object] | None = None,
    *,
    include_stereo: bool = True,
) -> str:
    """Create a compact, deterministic group id from reactants and conditions."""
    parts = rxn_smiles.split(">>")
    if len(parts) != 2:
        raise ValueError("Reaction SMILES must contain exactly one '>>'")
    # Product validity and map completeness are independent record checks.
    return _group_id(reactant_group_key(parts[0], conditions, include_stereo=include_stereo))
