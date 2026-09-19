"""Seed random generators and enable deterministic PyTorch operations."""

from __future__ import annotations

import os

import torch
from accelerate.utils import set_seed


_SUPPORTED_CUBLAS_WORKSPACE_CONFIGS = {":16:8", ":4096:8"}


def set_deterministic_seed(seed: int) -> None:
    """Seed Python, NumPy, and PyTorch and require deterministic kernels where supported.

    Call this before constructing an Accelerator or performing CUDA work so the
    cuBLAS workspace configuration is in place before CUDA libraries are initialized.
    """
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") not in _SUPPORTED_CUBLAS_WORKSPACE_CONFIGS:
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"

    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cuda.matmul.allow_tf32 = False
    set_seed(seed, deterministic=True)
