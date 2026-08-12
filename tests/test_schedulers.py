import pytest
import torch

from rxnresid.config import SchedulerConfig
from rxnresid.training.schedulers import build_scheduler


def test_linear_warmup_then_cosine_decay() -> None:
    parameter = torch.nn.Parameter(torch.tensor(1.0))
    optimizer = torch.optim.SGD([parameter], lr=1.0)
    scheduler, plan = build_scheduler(
        optimizer,
        SchedulerConfig(warmup_ratio=0.2, min_lr_ratio=0.1),
        total_steps=10,
    )

    learning_rates = []
    for _ in range(plan.total_steps):
        learning_rates.append(optimizer.param_groups[0]["lr"])
        optimizer.step()
        scheduler.step()

    assert plan.warmup_steps == 2
    assert learning_rates[:3] == pytest.approx([0.0, 0.5, 1.0])
    assert all(
        left >= right for left, right in zip(learning_rates[2:], learning_rates[3:], strict=False)
    )
    assert optimizer.param_groups[0]["lr"] == pytest.approx(0.1)
