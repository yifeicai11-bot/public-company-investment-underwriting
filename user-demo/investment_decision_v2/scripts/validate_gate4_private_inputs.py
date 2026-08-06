#!/usr/bin/env python3
"""Validate Gate 4 private inputs without printing raw portfolio values."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gate4_private_contract import (
    INPUT_STATUS_VALIDATED,
    load_and_validate_private_inputs,
    read_mapping,
)
from gate4_privacy import (
    PRIVATE_CLASSIFICATION,
    SYNTHETIC_CLASSIFICATION,
    PrivacyBoundaryError,
    assert_local_workspace,
)


def main() -> int:
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
    manifest_path = Path(args.manifest).expanduser().resolve(strict=False)
    try:
        manifest = read_mapping(manifest_path)
        classification = manifest.get("data_classification")
        if classification == PRIVATE_CLASSIFICATION:
            assert_local_workspace(
                manifest_path.parent,
                data_classification=PRIVATE_CLASSIFICATION,
            )
        elif classification == SYNTHETIC_CLASSIFICATION:
            assert_local_workspace(
                manifest_path.parent,
                data_classification=SYNTHETIC_CLASSIFICATION,
                allow_public_synthetic_read_only=True,
            )
    except PrivacyBoundaryError:
        print("status=GATE_4_PRIVATE_WORKSPACE_BLOCKED")
        print("detail=Move real Gate 4 inputs outside every Git worktree.")
        print("raw_values_printed=false")
        return 2
    except ValueError:
        pass

    _, diagnostic = load_and_validate_private_inputs(manifest_path)
    if args.diagnostic_json:
        print(json.dumps(diagnostic, indent=2))
    else:
        summary = diagnostic["check_summary"]
        print(f"status={diagnostic['status']}")
        print(f"checks={summary['total']}; failed={summary['failed']}")
        print("raw_values_printed=false")
    return 0 if diagnostic["status"] == INPUT_STATUS_VALIDATED else 2


if __name__ == "__main__":
    raise SystemExit(main())
