import torch
from accelerate import Accelerator
from torch.utils.data import DataLoader

from rxnresid.config import EarlyStoppingConfig
from rxnresid.data.collate import RxnResidBatch, collate_reaction_groups
from rxnresid.models.rxnresid import RxnResidOutput
from rxnresid.training.losses import LossWeights
from rxnresid.training.trainer import evaluate, fit, fit_fixed_epochs, predict
from tests.helpers import sample_of_size


class RxnResidContractModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.bias = torch.nn.Parameter(torch.tensor(0.0))
        for name in (
            "target_mean",
            "baseline_mean",
            "residual_mean",
        ):
            self.register_buffer(name, torch.tensor(0.0))
        for name in (
            "target_scale",
            "baseline_scale",
            "residual_scale",
        ):
            self.register_buffer(name, torch.tensor(1.0))

    def set_training_phase(self, phase: str) -> None:
        if phase not in {"baseline", "residual", "joint"}:
            raise ValueError(phase)

    def forward(self, batch: RxnResidBatch) -> RxnResidOutput:
        baseline_standardized = self.bias.expand(batch.num_paths)
        residual_standardized = self.bias.expand(batch.num_paths) * 0.0
        baseline = self.baseline_mean + self.baseline_scale * baseline_standardized
        residual = self.residual_mean + self.residual_scale * residual_standardized
        prediction = baseline + residual
        return RxnResidOutput(
            prediction=prediction,
            prediction_standardized=(prediction - self.target_mean) / self.target_scale,
            baseline=baseline,
            baseline_standardized=baseline_standardized,
            residual=residual,
            residual_standardized=residual_standardized,
            target_mean=self.target_mean,
            target_scale=self.target_scale,
            baseline_mean=self.baseline_mean,
            baseline_scale=self.baseline_scale,
            residual_mean=self.residual_mean,
            residual_scale=self.residual_scale,
        )


def _loader():  # type: ignore[no-untyped-def]
    samples = [sample_of_size(size) for size in (1, 2)]
    return DataLoader(samples, batch_size=2, collate_fn=collate_reaction_groups)


def test_rxnresid_contract_runs_through_accelerate_training_and_prediction() -> None:
    accelerator = Accelerator(cpu=True)
    model = RxnResidContractModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    train_loader = _loader()
    valid_loader = _loader()
    model, optimizer, train_loader, valid_loader = accelerator.prepare(
        model, optimizer, train_loader, valid_loader
    )
    result = fit(
        model,
        train_loader,
        valid_loader,
        optimizer,
        accelerator,
        epochs=1,
        weights=LossWeights(),
    )
    losses, metrics = evaluate(model, valid_loader, accelerator, LossWeights())
    records = predict(model, valid_loader, accelerator)
    assert result.summary.best_epoch == 1
    assert "loss_absolute" in losses
    assert metrics["mae"] is not None
    assert all(record.prediction == record.baseline + record.residual for record in records)
    assert len(records) == 3


def test_early_stopping_restores_best_epoch_after_minimum_budget() -> None:
    accelerator = Accelerator(cpu=True)
    model = RxnResidContractModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.0)
    train_loader = _loader()
    valid_loader = _loader()
    model, optimizer, train_loader, valid_loader = accelerator.prepare(
        model, optimizer, train_loader, valid_loader
    )
    result = fit(
        model,
        train_loader,
        valid_loader,
        optimizer,
        accelerator,
        epochs=5,
        early_stopping=EarlyStoppingConfig(min_epochs=3, patience=1),
    )
    assert result.summary.stopped_early
    assert result.summary.epochs_completed == 3
    assert result.summary.best_epoch == 1


def test_fixed_epoch_training_uses_exact_budget() -> None:
    accelerator = Accelerator(cpu=True)
    model = RxnResidContractModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.0)
    train_loader = _loader()
    model, optimizer, train_loader = accelerator.prepare(model, optimizer, train_loader)
    result = fit_fixed_epochs(
        model,
        train_loader,
        optimizer,
        accelerator,
        epochs=2,
    )
    assert [record.epoch for record in result.history] == [1, 2]
    assert result.final_state
