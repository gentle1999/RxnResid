"""Run Accelerate-based path-wise inference from a RxnResid checkpoint."""

from __future__ import annotations

import argparse
from typing import Any, Protocol, cast

import torch
from accelerate import Accelerator
from torch.utils.data import DataLoader

from rxnresid.config import ProjectConfig, ResolvedRunConfig
from rxnresid.data.collate import CachedPathCollator, RxnResidBatch
from rxnresid.data.dataset import ReactionGroupDataset, ReactionPathDataset, TargetStatistics
from rxnresid.data.samplers import CompleteGroupBatchSampler
from rxnresid.models.build import build_model
from rxnresid.prediction_output import write_prediction_csv
from rxnresid.training.trainer import predict


class TargetStatisticsModel(Protocol):
    def set_target_statistics(self, statistics: TargetStatistics) -> None: ...


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument(
        "--data",
        default="data/new_full_df_exact_balanced_40ene_40diene.csv",
    )
    parser.add_argument("--output", default="predictions.csv")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--mixed-precision", choices=("no", "fp16", "bf16"), default=None)
    parser.add_argument(
        "--component-id-columns",
        nargs="+",
        default=None,
        help="Metadata columns emitted first and used to sort substrate combinations.",
    )
    return parser


def _build_prediction_loader(
    dataset: ReactionPathDataset,
    *,
    batch_size: int,
    complete_groups: bool,
    pin_memory: bool,
) -> DataLoader[RxnResidBatch]:
    if complete_groups:
        loader = DataLoader(
            dataset,
            batch_sampler=CompleteGroupBatchSampler(
                dataset,
                batch_size,
                shuffle=False,
            ),
            collate_fn=CachedPathCollator(),
            num_workers=0,
            pin_memory=pin_memory,
        )
        return cast(DataLoader[RxnResidBatch], loader)
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=CachedPathCollator(),
        num_workers=0,
        pin_memory=pin_memory,
    )
    return cast(DataLoader[RxnResidBatch], loader)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    checkpoint: dict[str, Any] = torch.load(
        args.checkpoint,
        map_location="cpu",
        weights_only=False,
    )
    config = ProjectConfig.from_mapping(checkpoint.get("config"))
    resolved = ResolvedRunConfig.from_mapping(checkpoint.get("resolved_run"))
    mixed_precision = "no" if args.cpu else args.mixed_precision or resolved.mixed_precision
    accelerator = Accelerator(cpu=args.cpu, mixed_precision=mixed_precision)
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
        cast(TargetStatisticsModel, model).set_target_statistics(
            TargetStatistics.from_mapping(raw_statistics)
        )
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
    dataset = ReactionGroupDataset(
        args.data,
        target_column=config.data.target_column,
        reaction_column=config.data.reaction_column,
        condition_columns=config.data.condition_columns,
        route_id_column=config.data.route_id_column,
        baseline_reduction=config.data.baseline_reduction,
        component_hash_buckets=config.model.component_hash_buckets,
        cache_dir=config.data.cache_dir if config.data.cache_enabled else None,
    )
    path_dataset = ReactionPathDataset(dataset, list(range(len(dataset))))
    loader = _build_prediction_loader(
        path_dataset,
        batch_size=args.batch_size or resolved.batch_size_paths,
        complete_groups=config.training.group_complete_batches,
        pin_memory=accelerator.device.type == "cuda",
    )
    model, loader = accelerator.prepare(model, loader)
    records = predict(model, loader, accelerator, center_residual=config.loss.center_residual)
    accelerator.wait_for_everyone()
    if accelerator.is_main_process:
        component_id_columns = tuple(args.component_id_columns or config.data.component_id_columns)
        metadata_by_path = {row.path_id: row.metadata for row in dataset.rows}
        missing_columns = sorted(
            {
                column
                for metadata in metadata_by_path.values()
                for column in component_id_columns
                if column not in metadata
            }
        )
        if missing_columns:
            raise ValueError(f"Missing component id columns: {missing_columns}")
        write_prediction_csv(
            args.output,
            records,
            metadata_by_path,
            component_id_columns,
        )
    accelerator.print(f"wrote {len(records)} predictions to {args.output}")
    accelerator.end_training()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
