#!/usr/bin/env python3
"""Upgrade an audited underwriting contract to the shared Friday V1 schema.

This migration preserves the existing financial, market, source, period, and
evidence values. It applies only shared output semantics and validation rules.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_public_company_investment_layer import apply_friday_v1_contract_semantics
from underwriting_contract import finalize_output_contract


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def upgrade(contract_path: Path, research_input_path: Path, out_dir: Path) -> Path:
    contract = read_json(contract_path)
    research_input = read_json(research_input_path)
    upgraded = apply_friday_v1_contract_semantics(contract, research_input)
    upgraded = finalize_output_contract(upgraded)

    out_dir.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(upgraded, indent=2, ensure_ascii=False, default=str)
    for name in ("underwriting_output_contract.json", "step3_data.json", "investment_layer.json"):
        (out_dir / name).write_text(serialized, encoding="utf-8")
    return out_dir / "underwriting_output_contract.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upgrade an audited public-company contract to Friday V1 without refetching data."
    )
    parser.add_argument("contract", help="Existing audited underwriting_output_contract.json")
    parser.add_argument("research_input", help="Company research-input JSON")
    parser.add_argument("--out-dir", required=True, help="Destination Step 3 directory")
    args = parser.parse_args()
    output = upgrade(Path(args.contract), Path(args.research_input), Path(args.out_dir))
    payload = read_json(output)
    print(
        json.dumps(
            {
                "output": str(output),
                "schema_version": payload.get("schema_version"),
                "report_id": payload.get("report_id"),
                "contract_validation": payload.get("contract_validation", {}).get("status"),
                "data_gate": payload.get("data_gate", {}).get("level"),
                "hard_stops": len(payload.get("hard_stops", [])),
                "warnings": len(payload.get("warnings", [])),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
