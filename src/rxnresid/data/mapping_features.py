"""Public mapping/edit feature helpers."""

from __future__ import annotations

import hashlib
from functools import cache

import torch
from rdkit import Chem
from torch import Tensor

from rxnresid.data.reaction_parser import EDIT_FEATURE_NAMES, ParsedReaction, ReactionEdits


STEREO_SIGNATURE_HASH_BUCKETS = 4096
_STEREO_TOKEN_CACHE: dict[tuple[str, str, tuple[int, ...], int], int] = {}


@cache
def _cached_edit_features(edits: ReactionEdits) -> Tensor:
    return torch.tensor(edits.as_tuple(), dtype=torch.float32)


def reaction_edit_features(parsed: ParsedReaction) -> Tensor:
    """Convert the parser's fixed-size edit summary to a float tensor."""
    return _cached_edit_features(parsed.edits)


def reaction_stereo_signature_token(
    parsed: ParsedReaction,
    num_buckets: int = STEREO_SIGNATURE_HASH_BUCKETS,
) -> int:
    """Hash the mapped-center CIP/chiral sequence while reserving zero."""
    if num_buckets < 2:
        raise ValueError("num_buckets must reserve at least one stereo-signature bucket")
    cache_key = (
        parsed.mapped_reactants,
        parsed.mapped_products,
        parsed.edits.reaction_center_maps,
        num_buckets,
    )
    cached = _STEREO_TOKEN_CACHE.get(cache_key)
    if cached is not None:
        return cached
    product_atoms = {
        atom.GetAtomMapNum(): (
            atom.GetProp("_CIPCode") if atom.HasProp("_CIPCode") else "N",
            str(atom.GetChiralTag()),
        )
        for molecule in parsed.product_mols
        for atom in molecule.GetAtoms()
    }
    signature = tuple(
        product_atoms.get(
            map_number,
            ("N", str(Chem.ChiralType.CHI_UNSPECIFIED)),
        )
        for map_number in parsed.edits.reaction_center_maps
    )
    digest = hashlib.sha1(repr(signature).encode("ascii")).digest()
    token = int.from_bytes(digest[:8], "big") % (num_buckets - 1) + 1
    _STEREO_TOKEN_CACHE[cache_key] = token
    return token


__all__ = [
    "EDIT_FEATURE_NAMES",
    "STEREO_SIGNATURE_HASH_BUCKETS",
    "reaction_edit_features",
    "reaction_stereo_signature_token",
]
