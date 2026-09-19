import os
import subprocess
import sys
from pathlib import Path


def test_deterministic_seed_repeats_random_streams_and_graph_training() -> None:
    project_root = Path(__file__).resolve().parents[1]
    source_root = project_root / "src"
    child_environment = os.environ.copy()
    child_environment.pop("CUBLAS_WORKSPACE_CONFIG", None)
    child_environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(source_root), child_environment.get("PYTHONPATH", "")))
    )
    child_script = """
import os
import random

import numpy as np
import torch
from torch_geometric.data import Batch, Data

from rxnresid.data.featurizer import ATOM_FEATURE_DIM, EDGE_FEATURE_DIM
from rxnresid.models.encoders.gine_gatv2 import GINEGATv2Encoder
from rxnresid.utils.reproducibility import set_deterministic_seed


def run_random_streams():
    set_deterministic_seed(1731)
    python_value = random.random()
    numpy_value = float(np.random.random())
    torch_value = torch.rand(5)
    return python_value, numpy_value, torch_value


def run_graph_training(device):
    set_deterministic_seed(1731)
    edge_index = torch.tensor(
        [[0, 0, 0, 1, 1, 2, 2, 3, 3], [1, 2, 3, 0, 2, 0, 3, 0, 2]],
        dtype=torch.long,
    )
    graph = Data(
        x=torch.rand(4, ATOM_FEATURE_DIM),
        edge_index=edge_index,
        edge_attr=torch.rand(edge_index.shape[1], EDGE_FEATURE_DIM),
    )
    batch = Batch.from_data_list([graph]).to(device)
    model = GINEGATv2Encoder(
        hidden_dim=8, num_layers=2, gine_layers=1, heads=2, dropout=0.4
    ).to(device)
    model.train()
    output = model(batch).graph
    output.square().sum().backward()
    return (
        {name: value.detach().cpu().clone() for name, value in model.state_dict().items()},
        {
            name: parameter.grad.detach().cpu().clone()
            for name, parameter in model.named_parameters()
            if parameter.grad is not None
        },
        output.detach().cpu().clone(),
    )


first_random = run_random_streams()
second_random = run_random_streams()
assert first_random[0] == second_random[0]
assert first_random[1] == second_random[1]
assert torch.equal(first_random[2], second_random[2])

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
first_graph = run_graph_training(device)
second_graph = run_graph_training(device)
for first, second in zip(first_graph, second_graph, strict=True):
    if isinstance(first, dict):
        assert first.keys() == second.keys()
        assert all(torch.equal(first[key], second[key]) for key in first)
    else:
        assert torch.equal(first, second)

assert torch.are_deterministic_algorithms_enabled()
assert torch.backends.cudnn.deterministic
assert not torch.backends.cudnn.benchmark
assert not torch.backends.cudnn.allow_tf32
assert not torch.backends.cuda.matmul.allow_tf32
assert os.environ["CUBLAS_WORKSPACE_CONFIG"] == ":4096:8"
"""
    result = subprocess.run(
        [sys.executable, "-c", child_script],
        cwd=project_root,
        env=child_environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
