"""Additional molecular encoders backed by native PyG convolution layers."""

from __future__ import annotations

import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor
from torch_geometric.nn import GCNConv, GENConv, GINConv, TransformerConv

from rxnresid.data.featurizer import ATOM_FEATURE_DIM, EDGE_FEATURE_DIM
from rxnresid.data.protocols import PyGBatchStub
from rxnresid.models.encoders.base import EncoderOutput, MolecularEncoder
from rxnresid.models.encoders.pooling import pool_nodes


class _ResidualPyGEncoder(MolecularEncoder):
    """Shared projection, normalization, residual, and pooling contract."""

    def __init__(
        self,
        hidden_dim: int,
        num_layers: int,
        dropout: float,
        pooling: str,
        residual: bool,
        atom_dim: int,
    ) -> None:
        super().__init__(output_dim=hidden_dim)
        if num_layers < 1:
            raise ValueError("num_layers must be positive")
        self.pooling = pooling
        self.residual = residual
        self.input = nn.Linear(atom_dim, hidden_dim)
        self.norms = nn.ModuleList(nn.LayerNorm(hidden_dim) for _ in range(num_layers))
        self.dropout = nn.Dropout(dropout)

    def _update(self, layer_index: int, hidden: Tensor, batch: PyGBatchStub) -> Tensor:
        raise NotImplementedError

    def forward(self, batch: PyGBatchStub) -> EncoderOutput:
        hidden = F.silu(self.input(batch.x))
        for index, norm in enumerate(self.norms):
            update = self.dropout(F.silu(norm(self._update(index, hidden, batch))))
            hidden = hidden + update if self.residual else update
        return EncoderOutput(
            graph=pool_nodes(hidden, batch.batch, self.pooling),
            node=hidden,
        )


class GCNEncoder(_ResidualPyGEncoder):
    """PyG GCNConv stack for node-feature-only molecular baselines."""

    def __init__(
        self,
        hidden_dim: int = 256,
        num_layers: int = 4,
        dropout: float = 0.1,
        pooling: str = "mean",
        improved: bool = False,
        normalize: bool = True,
        residual: bool = True,
        atom_dim: int = ATOM_FEATURE_DIM,
    ) -> None:
        super().__init__(hidden_dim, num_layers, dropout, pooling, residual, atom_dim)
        self.convs = nn.ModuleList(
            GCNConv(hidden_dim, hidden_dim, improved=improved, normalize=normalize)
            for _ in range(num_layers)
        )

    def _update(self, layer_index: int, hidden: Tensor, batch: PyGBatchStub) -> Tensor:
        return self.convs[layer_index](hidden, batch.edge_index)


class GINEncoder(_ResidualPyGEncoder):
    """PyG GINConv stack when bond features are intentionally excluded."""

    def __init__(
        self,
        hidden_dim: int = 256,
        num_layers: int = 4,
        dropout: float = 0.1,
        pooling: str = "mean",
        train_eps: bool = True,
        residual: bool = True,
        atom_dim: int = ATOM_FEATURE_DIM,
    ) -> None:
        super().__init__(hidden_dim, num_layers, dropout, pooling, residual, atom_dim)
        self.convs = nn.ModuleList(
            GINConv(
                nn.Sequential(
                    nn.Linear(hidden_dim, hidden_dim),
                    nn.SiLU(),
                    nn.Linear(hidden_dim, hidden_dim),
                ),
                train_eps=train_eps,
            )
            for _ in range(num_layers)
        )

    def _update(self, layer_index: int, hidden: Tensor, batch: PyGBatchStub) -> Tensor:
        return self.convs[layer_index](hidden, batch.edge_index)


class TransformerEncoder(_ResidualPyGEncoder):
    """Edge-aware PyG TransformerConv molecular encoder."""

    def __init__(
        self,
        hidden_dim: int = 256,
        num_layers: int = 4,
        dropout: float = 0.1,
        pooling: str = "mean",
        heads: int = 4,
        beta: bool = True,
        root_weight: bool = True,
        residual: bool = True,
        atom_dim: int = ATOM_FEATURE_DIM,
        edge_dim: int = EDGE_FEATURE_DIM,
    ) -> None:
        if heads < 1:
            raise ValueError("heads must be positive")
        super().__init__(hidden_dim, num_layers, dropout, pooling, residual, atom_dim)
        self.heads = heads
        self.convs = nn.ModuleList(
            TransformerConv(
                hidden_dim,
                hidden_dim,
                heads=heads,
                concat=False,
                beta=beta,
                dropout=dropout,
                edge_dim=edge_dim,
                root_weight=root_weight,
            )
            for _ in range(num_layers)
        )

    def _update(self, layer_index: int, hidden: Tensor, batch: PyGBatchStub) -> Tensor:
        return self.convs[layer_index](hidden, batch.edge_index, batch.edge_attr)


class GENEncoder(_ResidualPyGEncoder):
    """Edge-aware PyG GENConv stack with learnable softmax aggregation."""

    def __init__(
        self,
        hidden_dim: int = 256,
        num_layers: int = 4,
        dropout: float = 0.1,
        pooling: str = "mean",
        aggregation: str = "softmax",
        learn_t: bool = True,
        message_norm: bool = True,
        learn_message_scale: bool = True,
        residual: bool = True,
        atom_dim: int = ATOM_FEATURE_DIM,
        edge_dim: int = EDGE_FEATURE_DIM,
    ) -> None:
        super().__init__(hidden_dim, num_layers, dropout, pooling, residual, atom_dim)
        self.convs = nn.ModuleList(
            GENConv(
                hidden_dim,
                hidden_dim,
                aggr=aggregation,
                learn_t=learn_t,
                msg_norm=message_norm,
                learn_msg_scale=learn_message_scale,
                norm="layer",
                edge_dim=edge_dim,
            )
            for _ in range(num_layers)
        )

    def _update(self, layer_index: int, hidden: Tensor, batch: PyGBatchStub) -> Tensor:
        return self.convs[layer_index](hidden, batch.edge_index, batch.edge_attr)


__all__ = ["GCNEncoder", "GENEncoder", "GINEncoder", "TransformerEncoder"]
