import pytest

from rxnresid.analysis.acquisition import acquisition_score, select_acquisition
from rxnresid.training.trainer import PredictionRecord


def _record(path_id: str, aleatoric: float, epistemic: float) -> PredictionRecord:
    return PredictionRecord(
        path_id=path_id,
        group_id="group",
        substrate_group="substrates",
        prediction=1.0,
        target=2.0,
        baseline=0.5,
        residual=0.5,
        aleatoric_variance=aleatoric,
        epistemic_variance=epistemic,
        predictive_variance=aleatoric + epistemic,
    )


def test_uncertainty_acquisition_ranks_individual_reactions() -> None:
    records = [_record("a", 4.0, 1.0), _record("b", 1.0, 5.0), _record("c", 2.0, 2.0)]

    assert select_acquisition(records, "predictive", 2) == [records[1], records[0]]
    assert select_acquisition(records, "epistemic", 1) == [records[1]]
    assert select_acquisition(records, "aleatoric", 1) == [records[0]]


def test_random_acquisition_is_seeded_and_does_not_require_uncertainty() -> None:
    records = [_record(str(index), 1.0, 1.0) for index in range(8)]
    first = select_acquisition(records, "random", 4, seed=7)
    second = select_acquisition(records, "random", 4, seed=7)

    assert first == second
    with pytest.raises(ValueError, match="does not define"):
        acquisition_score(records[0], "random")


def test_uncertainty_acquisition_rejects_missing_values() -> None:
    record = PredictionRecord(
        path_id="missing",
        group_id="group",
        substrate_group="substrates",
        prediction=1.0,
        target=2.0,
        baseline=0.5,
        residual=0.5,
    )

    with pytest.raises(ValueError, match="no finite epistemic"):
        select_acquisition([record], "epistemic", 1)
