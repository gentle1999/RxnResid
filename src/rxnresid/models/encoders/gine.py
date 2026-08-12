"""A compact GINE encoder with separate graph and node outputs."""

from __future__ import annotations

import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GINEConv

from rxnresid.data.featurizer import ATOM_FEATURE_DIM, EDGE_FEATURE_DIM
from rxnresid.data.protocols import PyGBatchStub
from rxnresid.models.encoders.base import EncoderOutput, MolecularEncoder
from rxnresid.models.encoders.pooling import pool_nodes


class GINEEncoder(MolecularEncoder):
    """GINE encoder whose parameters remain independent for each RxnResid graph role."""

    def __init__(
        self,
        hidden_dim: int = 256,
        num_layers: int = 4,
        dropout: float = 0.1,
        pooling: str = "mean",
        train_eps: bool = True,
        residual: bool = False,
        atom_dim: int = ATOM_FEATURE_DIM,
        edge_dim: int = EDGE_FEATURE_DIM,
    ) -> None:
        super().__init__(output_dim=hidden_dim)
        if num_layers < 1:
            raise ValueError("num_layers must be positive")
        self.pooling = pooling
        self.residual = residual
        self.input = nn.Linear(atom_dim, hidden_dim)
        self.convs = nn.ModuleList()
        self.norms = nn.ModuleList()
        self.dropout = nn.Dropout(dropout)
        for _ in range(num_layers):
            update = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim),
                nn.SiLU(),
                nn.Linear(hidden_dim, hidden_dim),
            )
            self.convs.append(GINEConv(update, train_eps=train_eps, edge_dim=edge_dim))
            self.norms.append(nn.LayerNorm(hidden_dim))

    def forward(self, batch: PyGBatchStub) -> EncoderOutput:
        hidden = F.silu(self.input(batch.x))
        for conv, norm in zip(self.convs, self.norms, strict=True):
            update = self.dropout(F.silu(norm(conv(hidden, batch.edge_index, batch.edge_attr))))
            hidden = hidden + update if self.residual else update
        graph = pool_nodes(hidden, batch.batch, self.pooling)
        return EncoderOutput(graph=graph, node=hidden)
