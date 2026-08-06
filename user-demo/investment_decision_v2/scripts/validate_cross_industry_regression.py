#!/usr/bin/env python3
"""Validate the supplemental Phase B regression governance matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regression_governance import (
    MATRIX_PATH,
    REPO_ROOT,
    TAXONOMY_PATH,
    build_governance_report,
    load_json,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=MATRIX_PATH)
    parser.add_argument("--taxonomy", type=Path, default=TAXONOMY_PATH)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    report = build_governance_report(
        load_json(args.matrix),
        load_json(args.taxonomy),
        REPO_ROOT,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
