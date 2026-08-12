"""Graph pooling selected independently from the message-passing backend."""

from __future__ import annotations

from torch import Tensor
from torch_geometric.nn import global_add_pool, global_max_pool, global_mean_pool


def pool_nodes(hidden: Tensor, batch_index: Tensor, pooling: str) -> Tensor:
    if pooling == "mean":
        return global_mean_pool(hidden, batch_index)
    if pooling == "sum":
        return global_add_pool(hidden, batch_index)
    if pooling == "max":
        return global_max_pool(hidden, batch_index)
    raise ValueError(f"Unknown graph pooling mode: {pooling}")
