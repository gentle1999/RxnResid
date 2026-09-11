from dataclasses import replace

import torch

from rxnresid.data.collate import collate_reaction_groups
from rxnresid.models.rxnresid import RxnResidOutput
from rxnresid.training.losses import LossWeights, group_balanced_reduce, rxnresid_loss
from rxnresid.training.metrics import metrics_from_tensors
from tests.helpers import sample_of_size, tiny_rxnresid_model


def test_group_balanced_reduction_weights_groups_equally() -> None:
    values = torch.tensor([0.0, 0.0, 10.0])
    groups = torch.tensor([0, 0, 1])
    assert group_balanced_reduce(values, groups, 2) == 5.0


def test_path_metrics_use_precomputed_mean_decomposition_targets() -> None:
    target = torch.tensor([10.0, 12.0])
    metrics = metrics_from_tensors(
        target,
        target,
        torch.tensor([11.0]),
        torch.tensor([-1.0, 1.0]),
        torch.tensor([0, 0]),
        baseline_target=torch.tensor([11.0, 11.0]),
        residual_target=torch.tensor([-1.0, 1.0]),
    )
    assert metrics["mae"] == 0.0
    assert metrics["baseline_mae"] == 0.0
    assert metrics["relative_mae"] == 0.0


def test_rxnresid_loss_returns_all_decomposition_terms() -> None:
    batch = collate_reaction_groups([sample_of_size(size) for size in (2, 1)])
    losses = rxnresid_loss(tiny_rxnresid_model()(batch), batch)
    assert set(losses) == {
        "loss",
        "loss_absolute",
        "loss_baseline",
        "loss_residual",
        "loss_pairwise",
        "loss_residual_center",
        "loss_evidential",
        "loss_evidential_nll",
        "loss_evidence_regularizer",
    }
    assert all(value.ndim == 0 and torch.isfinite(value) for value in losses.values())


def test_rxnresid_unblended_baseline_auxiliary_expands_group_values_to_paths() -> None:
    batch = collate_reaction_groups([sample_of_size(2), sample_of_size(1)])
    losses = rxnresid_loss(
        tiny_rxnresid_model()(batch),
        batch,
        LossWeights(baseline_auxiliary_unblended=True),
    )

    assert all(value.ndim == 0 and torch.isfinite(value) for value in losses.values())


def test_auxiliary_huber_betas_are_independent_from_absolute_beta() -> None:
    batch = collate_reaction_groups([sample_of_size(2), sample_of_size(1)])
    output = tiny_rxnresid_model()(batch)
    losses = rxnresid_loss(
        output,
        batch,
        LossWeights(
            absolute=0.0,
            baseline=1.0,
            residual=1.0,
            baseline_huber_beta=0.25,
            residual_huber_beta=0.5,
        ),
        beta=0.1,
    )
    baseline_target = (batch.baseline_targets - output.baseline_mean) / output.baseline_scale
    residual_target = (batch.residual_targets - output.residual_mean) / output.residual_scale
    assert torch.allclose(
        losses["loss_baseline"],
        torch.nn.functional.smooth_l1_loss(
            output.baseline_standardized,
            baseline_target,
            beta=0.25,
        ),
    )
    assert torch.allclose(
        losses["loss_residual"],
        torch.nn.functional.smooth_l1_loss(
            output.residual_standardized,
            residual_target,
            beta=0.5,
        ),
    )


def test_pairwise_loss_supervises_continuous_route_gaps() -> None:
    batch = collate_reaction_groups([sample_of_size(2)])
    target_residual = batch.residual_targets.clone()
    outputs = RxnResidOutput(
        prediction=batch.energies.clone(),
        prediction_standardized=batch.energies.clone(),
        baseline=batch.baseline_targets.clone(),
        baseline_standardized=batch.baseline_targets.clone(),
        residual=target_residual,
        residual_standardized=target_residual,
        target_mean=torch.tensor(0.0),
        target_scale=torch.tensor(1.0),
        baseline_mean=torch.tensor(0.0),
        baseline_scale=torch.tensor(1.0),
        residual_mean=torch.tensor(0.0),
        residual_scale=torch.tensor(1.0),
    )
    exact = rxnresid_loss(outputs, batch, LossWeights(pairwise=1.0, center_residual=True))
    assert torch.allclose(exact["loss_pairwise"], torch.tensor(0.0))
    reversed_outputs = replace(outputs, residual=target_residual.flip(0))
    reversed_loss = rxnresid_loss(
        reversed_outputs,
        batch,
        LossWeights(pairwise=1.0, center_residual=True),
    )
    assert reversed_loss["loss_pairwise"] > 0.0


def test_residual_loss_can_ignore_singleton_groups() -> None:
    batch = collate_reaction_groups([sample_of_size(2), sample_of_size(1)])
    output = tiny_rxnresid_model()(batch)
    losses = rxnresid_loss(
        output,
        batch,
        LossWeights(
            absolute=0.0,
            baseline=0.0,
            residual=1.0,
            residual_group_balanced=True,
            residual_multi_path_only=True,
        ),
    )
    expected_path = torch.nn.functional.smooth_l1_loss(
        output.residual_standardized[:2],
        batch.residual_targets[:2],
    )
    assert torch.allclose(losses["loss_residual"], expected_path)


def test_residual_loss_is_finite_for_singleton_only_batch() -> None:
    batch = collate_reaction_groups([sample_of_size(1)])
    losses = rxnresid_loss(
        tiny_rxnresid_model()(batch),
        batch,
        LossWeights(residual_multi_path_only=True),
    )
    assert torch.isfinite(losses["loss"])
    assert losses["loss_residual"].item() == 0.0
