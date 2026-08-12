"""Accelerate-based training, distributed evaluation, and prediction."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any, Protocol, cast

import torch
from accelerate import Accelerator
from accelerate.utils import gather_object
from torch import Tensor
from torch.optim import Optimizer
from torch.utils.data import DataLoader

from rxnresid.config import EarlyStoppingConfig
from rxnresid.data.collate import RxnResidBatch
from rxnresid.models.rxnresid import RxnResidOutput
from rxnresid.training.losses import LossWeights, model_loss
from rxnresid.training.metrics import (
    finite_metric_dict,
    metrics_from_tensors,
    prediction_decomposition,
)


TrainingPhase = str


@dataclass(frozen=True)
class PredictionRecord:
    path_id: str
    group_id: str
    substrate_group: str
    prediction: float
    target: float
    baseline: float
    residual: float
    baseline_target: float | None = None
    residual_target: float | None = None


@dataclass(frozen=True)
class EpochRecord:
    epoch: int
    learning_rate: float
    train: dict[str, float]
    valid_loss: dict[str, float]
    valid_metrics: dict[str, float | None]


@dataclass(frozen=True)
class TrainingSummary:
    epochs_requested: int
    epochs_completed: int
    best_epoch: int
    best_metric: float
    monitor: str
    stopped_early: bool

    @classmethod
    def from_mapping(cls, value: Any) -> TrainingSummary:
        if not isinstance(value, dict):
            raise ValueError("training summary must be a mapping")
        return cls(
            epochs_requested=int(value["epochs_requested"]),
            epochs_completed=int(value["epochs_completed"]),
            best_epoch=int(value["best_epoch"]),
            best_metric=float(value["best_metric"]),
            monitor=str(value["monitor"]),
            stopped_early=bool(value["stopped_early"]),
        )


@dataclass(frozen=True)
class FitResult:
    history: tuple[EpochRecord, ...]
    best_state: dict[str, Tensor]
    summary: TrainingSummary


@dataclass(frozen=True)
class FixedEpochRecord:
    epoch: int
    learning_rate: float
    train: dict[str, float]


@dataclass(frozen=True)
class FixedEpochResult:
    history: tuple[FixedEpochRecord, ...]
    final_state: dict[str, Tensor]


class LearningRateScheduler(Protocol):
    def step(self) -> None: ...


def _mean_losses(
    losses: list[dict[str, Tensor]],
    accelerator: Accelerator,
) -> dict[str, float]:
    if not losses:
        return {}
    output: dict[str, float] = {}
    for key in losses[0]:
        local_mean = torch.stack([loss[key].detach() for loss in losses]).mean()
        reduced = cast(Tensor, accelerator.reduce(local_mean, reduction="mean"))
        output[key] = float(reduced.item())
    return output


def _batch_records(outputs: RxnResidOutput, batch: RxnResidBatch) -> list[PredictionRecord]:
    baseline, residual = prediction_decomposition(outputs)
    values = (
        torch.stack(
            (
                batch.energies,
                baseline,
                residual,
                batch.baseline_targets,
                batch.residual_targets,
                batch.path_to_group.to(dtype=baseline.dtype),
            ),
            dim=1,
        )
        .detach()
        .float()
        .cpu()
        .tolist()
    )
    records: list[PredictionRecord] = []
    for path_id, row in zip(batch.path_ids, values, strict=True):
        target, baseline_value, residual_value, baseline_target, residual_target, group = row
        group_index = int(group)
        records.append(
            PredictionRecord(
                path_id=path_id,
                group_id=batch.group_ids[group_index],
                substrate_group=batch.substrate_groups[group_index],
                prediction=baseline_value + residual_value,
                target=target,
                baseline=baseline_value,
                residual=residual_value,
                baseline_target=baseline_target,
                residual_target=residual_target,
            )
        )
    return records


def _gather_unique_records(
    records: list[PredictionRecord],
    *,
    center_residual: bool = False,
) -> list[PredictionRecord]:
    gathered = gather_object(records)
    unique: dict[str, PredictionRecord] = {}
    for record in gathered:
        unique.setdefault(record.path_id, record)
    ordered = sorted(unique.values(), key=lambda record: (record.substrate_group, record.path_id))
    if not center_residual:
        return ordered
    residual_sums: dict[str, float] = {}
    residual_counts: dict[str, int] = {}
    for record in ordered:
        residual_sums[record.group_id] = residual_sums.get(record.group_id, 0.0) + record.residual
        residual_counts[record.group_id] = residual_counts.get(record.group_id, 0) + 1
    centered: list[PredictionRecord] = []
    for record in ordered:
        residual_mean = residual_sums[record.group_id] / residual_counts[record.group_id]
        residual = record.residual - residual_mean
        centered.append(
            replace(
                record,
                prediction=record.baseline + residual,
                residual=residual,
            )
        )
    return centered


def _metrics_from_records(records: list[PredictionRecord]) -> dict[str, float | None]:
    if not records:
        return {}
    group_to_index: dict[str, int] = {}
    group_baseline: dict[str, float] = {}
    path_to_group: list[int] = []
    for record in records:
        if record.group_id not in group_to_index:
            group_to_index[record.group_id] = len(group_to_index)
            group_baseline[record.group_id] = record.baseline
        path_to_group.append(group_to_index[record.group_id])
    prediction = torch.tensor([record.prediction for record in records], dtype=torch.float32)
    target = torch.tensor([record.target for record in records], dtype=torch.float32)
    baseline = torch.tensor(
        [group_baseline[group_id] for group_id in group_to_index],
        dtype=torch.float32,
    )
    residual = torch.tensor([record.residual for record in records], dtype=torch.float32)
    baseline_target = (
        torch.tensor(
            [record.baseline_target for record in records],
            dtype=torch.float32,
        )
        if all(record.baseline_target is not None for record in records)
        else None
    )
    residual_target = (
        torch.tensor(
            [record.residual_target for record in records],
            dtype=torch.float32,
        )
        if all(record.residual_target is not None for record in records)
        else None
    )
    metrics = metrics_from_tensors(
        prediction,
        target,
        baseline,
        residual,
        torch.tensor(path_to_group, dtype=torch.long),
        baseline_target=baseline_target,
        residual_target=residual_target,
    )
    return finite_metric_dict(metrics)


def train_epoch(
    model: torch.nn.Module,
    loader: Iterable[RxnResidBatch],
    optimizer: Optimizer,
    accelerator: Accelerator,
    weights: LossWeights,
    scheduler: LearningRateScheduler | None = None,
    beta: float = 1.0,
    training_phase: TrainingPhase = "joint",
) -> dict[str, float]:
    model.train()
    phase_setter = getattr(accelerator.unwrap_model(model), "set_training_phase", None)
    if callable(phase_setter):
        phase_setter(training_phase)
    losses: list[dict[str, Tensor]] = []
    for batch in loader:
        batch.to(accelerator.device, non_blocking=accelerator.device.type == "cuda")
        with accelerator.accumulate(model):
            optimizer.zero_grad(set_to_none=True)
            output = model(batch)
            loss = model_loss(output, batch, weights=weights, beta=beta)
            accelerator.backward(loss["loss"])
            optimizer.step()
            if scheduler is not None:
                scheduler.step()
        losses.append({key: value.detach() for key, value in loss.items()})
    return _mean_losses(losses, accelerator)


@torch.inference_mode()
def evaluate(
    model: torch.nn.Module,
    loader: Iterable[RxnResidBatch],
    accelerator: Accelerator,
    weights: LossWeights,
    beta: float = 1.0,
) -> tuple[dict[str, float], dict[str, float | None]]:
    model.eval()
    losses: list[dict[str, Tensor]] = []
    records: list[PredictionRecord] = []
    for batch in loader:
        batch.to(accelerator.device, non_blocking=accelerator.device.type == "cuda")
        output = model(batch)
        losses.append(model_loss(output, batch, weights=weights, beta=beta))
        records.extend(_batch_records(output, batch))
    return _mean_losses(losses, accelerator), _metrics_from_records(
        _gather_unique_records(records, center_residual=weights.center_residual)
    )


@torch.inference_mode()
def predict(
    model: torch.nn.Module,
    loader: Iterable[RxnResidBatch],
    accelerator: Accelerator,
    *,
    center_residual: bool = False,
) -> list[PredictionRecord]:
    """Run distributed inference and return de-duplicated path-wise records."""
    model.eval()
    records: list[PredictionRecord] = []
    for batch in loader:
        batch.to(accelerator.device, non_blocking=accelerator.device.type == "cuda")
        records.extend(_batch_records(model(batch), batch))
    return _gather_unique_records(records, center_residual=center_residual)


def _cpu_state_dict(model: torch.nn.Module, accelerator: Accelerator) -> dict[str, Tensor]:
    state_dict = cast(dict[str, Tensor], accelerator.get_state_dict(model))
    return {name: value.detach().cpu().clone() for name, value in state_dict.items()}


def fit(
    model: torch.nn.Module,
    train_loader: DataLoader[RxnResidBatch],
    valid_loader: DataLoader[RxnResidBatch],
    optimizer: Optimizer,
    accelerator: Accelerator,
    epochs: int,
    weights: LossWeights | None = None,
    scheduler: LearningRateScheduler | None = None,
    early_stopping: EarlyStoppingConfig | None = None,
    phase_weights: tuple[tuple[int, LossWeights], ...] = (),
    freeze_baseline_after_epoch: int = 0,
    beta: float = 1.0,
) -> FitResult:
    """Train with Accelerate and retain the state with the lowest validation MAE."""
    weights = weights or LossWeights()
    early_stopping = early_stopping or EarlyStoppingConfig()
    history: list[EpochRecord] = []
    best_state = _cpu_state_dict(model, accelerator)
    best_metric = float("inf") if early_stopping.mode == "min" else float("-inf")
    best_epoch = 0
    epochs_without_improvement = 0
    stopped_early = False
    for epoch in range(1, epochs + 1):
        epoch_weights = weights
        training_phase: TrainingPhase = "joint"
        for end_epoch, candidate_weights in phase_weights:
            if epoch <= end_epoch:
                epoch_weights = candidate_weights
                if (
                    candidate_weights.absolute == 0.0
                    and candidate_weights.baseline > 0.0
                    and candidate_weights.residual == 0.0
                ):
                    training_phase = "baseline"
                elif (
                    candidate_weights.absolute == 0.0
                    and candidate_weights.baseline == 0.0
                    and candidate_weights.residual > 0.0
                ):
                    training_phase = "residual"
                break
        if freeze_baseline_after_epoch and epoch > freeze_baseline_after_epoch:
            training_phase = "residual"
        train_losses = train_epoch(
            model,
            train_loader,
            optimizer,
            accelerator,
            epoch_weights,
            scheduler=scheduler,
            beta=beta,
            training_phase=training_phase,
        )
        valid_losses, valid_metrics = evaluate(
            model,
            valid_loader,
            accelerator,
            epoch_weights,
            beta=beta,
        )
        record = EpochRecord(
            epoch=epoch,
            learning_rate=float(optimizer.param_groups[0]["lr"]),
            train=train_losses,
            valid_loss=valid_losses,
            valid_metrics=valid_metrics,
        )
        history.append(record)
        monitored = valid_metrics.get(early_stopping.monitor)
        if not isinstance(monitored, (int, float)) or not math.isfinite(monitored):
            raise RuntimeError(
                f"Validation metric {early_stopping.monitor!r} is unavailable or non-finite"
            )
        if early_stopping.mode == "min":
            improved = monitored < best_metric - early_stopping.min_delta
        else:
            improved = monitored > best_metric + early_stopping.min_delta
        if improved:
            best_metric = monitored
            best_epoch = epoch
            best_state = _cpu_state_dict(model, accelerator)
            epochs_without_improvement = 0
        elif epoch >= early_stopping.min_epochs:
            epochs_without_improvement += 1
        accelerator.print(
            f"epoch={epoch} lr={record.learning_rate:.8g} "
            f"valid_{early_stopping.monitor}={monitored:.6f} best_epoch={best_epoch}"
        )
        if (
            early_stopping.enabled
            and epoch >= early_stopping.min_epochs
            and epochs_without_improvement >= early_stopping.patience
        ):
            stopped_early = True
            break
    accelerator.wait_for_everyone()
    accelerator.unwrap_model(model).load_state_dict(best_state)
    return FitResult(
        history=tuple(history),
        best_state=best_state,
        summary=TrainingSummary(
            epochs_requested=epochs,
            epochs_completed=len(history),
            best_epoch=best_epoch,
            best_metric=best_metric,
            monitor=early_stopping.monitor,
            stopped_early=stopped_early,
        ),
    )


def fit_fixed_epochs(
    model: torch.nn.Module,
    train_loader: DataLoader[RxnResidBatch],
    optimizer: Optimizer,
    accelerator: Accelerator,
    epochs: int,
    weights: LossWeights | None = None,
    scheduler: LearningRateScheduler | None = None,
    phase_weights: tuple[tuple[int, LossWeights], ...] = (),
    freeze_baseline_after_epoch: int = 0,
    beta: float = 1.0,
    progress_label: str = "refit_epoch",
) -> FixedEpochResult:
    """Train for an exact budget without selecting on the refit data."""
    if epochs < 1:
        raise ValueError("epochs must be at least one")
    weights = weights or LossWeights()
    history: list[FixedEpochRecord] = []
    for epoch in range(1, epochs + 1):
        epoch_weights = weights
        training_phase: TrainingPhase = "joint"
        for end_epoch, candidate_weights in phase_weights:
            if epoch <= end_epoch:
                epoch_weights = candidate_weights
                if (
                    candidate_weights.absolute == 0.0
                    and candidate_weights.baseline > 0.0
                    and candidate_weights.residual == 0.0
                ):
                    training_phase = "baseline"
                elif (
                    candidate_weights.absolute == 0.0
                    and candidate_weights.baseline == 0.0
                    and candidate_weights.residual > 0.0
                ):
                    training_phase = "residual"
                break
        if freeze_baseline_after_epoch and epoch > freeze_baseline_after_epoch:
            training_phase = "residual"
        train_losses = train_epoch(
            model,
            train_loader,
            optimizer,
            accelerator,
            epoch_weights,
            scheduler=scheduler,
            beta=beta,
            training_phase=training_phase,
        )
        record = FixedEpochRecord(
            epoch=epoch,
            learning_rate=float(optimizer.param_groups[0]["lr"]),
            train=train_losses,
        )
        history.append(record)
        accelerator.print(
            f"{progress_label}={epoch} lr={record.learning_rate:.8g} "
            f"train_loss={train_losses['loss']:.6f}"
        )
    accelerator.wait_for_everyone()
    return FixedEpochResult(
        history=tuple(history),
        final_state=_cpu_state_dict(model, accelerator),
    )
