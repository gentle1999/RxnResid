"""Static protocols for PyG graph objects used by RxnResid.

PyG stores custom graph attributes dynamically, so its runtime ``Data`` and
``Batch`` classes cannot fully describe the fields consumed by this project.
These structural protocols are typing-only stubs; collate still returns the
native PyG objects.
"""

from __future__ import annotations

from typing import Protocol, Self

import torch
from torch import Tensor


class PyGDataStub(Protocol):
    """Fields present on every RxnResid molecular or change graph."""

    x: Tensor
    edge_index: Tensor
    edge_attr: Tensor
    atom_map_numbers: Tensor
    component_id: Tensor
    component_token_id: Tensor


class PyGBatchStub(PyGDataStub, Protocol):
    """Batched PyG graph fields consumed by encoders and mapping."""

    batch: Tensor
    ptr: Tensor
    num_graphs: int
    num_nodes: int

    def to(self, device: torch.device | str, *, non_blocking: bool = False) -> Self:
        """Move all graph tensors to a device."""
        ...

    def pin_memory(self) -> Self:
        """Pin graph tensors for asynchronous host-to-device copies."""
        ...


__all__ = ["PyGBatchStub", "PyGDataStub"]
