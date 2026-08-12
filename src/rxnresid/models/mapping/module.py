"""Mode-selectable optional mapping module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import torch
import torch.nn as nn
from torch import Tensor

from rxnresid.data.collate import MappingBatch
from rxnresid.data.reaction_parser import EDIT_FEATURE_NAMES
from rxnresid.models.mapping.edit_features import EditFeatureEncoder
from rxnresid.models.mapping.latent_diff import LatentDifferenceEncoder


MappingMode = Literal["none", "edit_features", "latent_diff", "combined"]


@dataclass(frozen=True)
class MappingOutput:
    embedding: Tensor | None
    present: Tensor


class MappingModule(nn.Module):
    """Keep the upper architecture identical across mapping ablations."""

    def __init__(
        self,
        mode: MappingMode = "none",
        encoder_dim: int = 256,
        hidden_dim: int = 64,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if mode not in {"none", "edit_features", "latent_diff", "combined"}:
            raise ValueError(f"Unknown mapping mode: {mode}")
        self.mode = mode
        self.dropout = dropout
        self.output_dim = hidden_dim if mode != "none" else 0
        if mode in {"edit_features", "combined"}:
            self.edit = EditFeatureEncoder(len(EDIT_FEATURE_NAMES), hidden_dim)
        if mode in {"latent_diff", "combined"}:
            self.latent = LatentDifferenceEncoder(encoder_dim, hidden_dim)
        if mode == "combined":
            self.combine = nn.Sequential(
                nn.Linear(hidden_dim * 2, hidden_dim),
                nn.SiLU(),
                nn.Linear(hidden_dim, hidden_dim),
            )

    def forward(
        self,
        mapping: MappingBatch,
        substrate_node: Tensor,
        product_node: Tensor,
        num_paths: int,
    ) -> MappingOutput:
        present = mapping.mapping_present
        if self.mode == "none":
            return MappingOutput(embedding=None, present=present)
        if self.training and self.dropout:
            keep = (torch.rand_like(present) >= self.dropout).to(present.dtype)
        else:
            keep = torch.ones_like(present)
        effective_present = present * keep
        embeddings: list[Tensor] = []
        if self.mode in {"edit_features", "combined"}:
            embeddings.append(self.edit(mapping.edit_features))
        if self.mode in {"latent_diff", "combined"}:
            substrate = substrate_node[mapping.mapped_substrate_node]
            product = product_node[mapping.mapped_product_node]
            embeddings.append(
                self.latent(
                    substrate,
                    product,
                    mapping.mapping_to_path,
                    num_paths,
                )
            )
        embedding = (
            embeddings[0] if len(embeddings) == 1 else self.combine(torch.cat(embeddings, dim=-1))
        )
        embedding = embedding * effective_present.unsqueeze(-1)
        return MappingOutput(embedding=embedding, present=effective_present)
