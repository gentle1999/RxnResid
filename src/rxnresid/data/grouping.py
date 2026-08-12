"""Stable reaction-group keys derived from unmapped reactants."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from rdkit import Chem

from rxnresid.data.reaction_parser import ParsedReaction, parse_mapped_reaction


def canonical_reactant_key(mapped_reactants: str) -> str:
    """Canonicalize disconnected reactant components while removing map labels."""
    canonical_components: list[str] = []
    for component in mapped_reactants.split("."):
        mol = Chem.MolFromSmiles(component)
        if mol is None:
            raise ValueError(f"Could not parse reactant component: {component!r}")
        for atom in mol.GetAtoms():
            atom.SetAtomMapNum(0)
        canonical_components.append(Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True))
    return ".".join(sorted(canonical_components))


def reaction_group_key(
    parsed: ParsedReaction,
    conditions: Mapping[str, object] | None = None,
) -> str:
    """Build the auditable canonical key before hashing."""
    reactant_key = canonical_reactant_key(parsed.mapped_reactants)
    if not conditions:
        return reactant_key
    normalized = {name: str(value).strip() for name, value in conditions.items()}
    condition_key = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return f"{reactant_key}||{condition_key}"


def group_id_from_parsed(
    parsed: ParsedReaction,
    conditions: Mapping[str, object] | None = None,
) -> str:
    key = reaction_group_key(parsed, conditions)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"group_{digest}"


def group_id_from_reaction(
    rxn_smiles: str,
    conditions: Mapping[str, object] | None = None,
) -> str:
    """Create a compact, deterministic group id from reactants and conditions."""
    return group_id_from_parsed(parse_mapped_reaction(rxn_smiles), conditions)
