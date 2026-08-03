#!/usr/bin/env python3
"""Build the public synthetic S14 delivery without exposing private data."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gate4_reports import render_synthetic_delivery  # noqa: E402
from run_gate4_assessment import run_gate4_assessment  # noqa: E402


INVESTMENT_ROOT = SCRIPT_DIR.parent
REPO_ROOT = SCRIPT_DIR.parents[2]
SYNTHETIC_SOURCE = INVESTMENT_ROOT / "gate4" / "synthetic_examples"
DEFAULT_GATE3 = (
    INVESTMENT_ROOT
    / "friday_v1_outputs"
    / "crox_crocs_inc"
    / "step3"
    / "underwriting_output_contract.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "examples" / "gate4-synthetic"


def build_synthetic_demo(
    *,
    gate3_target: Path = DEFAULT_GATE3,
    output_dir: Path = DEFAULT_OUTPUT,
    pdf: bool = True,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="gate4-s14-synthetic-") as temporary:
        workspace = Path(temporary) / "synthetic_workspace"
        shutil.copytree(SYNTHETIC_SOURCE, workspace)
        manifest_path = workspace / "synthetic_gate4_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["private_output_dir"] = "private_outputs"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        contract, _ = run_gate4_assessment(gate3_target, manifest_path)
        if contract.get("contract_validation", {}).get("status") != "PASS":
            raise RuntimeError("The synthetic S14 contract failed validation.")
        return render_synthetic_delivery(contract, output_dir, pdf=pdf)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the bilingual public synthetic S14 report package."
    )
    parser.add_argument("--gate3", type=Path, default=DEFAULT_GATE3)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-pdf", action="store_true")
    args = parser.parse_args()
    try:
        result = build_synthetic_demo(
            gate3_target=args.gate3,
            output_dir=args.output_dir,
            pdf=not args.no_pdf,
        )
    except Exception:
        print("status=GATE_4_SYNTHETIC_DEMO_FAILED")
        return 2
    print("status=GATE_4_SYNTHETIC_DEMO_READY")
    print(f"system_assessment_hash={result.get('assessment_hash')}")
    print("data_classification=SYNTHETIC_PUBLIC_EXAMPLE")
    print("automatic_trade_execution=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
