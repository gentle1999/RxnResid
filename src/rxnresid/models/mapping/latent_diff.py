"""Reaction-center latent differences from substrate/product node states."""

from __future__ import annotations

import torch.nn as nn
from torch import Tensor

from rxnresid.utils.scatter import scatter_mean


class LatentDifferenceEncoder(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int = 64) -> None:
        super().__init__()
        self.projection = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.SiLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )

    def forward(
        self,
        substrate_nodes: Tensor,
        product_nodes: Tensor,
        mapping_to_path: Tensor,
        num_paths: int,
    ) -> Tensor:
        if mapping_to_path.numel() == 0:
            pooled = substrate_nodes.new_zeros((num_paths, substrate_nodes.shape[-1]))
        else:
            differences = product_nodes - substrate_nodes
            pooled = scatter_mean(differences, mapping_to_path, dim_size=num_paths)
        return self.projection(pooled)
