#!/usr/bin/env python3
"""Package the latest completed Heat Street run for review."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.utils.run_review_bundle import (
    BUNDLE_FILENAME,
    create_run_review_bundle,
    find_latest_run,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a complete ZIP review bundle for a Heat Street run."
    )
    parser.add_argument("--runs-dir", type=Path, default=Path("data/runs"))
    parser.add_argument("--run-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--allow-failed-qa", action="store_true")
    parser.add_argument("--required-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_root = args.run_root or find_latest_run(args.runs_dir)
    bundle = create_run_review_bundle(
        run_root,
        output_path=args.output,
        require_passing_qa=not args.allow_failed_qa,
        include_optional=not args.required_only,
    )
    print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
