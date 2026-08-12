"""GraphGPS-style local message passing with global self-attention."""

from __future__ import annotations

import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GINEConv, GPSConv

from rxnresid.data.featurizer import ATOM_FEATURE_DIM, EDGE_FEATURE_DIM
from rxnresid.data.protocols import PyGBatchStub
from rxnresid.models.encoders.base import EncoderOutput, MolecularEncoder
from rxnresid.models.encoders.pooling import pool_nodes


class GPSEncoder(MolecularEncoder):
    """Combine edge-aware GINE updates with graph-wide node attention."""

    def __init__(
        self,
        hidden_dim: int = 256,
        num_layers: int = 4,
        dropout: float = 0.1,
        pooling: str = "mean",
        heads: int = 4,
        train_eps: bool = True,
        atom_dim: int = ATOM_FEATURE_DIM,
        edge_dim: int = EDGE_FEATURE_DIM,
    ) -> None:
        super().__init__(output_dim=hidden_dim)
        if num_layers < 1:
            raise ValueError("num_layers must be positive")
        if heads < 1 or hidden_dim % heads:
            raise ValueError("GPS heads must be positive and divide hidden_dim")
        self.pooling = pooling
        self.heads = heads
        self.input = nn.Linear(atom_dim, hidden_dim)
        self.layers = nn.ModuleList()
        for _ in range(num_layers):
            update = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim),
                nn.SiLU(),
                nn.Linear(hidden_dim, hidden_dim),
            )
            local_conv = GINEConv(update, train_eps=train_eps, edge_dim=edge_dim)
            self.layers.append(
                GPSConv(
                    hidden_dim,
                    local_conv,
                    heads=heads,
                    dropout=dropout,
                    act="silu",
                    norm="layer_norm",
                )
            )

    def forward(self, batch: PyGBatchStub) -> EncoderOutput:
        hidden = F.silu(self.input(batch.x))
        for layer in self.layers:
            hidden = layer(
                hidden,
                batch.edge_index,
                batch=batch.batch,
                edge_attr=batch.edge_attr,
            )
        graph = pool_nodes(hidden, batch.batch, self.pooling)
        return EncoderOutput(graph=graph, node=hidden)


__all__ = ["GPSEncoder"]
