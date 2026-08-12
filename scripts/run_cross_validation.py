#!/usr/bin/env python3
"""Run resumable group-level cross-validation through torchrun and Accelerate."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import queue
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from rxnresid.config import (
    EarlyStoppingConfig,
    ProjectConfig,
    ResolvedRunConfig,
    SchedulerConfig,
    load_project_config,
)
from rxnresid.data.split import load_split_manifest
from rxnresid.models.encoders import available_encoders
from rxnresid.training.trainer import TrainingSummary


ENCODER_MODULES = ("substrate", "path", "product")


@dataclass(frozen=True)
class ExperimentSpec:
    name: str
    model_variant: str
    mapping_mode: str
    seed: int | None = None


EXPERIMENTS = (
    ExperimentSpec(
        "seed42",
        "rxnresid",
        "latent_diff",
        seed=42,
    ),
    ExperimentSpec(
        "seed43",
        "rxnresid",
        "latent_diff",
        seed=43,
    ),
)


@dataclass(frozen=True)
class CrossValidationConfig:
    data: str
    project_config: str
    split_manifest: str
    output_root: str
    substrate_encoder: str
    path_encoder: str
    product_encoder: str
    epochs: int
    nproc_per_node: int
    seed: int
    num_folds: int
    experiments: tuple[str, ...]
    fold_indices: tuple[int, ...]
    scheduler: SchedulerConfig
    early_stopping: EarlyStoppingConfig
    tasks_per_gpu: int
    gpu_indices: tuple[int, ...]
    stop_mae_ge: float | None
    refit_epochs: int
    refit_learning_rate_factor: float
    train_on_train_valid_from_scratch: bool
    two_stage_train_valid_from_scratch: bool
    selection_refit_from_scratch: bool
    stage1_epochs: int | None
    stage2_epochs: int | None
    stage2_learning_rate_factor: float
    stage2_auxiliary_weight_factor: float
    # The scheduler may vary one module per run.  The resolved encoder values
    # above are still retained so old summaries and checkpoints remain valid.
    encoder_module: str | None = None


@dataclass(frozen=True)
class FoldResult:
    experiment: str
    fold_index: int
    output_dir: str
    best_epoch: int
    epochs_completed: int
    stopped_early: bool
    duration_seconds: float
    resumed: bool
    metrics: dict[str, float | None]


@dataclass(frozen=True)
class MetricAggregate:
    metric: str
    mean: float
    std: float
    minimum: float
    maximum: float


@dataclass(frozen=True)
class ExperimentAggregate:
    experiment: str
    folds: int
    metrics: tuple[MetricAggregate, ...]


@dataclass(frozen=True)
class CrossValidationSummary:
    config: CrossValidationConfig
    fold_results: tuple[FoldResult, ...]
    aggregates: tuple[ExperimentAggregate, ...]


def _module_directory(config: CrossValidationConfig) -> str:
    modules = (
        config.substrate_encoder,
        config.path_encoder,
        config.product_encoder,
    )
    if modules == ("gine", "gine_gatv2", "gine"):
        return "gine"
    return "__".join(
        (
            f"substrate-{config.substrate_encoder}",
            f"path-{config.path_encoder}",
            f"product-{config.product_encoder}",
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/rxnresid.yaml")
    parser.add_argument(
        "--split-manifest",
        default=None,
        help="Override data.split_manifest and persist it in selection checkpoints.",
    )
    parser.add_argument("--output-root", default="runs/cross-validation")
    parser.add_argument(
        "--module",
        choices=ENCODER_MODULES,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--encoder",
        choices=available_encoders(),
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--path-encoder",
        choices=available_encoders(),
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--substrate-encoder",
        choices=available_encoders(),
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--product-encoder",
        choices=available_encoders(),
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--nproc-per-node", type=int, default=1)
    parser.add_argument(
        "--tasks-per-gpu",
        type=int,
        default=1,
        help="Run this many independent single-process tasks concurrently per GPU.",
    )
    parser.add_argument(
        "--gpu-indices",
        nargs="+",
        type=int,
        default=None,
        help="Physical GPU indices used for independent single-process tasks.",
    )
    parser.add_argument("--folds", nargs="+", type=int, default=None)
    parser.add_argument(
        "--experiments",
        nargs="+",
        choices=[experiment.name for experiment in EXPERIMENTS],
        default=[experiment.name for experiment in EXPERIMENTS],
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--stop-mae-ge",
        type=float,
        default=None,
        help="Stop later folds for an experiment after a test path MAE at or above this value.",
    )
    parser.add_argument(
        "--refit-epochs",
        type=int,
        default=180,
        help="Fixed train+validation second-stage epochs (default: 180).",
    )
    parser.add_argument(
        "--refit-learning-rate-factor",
        type=float,
        default=0.2,
        help="Second-stage learning-rate factor (default: 0.2).",
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
        default=True,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--stage1-epochs", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--stage2-epochs", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--stage2-learning-rate-factor", type=float, default=0.2, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--stage2-auxiliary-weight-factor",
        type=float,
        default=0.5,
        help="Second-stage auxiliary-loss factor (default: 0.5).",
    )
    return parser


def _resolve_encoder_selection(
    args: argparse.Namespace, project_config: ProjectConfig
) -> tuple[str, str, str, str | None]:
    """Resolve a scheduler run without allowing encoder-combination selection.

    A scheduler invocation is either the baseline (no override) or an ablation
    of exactly one role.  The three explicit role flags remain supported for
    compatibility with older scripts, but using more than one is rejected.
    ``--module/--encoder`` is the preferred, unambiguous spelling.
    """
    model_config = project_config.model
    role_values = {
        "substrate": args.substrate_encoder,
        "path": args.path_encoder,
        "product": args.product_encoder,
    }
    explicit_roles = [role for role, value in role_values.items() if value is not None]
    if (args.module is None) != (args.encoder is None):
        raise ValueError("--module and --encoder must be provided together")
    if args.module is not None:
        if explicit_roles:
            raise ValueError("--module/--encoder cannot be combined with role encoder flags")
        role_values[args.module] = args.encoder
        selected_module = args.module
    else:
        if len(explicit_roles) > 1:
            raise ValueError(
                "the scheduler selects one encoder module at a time; "
                "provide only one of --substrate-encoder, --path-encoder, "
                "or --product-encoder"
            )
        selected_module = explicit_roles[0] if explicit_roles else None

    configured = {
        "substrate": model_config.substrate_encoder.type,
        "path": model_config.path_encoder.type,
        "product": model_config.product_encoder.type,
    }
    resolved = {role: role_values[role] or configured[role] for role in ENCODER_MODULES}
    return (
        resolved["substrate"],
        resolved["path"],
        resolved["product"],
        selected_module,
    )


def _completed_result(
    output: Path,
    experiment: ExperimentSpec,
    fold_index: int,
    config: CrossValidationConfig,
) -> FoldResult | None:
    external_refit = config.refit_epochs and not config.selection_refit_from_scratch
    result_output = output / "refit" if external_refit else output
    metrics_path = result_output / "test_metrics.json"
    resolved_path = output / "resolved_run.json"
    history_path = output / "history.json"
    training_summary_path = output / "training_summary.json"
    split_path = output / "split.json"
    if not all(
        path.is_file()
        for path in (metrics_path, resolved_path, history_path, training_summary_path, split_path)
    ):
        return None
    protocol_path = output / "training_protocol.json"
    if (
        config.train_on_train_valid_from_scratch
        or config.two_stage_train_valid_from_scratch
        or config.selection_refit_from_scratch
    ):
        if not protocol_path.is_file():
            return None
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        expected_mode = (
            "selection_refit_from_scratch"
            if config.selection_refit_from_scratch
            else "two_stage_train_valid_from_scratch"
            if config.two_stage_train_valid_from_scratch
            else "train_valid_from_scratch"
        )
        if (
            protocol.get("mode") != expected_mode
            or protocol.get("initialization") != "random"
            or protocol.get("checkpoint_loaded") is not False
            or protocol.get("fixed_epochs") is not (not config.selection_refit_from_scratch)
            or protocol.get("stage1_epochs") != config.stage1_epochs
            or protocol.get("stage2_epochs")
            != (
                config.refit_epochs if config.selection_refit_from_scratch else config.stage2_epochs
            )
            or protocol.get("stage2_learning_rate_factor")
            != (
                config.refit_learning_rate_factor
                if config.selection_refit_from_scratch
                else config.stage2_learning_rate_factor
                if config.two_stage_train_valid_from_scratch
                else None
            )
            or protocol.get("stage2_auxiliary_weight_factor")
            != (
                config.stage2_auxiliary_weight_factor
                if config.two_stage_train_valid_from_scratch or config.selection_refit_from_scratch
                else None
            )
        ):
            return None
    elif protocol_path.is_file():
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        if protocol.get("mode") == "train_valid_from_scratch":
            return None
    split_metadata = json.loads(split_path.read_text(encoding="utf-8"))
    if split_metadata.get("manifest") != config.split_manifest:
        return None
    if external_refit:
        refit_summary_path = result_output / "refit_summary.json"
        if not refit_summary_path.is_file():
            return None
        refit_summary = json.loads(refit_summary_path.read_text(encoding="utf-8"))
        if (
            int(refit_summary.get("epochs_completed", 0)) != config.refit_epochs
            or float(refit_summary.get("learning_rate_factor", 0.0))
            != config.refit_learning_rate_factor
        ):
            return None
    resolved = ResolvedRunConfig.from_mapping(json.loads(resolved_path.read_text(encoding="utf-8")))
    if (
        resolved.model_variant != experiment.model_variant
        or resolved.mapping_mode != experiment.mapping_mode
        or resolved.path_encoder != config.path_encoder
        or resolved.substrate_encoder != config.substrate_encoder
        or resolved.product_encoder != config.product_encoder
        or resolved.epochs != config.epochs
        or resolved.seed != (experiment.seed if experiment.seed is not None else config.seed)
        or resolved.fold_index != fold_index
        or resolved.num_folds != config.num_folds
        or resolved.distributed.world_size != config.nproc_per_node
        or resolved.scheduler.name != config.scheduler.name
        or resolved.scheduler.warmup_ratio != config.scheduler.warmup_ratio
        or resolved.scheduler.min_lr_ratio != config.scheduler.min_lr_ratio
        or resolved.early_stopping != config.early_stopping
    ):
        return None
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    training_summary = TrainingSummary.from_mapping(
        json.loads(training_summary_path.read_text(encoding="utf-8"))
    )
    return FoldResult(
        experiment=experiment.name,
        fold_index=fold_index,
        output_dir=str(output),
        best_epoch=training_summary.best_epoch,
        epochs_completed=training_summary.epochs_completed,
        stopped_early=training_summary.stopped_early,
        duration_seconds=0.0,
        resumed=True,
        metrics=metrics,
    )


def _run_fold(
    repository: Path,
    torchrun: Path,
    experiment: ExperimentSpec,
    fold_index: int,
    config: CrossValidationConfig,
    force: bool,
    progress: str,
    cuda_device: int | None = None,
) -> FoldResult:
    module_directory = _module_directory(config)
    output = (
        Path(config.output_root) / module_directory / experiment.name / f"fold_{fold_index:02d}"
    )
    if not force:
        completed = _completed_result(output, experiment, fold_index, config)
        if completed is not None:
            print(f"{progress} resume {experiment.name} fold={fold_index}", flush=True)
            return completed
    selection_completed = None
    if not force and config.refit_epochs and not config.selection_refit_from_scratch:
        selection_completed = _completed_result(
            output,
            experiment,
            fold_index,
            replace(config, refit_epochs=0),
        )
    output.mkdir(parents=True, exist_ok=True)
    seed = experiment.seed if experiment.seed is not None else config.seed
    command = [
        str(torchrun),
        "--standalone",
        f"--nproc_per_node={config.nproc_per_node}",
        str(repository / "train.py"),
        "--config",
        config.project_config,
        "--split-manifest",
        config.split_manifest,
        "--output",
        str(output),
        "--epochs",
        str(config.epochs),
        "--seed",
        str(seed),
        "--model",
        experiment.model_variant,
        "--mapping-mode",
        experiment.mapping_mode,
        "--fold-index",
        str(fold_index),
    ]
    if config.train_on_train_valid_from_scratch:
        command.append("--train-on-train-valid-from-scratch")
    if config.two_stage_train_valid_from_scratch:
        command.extend(
            (
                "--two-stage-train-valid-from-scratch",
                "--stage1-epochs",
                str(config.stage1_epochs),
                "--stage2-epochs",
                str(config.stage2_epochs),
                "--stage2-learning-rate-factor",
                str(config.stage2_learning_rate_factor),
                "--stage2-auxiliary-weight-factor",
                str(config.stage2_auxiliary_weight_factor),
            )
        )
    if config.selection_refit_from_scratch:
        command.extend(
            (
                "--selection-refit-from-scratch",
                "--stage2-epochs",
                str(config.refit_epochs),
                "--stage2-learning-rate-factor",
                str(config.refit_learning_rate_factor),
                "--stage2-auxiliary-weight-factor",
                str(config.stage2_auxiliary_weight_factor),
            )
        )
    for option, value in (
        ("--path-encoder", config.path_encoder),
        ("--substrate-encoder", config.substrate_encoder),
        ("--product-encoder", config.product_encoder),
    ):
        command.extend((option, value))
    started = time.monotonic()
    environment = os.environ.copy()
    if cuda_device is not None:
        environment["CUDA_VISIBLE_DEVICES"] = str(cuda_device)
    if selection_completed is None:
        print(f"{progress} start {experiment.name} fold={fold_index}", flush=True)
        log_path = output / "torchrun.log"
        with log_path.open("w", encoding="utf-8") as log_handle:
            process = subprocess.run(
                command,
                cwd=repository,
                env=environment,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        if process.returncode != 0:
            raise RuntimeError(
                f"torchrun failed for {experiment.name} fold {fold_index}; see {log_path}"
            )
    else:
        print(f"{progress} resume selection {experiment.name} fold={fold_index}", flush=True)
    result_output = output
    if config.refit_epochs and not config.selection_refit_from_scratch:
        result_output = output / "refit"
        result_output.mkdir(parents=True, exist_ok=True)
        refit_command = [
            str(torchrun),
            "--standalone",
            f"--nproc_per_node={config.nproc_per_node}",
            str(repository / "train.py"),
            "--refit",
            "--checkpoint",
            str(output / "checkpoint.pt"),
            "--output",
            str(result_output),
            "--epochs",
            str(config.refit_epochs),
            "--learning-rate-factor",
            str(config.refit_learning_rate_factor),
        ]
        refit_log_path = result_output / "torchrun.log"
        print(f"{progress} refit {experiment.name} fold={fold_index}", flush=True)
        with refit_log_path.open("w", encoding="utf-8") as log_handle:
            process = subprocess.run(
                refit_command,
                cwd=repository,
                env=environment,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        if process.returncode != 0:
            raise RuntimeError(
                f"torchrun refit failed for {experiment.name} fold {fold_index}; "
                f"see {refit_log_path}"
            )
    duration = time.monotonic() - started
    metrics = json.loads((result_output / "test_metrics.json").read_text(encoding="utf-8"))
    training_summary = TrainingSummary.from_mapping(
        json.loads((output / "training_summary.json").read_text(encoding="utf-8"))
    )
    print(
        f"{progress} done {experiment.name} fold={fold_index} "
        f"mae={metrics['mae']:.6f} seconds={duration:.1f}",
        flush=True,
    )
    return FoldResult(
        experiment=experiment.name,
        fold_index=fold_index,
        output_dir=str(output),
        best_epoch=training_summary.best_epoch,
        epochs_completed=training_summary.epochs_completed,
        stopped_early=training_summary.stopped_early,
        duration_seconds=duration,
        resumed=False,
        metrics=metrics,
    )


def _aggregate(results: list[FoldResult]) -> tuple[ExperimentAggregate, ...]:
    aggregates: list[ExperimentAggregate] = []
    for experiment in sorted({result.experiment for result in results}):
        experiment_results = [result for result in results if result.experiment == experiment]
        metric_names = sorted(experiment_results[0].metrics)
        metrics: list[MetricAggregate] = []
        for metric in metric_names:
            values = [
                float(value)
                for result in experiment_results
                if (value := result.metrics[metric]) is not None
            ]
            if not values:
                continue
            metrics.append(
                MetricAggregate(
                    metric=metric,
                    mean=statistics.fmean(values),
                    std=statistics.stdev(values) if len(values) > 1 else 0.0,
                    minimum=min(values),
                    maximum=max(values),
                )
            )
        aggregates.append(
            ExperimentAggregate(
                experiment=experiment,
                folds=len(experiment_results),
                metrics=tuple(metrics),
            )
        )
    return tuple(aggregates)


def _write_summary(summary: CrossValidationSummary) -> None:
    output_root = Path(summary.config.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(
        json.dumps(asdict(summary), indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with (output_root / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["experiment", "folds", "metric", "mean", "std", "minimum", "maximum"],
        )
        writer.writeheader()
        for aggregate in summary.aggregates:
            for metric in aggregate.metrics:
                writer.writerow(
                    {
                        "experiment": aggregate.experiment,
                        "folds": aggregate.folds,
                        **asdict(metric),
                    }
                )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repository = Path(__file__).resolve().parents[1]
    project_config = load_project_config(args.config)
    split_manifest = args.split_manifest or project_config.data.split_manifest
    manifest = load_split_manifest(repository / split_manifest)
    selected_names = set(args.experiments)
    experiments = tuple(
        experiment for experiment in EXPERIMENTS if experiment.name in selected_names
    )
    (
        substrate_encoder,
        path_encoder,
        product_encoder,
        encoder_module,
    ) = _resolve_encoder_selection(args, project_config)
    epochs = args.epochs if args.epochs is not None else project_config.training.epochs
    fold_indices = tuple(args.folds) if args.folds is not None else tuple(range(manifest.num_folds))
    if len(set(fold_indices)) != len(fold_indices):
        raise ValueError("--folds must not contain duplicate indices")
    if any(index < 0 or index >= manifest.num_folds for index in fold_indices):
        raise ValueError(f"--folds values must be between 0 and {manifest.num_folds - 1}")
    if args.tasks_per_gpu < 1:
        raise ValueError("--tasks-per-gpu must be at least one")
    if args.stop_mae_ge is not None and args.stop_mae_ge <= 0.0:
        raise ValueError("--stop-mae-ge must be positive")
    if args.refit_epochs < 0:
        raise ValueError("--refit-epochs must be non-negative")
    if args.refit_learning_rate_factor <= 0.0:
        raise ValueError("--refit-learning-rate-factor must be positive")
    if args.stage2_auxiliary_weight_factor < 0.0:
        raise ValueError("--stage2-auxiliary-weight-factor must be non-negative")
    if args.train_on_train_valid_from_scratch and args.refit_epochs:
        raise ValueError(
            "--train-on-train-valid-from-scratch cannot be combined with --refit-epochs"
        )
    if args.train_on_train_valid_from_scratch and args.two_stage_train_valid_from_scratch:
        raise ValueError("from-scratch training modes are mutually exclusive")
    if args.selection_refit_from_scratch and (
        args.train_on_train_valid_from_scratch or args.two_stage_train_valid_from_scratch
    ):
        raise ValueError("from-scratch training modes are mutually exclusive")
    if args.selection_refit_from_scratch and args.refit_epochs < 1:
        raise ValueError("--selection-refit-from-scratch requires --refit-epochs >= 1")
    if args.two_stage_train_valid_from_scratch:
        if args.refit_epochs:
            raise ValueError(
                "--two-stage-train-valid-from-scratch cannot be combined with --refit-epochs"
            )
        if args.stage1_epochs is None or args.stage2_epochs is None:
            raise ValueError(
                "--stage1-epochs and --stage2-epochs are required for two-stage training"
            )
        if args.stage1_epochs < 1 or args.stage2_epochs < 1:
            raise ValueError("two-stage epoch counts must be positive")
        if args.stage2_learning_rate_factor <= 0.0:
            raise ValueError("--stage2-learning-rate-factor must be positive")
    elif args.stage1_epochs is not None or args.stage2_epochs is not None:
        raise ValueError("stage epoch options require --two-stage-train-valid-from-scratch")
    if args.nproc_per_node > 1 and args.tasks_per_gpu != 1:
        raise ValueError("--tasks-per-gpu requires --nproc-per-node=1")
    if args.gpu_indices is not None and any(index < 0 for index in args.gpu_indices):
        raise ValueError("--gpu-indices must contain non-negative indices")
    if (
        args.nproc_per_node == 1
        and project_config.training.device == "cpu"
        and (args.tasks_per_gpu != 1 or args.gpu_indices)
    ):
        raise ValueError("GPU task parallelism is unavailable with training.device=cpu")
    gpu_indices = tuple(args.gpu_indices or ())
    if args.nproc_per_node == 1 and args.tasks_per_gpu > 1 and not gpu_indices:
        import torch

        gpu_indices = tuple(range(torch.cuda.device_count()))
        if not gpu_indices:
            raise RuntimeError("--tasks-per-gpu requires at least one CUDA device")
    run_config = CrossValidationConfig(
        data=project_config.data.path,
        project_config=args.config,
        split_manifest=split_manifest,
        output_root=args.output_root,
        substrate_encoder=substrate_encoder,
        path_encoder=path_encoder,
        product_encoder=product_encoder,
        epochs=epochs,
        nproc_per_node=args.nproc_per_node,
        seed=project_config.training.seed,
        num_folds=manifest.num_folds,
        experiments=tuple(experiment.name for experiment in experiments),
        fold_indices=fold_indices,
        scheduler=project_config.training.scheduler,
        early_stopping=project_config.training.early_stopping,
        tasks_per_gpu=args.tasks_per_gpu,
        gpu_indices=gpu_indices,
        stop_mae_ge=args.stop_mae_ge,
        refit_epochs=args.refit_epochs,
        refit_learning_rate_factor=args.refit_learning_rate_factor,
        train_on_train_valid_from_scratch=args.train_on_train_valid_from_scratch,
        two_stage_train_valid_from_scratch=args.two_stage_train_valid_from_scratch,
        selection_refit_from_scratch=args.selection_refit_from_scratch,
        stage1_epochs=args.stage1_epochs,
        stage2_epochs=args.stage2_epochs,
        stage2_learning_rate_factor=args.stage2_learning_rate_factor,
        stage2_auxiliary_weight_factor=args.stage2_auxiliary_weight_factor,
        encoder_module=encoder_module,
    )
    torchrun = Path(sys.executable).with_name("torchrun")
    if not torchrun.is_file():
        raise FileNotFoundError(f"torchrun not found next to interpreter: {torchrun}")
    tasks = [(experiment, fold_index) for experiment in experiments for fold_index in fold_indices]
    results: list[FoldResult] = []
    slots: list[int | None]
    if args.nproc_per_node > 1 or not gpu_indices:
        slots = [None]
    else:
        slots = [gpu for gpu in gpu_indices for _ in range(args.tasks_per_gpu)]
    max_workers = min(len(tasks), len(slots))
    if args.stop_mae_ge is not None:
        max_workers = 1
    if max_workers <= 1:
        stopped_experiments: set[str] = set()
        for task_index, (experiment, fold_index) in enumerate(tasks, start=1):
            if experiment.name in stopped_experiments:
                continue
            result = _run_fold(
                repository,
                torchrun,
                experiment,
                fold_index,
                run_config,
                args.force,
                progress=f"[{task_index}/{len(tasks)}]",
                cuda_device=slots[0],
            )
            results.append(result)
            mae = result.metrics.get("mae")
            if (
                args.stop_mae_ge is not None
                and isinstance(mae, (int, float))
                and mae >= args.stop_mae_ge
            ):
                stopped_experiments.add(experiment.name)
                print(
                    f"[{task_index}/{len(tasks)}] stop {experiment.name}: "
                    f"mae={mae:.6f} >= {args.stop_mae_ge:.6f}",
                    flush=True,
                )
            _write_summary(
                CrossValidationSummary(
                    config=run_config,
                    fold_results=tuple(results),
                    aggregates=_aggregate(results),
                )
            )
    else:
        available_slots: queue.Queue[int | None] = queue.Queue()
        for slot in slots:
            available_slots.put(slot)

        def run_in_slot(
            experiment: ExperimentSpec,
            fold_index: int,
            task_index: int,
        ) -> FoldResult:
            # Hold a GPU slot for the whole subprocess lifetime. Task completion
            # order must not cause two active folds to share one device.
            cuda_device = available_slots.get()
            try:
                return _run_fold(
                    repository,
                    torchrun,
                    experiment,
                    fold_index,
                    run_config,
                    args.force,
                    progress=f"[{task_index}/{len(tasks)}]",
                    cuda_device=cuda_device,
                )
            finally:
                available_slots.put(cuda_device)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            pending = {
                executor.submit(
                    run_in_slot,
                    experiment,
                    fold_index,
                    task_index,
                ): task_index
                for task_index, (experiment, fold_index) in enumerate(tasks, start=1)
            }
            for future in concurrent.futures.as_completed(pending):
                results.append(future.result())
                _write_summary(
                    CrossValidationSummary(
                        config=run_config,
                        fold_results=tuple(results),
                        aggregates=_aggregate(results),
                    )
                )
    _write_summary(
        CrossValidationSummary(
            config=run_config,
            fold_results=tuple(results),
            aggregates=_aggregate(results),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
