"""Convenience APIs for single-reaction RxnResid inference."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

import torch

from rxnresid.config import ProjectConfig, ResolvedRunConfig
from rxnresid.data.collate import collate_reaction_paths
from rxnresid.data.dataset import ReactionGroupDataset, TargetStatistics
from rxnresid.models.build import build_model
from rxnresid.training.trainer import PredictionRecord


def _load_model(
    checkpoint_path: str | Path,
    *,
    device: torch.device,
) -> tuple[torch.nn.Module, ProjectConfig, ResolvedRunConfig]:
    checkpoint: dict[str, Any] = torch.load(
        checkpoint_path,
        map_location="cpu",
        weights_only=False,
    )
    config = ProjectConfig.from_mapping(checkpoint.get("config"))
    resolved = ResolvedRunConfig.from_mapping(checkpoint.get("resolved_run"))
    model, _ = build_model(
        config.model,
        variant_override=resolved.model_variant,
        mapping_mode_override=resolved.mapping_mode,
        group_encoder_override=resolved.group_encoder,
        path_encoder_override=resolved.path_encoder,
        substrate_encoder_override=resolved.substrate_encoder,
        product_encoder_override=resolved.product_encoder,
    )
    raw_statistics = checkpoint.get("target_statistics")
    if isinstance(raw_statistics, dict):
        cast(Any, model).set_target_statistics(TargetStatistics.from_mapping(raw_statistics))
    incompatible = model.load_state_dict(checkpoint["model_state"], strict=False)
    allowed_missing = {
        "target_mean",
        "target_scale",
        "baseline_mean",
        "baseline_scale",
        "residual_mean",
        "residual_scale",
    }
    unexpected_missing = set(incompatible.missing_keys) - allowed_missing
    if unexpected_missing or incompatible.unexpected_keys:
        raise RuntimeError(
            "Checkpoint state mismatch: "
            f"missing={sorted(unexpected_missing)}, "
            f"unexpected={sorted(incompatible.unexpected_keys)}"
        )
    model.to(device)
    model.eval()
    return model, config, resolved


def _device_from_setting(device: Literal["auto", "cpu"] | torch.device) -> torch.device:
    if isinstance(device, torch.device):
        return device
    if device == "cpu":
        return torch.device("cpu")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


@torch.inference_mode()
def predict_one(
    checkpoint_path: str | Path,
    reaction_smiles: str,
    *,
    route_id: int = 0,
    path_id: str = "reaction-0",
    conditions: Mapping[str, str] | None = None,
    device: Literal["auto", "cpu"] | torch.device = "auto",
) -> PredictionRecord:
    """Predict one mapped reaction and return physical-unit uncertainty fields.

    ``reaction_smiles`` must use the same atom-mapping convention as training.
    A dummy target is used only to satisfy the dataset preprocessing contract;
    the returned ``PredictionRecord.target`` is ``NaN`` because no label was
    supplied at inference time.
    """
    if route_id < 0:
        raise ValueError("route_id must be non-negative")
    if not reaction_smiles.strip():
        raise ValueError("reaction_smiles must not be empty")
    if not path_id.strip():
        raise ValueError("path_id must not be empty")

    target_device = _device_from_setting(device)
    model, config, _ = _load_model(checkpoint_path, device=target_device)
    if route_id >= config.model.route_id_count:
        raise ValueError(
            f"route_id {route_id} is outside the configured range "
            f"[0, {config.model.route_id_count})"
        )
    supplied_conditions = dict(conditions or {})
    unknown_conditions = set(supplied_conditions) - set(config.data.condition_columns)
    if unknown_conditions:
        raise ValueError(f"Unknown condition columns: {sorted(unknown_conditions)}")
    missing_conditions = [
        column
        for column in config.data.condition_columns
        if not supplied_conditions.get(column, "").strip()
    ]
    if missing_conditions:
        raise ValueError(f"Missing configured conditions: {missing_conditions}")
    reserved_columns = {
        "path_id",
        config.data.reaction_column,
        config.data.target_column,
        config.data.route_id_column,
    }
    if reserved_columns.intersection(supplied_conditions):
        raise ValueError("conditions cannot override path, reaction, target, or route columns")
    source = [
        {
            "path_id": path_id,
            config.data.reaction_column: reaction_smiles,
            config.data.target_column: "0.0",
            **(
                {config.data.route_id_column: str(route_id)}
                if config.data.route_id_column is not None
                else {}
            ),
            **dict(supplied_conditions),
        }
    ]
    dataset = ReactionGroupDataset(
        source,
        target_column=config.data.target_column,
        reaction_column=config.data.reaction_column,
        condition_columns=config.data.condition_columns,
        route_id_column=config.data.route_id_column,
        baseline_reduction=config.data.baseline_reduction,
        component_hash_buckets=config.model.component_hash_buckets,
        cache_dir=None,
    )
    batch = collate_reaction_paths(list(dataset[0].path_samples()))
    batch.to(target_device)
    output = model(batch)
    path_index = 0
    return PredictionRecord(
        path_id=path_id,
        group_id=batch.group_ids[int(batch.path_to_group[path_index].item())],
        substrate_group=batch.substrate_groups[int(batch.path_to_group[path_index].item())],
        prediction=float(output.prediction[path_index].item()),
        target=float("nan"),
        baseline=float(output.baseline[path_index].item()),
        residual=float(output.residual[path_index].item()),
        baseline_target=None,
        residual_target=None,
        aleatoric_variance=float(output.aleatoric_variance[path_index].item()),
        epistemic_variance=float(output.epistemic_variance[path_index].item()),
        predictive_variance=float(output.predictive_variance[path_index].item()),
    )


__all__ = ["predict_one"]
