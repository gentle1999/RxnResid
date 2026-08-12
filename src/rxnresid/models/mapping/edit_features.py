"""MLP projection for fixed-size reaction edit features."""

from __future__ import annotations

import torch.nn as nn


class EditFeatureEncoder(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int = 64) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.SiLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.SiLU(),
        )

    def forward(self, features):  # type: ignore[no-untyped-def]
        return self.network(features)
