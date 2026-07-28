#!/usr/bin/env python3
"""Validate Gate 4 private inputs without printing raw portfolio values."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gate4_private_contract import (
    INPUT_STATUS_VALIDATED,
    load_and_validate_private_inputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a local Gate 4 private-workspace manifest."
    )
    parser.add_argument("manifest", help="Path to the local private workspace manifest.")
    parser.add_argument(
        "--diagnostic-json",
        action="store_true",
        help="Print the privacy-safe diagnostic object; raw input values are never printed.",
    )
    args = parser.parse_args()

    _, diagnostic = load_and_validate_private_inputs(Path(args.manifest))
    if args.diagnostic_json:
        print(json.dumps(diagnostic, indent=2))
    else:
        summary = diagnostic["check_summary"]
        print(f"status={diagnostic['status']}")
        print(f"checks={summary['total']}; failed={summary['failed']}")
        print("raw_values_printed=false")
    raise SystemExit(0 if diagnostic["status"] == INPUT_STATUS_VALIDATED else 2)


if __name__ == "__main__":
    main()
