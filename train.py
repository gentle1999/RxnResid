"""Train RxnResid on a path-wise CSV with leakage-free group splits."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Protocol, cast

import torch
from accelerate import Accelerator, DataLoaderConfiguration, DistributedDataParallelKwargs
from accelerate.utils import set_seed
from torch.utils.data import DataLoader

from rxnresid.config import (
    DistributedRun,
    ProjectConfig,
    ResolvedRunConfig,
    ResolvedScheduler,
    SplitSizes,
    load_project_config,
)
from rxnresid.data.collate import CachedPathCollator
from rxnresid.data.dataset import ReactionGroupDataset, ReactionPathDataset, TargetStatistics
from rxnresid.data.prepare import write_prepared_dataset
from rxnresid.data.samplers import CompleteGroupBatchSampler
from rxnresid.data.split import load_split_manifest, split_datasets, split_group_labels
from rxnresid.models.build import build_model
from rxnresid.models.encoders import available_encoders
from rxnresid.prediction_output import write_prediction_csv
from rxnresid.training.losses import LossWeights
from rxnresid.training.schedulers import build_scheduler
from rxnresid.training.trainer import TrainingSummary, evaluate, fit, fit_fixed_epochs, predict


class TargetStatisticsModel(Protocol):
    def set_target_statistics(self, statistics: TargetStatistics) -> None: ...

    def set_residual_statistics(self, statistics: TargetStatistics) -> None: ...


@dataclass(frozen=True)
class RefitSummary:
    """Metadata for the train+validation warm-start stage."""

    selection_checkpoint: str
    selected_epoch: int
    epoch_factor: float
    learning_rate_factor: float
    epochs_completed: int
    train_groups: int
    train_paths: int
    scheduler_total_steps: int
    scheduler_warmup_steps: int


DEFAULT_CONFIG = "configs/rxnresid.yaml"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=None,
        help="Project configuration (default: configs/rxnresid.yaml).",
    )
    parser.add_argument(
        "--split-manifest",
        default=None,
        help="Override data.split_manifest for regular training.",
    )
    parser.add_argument("--output", default="runs/default")
    parser.add_argument(
        "--refit",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--train-on-train-valid-from-scratch",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--two-stage-train-valid-from-scratch",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--selection-refit-from-scratch",
        action="store_true",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--stage1-epochs",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--stage2-epochs",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--stage2-learning-rate-factor",
        type=float,
        default=0.2,
        help="Learning-rate multiplier for the second from-scratch training stage.",
    )
    parser.add_argument(
        "--stage2-auxiliary-weight-factor",
        type=float,
        default=0.5,
        help=(
            "Multiplier for baseline, residual, and pairwise auxiliary losses in "
            "the second from-scratch training stage; absolute loss is unchanged."
        ),
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--device", choices=("auto", "cpu"), default=None)
    parser.add_argument("--mixed-precision", choices=("no", "fp16", "bf16"), default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--model",
        choices=("rxnresid",),
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--mapping-mode",
        choices=("none", "edit_features", "latent_diff", "combined"),
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--encoder", choices=available_encoders(), default=None, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--path-encoder", choices=available_encoders(), default=None, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--substrate-encoder", choices=available_encoders(), default=None, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--product-encoder", choices=available_encoders(), default=None, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--epoch-factor",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--learning-rate-factor",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--fold-index", type=int, default=None)
    return parser


def _build_path_loader(
    dataset: ReactionPathDataset,
    *,
    batch_size: int,
    complete_groups: bool,
    shuffle: bool,
    seed: int,
    pin_memory: bool,
) -> DataLoader:
    if complete_groups:
        return DataLoader(
            dataset,
            batch_sampler=CompleteGroupBatchSampler(
                dataset,
                batch_size,
                shuffle=shuffle,
                seed=seed,
            ),
            collate_fn=CachedPathCollator(),
            num_workers=0,
            pin_memory=pin_memory,
        )
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        collate_fn=CachedPathCollator(),
        num_workers=0,
        pin_memory=pin_memory,
    )


def _loss_weights(config: ProjectConfig) -> LossWeights:
    return LossWeights(
        absolute=config.loss.absolute,
        baseline=config.loss.baseline,
        residual=config.loss.residual,
        pairwise=config.loss.pairwise,
        center_residual=config.loss.center_residual,
        baseline_group_balanced=config.loss.baseline_group_balanced,
        residual_group_balanced=config.loss.residual_group_balanced,
        residual_multi_path_only=config.loss.residual_multi_path_only,
        baseline_auxiliary_unblended=config.loss.baseline_auxiliary_unblended,
        baseline_huber_beta=config.loss.baseline_huber_beta,
        residual_huber_beta=config.loss.residual_huber_beta,
    )


def _phase_weights(
    config: ProjectConfig,
    weights: LossWeights,
) -> tuple[tuple[int, LossWeights], ...]:
    return tuple(
        phase
        for phase in (
            (
                config.training.baseline_pretrain_epochs,
                replace(weights, absolute=0.0, residual=0.0, pairwise=0.0),
            ),
            (
                config.training.baseline_pretrain_epochs + config.training.residual_pretrain_epochs,
                replace(weights, absolute=0.0, baseline=0.0),
            ),
        )
        if phase[0] > 0
    )


def _build_optimizer(
    model: torch.nn.Module,
    config: ProjectConfig,
    *,
    learning_rate_factor: float = 1.0,
) -> torch.optim.AdamW:
    component_parameters = [
        parameter
        for name, parameter in model.named_parameters()
        if parameter.requires_grad
        and name.startswith(
            (
                "component_embedding.",
                "component_identity_projector.",
                "ene_factor_embedding.",
                "diene_factor_embedding.",
                "ene_factor_bias.",
                "diene_factor_bias.",
                "baseline_predictor.ene_identity_factor.",
                "baseline_predictor.diene_identity_factor.",
                "baseline_predictor.ene_identity_bias.",
                "baseline_predictor.diene_identity_bias.",
                "baseline_predictor.component_identity_factor.",
                "baseline_predictor.component_identity_bias.",
                "residual_component_embedding.",
                "residual_component_identity_projector.",
                "stereo_signature_bias.",
                "component_stereo_bias.",
            )
        )
    ]
    component_parameter_ids = {id(parameter) for parameter in component_parameters}
    base_parameters = [
        parameter
        for parameter in model.parameters()
        if parameter.requires_grad and id(parameter) not in component_parameter_ids
    ]
    parameter_groups: list[dict[str, object]] = [{"params": base_parameters}]
    if component_parameters:
        parameter_groups.append(
            {
                "params": component_parameters,
                "lr": (config.training.component_learning_rate or config.training.learning_rate)
                * learning_rate_factor,
            }
        )
    return torch.optim.AdamW(
        parameter_groups,
        lr=config.training.learning_rate * learning_rate_factor,
        weight_decay=config.training.weight_decay,
        fused=config.training.fused_optimizer,
    )


def _validate_args(args: argparse.Namespace) -> None:
    if args.selection_refit_from_scratch is None:
        args.selection_refit_from_scratch = not (
            args.refit
            or args.train_on_train_valid_from_scratch
            or args.two_stage_train_valid_from_scratch
        )
        if args.selection_refit_from_scratch and args.stage2_epochs is None:
            args.stage2_epochs = 180
    selection_mode = bool(args.selection_refit_from_scratch)
    from_scratch_modes = sum(
        (
            bool(args.train_on_train_valid_from_scratch),
            bool(args.two_stage_train_valid_from_scratch),
            selection_mode,
        )
    )
    if from_scratch_modes > 1:
        raise ValueError("from-scratch training modes are mutually exclusive")
    if args.refit:
        if from_scratch_modes:
            raise ValueError("--refit cannot be combined with a from-scratch training mode")
        if args.checkpoint is None:
            raise ValueError("--checkpoint is required with --refit")
        if args.fold_index is not None:
            raise ValueError("--fold-index is loaded from --checkpoint during --refit")
        if args.config is not None:
            raise ValueError("--config is loaded from --checkpoint during --refit")
        if args.split_manifest is not None:
            raise ValueError("--split-manifest is loaded from --checkpoint during --refit")
        for option, attribute in (
            ("--seed", "seed"),
            ("--model", "model"),
            ("--mapping-mode", "mapping_mode"),
            ("--encoder", "encoder"),
            ("--path-encoder", "path_encoder"),
            ("--substrate-encoder", "substrate_encoder"),
            ("--product-encoder", "product_encoder"),
        ):
            if getattr(args, attribute) is not None:
                raise ValueError(f"{option} is loaded from --checkpoint during --refit")
        if args.epoch_factor is not None and args.epoch_factor <= 0.0:
            raise ValueError("--epoch-factor must be positive")
        if args.learning_rate_factor is not None and args.learning_rate_factor <= 0.0:
            raise ValueError("--learning-rate-factor must be positive")
    else:
        if args.fold_index is None:
            raise ValueError("--fold-index is required unless --refit is used")
        if args.checkpoint is not None:
            raise ValueError("--checkpoint is only valid with --refit")
        if args.epoch_factor is not None:
            raise ValueError("--epoch-factor is only valid with --refit")
        if args.learning_rate_factor is not None:
            raise ValueError("--learning-rate-factor is only valid with --refit")
    if args.two_stage_train_valid_from_scratch:
        if args.stage1_epochs is None or args.stage2_epochs is None:
            raise ValueError(
                "--stage1-epochs and --stage2-epochs are required for two-stage training"
            )
        if args.stage1_epochs < 1 or args.stage2_epochs < 1:
            raise ValueError("two-stage epoch counts must be positive")
        if args.stage2_learning_rate_factor <= 0.0:
            raise ValueError("--stage2-learning-rate-factor must be positive")
    elif (args.stage1_epochs is not None or args.stage2_epochs is not None) and not selection_mode:
        raise ValueError("--stage1-epochs and --stage2-epochs require two-stage training")
    if selection_mode:
        if args.stage1_epochs is not None:
            raise ValueError("--stage1-epochs is not used by --selection-refit-from-scratch")
        if args.stage2_epochs is None:
            raise ValueError("--stage2-epochs is required for selection-refit training")
        if args.stage2_epochs < 1:
            raise ValueError("--stage2-epochs must be positive")
        if args.stage2_learning_rate_factor <= 0.0:
            raise ValueError("--stage2-learning-rate-factor must be positive")
    if args.stage2_auxiliary_weight_factor < 0.0:
        raise ValueError("--stage2-auxiliary-weight-factor must be non-negative")
    if args.epochs is not None and args.epochs < 1:
        raise ValueError("--epochs must be positive")


def _run_refit(args: argparse.Namespace) -> int:
    checkpoint_path = Path(cast(str, args.checkpoint))
    checkpoint: dict[str, Any] = torch.load(
        checkpoint_path,
        map_location="cpu",
        weights_only=False,
    )
    config = ProjectConfig.from_mapping(checkpoint.get("config"))
    resolved = ResolvedRunConfig.from_mapping(checkpoint.get("resolved_run"))
    selection_summary = TrainingSummary.from_mapping(checkpoint.get("training_summary"))
    epoch_factor = args.epoch_factor if args.epoch_factor is not None else 1.0
    learning_rate_factor = (
        args.learning_rate_factor if args.learning_rate_factor is not None else 0.2
    )
    refit_epochs = args.epochs or max(
        1,
        round(selection_summary.best_epoch * epoch_factor),
    )
    device_setting = args.device or config.training.device
    mixed_precision = args.mixed_precision or resolved.mixed_precision
    accelerator = Accelerator(
        cpu=device_setting == "cpu",
        mixed_precision=mixed_precision,
        kwargs_handlers=[
            DistributedDataParallelKwargs(
                find_unused_parameters=(
                    config.training.baseline_pretrain_epochs > 0
                    or config.training.residual_pretrain_epochs > 0
                    or config.training.freeze_baseline_after_pretrain
                )
            )
        ],
        gradient_accumulation_steps=config.training.gradient_accumulation_steps,
        dataloader_config=DataLoaderConfiguration(
            split_batches=config.training.split_batches,
        ),
    )
    set_seed(resolved.seed)
    dataset = ReactionGroupDataset(
        config.data.path,
        target_column=config.data.target_column,
        reaction_column=config.data.reaction_column,
        condition_columns=config.data.condition_columns,
        route_id_column=config.data.route_id_column,
        baseline_reduction=config.data.baseline_reduction,
        component_hash_buckets=config.model.component_hash_buckets,
        cache_dir=config.data.cache_dir if config.data.cache_enabled else None,
    )
    manifest = load_split_manifest(config.data.split_manifest)
    split = manifest.resolve(dataset, resolved.fold_index)
    refit_dataset = ReactionPathDataset(dataset, [*split.train, *split.valid])
    test_dataset = ReactionPathDataset(dataset, split.test)
    refit_target_statistics = refit_dataset.target_statistics(
        residual_multi_path_only=config.training.residual_statistics_multi_path_only
    )
    batch_size = args.batch_size or resolved.batch_size_paths
    loader_options = {
        "batch_size": batch_size,
        "complete_groups": config.training.group_complete_batches,
        "seed": resolved.seed,
        "pin_memory": accelerator.device.type == "cuda",
    }
    train_loader = _build_path_loader(refit_dataset, shuffle=True, **loader_options)
    test_loader = _build_path_loader(test_dataset, shuffle=False, **loader_options)
    model, model_config = build_model(
        config.model,
        variant_override=resolved.model_variant,
        mapping_mode_override=resolved.mapping_mode,
        group_encoder_override=resolved.group_encoder,
        path_encoder_override=resolved.path_encoder,
        substrate_encoder_override=resolved.substrate_encoder,
        product_encoder_override=resolved.product_encoder,
    )
    phase_setter = getattr(model, "set_training_phase", None)
    if callable(phase_setter):
        phase_setter("joint")
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
    raw_statistics = checkpoint.get("target_statistics")
    target_statistics = (
        TargetStatistics.from_mapping(raw_statistics)
        if isinstance(raw_statistics, dict)
        else refit_target_statistics
    )
    statistics_model = cast(TargetStatisticsModel, model)
    if config.training.target_scaling:
        statistics_model.set_target_statistics(target_statistics)
    elif config.training.residual_target_scaling and model_config.variant.startswith("rxnresid"):
        statistics_model.set_residual_statistics(target_statistics)
    optimizer = _build_optimizer(
        model,
        config,
        learning_rate_factor=learning_rate_factor,
    )
    optimizer_steps_per_epoch = math.ceil(
        len(train_loader) / config.training.gradient_accumulation_steps
    )
    scheduler, scheduler_plan = build_scheduler(
        optimizer,
        config.training.scheduler,
        total_steps=refit_epochs * optimizer_steps_per_epoch,
    )
    model, optimizer, train_loader, test_loader, scheduler = accelerator.prepare(
        model,
        optimizer,
        train_loader,
        test_loader,
        scheduler,
    )
    weights = _loss_weights(config)
    fit_result = fit_fixed_epochs(
        model,
        train_loader,
        optimizer,
        accelerator,
        refit_epochs,
        weights=weights,
        scheduler=scheduler,
        phase_weights=_phase_weights(config, weights),
        freeze_baseline_after_epoch=(
            config.training.baseline_pretrain_epochs
            if config.training.freeze_baseline_after_pretrain
            else 0
        ),
        beta=config.loss.huber_beta,
    )
    _, test_metrics = evaluate(
        model,
        test_loader,
        accelerator,
        weights,
        beta=config.loss.huber_beta,
    )
    test_records = predict(
        model,
        test_loader,
        accelerator,
        center_residual=weights.center_residual,
    )
    refit_summary = RefitSummary(
        selection_checkpoint=str(checkpoint_path),
        selected_epoch=selection_summary.best_epoch,
        epoch_factor=epoch_factor,
        learning_rate_factor=learning_rate_factor,
        epochs_completed=refit_epochs,
        train_groups=len(split.train) + len(split.valid),
        train_paths=len(refit_dataset),
        scheduler_total_steps=scheduler_plan.total_steps,
        scheduler_warmup_steps=scheduler_plan.warmup_steps,
    )
    accelerator.wait_for_everyone()
    if accelerator.is_main_process:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        labels = split_group_labels(dataset, split)
        accelerator.save(
            {
                "model_state": fit_result.final_state,
                "config": config.to_dict(),
                "resolved_run": resolved.to_dict(),
                "training_summary": asdict(selection_summary),
                "refit_summary": asdict(refit_summary),
                "target_statistics": asdict(target_statistics),
                "group_ids": dataset.group_ids,
                "split_labels": labels,
            },
            output_dir / "checkpoint.pt",
        )
        (output_dir / "refit_history.json").write_text(
            json.dumps(
                [asdict(record) for record in fit_result.history],
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (output_dir / "refit_summary.json").write_text(
            json.dumps(asdict(refit_summary), indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (output_dir / "test_metrics.json").write_text(
            json.dumps(test_metrics, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        metadata_by_path = {row.path_id: row.metadata for row in dataset.rows}
        write_prediction_csv(
            output_dir / "test_predictions.csv",
            test_records,
            metadata_by_path,
            config.data.component_id_columns,
        )
    accelerator.print(
        json.dumps(
            {
                "device": str(accelerator.device),
                "world_size": accelerator.num_processes,
                "refit": asdict(refit_summary),
                "test": test_metrics,
            }
        )
    )
    accelerator.end_training()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _validate_args(args)
    if args.refit:
        return _run_refit(args)
    fold_index = cast(int, args.fold_index)
    config = load_project_config(args.config or DEFAULT_CONFIG)
    if args.split_manifest is not None:
        config = replace(
            config,
            data=replace(config.data, split_manifest=args.split_manifest),
        )
    seed = args.seed if args.seed is not None else config.training.seed
    device_setting = args.device or config.training.device
    mixed_precision = args.mixed_precision or config.training.mixed_precision
    gradient_accumulation_steps = config.training.gradient_accumulation_steps
    accelerator = Accelerator(
        cpu=device_setting == "cpu",
        mixed_precision=mixed_precision,
        kwargs_handlers=[
            DistributedDataParallelKwargs(
                find_unused_parameters=(
                    config.training.baseline_pretrain_epochs > 0
                    or config.training.residual_pretrain_epochs > 0
                    or config.training.freeze_baseline_after_pretrain
                )
            )
        ],
        gradient_accumulation_steps=gradient_accumulation_steps,
        dataloader_config=DataLoaderConfiguration(
            split_batches=config.training.split_batches,
        ),
    )
    set_seed(seed)
    dataset = ReactionGroupDataset(
        config.data.path,
        target_column=config.data.target_column,
        reaction_column=config.data.reaction_column,
        condition_columns=config.data.condition_columns,
        route_id_column=config.data.route_id_column,
        baseline_reduction=config.data.baseline_reduction,
        component_hash_buckets=config.model.component_hash_buckets,
        cache_dir=config.data.cache_dir if config.data.cache_enabled else None,
    )
    manifest = load_split_manifest(config.data.split_manifest)
    split = manifest.resolve(dataset, fold_index)
    subsets = split_datasets(dataset, split)
    train_on_train_valid = args.train_on_train_valid_from_scratch
    two_stage_train_on_train_valid = args.two_stage_train_valid_from_scratch
    selection_refit_from_scratch = bool(args.selection_refit_from_scratch)
    from_scratch_train_on_train_valid = (
        train_on_train_valid or two_stage_train_on_train_valid or selection_refit_from_scratch
    )
    training_indices = (
        split.train
        if two_stage_train_on_train_valid or selection_refit_from_scratch
        else [*split.train, *split.valid]
        if train_on_train_valid
        else split.train
    )
    training_dataset = (
        ReactionPathDataset(dataset, training_indices) if train_on_train_valid else subsets["train"]
    )
    target_statistics = training_dataset.target_statistics(
        residual_multi_path_only=config.training.residual_statistics_multi_path_only
    )
    output_dir = Path(args.output)
    labels = split_group_labels(dataset, split)
    if accelerator.is_main_process:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_prepared_dataset(
            dataset,
            output_dir / "preprocessed.csv",
            report_path=output_dir / "preprocessing_report.json",
            anomalies_path=output_dir / "preprocessing_anomalies.csv",
            group_split=split,
        )
        (output_dir / "split.json").write_text(
            json.dumps(
                {
                    "strategy": manifest.strategy,
                    "manifest": config.data.split_manifest,
                    "num_folds": manifest.num_folds,
                    "fold_index": fold_index,
                    "train": [dataset.group_ids[index] for index in split.train],
                    "valid": [dataset.group_ids[index] for index in split.valid],
                    "test": [dataset.group_ids[index] for index in split.test],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    accelerator.wait_for_everyone()
    batch_size = args.batch_size or config.training.batch_size_paths
    loader_kwargs = {
        "batch_size": batch_size,
        "complete_groups": config.training.group_complete_batches,
        "pin_memory": accelerator.device.type == "cuda",
    }
    train_loader = _build_path_loader(training_dataset, shuffle=True, seed=seed, **loader_kwargs)
    valid_loader = _build_path_loader(subsets["valid"], shuffle=False, seed=seed, **loader_kwargs)
    test_loader = _build_path_loader(subsets["test"], shuffle=False, seed=seed, **loader_kwargs)
    epochs = args.epochs if args.epochs is not None else config.training.epochs
    model, resolved_model = build_model(
        config.model,
        variant_override=args.model,
        mapping_mode_override=args.mapping_mode,
        encoder_override=args.encoder,
        path_encoder_override=args.path_encoder,
        substrate_encoder_override=args.substrate_encoder,
        product_encoder_override=args.product_encoder,
    )
    statistics_model = cast(TargetStatisticsModel, model)
    if config.training.target_scaling:
        statistics_model.set_target_statistics(target_statistics)
    elif config.training.residual_target_scaling and resolved_model.variant.startswith("rxnresid"):
        statistics_model.set_residual_statistics(target_statistics)
    phase_setter = getattr(model, "set_training_phase", None)
    if callable(phase_setter):
        phase_setter("joint")
    optimizer = _build_optimizer(model, config)
    optimizer_steps_per_epoch = math.ceil(len(train_loader) / gradient_accumulation_steps)
    scheduler, scheduler_plan = build_scheduler(
        optimizer,
        config.training.scheduler,
        total_steps=epochs * optimizer_steps_per_epoch,
    )
    weights = _loss_weights(config)
    huber_beta = config.loss.huber_beta
    resolved_run = ResolvedRunConfig(
        model_variant=resolved_model.variant,
        mapping_mode=resolved_model.mapping_mode,
        hidden_dim=resolved_model.hidden_dim,
        group_encoder=resolved_model.group_encoder,
        path_encoder=resolved_model.path_encoder,
        substrate_encoder=resolved_model.substrate_encoder,
        product_encoder=resolved_model.product_encoder,
        epochs=epochs,
        batch_size_paths=batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        split_batches=config.training.split_batches,
        mixed_precision=mixed_precision,
        seed=seed,
        huber_beta=huber_beta,
        split_groups=SplitSizes(
            train=len(split.train),
            valid=len(split.valid),
            test=len(split.test),
        ),
        split_paths=SplitSizes(
            train=len(subsets["train"]),
            valid=len(subsets["valid"]),
            test=len(subsets["test"]),
        ),
        group_complete_batches=config.training.group_complete_batches,
        center_residual=config.loss.center_residual,
        freeze_baseline_after_pretrain=config.training.freeze_baseline_after_pretrain,
        pairwise_loss_weight=config.loss.pairwise,
        distributed=DistributedRun(
            world_size=accelerator.num_processes,
            backend=str(accelerator.distributed_type),
        ),
        scheduler=ResolvedScheduler(
            name=config.training.scheduler.name,
            warmup_ratio=config.training.scheduler.warmup_ratio,
            min_lr_ratio=config.training.scheduler.min_lr_ratio,
            total_steps=scheduler_plan.total_steps,
            warmup_steps=scheduler_plan.warmup_steps,
        ),
        early_stopping=config.training.early_stopping,
        split_strategy=manifest.strategy,
        num_folds=manifest.num_folds,
        fold_index=fold_index,
    )
    if accelerator.is_main_process:
        (output_dir / "resolved_run.json").write_text(
            json.dumps(resolved_run.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
    stage_histories: dict[str, Any] = {}
    if selection_refit_from_scratch:
        model, optimizer, train_loader, valid_loader, test_loader, scheduler = accelerator.prepare(
            model,
            optimizer,
            train_loader,
            valid_loader,
            test_loader,
            scheduler,
        )
        selection_result = fit(
            model,
            train_loader,
            valid_loader,
            optimizer,
            accelerator,
            epochs,
            weights=weights,
            scheduler=scheduler,
            early_stopping=config.training.early_stopping,
            phase_weights=_phase_weights(config, weights),
            freeze_baseline_after_epoch=(
                config.training.baseline_pretrain_epochs
                if config.training.freeze_baseline_after_pretrain
                else 0
            ),
            beta=huber_beta,
        )
        accelerator.unwrap_model(model).load_state_dict(selection_result.best_state)
        set_seed(seed)
        stage2_indices = [*split.train, *split.valid]
        stage2_dataset = ReactionPathDataset(dataset, stage2_indices)
        stage2_loader = _build_path_loader(
            stage2_dataset,
            shuffle=True,
            seed=seed,
            **loader_kwargs,
        )
        stage2_epochs = cast(int, args.stage2_epochs)
        stage2_optimizer = _build_optimizer(
            model,
            config,
            learning_rate_factor=args.stage2_learning_rate_factor,
        )
        stage2_steps_per_epoch = math.ceil(len(stage2_loader) / gradient_accumulation_steps)
        stage2_scheduler, _ = build_scheduler(
            stage2_optimizer,
            config.training.scheduler,
            total_steps=stage2_epochs * stage2_steps_per_epoch,
        )
        stage2_optimizer, stage2_loader, stage2_scheduler = accelerator.prepare(
            stage2_optimizer,
            stage2_loader,
            stage2_scheduler,
        )
        stage2_result = fit_fixed_epochs(
            model,
            stage2_loader,
            stage2_optimizer,
            accelerator,
            stage2_epochs,
            weights=replace(
                weights,
                baseline=weights.baseline * args.stage2_auxiliary_weight_factor,
                residual=weights.residual * args.stage2_auxiliary_weight_factor,
                pairwise=weights.pairwise * args.stage2_auxiliary_weight_factor,
            ),
            scheduler=stage2_scheduler,
            phase_weights=_phase_weights(
                config,
                replace(
                    weights,
                    baseline=weights.baseline * args.stage2_auxiliary_weight_factor,
                    residual=weights.residual * args.stage2_auxiliary_weight_factor,
                    pairwise=weights.pairwise * args.stage2_auxiliary_weight_factor,
                ),
            ),
            freeze_baseline_after_epoch=(
                config.training.baseline_pretrain_epochs
                if config.training.freeze_baseline_after_pretrain
                else 0
            ),
            beta=huber_beta,
            progress_label="stage2_epoch",
        )
        stage_histories = {
            "selection": [asdict(record) for record in selection_result.history],
            "stage2": [asdict(record) for record in stage2_result.history],
        }
        training_summary = TrainingSummary(
            epochs_requested=selection_result.summary.epochs_completed + stage2_epochs,
            epochs_completed=selection_result.summary.epochs_completed + stage2_epochs,
            best_epoch=selection_result.summary.best_epoch + stage2_epochs,
            best_metric=float(stage2_result.history[-1].train["loss"]),
            monitor="selection_refit_train_loss",
            stopped_early=False,
        )
        checkpoint_state = stage2_result.final_state
        history = (*selection_result.history, *stage2_result.history)
    elif from_scratch_train_on_train_valid:
        model, optimizer, train_loader, test_loader, scheduler = accelerator.prepare(
            model,
            optimizer,
            train_loader,
            test_loader,
            scheduler,
        )
        stage1_epochs = args.stage1_epochs if two_stage_train_on_train_valid else epochs
        fixed_result = fit_fixed_epochs(
            model,
            train_loader,
            optimizer,
            accelerator,
            stage1_epochs,
            weights=weights,
            scheduler=scheduler,
            phase_weights=_phase_weights(config, weights),
            freeze_baseline_after_epoch=(
                config.training.baseline_pretrain_epochs
                if config.training.freeze_baseline_after_pretrain
                else 0
            ),
            beta=huber_beta,
            progress_label=("stage1_epoch" if two_stage_train_on_train_valid else "fixed_epoch"),
        )
        stage_histories = {"stage1": [asdict(record) for record in fixed_result.history]}
        if two_stage_train_on_train_valid:
            stage2_indices = [*split.train, *split.valid]
            stage2_dataset = ReactionPathDataset(dataset, stage2_indices)
            stage2_loader = _build_path_loader(
                stage2_dataset,
                shuffle=True,
                seed=seed,
                **loader_kwargs,
            )
            stage2_epochs = cast(int, args.stage2_epochs)
            stage2_optimizer = _build_optimizer(
                model,
                config,
                learning_rate_factor=args.stage2_learning_rate_factor,
            )
            stage2_steps_per_epoch = math.ceil(len(stage2_loader) / gradient_accumulation_steps)
            stage2_scheduler, _ = build_scheduler(
                stage2_optimizer,
                config.training.scheduler,
                total_steps=stage2_epochs * stage2_steps_per_epoch,
            )
            stage2_optimizer, stage2_loader, stage2_scheduler = accelerator.prepare(
                stage2_optimizer,
                stage2_loader,
                stage2_scheduler,
            )
            stage2_result = fit_fixed_epochs(
                model,
                stage2_loader,
                stage2_optimizer,
                accelerator,
                stage2_epochs,
                weights=weights,
                scheduler=stage2_scheduler,
                phase_weights=_phase_weights(config, weights),
                freeze_baseline_after_epoch=(
                    config.training.baseline_pretrain_epochs
                    if config.training.freeze_baseline_after_pretrain
                    else 0
                ),
                beta=huber_beta,
                progress_label="stage2_epoch",
            )
            stage_histories["stage2"] = [asdict(record) for record in stage2_result.history]
            training_summary = TrainingSummary(
                epochs_requested=stage1_epochs + stage2_epochs,
                epochs_completed=stage1_epochs + stage2_epochs,
                best_epoch=stage1_epochs + stage2_epochs,
                best_metric=float(stage2_result.history[-1].train["loss"]),
                monitor="fixed_two_stage_train_loss",
                stopped_early=False,
            )
            checkpoint_state = stage2_result.final_state
            history = (*fixed_result.history, *stage2_result.history)
        else:
            training_summary = TrainingSummary(
                epochs_requested=epochs,
                epochs_completed=epochs,
                best_epoch=epochs,
                best_metric=float(fixed_result.history[-1].train["loss"]),
                monitor="train_loss",
                stopped_early=False,
            )
            checkpoint_state = fixed_result.final_state
            history = fixed_result.history
    else:
        model, optimizer, train_loader, valid_loader, test_loader, scheduler = accelerator.prepare(
            model,
            optimizer,
            train_loader,
            valid_loader,
            test_loader,
            scheduler,
        )
        fit_result = fit(
            model,
            train_loader,
            valid_loader,
            optimizer,
            accelerator,
            epochs,
            weights=weights,
            scheduler=scheduler,
            early_stopping=config.training.early_stopping,
            phase_weights=_phase_weights(config, weights),
            freeze_baseline_after_epoch=(
                config.training.baseline_pretrain_epochs
                if config.training.freeze_baseline_after_pretrain
                else 0
            ),
            beta=huber_beta,
        )
        training_summary = fit_result.summary
        checkpoint_state = fit_result.best_state
        history = fit_result.history
    _, test_metrics = evaluate(model, test_loader, accelerator, weights, beta=huber_beta)
    test_records = predict(
        model,
        test_loader,
        accelerator,
        center_residual=weights.center_residual,
    )
    selection_records = []
    if not from_scratch_train_on_train_valid or selection_refit_from_scratch:
        selection_records = [
            *predict(
                model,
                train_loader,
                accelerator,
                center_residual=weights.center_residual,
            ),
            *predict(
                model,
                valid_loader,
                accelerator,
                center_residual=weights.center_residual,
            ),
            *test_records,
        ]
    accelerator.wait_for_everyone()
    if accelerator.is_main_process:
        accelerator.save(
            {
                "model_state": checkpoint_state,
                "config": config.to_dict(),
                "resolved_run": resolved_run.to_dict(),
                "training_summary": asdict(training_summary),
                "target_statistics": asdict(target_statistics),
                "group_ids": dataset.group_ids,
                "split_labels": labels,
                "training_protocol": {
                    "mode": (
                        "selection_refit_from_scratch"
                        if selection_refit_from_scratch
                        else "two_stage_train_valid_from_scratch"
                        if two_stage_train_on_train_valid
                        else "train_valid_from_scratch"
                        if train_on_train_valid
                        else "train_valid_selection"
                    ),
                    "initialization": "random",
                    "checkpoint_loaded": False,
                    "training_groups": len(training_indices),
                    "training_paths": len(training_dataset),
                    "stage1_epochs": args.stage1_epochs,
                    "stage2_epochs": args.stage2_epochs,
                    "stage2_learning_rate_factor": (
                        args.stage2_learning_rate_factor
                        if two_stage_train_on_train_valid or selection_refit_from_scratch
                        else None
                    ),
                    "stage2_auxiliary_weight_factor": (
                        args.stage2_auxiliary_weight_factor
                        if two_stage_train_on_train_valid or selection_refit_from_scratch
                        else None
                    ),
                },
            },
            output_dir / "checkpoint.pt",
        )
        (output_dir / "history.json").write_text(
            json.dumps(
                [asdict(cast(Any, record)) for record in history],
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        if from_scratch_train_on_train_valid and (
            two_stage_train_on_train_valid or selection_refit_from_scratch
        ):
            (output_dir / "stage_histories.json").write_text(
                json.dumps(stage_histories, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
        (output_dir / "training_summary.json").write_text(
            json.dumps(asdict(training_summary), indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (output_dir / "training_protocol.json").write_text(
            json.dumps(
                {
                    "mode": (
                        "selection_refit_from_scratch"
                        if selection_refit_from_scratch
                        else "two_stage_train_valid_from_scratch"
                        if two_stage_train_on_train_valid
                        else "train_valid_from_scratch"
                        if train_on_train_valid
                        else "train_valid_selection"
                    ),
                    "initialization": "random",
                    "checkpoint_loaded": False,
                    "training_groups": len(training_indices),
                    "training_paths": len(training_dataset),
                    "fixed_epochs": (
                        from_scratch_train_on_train_valid and not selection_refit_from_scratch
                    ),
                    "stage1_epochs": args.stage1_epochs,
                    "stage2_epochs": args.stage2_epochs,
                    "stage2_learning_rate_factor": (
                        args.stage2_learning_rate_factor
                        if two_stage_train_on_train_valid or selection_refit_from_scratch
                        else None
                    ),
                    "stage2_auxiliary_weight_factor": (
                        args.stage2_auxiliary_weight_factor
                        if two_stage_train_on_train_valid or selection_refit_from_scratch
                        else None
                    ),
                },
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (output_dir / "test_metrics.json").write_text(
            json.dumps(test_metrics, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        metadata_by_path = {row.path_id: row.metadata for row in dataset.rows}
        write_prediction_csv(
            output_dir / "test_predictions.csv",
            test_records,
            metadata_by_path,
            config.data.component_id_columns,
        )
        if selection_records:
            write_prediction_csv(
                output_dir / "selection_predictions.csv",
                selection_records,
                metadata_by_path,
                config.data.component_id_columns,
            )
    accelerator.print(
        json.dumps(
            {
                "device": str(accelerator.device),
                "world_size": accelerator.num_processes,
                "model": resolved_model.variant,
                "groups": len(dataset),
                "paths": len(dataset.rows),
                "training": asdict(training_summary),
                "test": test_metrics,
            }
        )
    )
    accelerator.end_training()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
