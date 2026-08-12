from predict import _build_prediction_loader
from rxnresid.data.dataset import ReactionPathDataset
from rxnresid.prediction_output import prediction_rows
from rxnresid.training.trainer import PredictionRecord
from tests.helpers import dataset


def _record(path_id: str) -> PredictionRecord:
    return PredictionRecord(
        path_id=path_id,
        group_id=f"group-{path_id}",
        substrate_group=f"substrate-{path_id}",
        prediction=2.0,
        target=3.0,
        baseline=1.5,
        residual=0.5,
    )


def test_prediction_rows_are_sorted_by_numeric_component_ids() -> None:
    records = [_record("10"), _record("2"), _record("1")]
    metadata = {
        "10": {"ene_id": "2", "diene_id": "10"},
        "2": {"ene_id": "2", "diene_id": "2"},
        "1": {"ene_id": "10", "diene_id": "1"},
    }

    rows = prediction_rows(records, metadata, ("ene_id", "diene_id"))

    assert [row["path_id"] for row in rows] == ["2", "10", "1"]
    assert rows[0]["ene_id"] == "2"
    assert rows[0]["prediction"] == rows[0]["baseline"] + rows[0]["residual"]


def test_grouped_prediction_loader_does_not_split_route_sets() -> None:
    source = dataset()
    group_indices = [
        next(index for index, sample in enumerate(source) if len(sample) == size) for size in (2, 4)
    ]
    paths = ReactionPathDataset(source, group_indices)
    loader = _build_prediction_loader(
        paths,
        batch_size=3,
        complete_groups=True,
        pin_memory=False,
    )
    batches = list(loader)
    assert sorted(batch.num_paths for batch in batches) == [2, 4]
    assert all(batch.num_groups == 1 for batch in batches)
