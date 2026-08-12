"""Absolute, relative, and within-group ranking metrics."""

from __future__ import annotations

import math

import torch
from torch import Tensor

from rxnresid.data.collate import RxnResidBatch
from rxnresid.models.rxnresid import RxnResidOutput
from rxnresid.utils.scatter import scatter_mean


def _r2(prediction: Tensor, target: Tensor) -> float:
    if target.numel() < 2:
        return float("nan")
    denominator = torch.sum((target - target.mean()) ** 2)
    if denominator.item() == 0:
        return float("nan")
    return float((1 - torch.sum((prediction - target) ** 2) / denominator).item())


def _ranking_metrics(prediction: Tensor, target: Tensor, path_to_group: Tensor) -> dict[str, float]:
    top1_hits = 0
    top1_total = 0
    pair_hits = 0
    pair_total = 0
    for group_index in torch.unique(path_to_group, sorted=True).tolist():
        indices = torch.where(path_to_group == group_index)[0]
        if indices.numel() < 2:
            continue
        top1_total += 1
        if prediction[indices].argmin() == target[indices].argmin():
            top1_hits += 1
        for left in range(indices.numel()):
            for right in range(left + 1, indices.numel()):
                target_difference = target[indices[left]] - target[indices[right]]
                if target_difference == 0:
                    continue
                prediction_difference = prediction[indices[left]] - prediction[indices[right]]
                pair_total += 1
                if torch.sign(target_difference) == torch.sign(prediction_difference):
                    pair_hits += 1
    return {
        "top1_accuracy": top1_hits / top1_total if top1_total else float("nan"),
        "pairwise_order_accuracy": pair_hits / pair_total if pair_total else float("nan"),
        "ranking_groups": float(top1_total),
    }


def metrics_from_tensors(
    prediction: Tensor,
    target: Tensor,
    baseline: Tensor,
    residual: Tensor,
    path_to_group: Tensor,
    *,
    baseline_target: Tensor | None = None,
    residual_target: Tensor | None = None,
) -> dict[str, float]:
    """Compute metrics after aggregating batches with globally offset group ids."""
    baseline_target_path = (
        baseline_target
        if baseline_target is not None
        else scatter_mean(target, path_to_group)[path_to_group]
    )
    residual_target_path = (
        residual_target if residual_target is not None else target - baseline_target_path
    )
    target_baseline = scatter_mean(baseline_target_path, path_to_group)
    baseline_path = baseline if baseline.numel() == prediction.numel() else baseline[path_to_group]
    predicted_baseline = scatter_mean(baseline_path, path_to_group)
    abs_error = (prediction - target).abs()
    relative_error = (residual - residual_target_path).abs()
    group_abs = scatter_mean(abs_error, path_to_group)
    group_relative = scatter_mean(relative_error, path_to_group)
    residual_scale = (
        residual_target_path.abs().mean().clamp_min(torch.finfo(residual_target_path.dtype).eps)
    )
    values = {
        "mae": float(abs_error.mean().item()),
        "rmse": float(torch.sqrt(torch.mean((prediction - target) ** 2)).item()),
        "r2": _r2(prediction, target),
        "group_balanced_mae": float(group_abs.mean().item()),
        "baseline_mae": float((predicted_baseline - target_baseline).abs().mean().item()),
        "baseline_rmse": float(
            torch.sqrt(torch.mean((predicted_baseline - target_baseline) ** 2)).item()
        ),
        "relative_mae": float(relative_error.mean().item()),
        "relative_rmse": float(
            torch.sqrt(torch.mean((residual - residual_target_path) ** 2)).item()
        ),
        "residual_normalized_mae": float((relative_error.mean() / residual_scale).item()),
        "residual_normalized_rmse": float(
            (torch.sqrt(torch.mean((residual - residual_target_path) ** 2)) / residual_scale).item()
        ),
        "group_balanced_relative_mae": float(group_relative.mean().item()),
    }
    values.update(_ranking_metrics(prediction, target, path_to_group))
    return values


def compute_metrics(outputs: RxnResidOutput, batch: RxnResidBatch) -> dict[str, float]:
    baseline, residual = prediction_decomposition(outputs)
    return metrics_from_tensors(
        outputs.prediction.detach(),
        batch.energies.detach(),
        baseline.detach(),
        residual.detach(),
        batch.path_to_group.detach(),
        baseline_target=batch.baseline_targets.detach(),
        residual_target=batch.residual_targets.detach(),
    )


def prediction_decomposition(
    outputs: RxnResidOutput,
) -> tuple[Tensor, Tensor]:
    """Return the explicit physical RxnResid decomposition."""
    return outputs.baseline, outputs.residual


def finite_metric_dict(metrics: dict[str, float]) -> dict[str, float | None]:
    """Convert NaN ranking values to JSON-compatible nulls."""
    return {key: value if math.isfinite(value) else None for key, value in metrics.items()}
