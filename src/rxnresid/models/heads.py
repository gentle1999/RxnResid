"""Baseline and residual regression heads."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import torch.nn as nn
from torch import Tensor


@dataclass(frozen=True)
class HeadConfig:
    hidden_dims: tuple[int, ...] = (256, 64)


class MLPHead(nn.Module):
    def __init__(self, input_dim: int, hidden_dims: Sequence[int] = (256, 64)) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        current = input_dim
        for hidden_dim in hidden_dims:
            layers.extend((nn.Linear(current, hidden_dim), nn.SiLU()))
            current = hidden_dim
        layers.append(nn.Linear(current, 1))
        self.network = nn.Sequential(*layers)

    def forward(self, inputs: Tensor) -> Tensor:
        return self.network(inputs)
