from rdkit import Chem

from rxnresid.data.featurizer import (
    ATOM_FEATURE_DIM,
    EDGE_FEATURE_DIM,
    component_token_id,
    molecules_to_graph,
)
from rxnresid.data.mapping_features import reaction_stereo_signature_token
from rxnresid.data.reaction_parser import parse_mapped_reaction
from tests.helpers import dataset


def test_reaction_graph_contains_features_and_map_numbers() -> None:
    sample = dataset()[0]
    assert sample.reactant.x.shape[1] == ATOM_FEATURE_DIM
    assert sample.reactant.edge_attr.shape[1] == EDGE_FEATURE_DIM
    assert sample.products[0].x.shape[1] == ATOM_FEATURE_DIM
    assert int(sample.reactant.atom_map_numbers.max()) > 0
    assert sample.mappings[0].edits.reaction_center_atoms > 0


def test_parser_preserves_stereo_and_mapping() -> None:
    parsed = parse_mapped_reaction(
        "F[C@:1](Cl)(Br)I>>F[C@@:1](Cl)(Br)I",
        require_complete_mapping=True,
    )
    assert parsed.atom_mapping[1] == (1, 1)
    assert parsed.edits.tetrahedral_inversion == 1


def test_stereo_signature_token_is_stable_and_reserved_from_zero() -> None:
    mapping = dataset()[0].mappings[0]
    token = reaction_stereo_signature_token(mapping)
    assert token > 0
    assert token == reaction_stereo_signature_token(mapping)


def test_component_hash_bucket_count_controls_preprocessed_tokens() -> None:
    molecule = Chem.MolFromSmiles("C")
    assert molecule is not None

    default_token = component_token_id(molecule)
    expanded_token = component_token_id(molecule, 65536)
    graph = molecules_to_graph((molecule,), component_hash_buckets=65536)

    assert 0 < default_token < 4096
    assert 4096 <= expanded_token < 65536
    assert graph.component_token_id.unique().tolist() == [expanded_token]
