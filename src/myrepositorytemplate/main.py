from __future__ import annotations

import argparse
from collections.abc import Sequence

from myrepositorytemplate import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="myrepositorytemplate")
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the package version and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    print("Hello from myrepositorytemplate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
