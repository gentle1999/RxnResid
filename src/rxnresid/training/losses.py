"""Path-level barrier losses with precomputed baseline/residual targets."""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F
from torch import Tensor

from rxnresid.data.collate import RxnResidBatch
from rxnresid.models.rxnresid import RxnResidModelOutput, RxnResidOutput
from rxnresid.utils.scatter import scatter_mean


@dataclass(frozen=True)
class LossWeights:
    absolute: float = 1.0
    baseline: float = 0.2
    residual: float = 1.0
    pairwise: float = 0.0
    center_residual: bool = False
    baseline_group_balanced: bool = False
    residual_group_balanced: bool = False
    residual_multi_path_only: bool = False
    baseline_auxiliary_unblended: bool = False
    baseline_huber_beta: float | None = None
    residual_huber_beta: float | None = None


def group_balanced_reduce(
    values: Tensor,
    path_to_group: Tensor,
    num_groups: int,
    group_mask: Tensor | None = None,
    value_mask: Tensor | None = None,
) -> Tensor:
    """Average paths within groups, then average the selected groups equally."""
    if value_mask is not None:
        values = values[value_mask]
        path_to_group = path_to_group[value_mask]
    if values.numel() == 0:
        return values.sum() * 0.0
    group_values = scatter_mean(values, path_to_group, dim_size=num_groups)
    if group_mask is None:
        return group_values.mean()
    selected = group_values[group_mask]
    if selected.numel() == 0:
        return values.sum() * 0.0
    return selected.mean()


def center_within_groups(
    values: Tensor,
    path_to_group: Tensor,
    num_groups: int,
) -> Tensor:
    """Remove the per-group offset that is unidentifiable at inference."""
    group_mean = scatter_mean(values, path_to_group, dim_size=num_groups)
    return values - group_mean[path_to_group]


def pairwise_gap_loss(
    prediction: Tensor,
    target: Tensor,
    path_to_group: Tensor,
    num_groups: int,
    beta: float,
) -> Tensor:
    """Average continuous path-gap supervision equally over multi-path groups."""
    group_losses: list[Tensor] = []
    for group_index in range(num_groups):
        indices = (path_to_group == group_index).nonzero(as_tuple=False).flatten()
        if indices.numel() < 2:
            continue
        pairs = torch.combinations(indices, r=2)
        prediction_gap = prediction[pairs[:, 0]] - prediction[pairs[:, 1]]
        target_gap = target[pairs[:, 0]] - target[pairs[:, 1]]
        group_losses.append(
            F.smooth_l1_loss(prediction_gap, target_gap, beta=beta, reduction="mean")
        )
    if not group_losses:
        return prediction.sum() * 0.0
    return torch.stack(group_losses).mean()


def rxnresid_loss(
    outputs: RxnResidOutput,
    batch: RxnResidBatch,
    weights: LossWeights | None = None,
    beta: float = 1.0,
) -> dict[str, Tensor]:
    """Compute one-to-one path, baseline, and residual Huber terms."""
    weights = weights or LossWeights()
    baseline_beta = weights.baseline_huber_beta or beta
    residual_beta = weights.residual_huber_beta or beta
    target = (batch.energies - outputs.target_mean) / outputs.target_scale
    baseline = (
        outputs.neural_baseline_standardized[batch.path_to_group]
        if weights.baseline_auxiliary_unblended and isinstance(outputs, RxnResidModelOutput)
        else outputs.baseline_standardized
    )
    if weights.center_residual:
        residual_physical = center_within_groups(
            outputs.raw_residual,
            batch.path_to_group,
            batch.num_groups,
        )
        prediction_physical = outputs.baseline + residual_physical
        prediction = (prediction_physical - outputs.target_mean) / outputs.target_scale
        residual = (residual_physical - outputs.residual_mean) / outputs.residual_scale
    else:
        prediction = outputs.prediction_standardized
        residual = outputs.residual_standardized
    target_baseline = (batch.baseline_targets - outputs.baseline_mean) / outputs.baseline_scale
    target_residual = (batch.residual_targets - outputs.residual_mean) / outputs.residual_scale
    absolute_path = F.smooth_l1_loss(prediction, target, reduction="none", beta=beta)
    residual_path = F.smooth_l1_loss(
        residual,
        target_residual,
        reduction="none",
        beta=residual_beta,
    )
    loss_absolute = absolute_path.mean()
    baseline_path = F.smooth_l1_loss(
        baseline,
        target_baseline,
        reduction="none",
        beta=baseline_beta,
    )
    if weights.baseline_group_balanced:
        loss_baseline = group_balanced_reduce(
            baseline_path,
            batch.path_to_group,
            batch.num_groups,
        )
    else:
        loss_baseline = baseline_path.mean()
    residual_group_mask = None
    residual_value_mask = None
    if weights.residual_multi_path_only:
        residual_group_mask = batch.group_sizes > 1
        residual_value_mask = residual_group_mask[batch.path_to_group]
    if weights.residual_group_balanced:
        loss_residual = group_balanced_reduce(
            residual_path,
            batch.path_to_group,
            batch.num_groups,
            group_mask=residual_group_mask,
            value_mask=residual_value_mask,
        )
    elif residual_value_mask is not None:
        selected_residual = residual_path[residual_value_mask]
        loss_residual = (
            selected_residual.mean() if selected_residual.numel() else residual_path.sum() * 0.0
        )
    else:
        loss_residual = residual_path.mean()
    loss_pairwise = (
        pairwise_gap_loss(
            residual,
            target_residual,
            batch.path_to_group,
            batch.num_groups,
            beta,
        )
        if weights.pairwise > 0.0
        else prediction.sum() * 0.0
    )
    total = (
        weights.absolute * loss_absolute
        + weights.baseline * loss_baseline
        + weights.residual * loss_residual
        + weights.pairwise * loss_pairwise
    )
    return {
        "loss": total,
        "loss_absolute": loss_absolute,
        "loss_baseline": loss_baseline,
        "loss_residual": loss_residual,
        "loss_pairwise": loss_pairwise,
    }


def model_loss(
    outputs: RxnResidOutput,
    batch: RxnResidBatch,
    weights: LossWeights | None = None,
    beta: float = 1.0,
) -> dict[str, Tensor]:
    """Evaluate the production RxnResid baseline-residual objective."""
    return rxnresid_loss(outputs, batch, weights=weights, beta=beta)
