"""PyG-first scatter reductions with a pure PyTorch fallback."""

from __future__ import annotations

import importlib
from typing import Any, cast

import torch
from torch import Tensor


try:
    from torch_geometric.utils import scatter as _pyg_scatter
except ImportError:  # pragma: no cover - exercised by monkeypatch in tests.
    _pyg_scatter = None  # type: ignore[assignment]

try:
    _torch_scatter_module = importlib.import_module("torch_scatter")
    _torch_scatter = _torch_scatter_module.scatter
except (ImportError, OSError):  # pragma: no cover - depends on optional CUDA wheels.
    _torch_scatter = None


def _validate_index(index: Tensor) -> Tensor:
    if index.ndim != 1:
        raise ValueError("scatter index must be one-dimensional")
    return index.to(dtype=torch.long)


def _prepare_inputs(
    src: Tensor,
    index: Tensor,
    dim_size: int | None,
) -> tuple[Tensor, Tensor, int]:
    if src.ndim == 0:
        src = src.reshape(1)
    index = _validate_index(index).to(device=src.device)
    if src.shape[0] != index.numel():
        raise ValueError("src and index must have the same first dimension")
    if dim_size is None:
        dim_size = int(index.max().item()) + 1 if index.numel() else 0
    if dim_size < 0:
        raise ValueError("dim_size must be non-negative")
    return src, index, dim_size


def _scatter_sum_fallback(src: Tensor, index: Tensor, dim_size: int) -> Tensor:
    output = src.new_zeros((dim_size, *src.shape[1:]))
    if index.numel():
        output.index_add_(0, index, src)
    return output


def _scatter_mean_fallback(src: Tensor, index: Tensor, dim_size: int) -> Tensor:
    total = _scatter_sum_fallback(src, index, dim_size)
    counts = src.new_zeros(dim_size)
    if index.numel():
        counts.index_add_(0, index, src.new_ones(index.numel()))
    shape = (dim_size,) + (1,) * (src.ndim - 1)
    return total / counts.clamp_min(1).reshape(shape)


def _scatter_extreme_fallback(
    src: Tensor,
    index: Tensor,
    dim_size: int,
    *,
    reduce: str,
) -> Tensor:
    if reduce not in {"amin", "amax"}:
        raise ValueError("extreme scatter reduction must be amin or amax")
    output = src.new_zeros((dim_size, *src.shape[1:]))
    if not index.numel():
        return output
    expanded_index = index.reshape((-1,) + (1,) * (src.ndim - 1)).expand_as(src)
    return output.scatter_reduce(0, expanded_index, src, reduce=reduce, include_self=False)


def _zero_empty_bins(output: Tensor, index: Tensor, dim_size: int) -> Tensor:
    if dim_size == 0:
        return output
    occupied = torch.bincount(index, minlength=dim_size) > 0
    shape = (dim_size,) + (1,) * (output.ndim - 1)
    return torch.where(occupied.reshape(shape), output, torch.zeros_like(output))


def _torch_scatter_reduce(
    src: Tensor,
    index: Tensor,
    dim_size: int,
    *,
    reduce: str,
) -> Tensor:
    if _torch_scatter is None:
        raise RuntimeError("torch_scatter is not available")
    result: Any = _torch_scatter(
        src,
        index,
        dim=0,
        dim_size=dim_size,
        reduce=reduce,
    )
    if reduce in {"min", "max"}:
        result = result[0]
    return cast(Tensor, result)


def scatter_sum(src: Tensor, index: Tensor, dim_size: int | None = None) -> Tensor:
    """Sum rows of ``src`` according to ``index`` along the first dimension."""
    src, index, resolved_size = _prepare_inputs(src, index, dim_size)
    if _pyg_scatter is not None:
        return _pyg_scatter(src, index, dim=0, dim_size=resolved_size, reduce="sum")
    if _torch_scatter is not None:
        return _torch_scatter_reduce(src, index, resolved_size, reduce="sum")
    return _scatter_sum_fallback(src, index, resolved_size)


def scatter_mean(src: Tensor, index: Tensor, dim_size: int | None = None) -> Tensor:
    """Mean rows of ``src`` according to ``index`` along the first dimension."""
    src, index, resolved_size = _prepare_inputs(src, index, dim_size)
    if _pyg_scatter is not None:
        return _pyg_scatter(src, index, dim=0, dim_size=resolved_size, reduce="mean")
    if _torch_scatter is not None:
        return _torch_scatter_reduce(src, index, resolved_size, reduce="mean")
    return _scatter_mean_fallback(src, index, resolved_size)


def scatter_min(src: Tensor, index: Tensor, dim_size: int | None = None) -> Tensor:
    """Take the elementwise minimum per index, returning zeros for empty bins."""
    src, index, resolved_size = _prepare_inputs(src, index, dim_size)
    if _pyg_scatter is not None:
        output = _pyg_scatter(src, index, dim=0, dim_size=resolved_size, reduce="min")
    elif _torch_scatter is not None:
        output = _torch_scatter_reduce(src, index, resolved_size, reduce="min")
    else:
        output = _scatter_extreme_fallback(src, index, resolved_size, reduce="amin")
    return _zero_empty_bins(output, index, resolved_size)


def scatter_max(src: Tensor, index: Tensor, dim_size: int | None = None) -> Tensor:
    """Take the elementwise maximum per index, returning zeros for empty bins."""
    src, index, resolved_size = _prepare_inputs(src, index, dim_size)
    if _pyg_scatter is not None:
        output = _pyg_scatter(src, index, dim=0, dim_size=resolved_size, reduce="max")
    elif _torch_scatter is not None:
        output = _torch_scatter_reduce(src, index, resolved_size, reduce="max")
    else:
        output = _scatter_extreme_fallback(src, index, resolved_size, reduce="amax")
    return _zero_empty_bins(output, index, resolved_size)


__all__ = ["scatter_max", "scatter_mean", "scatter_min", "scatter_sum"]
