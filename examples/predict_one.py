"""Print one RxnResid prediction and its native uncertainty decomposition."""

from __future__ import annotations

import argparse

from rxnresid.inference import predict_one


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--reaction", required=True, help="Atom-mapped reaction SMILES")
    parser.add_argument("--route-id", type=int, default=0)
    parser.add_argument("--path-id", default="reaction-0")
    parser.add_argument(
        "--condition",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Configured condition column; may be supplied more than once.",
    )
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()

    conditions: dict[str, str] = {}
    for item in args.condition:
        name, separator, value = item.partition("=")
        if not separator or not name.strip() or not value.strip():
            parser.error(f"--condition must have the form NAME=VALUE, got {item!r}")
        conditions[name.strip()] = value.strip()

    record = predict_one(
        args.checkpoint,
        args.reaction,
        route_id=args.route_id,
        path_id=args.path_id,
        conditions=conditions,
        device="cpu" if args.cpu else "auto",
    )
    print(f"prediction: {record.prediction:.6f}")
    print(f"aleatoric_variance: {record.aleatoric_variance:.6f}")
    print(f"epistemic_variance: {record.epistemic_variance:.6f}")
    print(f"predictive_variance: {record.predictive_variance:.6f}")
    print(f"aleatoric_std: {record.aleatoric_std:.6f}")
    print(f"epistemic_std: {record.epistemic_std:.6f}")
    print(f"predictive_std: {record.predictive_std:.6f}")
    print(f"95% interval: [{record.lower_95:.6f}, {record.upper_95:.6f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
