"""GraphSAGE molecular encoder as a node-feature-only alternative backend."""

from __future__ import annotations

import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import SAGEConv

from rxnresid.data.featurizer import ATOM_FEATURE_DIM
from rxnresid.data.protocols import PyGBatchStub
from rxnresid.models.encoders.base import EncoderOutput, MolecularEncoder
from rxnresid.models.encoders.pooling import pool_nodes


class GraphSAGEEncoder(MolecularEncoder):
    """GraphSAGE backend retaining the same graph/node output contract."""

    def __init__(
        self,
        hidden_dim: int = 256,
        num_layers: int = 4,
        dropout: float = 0.1,
        pooling: str = "mean",
        aggregation: str = "mean",
        atom_dim: int = ATOM_FEATURE_DIM,
    ) -> None:
        super().__init__(output_dim=hidden_dim)
        if num_layers < 1:
            raise ValueError("num_layers must be positive")
        self.pooling = pooling
        self.input = nn.Linear(atom_dim, hidden_dim)
        self.convs = nn.ModuleList(
            SAGEConv(hidden_dim, hidden_dim, aggr=aggregation) for _ in range(num_layers)
        )
        self.norms = nn.ModuleList(nn.LayerNorm(hidden_dim) for _ in range(num_layers))
        self.dropout = nn.Dropout(dropout)

    def forward(self, batch: PyGBatchStub) -> EncoderOutput:
        hidden = F.silu(self.input(batch.x))
        for conv, norm in zip(self.convs, self.norms, strict=True):
            hidden = self.dropout(F.silu(norm(conv(hidden, batch.edge_index))))
        graph = pool_nodes(hidden, batch.batch, self.pooling)
        return EncoderOutput(graph=graph, node=hidden)
