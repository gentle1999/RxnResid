"""Encoder contracts and configuration shared by molecular graph backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import torch.nn as nn
from torch import Tensor

from rxnresid.data.protocols import PyGBatchStub


@dataclass(frozen=True)
class EncoderOutput:
    graph: Tensor
    node: Tensor


@dataclass(frozen=True)
class EncoderConfig:
    """Backend-independent encoder configuration."""

    type: str = "gine"
    num_layers: int = 4
    dropout: float = 0.1
    pooling: str = "mean"
    options: dict[str, Any] = field(default_factory=dict)


class MolecularEncoder(nn.Module, ABC):
    """Common graph encoder interface required by all model variants."""

    def __init__(self, output_dim: int) -> None:
        super().__init__()
        self.output_dim = output_dim

    @abstractmethod
    def forward(self, batch: PyGBatchStub) -> EncoderOutput:
        """Encode a PyG batch into graph-level and node-level states."""
