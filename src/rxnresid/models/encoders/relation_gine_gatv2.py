"""Covalent GINE followed by attention over all reaction relations."""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor
from torch_geometric.nn import GATv2Conv, GINEConv

from rxnresid.data.featurizer import ATOM_FEATURE_DIM, EDGE_FEATURE_DIM
from rxnresid.data.protocols import PyGBatchStub
from rxnresid.models.encoders.base import EncoderOutput, MolecularEncoder
from rxnresid.models.encoders.pooling import pool_nodes


def covalent_edge_view(edge_index: Tensor, edge_attr: Tensor) -> tuple[Tensor, Tensor]:
    """Select substrate covalent edges and hide product/change channels from GINE."""
    if edge_attr.shape[0] == 0:
        return edge_index, edge_attr
    substrate_width = min(EDGE_FEATURE_DIM, edge_attr.shape[1])
    selected = edge_attr[:, :substrate_width].abs().sum(dim=-1) > 0.0
    covalent_attr = torch.zeros_like(edge_attr[selected])
    covalent_attr[:, :substrate_width] = edge_attr[selected, :substrate_width]
    return edge_index[:, selected], covalent_attr


class RelationGINEGATv2Encoder(MolecularEncoder):
    """Learn local molecules before propagating over possible or exact change edges."""

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
            raise ValueError("relation_gine_gatv2 requires at least two layers")
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
        self.relation_convs = nn.ModuleList(
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
        self.relation_norms = nn.ModuleList(
            nn.LayerNorm(hidden_dim) for _ in range(num_layers - gine_layers)
        )
        self.dropout = nn.Dropout(dropout)

    def forward(self, batch: PyGBatchStub) -> EncoderOutput:
        hidden = F.silu(self.input(batch.x))
        covalent_index, covalent_attr = covalent_edge_view(batch.edge_index, batch.edge_attr)
        for conv, norm in zip(self.gine_convs, self.gine_norms, strict=True):
            update = self.dropout(F.silu(norm(conv(hidden, covalent_index, covalent_attr))))
            hidden = hidden + update if self.residual else update
        for conv, norm in zip(self.relation_convs, self.relation_norms, strict=True):
            update = self.dropout(F.silu(norm(conv(hidden, batch.edge_index, batch.edge_attr))))
            hidden = hidden + update if self.residual else update
        return EncoderOutput(
            graph=pool_nodes(hidden, batch.batch, self.pooling),
            node=hidden,
        )


__all__ = ["RelationGINEGATv2Encoder", "covalent_edge_view"]
