#!/usr/bin/env python3
"""Build a fixed equal-weight ensemble from completed fold directories."""

from __future__ import annotations

import argparse
from pathlib import Path

from rxnresid.analysis.ensemble import build_equal_weight_ensemble


def _member(value: str) -> tuple[str, Path]:
    name, separator, root = value.partition("=")
    if not separator or not name or not root:
        raise argparse.ArgumentTypeError("members must use NAME=ROOT")
    return name, Path(root)


def _fold_directory(value: str) -> tuple[str, int, Path]:
    member_fold, separator, directory = value.partition("=")
    member, fold_separator, fold = member_fold.partition(":")
    if not separator or not fold_separator or not member or not fold or not directory:
        raise argparse.ArgumentTypeError("fold directories must use NAME:FOLD=DIR")
    return member, int(fold), Path(directory)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--member", action="append", type=_member, required=True)
    parser.add_argument("--folds", nargs="+", type=int, default=list(range(10)))
    parser.add_argument("--fold-dir", action="append", type=_fold_directory, default=[])
    parser.add_argument("--output", default="runs/ensemble/summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    members = dict(args.member)
    if len(members) != len(args.member):
        raise ValueError("Ensemble member names must be unique")
    fold_directories: dict[str, dict[int, Path]] = {}
    for member, fold_index, directory in args.fold_dir:
        if member not in members:
            raise ValueError(f"Unknown fold-directory member: {member}")
        if fold_index in fold_directories.setdefault(member, {}):
            raise ValueError(f"Duplicate fold-directory override: {member}:{fold_index}")
        fold_directories[member][fold_index] = directory
    result = build_equal_weight_ensemble(
        members,
        tuple(args.folds),
        fold_directories=fold_directories,
    )
    result.write(args.output)
    print(
        f"paths={result.summary['num_paths']} "
        f"path_weighted_mae={result.summary['path_weighted_mae']:.6f} "
        f"fold_mean_mae={result.summary['fold_mean_mae']:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
