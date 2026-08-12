from scripts.install_pyg_accelerators import (
    TorchBuild,
    _available_packages_from_page,
    _cuda_tag,
    _install_command,
    _torch_wheel_version,
)


def test_pyg_wheel_version_and_cuda_tag_are_normalized() -> None:
    assert _torch_wheel_version("2.13.0+cu130") == "2.13.0"
    assert _cuda_tag("12.4") == "cu124"


def test_pyg_install_command_is_binary_only_and_version_scoped(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("scripts.install_pyg_accelerators.shutil.which", lambda _: "/usr/bin/uv")
    build = TorchBuild(
        torch_version="2.13.0+cu130",
        torch_wheel_version="2.13.0",
        cuda_version="13.0",
        cuda_tag="cu130",
        wheel_url="https://data.pyg.org/whl/torch-2.13.0+cu130.html",
    )

    command = _install_command(build, ["torch_scatter"])

    assert command == [
        "/usr/bin/uv",
        "pip",
        "install",
        "--python",
        command[4],
        "--no-index",
        "--find-links",
        build.wheel_url,
        "--only-binary=:all:",
        "--upgrade",
        "torch_scatter",
    ]


def test_available_packages_are_selected_from_wheel_page() -> None:
    page = """
    <a href="torch-2.13.0%2Bcu130/pyg_lib-0.8.0%2Bpt213cu130-cp310-abi3-manylinux_x86_64.whl">
    pyg_lib</a>
    <a href="torch-2.13.0%2Bcu130/torch_sparse-2.0.0-cp311-cp311-manylinux_x86_64.whl">
    torch_sparse</a>
    """

    assert _available_packages_from_page(page, ["pyg_lib", "torch_scatter", "torch_sparse"]) == [
        "pyg_lib",
        "torch_sparse",
    ]
