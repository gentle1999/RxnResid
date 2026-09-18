import pytest
import torch
from torch_geometric.data import Data

from rxnresid.data.change_graphs import (
    CHANGE_ATOM_FEATURE_DIM,
    CHANGE_EDGE_FEATURE_DIM,
    reaction_change_graphs,
)
from rxnresid.data.reaction_parser import parse_mapped_reaction


FORMING = "[CH3:1].[CH3:2]>>[CH3:1][CH3:2]"
UNCHANGED = "[CH3:1].[CH3:2]>>[CH3:1].[CH3:2]"


def _edge_feature(graph: Data, left: int, right: int) -> torch.Tensor | None:
    matches = (graph.edge_index[0] == left) & (graph.edge_index[1] == right)
    indices = matches.nonzero(as_tuple=False).flatten()
    if indices.numel() == 0:
        return None
    assert indices.numel() == 1
    return graph.edge_attr[indices.item()]


def test_union_graph_tracks_possible_forming_bond_support() -> None:
    graphs = reaction_change_graphs(
        [parse_mapped_reaction(FORMING), parse_mapped_reaction(UNCHANGED)]
    )

    assert graphs.group.x.shape == (2, CHANGE_ATOM_FEATURE_DIM)
    assert graphs.group.edge_attr.shape == (2, CHANGE_EDGE_FEATURE_DIM)
    group_edge = _edge_feature(graphs.group, 0, 1)
    assert group_edge is not None
    assert group_edge[-5:].tolist() == pytest.approx([0.5, 0.0, 0.0, 0.0, 0.5])

    forming_edge = _edge_feature(graphs.paths[0], 0, 1)
    assert forming_edge is not None
    assert forming_edge[-5:].tolist() == pytest.approx([1.0, 0.0, 0.0, 0.0, 1.0])
    assert _edge_feature(graphs.paths[1], 0, 1) is None
    unchanged_delta = _edge_feature(graphs.deltas[1], 0, 1)
    assert unchanged_delta is not None
    assert unchanged_delta[-5:].tolist() == pytest.approx([-0.5, 0.0, 0.0, 0.0, -0.5])


def test_union_graph_is_invariant_to_path_order() -> None:
    mappings = [parse_mapped_reaction(FORMING), parse_mapped_reaction(UNCHANGED)]
    forward = reaction_change_graphs(mappings).group
    reverse = reaction_change_graphs(list(reversed(mappings))).group

    assert torch.equal(forward.edge_index, reverse.edge_index)
    assert torch.allclose(forward.x, reverse.x)
    assert torch.allclose(forward.edge_attr, reverse.edge_attr)


def test_change_graph_rejects_inconsistent_group_reactants() -> None:
    inconsistent = parse_mapped_reaction("[CH3:1].[OH:2]>>[CH3:1][OH:2]")
    with pytest.raises(ValueError, match="consistent mapped reactant"):
        reaction_change_graphs([parse_mapped_reaction(FORMING), inconsistent])


def test_change_graph_rejects_incompatible_mapped_bond_topology() -> None:
    first = parse_mapped_reaction("[CH3:1][CH2:2].[CH3:3][CH2:4]>>[CH3:1][CH2:2].[CH3:3][CH2:4]")
    second = parse_mapped_reaction("[CH3:1][CH2:2][CH3:3].[CH2:4]>>[CH3:1][CH2:2][CH3:3].[CH2:4]")
    with pytest.raises(ValueError, match="incompatible unmapped reactant structure/topology"):
        reaction_change_graphs([first, second])


def test_change_graph_rejects_non_equivalent_reactant_stereo() -> None:
    first = parse_mapped_reaction(r"[F:1]/[C:2]=[C:3]/[F:4]>>[F:1]/[C:2]=[C:3]/[F:4]")
    second = parse_mapped_reaction(r"[F:1]/[C:2]=[C:3]\[F:4]>>[F:1]/[C:2]=[C:3]\[F:4]")
    with pytest.raises(ValueError, match="non-equivalent reactant stereo"):
        reaction_change_graphs([first, second])


def test_change_graph_requires_complete_mapping() -> None:
    incomplete = parse_mapped_reaction("[CH3:1].O>>[CH3:1]O")
    with pytest.raises(ValueError, match="every reactant atom"):
        reaction_change_graphs([incomplete])
