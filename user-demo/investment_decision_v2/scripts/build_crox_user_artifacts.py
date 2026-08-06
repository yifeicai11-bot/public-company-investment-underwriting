#!/usr/bin/env python3
"""CROX regression wrapper for the shared public-company pipeline.

CROX is a fixture, not a rule source. All facts, calculations, conclusions,
and rendering behavior live in the shared data, analysis, and rendering
components. This wrapper contains no CROX financial values or conclusions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[3]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_public_company_investment_layer import DEFAULT_OUT_ROOT, build_investment_layer  # noqa: E402
from render_public_company_artifacts import DEFAULT_OUT_ROOT as DELIVERY_ROOT  # noqa: E402
from render_public_company_artifacts import render  # noqa: E402


def build(*, research_input: Path | None = None, pdf: bool = False) -> dict[str, object]:
    step3_dir = build_investment_layer("CROX", DEFAULT_OUT_ROOT, research_input)
    contract = step3_dir / "underwriting_output_contract.json"
    delivery = DELIVERY_ROOT / "crox"
    return render(contract, delivery, pdf=pdf)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CROX regression wrapper through the shared underwriting pipeline.")
    parser.add_argument("--research-input", help="Optional analyst-owned research input JSON.")
    parser.add_argument("--pdf", action="store_true", help="Print user-ready PDFs when formal rendering is allowed.")
    args = parser.parse_args()
    manifest = build(
        research_input=Path(args.research_input) if args.research_input else None,
        pdf=args.pdf,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
