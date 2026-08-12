"""Composable local GINE and edge-aware GATv2 graph encoder."""

from __future__ import annotations

import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GATv2Conv, GINEConv

from rxnresid.data.featurizer import ATOM_FEATURE_DIM, EDGE_FEATURE_DIM
from rxnresid.data.protocols import PyGBatchStub
from rxnresid.models.encoders.base import EncoderOutput, MolecularEncoder
from rxnresid.models.encoders.pooling import pool_nodes


class GINEGATv2Encoder(MolecularEncoder):
    """Propagate local edit chemistry before selecting interactions with attention."""

    def __init__(
        self,
        hidden_dim: int = 256,
        num_layers: int = 4,
        gine_layers: int = 2,
        dropout: float = 0.1,
        pooling: str = "sum",
        heads: int = 4,
        train_eps: bool = True,
        residual: bool = True,
        atom_dim: int = ATOM_FEATURE_DIM,
        edge_dim: int = EDGE_FEATURE_DIM,
    ) -> None:
        super().__init__(output_dim=hidden_dim)
        if num_layers < 2:
            raise ValueError("gine_gatv2 requires at least two layers")
        if not 1 <= gine_layers < num_layers:
            raise ValueError("gine_layers must be between one and num_layers - 1")
        if heads < 1:
            raise ValueError("heads must be positive")
        self.pooling = pooling
        self.residual = residual
        self.input = nn.Linear(atom_dim, hidden_dim)
        self.gine_convs = nn.ModuleList()
        self.gine_norms = nn.ModuleList()
        for _ in range(gine_layers):
            update = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim),
                nn.SiLU(),
                nn.Linear(hidden_dim, hidden_dim),
            )
            self.gine_convs.append(GINEConv(update, train_eps=train_eps, edge_dim=edge_dim))
            self.gine_norms.append(nn.LayerNorm(hidden_dim))
        self.gat_convs = nn.ModuleList(
            GATv2Conv(
                hidden_dim,
                hidden_dim,
                heads=heads,
                concat=False,
                dropout=dropout,
                edge_dim=edge_dim,
            )
            for _ in range(num_layers - gine_layers)
        )
        self.gat_norms = nn.ModuleList(
            nn.LayerNorm(hidden_dim) for _ in range(num_layers - gine_layers)
        )
        self.dropout = nn.Dropout(dropout)

    def forward(self, batch: PyGBatchStub) -> EncoderOutput:
        hidden = F.silu(self.input(batch.x))
        for conv, norm in zip(self.gine_convs, self.gine_norms, strict=True):
            update = self.dropout(F.silu(norm(conv(hidden, batch.edge_index, batch.edge_attr))))
            hidden = hidden + update if self.residual else update
        for conv, norm in zip(self.gat_convs, self.gat_norms, strict=True):
            update = self.dropout(F.silu(norm(conv(hidden, batch.edge_index, batch.edge_attr))))
            hidden = hidden + update if self.residual else update
        return EncoderOutput(
            graph=pool_nodes(hidden, batch.batch, self.pooling),
            node=hidden,
        )


__all__ = ["GINEGATv2Encoder"]
