"""Explicit dataclass configuration models for training and inference."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from rxnresid.models.encoders import EncoderConfig
from rxnresid.models.heads import HeadConfig
from rxnresid.models.mapping.module import MappingMode


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} configuration must be a mapping")
    return value


def _encoder_config(value: Any, *, default_pooling: str = "mean") -> EncoderConfig:
    mapping = _mapping(value, "encoder")
    options = _mapping(mapping.get("options"), "encoder options")
    return EncoderConfig(
        type=str(mapping.get("type", "gine")),
        num_layers=int(mapping.get("num_layers", 4)),
        dropout=float(mapping.get("dropout", 0.1)),
        pooling=str(mapping.get("pooling", default_pooling)),
        options=dict(options),
    )


def _head_config(value: Any) -> HeadConfig:
    mapping = _mapping(value, "head")
    hidden_dims = mapping.get("hidden_dims", [256, 64])
    if not isinstance(hidden_dims, (list, tuple)) or not hidden_dims:
        raise ValueError("head hidden_dims must be a non-empty sequence")
    return HeadConfig(hidden_dims=tuple(int(dimension) for dimension in hidden_dims))


@dataclass(frozen=True)
class DataConfig:
    path: str = "data/new_full_df_exact_balanced_40ene_40diene.csv"
    cache_enabled: bool = True
    cache_dir: str = ".cache/rxnresid"
    target_column: str = "G_T_activate"
    reaction_column: str = "rxn_smiles"
    condition_columns: tuple[str, ...] = ()
    component_id_columns: tuple[str, ...] = ("ene_id", "diene_id")
    route_id_column: str | None = "prod_id"
    baseline_reduction: Literal["mean"] = "mean"
    split_manifest: str = "data/splits/group_10fold_seed42.json"

    @classmethod
    def from_mapping(cls, value: Any) -> DataConfig:
        mapping = _mapping(value, "data")
        condition_columns = mapping.get("condition_columns", [])
        if not isinstance(condition_columns, (list, tuple)):
            raise ValueError("data.condition_columns must be a sequence")
        component_id_columns = mapping.get("component_id_columns", ["ene_id", "diene_id"])
        if not isinstance(component_id_columns, (list, tuple)):
            raise ValueError("data.component_id_columns must be a sequence")
        if not component_id_columns:
            raise ValueError("data.component_id_columns must contain at least one column")
        path = str(mapping.get("path", "data/new_full_df_exact_balanced_40ene_40diene.csv"))
        cache_dir = str(mapping.get("cache_dir", ".cache/rxnresid")).strip()
        split_manifest = str(mapping.get("split_manifest", "data/splits/group_10fold_seed42.json"))
        if not path:
            raise ValueError("data.path must not be empty")
        if not cache_dir:
            raise ValueError("data.cache_dir must not be empty")
        if not split_manifest:
            raise ValueError("data.split_manifest must not be empty")
        route_id_column = (
            str(mapping.get("route_id_column", "prod_id")).strip()
            if mapping.get("route_id_column", "prod_id") is not None
            else None
        )
        if route_id_column == "":
            raise ValueError("data.route_id_column must not be empty")
        baseline_reduction = str(mapping.get("baseline_reduction", "mean"))
        if baseline_reduction != "mean":
            raise ValueError("RxnResid requires data.baseline_reduction=mean")
        normalized_component_columns = tuple(str(column).strip() for column in component_id_columns)
        if any(not column for column in normalized_component_columns):
            raise ValueError("data.component_id_columns must not contain empty columns")
        if len(set(normalized_component_columns)) != len(normalized_component_columns):
            raise ValueError("data.component_id_columns must be unique")
        return cls(
            path=path,
            cache_enabled=bool(mapping.get("cache_enabled", True)),
            cache_dir=cache_dir,
            target_column=str(mapping.get("target_column", "G_T_activate")),
            reaction_column=str(mapping.get("reaction_column", "rxn_smiles")),
            condition_columns=tuple(str(column) for column in condition_columns),
            component_id_columns=normalized_component_columns,
            route_id_column=route_id_column,
            baseline_reduction=cast(Literal["mean"], baseline_reduction),
            split_manifest=split_manifest,
        )


@dataclass(frozen=True)
class MappingConfig:
    mode: MappingMode = "latent_diff"
    hidden_dim: int = 64
    dropout: float = 0.05

    @classmethod
    def from_mapping(cls, value: Any) -> MappingConfig:
        mapping = _mapping(value, "mapping")
        mode_value = str(mapping.get("mode", "latent_diff"))
        if mode_value not in {"none", "edit_features", "latent_diff", "combined"}:
            raise ValueError(f"Unknown mapping mode: {mode_value}")
        return cls(
            mode=cast(MappingMode, mode_value),
            hidden_dim=int(mapping.get("hidden_dim", 64)),
            dropout=float(mapping.get("dropout", 0.05)),
        )


@dataclass(frozen=True)
class ModelConfig:
    """Configuration surface for the production RxnResid architecture."""

    variant: Literal["rxnresid"] = "rxnresid"
    hidden_dim: int = 192
    baseline_graph_contribution: bool = True
    baseline_identity_factors: bool = True
    baseline_product_group_correction: bool = True
    component_hash_buckets: int = 4096
    component_roles: tuple[str, ...] = ("ene", "diene")
    baseline_factor_rank: int = 48
    route_id_count: int = 8
    route_embedding_dim: int = 8
    share_path_delta_encoder: bool = False
    substrate_encoder: EncoderConfig = field(default_factory=EncoderConfig)
    path_encoder: EncoderConfig = field(default_factory=EncoderConfig)
    product_encoder: EncoderConfig = field(default_factory=EncoderConfig)
    mapping: MappingConfig = field(default_factory=MappingConfig)
    baseline_head: HeadConfig = field(default_factory=HeadConfig)
    residual_head: HeadConfig = field(default_factory=HeadConfig)

    @classmethod
    def from_mapping(cls, value: Any) -> ModelConfig:
        mapping = _mapping(value, "model")
        variant = str(mapping.get("variant", "rxnresid"))
        if variant == "rxnresid_v5":
            variant = "rxnresid"
        if variant != "rxnresid":
            raise ValueError("model.variant must be 'rxnresid'")
        hidden_dim = int(mapping.get("hidden_dim", 192))
        if hidden_dim < 1:
            raise ValueError("model.hidden_dim must be positive")
        component_hash_buckets = int(mapping.get("component_hash_buckets", 4096))
        if component_hash_buckets < 2:
            raise ValueError("model.component_hash_buckets must be at least two")
        baseline_factor_rank = int(mapping.get("baseline_factor_rank", 48))
        if baseline_factor_rank < 1:
            raise ValueError("model.baseline_factor_rank must be positive")
        route_id_count = int(mapping.get("route_id_count", 8))
        if route_id_count < 1:
            raise ValueError("model.route_id_count must be positive")
        route_embedding_dim = int(mapping.get("route_embedding_dim", 8))
        if route_embedding_dim < 1:
            raise ValueError("model.route_embedding_dim must be positive")
        component_roles = mapping.get("component_roles", ["ene", "diene"])
        if not isinstance(component_roles, (list, tuple)) or not component_roles:
            raise ValueError("model.component_roles must be a non-empty sequence")
        component_roles = tuple(str(role).strip() for role in component_roles)
        if any(not role for role in component_roles):
            raise ValueError("model.component_roles must not contain empty roles")
        if len(set(component_roles)) != len(component_roles):
            raise ValueError("model.component_roles must be unique")
        return cls(
            variant=cast(Literal["rxnresid"], variant),
            hidden_dim=hidden_dim,
            baseline_graph_contribution=bool(mapping.get("baseline_graph_contribution", True)),
            baseline_identity_factors=bool(mapping.get("baseline_identity_factors", True)),
            baseline_product_group_correction=bool(
                mapping.get("baseline_product_group_correction", True)
            ),
            component_hash_buckets=component_hash_buckets,
            component_roles=component_roles,
            baseline_factor_rank=baseline_factor_rank,
            route_id_count=route_id_count,
            route_embedding_dim=route_embedding_dim,
            share_path_delta_encoder=bool(mapping.get("share_path_delta_encoder", False)),
            substrate_encoder=_encoder_config(mapping.get("substrate_encoder")),
            path_encoder=_encoder_config(mapping.get("path_encoder"), default_pooling="sum"),
            product_encoder=_encoder_config(mapping.get("product_encoder")),
            mapping=MappingConfig.from_mapping(mapping.get("mapping")),
            baseline_head=_head_config(mapping.get("baseline_head")),
            residual_head=_head_config(mapping.get("residual_head")),
        )


@dataclass(frozen=True)
class LossConfig:
    absolute: float = 1.0
    baseline: float = 0.35
    residual: float = 0.2
    pairwise: float = 0.0
    center_residual: bool = False
    baseline_group_balanced: bool = True
    residual_group_balanced: bool = False
    residual_multi_path_only: bool = False
    baseline_auxiliary_unblended: bool = False
    huber_beta: float = 1.0
    baseline_huber_beta: float | None = None
    residual_huber_beta: float | None = None

    @classmethod
    def from_mapping(cls, value: Any) -> LossConfig:
        mapping = _mapping(value, "loss")
        config = cls(
            absolute=float(mapping.get("absolute", 1.0)),
            baseline=float(mapping.get("baseline", 0.35)),
            residual=float(mapping.get("residual", 0.2)),
            pairwise=float(mapping.get("pairwise", 0.0)),
            center_residual=bool(mapping.get("center_residual", False)),
            baseline_group_balanced=bool(mapping.get("baseline_group_balanced", True)),
            residual_group_balanced=bool(mapping.get("residual_group_balanced", False)),
            residual_multi_path_only=bool(mapping.get("residual_multi_path_only", False)),
            baseline_auxiliary_unblended=bool(mapping.get("baseline_auxiliary_unblended", False)),
            huber_beta=float(mapping.get("huber_beta", 1.0)),
            baseline_huber_beta=(
                float(mapping["baseline_huber_beta"])
                if mapping.get("baseline_huber_beta") is not None
                else None
            ),
            residual_huber_beta=(
                float(mapping["residual_huber_beta"])
                if mapping.get("residual_huber_beta") is not None
                else None
            ),
        )
        if min(config.absolute, config.baseline, config.residual, config.pairwise) < 0.0:
            raise ValueError("loss weights must be non-negative")
        if config.huber_beta <= 0.0:
            raise ValueError("loss.huber_beta must be positive")
        if config.baseline_huber_beta is not None and config.baseline_huber_beta <= 0.0:
            raise ValueError("loss.baseline_huber_beta must be positive when provided")
        if config.residual_huber_beta is not None and config.residual_huber_beta <= 0.0:
            raise ValueError("loss.residual_huber_beta must be positive when provided")
        return config


@dataclass(frozen=True)
class SchedulerConfig:
    name: Literal["linear_warmup_cosine"] = "linear_warmup_cosine"
    warmup_ratio: float = 0.05
    min_lr_ratio: float = 0.0

    @classmethod
    def from_mapping(cls, value: Any) -> SchedulerConfig:
        mapping = _mapping(value, "scheduler")
        name = str(mapping.get("name", "linear_warmup_cosine"))
        if name != "linear_warmup_cosine":
            raise ValueError("training.scheduler.name must be linear_warmup_cosine")
        warmup_ratio = float(mapping.get("warmup_ratio", 0.05))
        min_lr_ratio = float(mapping.get("min_lr_ratio", 0.0))
        if not 0.0 <= warmup_ratio < 1.0:
            raise ValueError("training.scheduler.warmup_ratio must be in [0, 1)")
        if not 0.0 <= min_lr_ratio <= 1.0:
            raise ValueError("training.scheduler.min_lr_ratio must be in [0, 1]")
        return cls(
            name=cast(Literal["linear_warmup_cosine"], name),
            warmup_ratio=warmup_ratio,
            min_lr_ratio=min_lr_ratio,
        )


@dataclass(frozen=True)
class EarlyStoppingConfig:
    enabled: bool = True
    monitor: str = "mae"
    mode: Literal["min", "max"] = "min"
    min_epochs: int = 300
    patience: int = 200
    min_delta: float = 0.0

    @classmethod
    def from_mapping(cls, value: Any) -> EarlyStoppingConfig:
        mapping = _mapping(value, "early_stopping")
        monitor = str(mapping.get("monitor", "mae"))
        mode = str(mapping.get("mode", "min"))
        min_epochs = int(mapping.get("min_epochs", 300))
        patience = int(mapping.get("patience", 200))
        min_delta = float(mapping.get("min_delta", 0.0))
        if not monitor:
            raise ValueError("training.early_stopping.monitor must not be empty")
        if mode not in {"min", "max"}:
            raise ValueError("training.early_stopping.mode must be min or max")
        if min_epochs < 0:
            raise ValueError("training.early_stopping.min_epochs must be non-negative")
        if patience < 1:
            raise ValueError("training.early_stopping.patience must be at least one")
        if min_delta < 0.0:
            raise ValueError("training.early_stopping.min_delta must be non-negative")
        return cls(
            enabled=bool(mapping.get("enabled", True)),
            monitor=monitor,
            mode=cast(Literal["min", "max"], mode),
            min_epochs=min_epochs,
            patience=patience,
            min_delta=min_delta,
        )


@dataclass(frozen=True)
class TrainingConfig:
    batch_size_paths: int = 512
    epochs: int = 1000
    learning_rate: float = 5e-4
    component_learning_rate: float | None = 1e-3
    weight_decay: float = 2e-4
    fused_optimizer: bool = True
    seed: int = 42
    device: str = "auto"
    mixed_precision: str = "no"
    gradient_accumulation_steps: int = 1
    split_batches: bool = False
    group_complete_batches: bool = True
    target_scaling: bool = True
    residual_target_scaling: bool = False
    residual_statistics_multi_path_only: bool = False
    baseline_pretrain_epochs: int = 0
    residual_pretrain_epochs: int = 0
    freeze_baseline_after_pretrain: bool = False
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    early_stopping: EarlyStoppingConfig = field(default_factory=EarlyStoppingConfig)

    @classmethod
    def from_mapping(cls, value: Any) -> TrainingConfig:
        mapping = _mapping(value, "training")
        device = str(mapping.get("device", "auto"))
        mixed_precision = str(mapping.get("mixed_precision", "no"))
        if device not in {"auto", "cpu"}:
            raise ValueError("training.device must be 'auto' or 'cpu'")
        if mixed_precision not in {"no", "fp16", "bf16"}:
            raise ValueError("training.mixed_precision must be no, fp16, or bf16")
        component_learning_rate = mapping.get("component_learning_rate", 1e-3)
        config = cls(
            batch_size_paths=int(
                mapping.get("batch_size_paths", mapping.get("batch_size_groups", 512))
            ),
            epochs=int(mapping.get("epochs", 1000)),
            learning_rate=float(mapping.get("learning_rate", 5e-4)),
            component_learning_rate=(
                float(component_learning_rate) if component_learning_rate is not None else None
            ),
            weight_decay=float(mapping.get("weight_decay", 2e-4)),
            fused_optimizer=bool(mapping.get("fused_optimizer", True)),
            seed=int(mapping.get("seed", 42)),
            device=device,
            mixed_precision=mixed_precision,
            gradient_accumulation_steps=int(mapping.get("gradient_accumulation_steps", 1)),
            split_batches=bool(mapping.get("split_batches", False)),
            group_complete_batches=bool(mapping.get("group_complete_batches", True)),
            target_scaling=bool(mapping.get("target_scaling", True)),
            residual_target_scaling=bool(mapping.get("residual_target_scaling", False)),
            residual_statistics_multi_path_only=bool(
                mapping.get("residual_statistics_multi_path_only", False)
            ),
            baseline_pretrain_epochs=int(mapping.get("baseline_pretrain_epochs", 0)),
            residual_pretrain_epochs=int(mapping.get("residual_pretrain_epochs", 0)),
            freeze_baseline_after_pretrain=bool(
                mapping.get("freeze_baseline_after_pretrain", False)
            ),
            scheduler=SchedulerConfig.from_mapping(mapping.get("scheduler")),
            early_stopping=EarlyStoppingConfig.from_mapping(mapping.get("early_stopping")),
        )
        if config.batch_size_paths < 1:
            raise ValueError("training.batch_size_paths must be at least one")
        if config.epochs < 1:
            raise ValueError("training.epochs must be at least one")
        if config.learning_rate <= 0.0:
            raise ValueError("training.learning_rate must be positive")
        if config.component_learning_rate is not None and config.component_learning_rate <= 0.0:
            raise ValueError("training.component_learning_rate must be positive")
        if config.weight_decay < 0.0:
            raise ValueError("training.weight_decay must be non-negative")
        if config.gradient_accumulation_steps < 1:
            raise ValueError("training.gradient_accumulation_steps must be at least one")
        if config.baseline_pretrain_epochs < 0 or config.residual_pretrain_epochs < 0:
            raise ValueError("pretrain epochs must be non-negative")
        if config.baseline_pretrain_epochs + config.residual_pretrain_epochs >= config.epochs:
            raise ValueError("pretrain epochs must leave at least one joint-training epoch")
        if config.group_complete_batches and config.split_batches:
            raise ValueError(
                "training.group_complete_batches requires training.split_batches=false"
            )
        return config


@dataclass(frozen=True)
class ProjectConfig:
    data: DataConfig = field(default_factory=DataConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    loss: LossConfig = field(default_factory=LossConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)

    @classmethod
    def from_mapping(cls, value: Any) -> ProjectConfig:
        mapping = _mapping(value, "project")
        config = cls(
            data=DataConfig.from_mapping(mapping.get("data")),
            model=ModelConfig.from_mapping(mapping.get("model")),
            loss=LossConfig.from_mapping(mapping.get("loss")),
            training=TrainingConfig.from_mapping(mapping.get("training")),
        )
        if not config.training.group_complete_batches:
            raise ValueError(
                "RxnResid route centering requires training.group_complete_batches=true"
            )
        if config.data.baseline_reduction != "mean":
            raise ValueError("RxnResid requires data.baseline_reduction=mean")
        if len(config.data.component_id_columns) != len(config.model.component_roles):
            raise ValueError(
                "data.component_id_columns and model.component_roles must have the same length"
            )
        return config

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_project_config(path: str | Path) -> ProjectConfig:
    with Path(path).open(encoding="utf-8") as handle:
        return ProjectConfig.from_mapping(yaml.safe_load(handle))


@dataclass(frozen=True)
class SplitSizes:
    train: int
    valid: int
    test: int


@dataclass(frozen=True)
class DistributedRun:
    world_size: int
    backend: str


@dataclass(frozen=True)
class ResolvedScheduler:
    name: str
    warmup_ratio: float
    min_lr_ratio: float
    total_steps: int
    warmup_steps: int

    @classmethod
    def from_mapping(cls, value: Any) -> ResolvedScheduler:
        mapping = _mapping(value, "scheduler")
        return cls(
            name=str(mapping.get("name", "linear_warmup_cosine")),
            warmup_ratio=float(mapping.get("warmup_ratio", 0.1)),
            min_lr_ratio=float(mapping.get("min_lr_ratio", 0.0)),
            total_steps=int(mapping.get("total_steps", 0)),
            warmup_steps=int(mapping.get("warmup_steps", 0)),
        )


@dataclass(frozen=True)
class ResolvedRunConfig:
    model_variant: str
    mapping_mode: str
    hidden_dim: int
    substrate_encoder: str
    product_encoder: str
    epochs: int
    batch_size_paths: int
    gradient_accumulation_steps: int
    split_batches: bool
    mixed_precision: str
    seed: int
    huber_beta: float
    split_groups: SplitSizes
    distributed: DistributedRun
    split_paths: SplitSizes = field(default_factory=lambda: SplitSizes(0, 0, 0))
    group_complete_batches: bool = False
    center_residual: bool = False
    freeze_baseline_after_pretrain: bool = False
    pairwise_loss_weight: float = 0.0
    scheduler: ResolvedScheduler = field(
        default_factory=lambda: ResolvedScheduler(
            name="linear_warmup_cosine",
            warmup_ratio=0.1,
            min_lr_ratio=0.0,
            total_steps=0,
            warmup_steps=0,
        )
    )
    early_stopping: EarlyStoppingConfig = field(default_factory=EarlyStoppingConfig)
    split_strategy: str = "group_kfold"
    num_folds: int = 1
    fold_index: int = 0
    group_encoder: str = "gine"
    path_encoder: str = "gine"

    @classmethod
    def from_mapping(cls, value: Any) -> ResolvedRunConfig:
        mapping = _mapping(value, "resolved_run")
        split = _mapping(mapping.get("split_groups"), "split_groups")
        split_paths = _mapping(mapping.get("split_paths"), "split_paths")
        distributed = _mapping(mapping.get("distributed"), "distributed")
        return cls(
            model_variant=(
                "rxnresid"
                if str(mapping["model_variant"]) == "rxnresid_v5"
                else str(mapping["model_variant"])
            ),
            mapping_mode=str(mapping["mapping_mode"]),
            hidden_dim=int(mapping["hidden_dim"]),
            group_encoder=str(
                mapping.get("group_encoder", mapping.get("substrate_encoder", "gine"))
            ),
            path_encoder=str(mapping.get("path_encoder", mapping.get("product_encoder", "gine"))),
            substrate_encoder=str(mapping["substrate_encoder"]),
            product_encoder=str(mapping["product_encoder"]),
            epochs=int(mapping["epochs"]),
            batch_size_paths=int(
                mapping.get("batch_size_paths", mapping.get("batch_size_groups", 32))
            ),
            gradient_accumulation_steps=int(mapping.get("gradient_accumulation_steps", 1)),
            split_batches=bool(mapping.get("split_batches", True)),
            mixed_precision=str(mapping.get("mixed_precision", "no")),
            seed=int(mapping["seed"]),
            huber_beta=float(mapping["huber_beta"]),
            split_groups=SplitSizes(
                train=int(split["train"]),
                valid=int(split["valid"]),
                test=int(split["test"]),
            ),
            distributed=DistributedRun(
                world_size=int(distributed.get("world_size", 1)),
                backend=str(distributed.get("backend", "NO")),
            ),
            split_paths=SplitSizes(
                train=int(split_paths.get("train", 0)),
                valid=int(split_paths.get("valid", 0)),
                test=int(split_paths.get("test", 0)),
            ),
            group_complete_batches=bool(mapping.get("group_complete_batches", False)),
            center_residual=bool(mapping.get("center_residual", False)),
            freeze_baseline_after_pretrain=bool(
                mapping.get("freeze_baseline_after_pretrain", False)
            ),
            pairwise_loss_weight=float(mapping.get("pairwise_loss_weight", 0.0)),
            scheduler=ResolvedScheduler.from_mapping(mapping.get("scheduler")),
            early_stopping=EarlyStoppingConfig.from_mapping(mapping.get("early_stopping")),
            split_strategy=str(mapping.get("split_strategy", "group_kfold")),
            num_folds=int(mapping.get("num_folds", 1)),
            fold_index=int(mapping.get("fold_index", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
