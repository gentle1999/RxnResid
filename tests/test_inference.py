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


def test_predict_one_reuses_external_route_encoding(monkeypatch) -> None:
    config = load_project_config("configs/rxnresid.yaml")
    model = tiny_rxnresid_model().eval()
    large_label = "900719925474099312345678901"
    model._route_id_vocabulary = {"000001": 0, large_label: 3}
    monkeypatch.setattr(
        inference, "_load_model", lambda checkpoint_path, device: (model, config, None)
    )
    batches = []
    model.register_forward_pre_hook(lambda _model, args: batches.append(args[0]))
    record = inference.predict_one(
        Path("synthetic.pt"),
        "[CH3:1][CH2:2][OH:3]>>[CH3:1][CH:2]=[O:3]",
        route_id=large_label,
        path_id="000002",
        device="cpu",
    )
    assert record.path_id == "000002"
    assert batches[0].route_ids.tolist() == [3]
    with pytest.raises(ValueError, match="Unknown external route_id"):
        inference.predict_one(
            Path("synthetic.pt"), "[CH4:1]>>[CH4:1]", route_id="missing", device="cpu"
        )
