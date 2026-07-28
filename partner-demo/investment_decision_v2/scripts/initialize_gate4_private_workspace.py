#!/usr/bin/env python3
"""Initialize an empty Gate 4 workspace outside Git."""

from __future__ import annotations

import argparse
from pathlib import Path

from gate4_privacy import (
    DEFAULT_PRIVATE_ROOT,
    PrivacyBoundaryError,
    initialize_private_workspace,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an empty, local-only Gate 4 workspace with secure permissions."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PRIVATE_ROOT,
        help="Local directory outside every Git worktree (default: ~/investment_private).",
    )
    args = parser.parse_args()
    try:
        result = initialize_private_workspace(args.root)
    except PrivacyBoundaryError:
        print("status=GATE_4_PRIVATE_WORKSPACE_BLOCKED")
        print("detail=Use an empty local directory outside every Git worktree.")
        return 2

    print(f"status={result['status']}")
    print(f"workspace={args.root.expanduser()}")
    print("private_values_written=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
