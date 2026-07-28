#!/usr/bin/env python3
"""Block likely private Gate 4 files before they enter Git history."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gate4_privacy import REPO_ROOT, scan_repository_paths  # noqa: E402


def staged_paths(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return [
        Path(value.decode("utf-8"))
        for value in result.stdout.split(b"\0")
        if value
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan staged or selected files for likely private portfolio data."
    )
    parser.add_argument("--staged", action="store_true", help="Scan staged Git files.")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    if not args.staged and not args.paths:
        parser.error("Use --staged or provide one or more paths.")

    try:
        paths = staged_paths(REPO_ROOT) if args.staged else args.paths
    except (OSError, subprocess.CalledProcessError):
        print("Gate 4 privacy scan could not inspect the staged file list.")
        return 2

    violations = scan_repository_paths(paths, repo_root=REPO_ROOT)
    if violations:
        print("Gate 4 privacy scan blocked the commit.")
        for violation in violations:
            print(f"- {violation['path']}: {violation['rule']}")
        print("Move private inputs and outputs to ~/investment_private and unstage them.")
        return 1
    print(f"Gate 4 privacy scan passed ({len(paths)} files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
