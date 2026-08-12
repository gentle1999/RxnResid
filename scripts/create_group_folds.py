#!/usr/bin/env python3
"""Create a versioned group-level cross-validation split manifest."""

from __future__ import annotations

import argparse
import json

from rxnresid.config import load_project_config
from rxnresid.data.dataset import ReactionGroupDataset
from rxnresid.data.split import create_group_kfold_manifest, save_split_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        default=None,
        help="Override data.path from the project configuration",
    )
    parser.add_argument("--config", default="configs/rxnresid.yaml")
    parser.add_argument("--output", default="data/splits/group_10fold_seed42.json")
    parser.add_argument("--num-folds", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_project_config(args.config)
    data_path = args.data or config.data.path
    dataset = ReactionGroupDataset(
        data_path,
        target_column=config.data.target_column,
        reaction_column=config.data.reaction_column,
        condition_columns=config.data.condition_columns,
        route_id_column=config.data.route_id_column,
        baseline_reduction=config.data.baseline_reduction,
        component_hash_buckets=config.model.component_hash_buckets,
        cache_dir=config.data.cache_dir if config.data.cache_enabled else None,
    )
    manifest = create_group_kfold_manifest(
        dataset,
        num_folds=args.num_folds,
        seed=args.seed,
    )
    save_split_manifest(manifest, args.output)
    print(
        json.dumps(
            {
                "output": args.output,
                "groups": manifest.dataset_group_count,
                "num_folds": manifest.num_folds,
                "seed": manifest.seed,
                "fingerprint": manifest.dataset_fingerprint,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
