#!/usr/bin/env python3
"""Sanitize one local Gate 4 PDF without printing private paths or values."""

from __future__ import annotations

import argparse
from pathlib import Path

from gate4_privacy import (
    DEFAULT_PRIVATE_ROOT,
    PrivacyBoundaryError,
    sanitize_private_pdf,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove private PDF metadata locally and verify the sanitized output."
    )
    parser.add_argument("source", type=Path, help="Unsanitized PDF inside the private workspace.")
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Sanitized PDF destination inside the private workspace.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PRIVATE_ROOT,
        help="Private workspace root outside every Git worktree.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Fail if the sanitized destination already exists.",
    )
    args = parser.parse_args()
    try:
        result = sanitize_private_pdf(
            args.source,
            args.output,
            workspace_root=args.root,
            overwrite=not args.no_overwrite,
        )
    except (PrivacyBoundaryError, OSError, ValueError):
        print("status=GATE_4_PRIVATE_PDF_BLOCKED")
        print("detail=Review the local PDF boundary and sanitizer requirements.")
        print("private_paths_printed=false")
        return 2

    print(f"status={result['status']}")
    print(f"pages={result['page_count']}")
    print("metadata_sanitized=true")
    print("private_paths_printed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
