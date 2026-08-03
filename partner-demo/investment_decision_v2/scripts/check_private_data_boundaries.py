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


def tracked_paths(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
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
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--staged", action="store_true", help="Scan staged Git files.")
    selection.add_argument("--tracked", action="store_true", help="Scan every Git-tracked file (CI mode).")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    if not args.staged and not args.tracked and not args.paths:
        parser.error("Use --staged, --tracked, or provide one or more paths.")
    if (args.staged or args.tracked) and args.paths:
        parser.error("Do not combine --staged or --tracked with explicit paths.")

    try:
        if args.staged:
            paths = staged_paths(REPO_ROOT)
        elif args.tracked:
            paths = tracked_paths(REPO_ROOT)
        else:
            paths = args.paths
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
