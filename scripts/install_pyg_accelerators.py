#!/usr/bin/env python3
"""Install PyG CUDA extension wheels matched to the active PyTorch build."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import torch


PYG_WHEEL_BASE = "https://data.pyg.org/whl"
DEFAULT_PACKAGES = (
    "pyg_lib",
    "torch_scatter",
    "torch_sparse",
    "torch_cluster",
    "torch_spline_conv",
)
PYG_DISTRIBUTIONS = {
    "pyg_lib": "pyg-lib",
    "torch_scatter": "torch-scatter",
    "torch_sparse": "torch-sparse",
    "torch_cluster": "torch-cluster",
    "torch_spline_conv": "torch-spline-conv",
}


@dataclass(frozen=True)
class TorchBuild:
    """The version tuple used to select a PyG wheel page."""

    torch_version: str
    torch_wheel_version: str
    cuda_version: str
    cuda_tag: str
    wheel_url: str


def _torch_wheel_version(version: str) -> str:
    match = re.match(r"^(\d+\.\d+\.\d+)", version)
    if match is None:
        raise ValueError(f"Cannot parse a PyTorch version: {version!r}")
    return match.group(1)


def _cuda_tag(cuda_version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)", cuda_version)
    if match is None:
        raise ValueError(f"Cannot parse a CUDA version: {cuda_version!r}")
    return f"cu{match.group(1)}{match.group(2)}"


def detect_torch_build() -> TorchBuild:
    """Read PyTorch's compiled CUDA version, rather than the host toolkit."""
    cuda_version = torch.version.cuda
    if cuda_version is None:
        raise RuntimeError(
            "The active PyTorch installation is CPU-only; install a CUDA PyTorch build first."
        )
    torch_version = torch.__version__
    wheel_version = _torch_wheel_version(torch_version)
    cuda_tag = _cuda_tag(cuda_version)
    return TorchBuild(
        torch_version=torch_version,
        torch_wheel_version=wheel_version,
        cuda_version=cuda_version,
        cuda_tag=cuda_tag,
        wheel_url=f"{PYG_WHEEL_BASE}/torch-{wheel_version}+{cuda_tag}.html",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--packages",
        nargs="+",
        choices=DEFAULT_PACKAGES,
        default=list(DEFAULT_PACKAGES),
        help="PyG extension distributions to install.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the matched install command without changing the environment.",
    )
    return parser


def _install_command(build: TorchBuild, packages: list[str]) -> list[str]:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required to install matched PyG wheels")
    return [
        uv,
        "pip",
        "install",
        "--python",
        sys.executable,
        "--no-index",
        "--find-links",
        build.wheel_url,
        "--only-binary=:all:",
        "--upgrade",
        *packages,
    ]


class _WheelLinkParser(HTMLParser):
    """Collect wheel filenames from a PyG simple-index page."""

    def __init__(self) -> None:
        super().__init__()
        self.wheel_names: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href is None:
            return
        filename = unquote(urlparse(href).path).rsplit("/", maxsplit=1)[-1]
        if filename.endswith(".whl"):
            self.wheel_names.append(filename.lower())


def _available_packages_from_page(html: str, packages: list[str]) -> list[str]:
    parser = _WheelLinkParser()
    parser.feed(html)
    wheel_names = set(parser.wheel_names)
    available: list[str] = []
    for package in packages:
        normalized_name = PYG_DISTRIBUTIONS[package].replace("-", "_").lower()
        if any(name.startswith(f"{normalized_name}-") for name in wheel_names):
            available.append(package)
    return available


def _available_packages(build: TorchBuild, packages: list[str]) -> list[str]:
    request = Request(build.wheel_url, headers={"User-Agent": "rxnresid-pyg-installer"})
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8")
    return _available_packages_from_page(html, packages)


def _installed_versions(packages: list[str]) -> dict[str, str | None]:
    return {package: _distribution_version(PYG_DISTRIBUTIONS[package]) for package in packages}


def _distribution_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _verify_imports(packages: list[str]) -> dict[str, Any]:
    missing = [package for package in packages if importlib.util.find_spec(package) is None]
    if missing:
        raise RuntimeError(f"Installed distributions are not importable: {missing}")
    return {
        "modules": dict.fromkeys(packages, True),
        "torch_scatter_enabled_in_pyg": _pyg_torch_scatter_enabled(),
    }


def _pyg_torch_scatter_enabled() -> bool:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from torch_geometric import typing; print(typing.WITH_TORCH_SCATTER)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() == "True"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    build = detect_torch_build()
    packages = list(args.packages)
    available_packages = _available_packages(build, packages)
    unavailable_packages = [package for package in packages if package not in available_packages]
    command = _install_command(build, available_packages)
    report = {
        "torch": asdict(build),
        "cuda_available": bool(torch.cuda.is_available()),
        "requested_packages": packages,
        "available_packages": available_packages,
        "skipped_unavailable": unavailable_packages,
        "installed_before": _installed_versions(packages),
        "command": command,
    }
    if args.dry_run:
        print(json.dumps(report, indent=2))
        return 0

    if not available_packages:
        print(json.dumps(report, indent=2))
        return 2

    subprocess.run(command, check=True)
    report["installed_after"] = _installed_versions(available_packages)
    report["verification"] = _verify_imports(available_packages)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
