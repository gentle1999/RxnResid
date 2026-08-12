"""Directed bond message passing for reaction change graphs."""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor

from rxnresid.data.featurizer import ATOM_FEATURE_DIM, EDGE_FEATURE_DIM
from rxnresid.data.protocols import PyGBatchStub
from rxnresid.models.encoders.base import EncoderOutput, MolecularEncoder
from rxnresid.models.encoders.pooling import pool_nodes
from rxnresid.utils.scatter import scatter_sum


class DMPNNEncoder(MolecularEncoder):
    """Chemprop-style non-backtracking directed bond message passing."""

    def __init__(
        self,
        hidden_dim: int = 256,
        num_layers: int = 4,
        dropout: float = 0.1,
        pooling: str = "sum",
        center_global_weight: float = 0.1,
        atom_dim: int = ATOM_FEATURE_DIM,
        edge_dim: int = EDGE_FEATURE_DIM,
    ) -> None:
        super().__init__(output_dim=hidden_dim)
        if num_layers < 1:
            raise ValueError("num_layers must be positive")
        if center_global_weight < 0.0:
            raise ValueError("center_global_weight must be non-negative")
        self.pooling = pooling
        self.center_global_weight = center_global_weight
        self.edge_input = nn.Linear(atom_dim + edge_dim, hidden_dim)
        self.message_layers = nn.ModuleList(
            nn.Linear(hidden_dim, hidden_dim, bias=False) for _ in range(num_layers - 1)
        )
        self.atom_output = nn.Linear(atom_dim + hidden_dim, hidden_dim)
        self.atom_norm = nn.LayerNorm(hidden_dim)
        self.dropout = nn.Dropout(dropout)

    @staticmethod
    def _reverse_edge_index(edge_index: Tensor) -> Tensor:
        edge_count = edge_index.shape[1]
        if edge_count % 2:
            raise ValueError("DMPNN requires paired directed edges")
        reverse = torch.arange(edge_count, device=edge_index.device) ^ 1
        if edge_count and not torch.equal(edge_index[:, reverse], edge_index.flip(0)):
            raise ValueError("Directed edge pairs must be adjacent and reversed")
        return reverse

    def forward(self, batch: PyGBatchStub) -> EncoderOutput:
        source, target = batch.edge_index
        if source.numel():
            reverse = self._reverse_edge_index(batch.edge_index)
            initial = F.silu(self.edge_input(torch.cat((batch.x[source], batch.edge_attr), dim=-1)))
            message = initial
            for layer in self.message_layers:
                incoming = scatter_sum(message, target, dim_size=batch.num_nodes)
                non_backtracking = incoming[source] - message[reverse]
                message = self.dropout(F.silu(initial + layer(non_backtracking)))
            atom_message = scatter_sum(message, target, dim_size=batch.num_nodes)
        else:
            atom_message = batch.x.new_zeros((batch.num_nodes, self.output_dim))
        node = self.dropout(
            F.silu(self.atom_norm(self.atom_output(torch.cat((batch.x, atom_message), dim=-1))))
        )
        if self.pooling == "center_sum":
            atom_support = batch.x[:, -1].clamp(0.0, 1.0)
            edge_support = scatter_sum(
                batch.edge_attr[:, -1], target, dim_size=batch.num_nodes
            ).clamp(0.0, 1.0)
            center_weight = self.center_global_weight + torch.maximum(atom_support, edge_support)
            graph = scatter_sum(
                node * center_weight.unsqueeze(-1),
                batch.batch,
            )
        else:
            graph = pool_nodes(node, batch.batch, self.pooling)
        return EncoderOutput(graph=graph, node=node)


__all__ = ["DMPNNEncoder"]
