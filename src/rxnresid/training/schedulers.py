"""Learning-rate scheduler construction for optimizer-step based training."""

from __future__ import annotations

import math
from dataclasses import dataclass

from torch.optim import Optimizer
from torch.optim.lr_scheduler import LambdaLR

from rxnresid.config import SchedulerConfig


@dataclass(frozen=True)
class SchedulerPlan:
    total_steps: int
    warmup_steps: int


def build_scheduler(
    optimizer: Optimizer,
    config: SchedulerConfig,
    total_steps: int,
) -> tuple[LambdaLR, SchedulerPlan]:
    """Build a linear-warmup then cosine-decay schedule."""
    if total_steps < 1:
        raise ValueError("total_steps must be at least one")
    warmup_steps = round(total_steps * config.warmup_ratio)
    if config.warmup_ratio > 0.0:
        warmup_steps = max(1, warmup_steps)

    def lr_factor(current_step: int) -> float:
        if warmup_steps and current_step < warmup_steps:
            return current_step / warmup_steps
        decay_steps = max(1, total_steps - warmup_steps)
        progress = min(1.0, max(0.0, (current_step - warmup_steps) / decay_steps))
        cosine = 0.5 * (1.0 + math.cos(math.pi * progress))
        return config.min_lr_ratio + (1.0 - config.min_lr_ratio) * cosine

    return LambdaLR(optimizer, lr_lambda=lr_factor), SchedulerPlan(
        total_steps=total_steps,
        warmup_steps=warmup_steps,
    )
