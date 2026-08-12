import pytest

from rxnresid.data.grouping import canonical_reactant_key, group_id_from_reaction
from rxnresid.data.reaction_parser import ReactionParseError, parse_mapped_reaction


REACTION = "[C:1](=[C:2])([H:3])[H:4].[c:5]1[s:6][c:7][c:8][c:9]1>>[C:1]1([H:3])([H:4])[C:2]([H:5])([H:6])[c:5]2[s:6][c:7][c:8][c:9]12"


def test_map_numbers_do_not_change_group_id() -> None:
    changed = REACTION.replace(":1", ":101").replace(":2", ":102").replace(":5", ":105")
    assert group_id_from_reaction(REACTION) == group_id_from_reaction(changed)
    assert canonical_reactant_key("[C:1]=[C:2].[O:3]") == canonical_reactant_key(
        "[O:30].[C:20]=[C:10]"
    )


def test_stereochemistry_changes_reactant_group_key() -> None:
    left = "F[C@:1](Cl)(Br)I>>F[C@:1](Cl)(Br)I"
    right = "F[C@@:1](Cl)(Br)I>>F[C@@:1](Cl)(Br)I"
    assert group_id_from_reaction(left) != group_id_from_reaction(right)


def test_configured_conditions_change_group_id() -> None:
    assert group_id_from_reaction(REACTION, {"solvent": "THF"}) != group_id_from_reaction(
        REACTION,
        {"solvent": "water"},
    )


def test_parser_rejects_malformed_reactions() -> None:
    with pytest.raises(ReactionParseError):
        parse_mapped_reaction("C>>C>>C")
