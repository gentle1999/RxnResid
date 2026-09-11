from pathlib import Path

import pytest
import torch

import rxnresid.inference as inference
from rxnresid.config import load_project_config
from tests.helpers import tiny_rxnresid_model


def test_predict_one_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="route_id"):
        inference.predict_one(Path("missing.pt"), "C>>C", route_id=-1)
    with pytest.raises(ValueError, match="reaction_smiles"):
        inference.predict_one(Path("missing.pt"), " ")
    with pytest.raises(ValueError, match="path_id"):
        inference.predict_one(Path("missing.pt"), "C>>C", path_id=" ")


def test_predict_one_returns_physical_prediction_and_uncertainty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config = load_project_config("configs/rxnresid.yaml")
    model = tiny_rxnresid_model().eval()
    monkeypatch.setattr(
        inference,
        "_load_model",
        lambda checkpoint_path, device: (model, config, None),
    )

    record = inference.predict_one(
        Path("synthetic.pt"),
        "[CH2:1]=[CH:2][CH:3]=[CH:4]>>[CH2:1]1[CH:2][CH:3][CH:4]1",
        device="cpu",
    )

    assert record.path_id == "reaction-0"
    assert torch.isfinite(torch.tensor(record.prediction))
    assert record.aleatoric_variance is not None
    assert record.epistemic_variance is not None
    assert record.predictive_variance is not None
    assert record.predictive_variance == pytest.approx(
        record.aleatoric_variance + record.epistemic_variance
    )
    assert record.lower_95 is not None
    assert record.upper_95 is not None
