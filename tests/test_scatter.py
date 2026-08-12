import importlib

import torch


scatter_module = importlib.import_module("rxnresid.utils.scatter")


def test_scatter_prefers_pyg(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    original = scatter_module._pyg_scatter
    assert original is not None
    reductions: list[str] = []

    def spy(src, index, *, dim, dim_size, reduce):  # type: ignore[no-untyped-def]
        reductions.append(reduce)
        return original(src, index, dim=dim, dim_size=dim_size, reduce=reduce)

    monkeypatch.setattr(scatter_module, "_pyg_scatter", spy)
    source = torch.tensor([1.0, 3.0, 5.0])
    index = torch.tensor([0, 0, 1])
    assert torch.equal(scatter_module.scatter_sum(source, index), torch.tensor([4.0, 5.0]))
    assert torch.equal(scatter_module.scatter_mean(source, index), torch.tensor([2.0, 5.0]))
    assert torch.equal(scatter_module.scatter_min(source, index), torch.tensor([1.0, 5.0]))
    assert torch.equal(scatter_module.scatter_max(source, index), torch.tensor([3.0, 5.0]))
    assert reductions == ["sum", "mean", "min", "max"]


def test_scatter_falls_back_to_index_add(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(scatter_module, "_pyg_scatter", None)
    monkeypatch.setattr(scatter_module, "_torch_scatter", None)
    source = torch.tensor([[1.0, 2.0], [3.0, 4.0], [5.0, 8.0]])
    index = torch.tensor([0, 0, 2])
    expected_sum = torch.tensor([[4.0, 6.0], [0.0, 0.0], [5.0, 8.0]])
    expected_mean = torch.tensor([[2.0, 3.0], [0.0, 0.0], [5.0, 8.0]])
    expected_min = torch.tensor([[1.0, 2.0], [0.0, 0.0], [5.0, 8.0]])
    expected_max = torch.tensor([[3.0, 4.0], [0.0, 0.0], [5.0, 8.0]])
    assert torch.equal(scatter_module.scatter_sum(source, index, dim_size=3), expected_sum)
    assert torch.equal(scatter_module.scatter_mean(source, index, dim_size=3), expected_mean)
    assert torch.equal(scatter_module.scatter_min(source, index, dim_size=3), expected_min)
    assert torch.equal(scatter_module.scatter_max(source, index, dim_size=3), expected_max)


def test_scatter_uses_torch_scatter_after_pyg(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(scatter_module, "_pyg_scatter", None)
    calls: list[str] = []

    def fake_scatter(src, index, *, dim, dim_size, reduce):  # type: ignore[no-untyped-def]
        calls.append(reduce)
        if reduce in {"min", "max"}:
            return scatter_module._scatter_extreme_fallback(
                src,
                index,
                dim_size,
                reduce="a" + reduce,
            ), None
        if reduce == "sum":
            return scatter_module._scatter_sum_fallback(src, index, dim_size)
        return scatter_module._scatter_mean_fallback(src, index, dim_size)

    monkeypatch.setattr(scatter_module, "_torch_scatter", fake_scatter)
    source = torch.tensor([1.0, 3.0, 5.0])
    index = torch.tensor([0, 0, 1])
    assert torch.equal(scatter_module.scatter_sum(source, index), torch.tensor([4.0, 5.0]))
    assert torch.equal(scatter_module.scatter_mean(source, index), torch.tensor([2.0, 5.0]))
    assert torch.equal(scatter_module.scatter_min(source, index), torch.tensor([1.0, 5.0]))
    assert torch.equal(scatter_module.scatter_max(source, index), torch.tensor([3.0, 5.0]))
    assert calls == ["sum", "mean", "min", "max"]


def test_scatter_min_max_preserve_gradients() -> None:
    source = torch.tensor([[1.0, 4.0], [3.0, 2.0], [5.0, 8.0]], requires_grad=True)
    index = torch.tensor([0, 0, 1])
    output = scatter_module.scatter_min(source, index) + scatter_module.scatter_max(source, index)
    output.sum().backward()
    assert source.grad is not None
    assert torch.isfinite(source.grad).all()
