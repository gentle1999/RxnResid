"""Edge-aware graph attention encoder backed by PyG GATv2Conv."""

from __future__ import annotations

import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GATv2Conv

from rxnresid.data.featurizer import ATOM_FEATURE_DIM, EDGE_FEATURE_DIM
from rxnresid.data.protocols import PyGBatchStub
from rxnresid.models.encoders.base import EncoderOutput, MolecularEncoder
from rxnresid.models.encoders.pooling import pool_nodes


class GATv2Encoder(MolecularEncoder):
    """Multi-head attention over atoms and reaction-aware edge features."""

    def __init__(
        self,
        hidden_dim: int = 256,
        num_layers: int = 4,
        dropout: float = 0.1,
        pooling: str = "sum",
        heads: int = 4,
        share_weights: bool = False,
        residual: bool = True,
        atom_dim: int = ATOM_FEATURE_DIM,
        edge_dim: int = EDGE_FEATURE_DIM,
    ) -> None:
        super().__init__(output_dim=hidden_dim)
        if num_layers < 1:
            raise ValueError("num_layers must be positive")
        if heads < 1:
            raise ValueError("heads must be positive")
        self.pooling = pooling
        self.residual = residual
        self.input = nn.Linear(atom_dim, hidden_dim)
        self.convs = nn.ModuleList(
            GATv2Conv(
                hidden_dim,
                hidden_dim,
                heads=heads,
                concat=False,
                dropout=dropout,
                edge_dim=edge_dim,
                share_weights=share_weights,
            )
            for _ in range(num_layers)
        )
        self.norms = nn.ModuleList(nn.LayerNorm(hidden_dim) for _ in range(num_layers))
        self.dropout = nn.Dropout(dropout)

    def forward(self, batch: PyGBatchStub) -> EncoderOutput:
        hidden = F.silu(self.input(batch.x))
        for conv, norm in zip(self.convs, self.norms, strict=True):
            update = self.dropout(F.silu(norm(conv(hidden, batch.edge_index, batch.edge_attr))))
            hidden = hidden + update if self.residual else update
        graph = pool_nodes(hidden, batch.batch, self.pooling)
        return EncoderOutput(graph=graph, node=hidden)


__all__ = ["GATv2Encoder"]
