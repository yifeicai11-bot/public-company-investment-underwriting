#!/usr/bin/env python3
"""Adjudicate one preserved S17 held-out run without changing its artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_blind_company_forward_test import (  # noqa: E402
    load_manifest,
    verify_manifest_and_freeze,
    verify_preserved_run,
)
from underwriting_contract import validate_output_contract  # noqa: E402


EXPECTED_MODULES = {
    "business_and_industry",
    "earnings_quality",
    "working_capital_and_cash_conversion",
    "liquidity_sources_and_uses",
    "debt_leases_covenants_refinancing",
    "capital_allocation",
    "management_guidance_and_subsequent_events",
    "stress_test",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def is_iso_date(value: Any) -> bool:
    try:
        date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False
    return True


def contract_boundary_errors(contract: dict[str, Any], run_dir: Path) -> list[str]:
    errors = list(validate_output_contract(contract))
    if contract.get("contract_validation", {}).get("status") != "PASS":
        errors.append("CONTRACT_VALIDATION_NOT_PASS")
    if contract.get("hard_stops"):
        errors.append("HELD_OUT_HARD_STOP_REQUIRES_ADJUDICATION")
    if contract.get("supported_universe", {}).get("status") != "SUPPORTED_CORE":
        errors.append("HELD_OUT_NOT_IN_SUPPORTED_CORE")

    gate = float(contract.get("data_gate", {}).get("level", 0))
    if gate < 1:
        errors.append("HELD_OUT_DID_NOT_REACH_CORE_DATA_GATE")
    if gate < 3:
        if contract.get("target_price") is not None:
            errors.append("TARGET_PRICE_LEAKED_BELOW_GATE3")
        if contract.get("probability_weighted_return") is not None:
            errors.append("EXPECTED_RETURN_LEAKED_BELOW_GATE3")
        for scenario in contract.get("scenarios", []):
            if scenario.get("implied_price") is not None or scenario.get("price_change_vs_current") is not None:
                errors.append("SCENARIO_PRICE_LEAKED_BELOW_GATE3")
                break
        formal_artifacts = [
            path
            for path in run_dir.rglob("*")
            if path.is_file()
            and any(
                token in path.name
                for token in ("One_Page_Summary", "Full_Report", "Evidence_Audit_Appendix")
            )
        ]
        if formal_artifacts:
            errors.append("FORMAL_ARTIFACT_RENDERED_BELOW_GATE3")

    if contract.get("position_sizing") is not None:
        errors.append("POSITION_SIZING_PRESENT_WITHOUT_GATE4")
    if contract.get("portfolio_action") != "Not Evaluated":
        errors.append("PORTFOLIO_ACTION_PRESENT_WITHOUT_GATE4")
    if contract.get("portfolio_context", {}).get("status") != "DISABLED":
        errors.append("PORTFOLIO_CONTEXT_NOT_DISABLED")

    module_keys = set(contract.get("issuer_underwriting", {}).get("modules", {}))
    missing_modules = sorted(EXPECTED_MODULES - module_keys)
    if missing_modules:
        errors.append(f"ISSUER_MODULES_MISSING:{missing_modules}")

    dates = contract.get("report_dates", {})
    for field in (
        "financial_statement_date",
        "market_price_date",
        "share_count_date",
        "subsequent_event_index_review_through",
    ):
        if not is_iso_date(dates.get(field)):
            errors.append(f"REPORT_DATE_INVALID:{field}")

    evidence_ids = [
        str(row.get("evidence_id"))
        for row in contract.get("evidence_records", [])
        if row.get("evidence_id")
    ]
    if not evidence_ids:
        errors.append("EVIDENCE_RECORDS_MISSING")
    if len(evidence_ids) != len(set(evidence_ids)):
        errors.append("DUPLICATE_EVIDENCE_ID")
    if not contract.get("source_registry"):
        errors.append("SOURCE_REGISTRY_MISSING")

    evidence_records = contract.get("evidence_records", [])
    metric_names = {
        str(row.get("metric_name"))
        for row in evidence_records
        if row.get("metric_name")
    }
    if metric_names & {
        "latest_ytd_fcf",
        "latest_annual_fcf",
        "latest_quarter_fcf",
        "derived_latest_quarter_fcf",
    }:
        capex_checks = [
            row
            for row in contract.get("validation_issues", [])
            if row.get("check_id") == "P0-cash-capex-component-coverage"
        ]
        if len(capex_checks) != 1 or capex_checks[0].get("status") != "PASS":
            errors.append("FCF_CAPEX_COMPONENT_COVERAGE_NOT_VALIDATED")
        capex_rows = [
            row
            for row in evidence_records
            if row.get("metric_name")
            in {
                "latest_ytd_capex",
                "latest_annual_capex",
                "latest_quarter_capex",
                "derived_latest_quarter_capex",
            }
        ]
        if not capex_rows:
            errors.append("FCF_CAPEX_PARENT_ROW_MISSING")
        elif any(
            row.get("reported_or_calculated") == "calculated"
            and (not row.get("formula") or not row.get("input_evidence_ids"))
            for row in capex_rows
        ):
            errors.append("FCF_CAPEX_COMPONENT_LINEAGE_MISSING")
        if any(
            "CapitalExpendituresIncurredButNotYetPaid" in str(row.get("source_tag"))
            for row in capex_rows
        ):
            errors.append("NONCASH_CAPEX_USED_IN_CFO_BASED_FCF")
    return sorted(set(errors))


def validate_s17_run(manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = load_manifest(manifest_path)
    errors: list[str] = []
    if manifest.get("session") != "S17" or manifest.get("phase") != "F":
        errors.append("NOT_AN_S17_PHASE_F_MANIFEST")
    try:
        selection_integrity = verify_manifest_and_freeze(manifest)
    except Exception as exc:
        selection_integrity = {"status": "FAIL", "error": type(exc).__name__}
        errors.append("SELECTION_OR_FREEZE_INTEGRITY_FAILED")

    run_dir = manifest_path.parent / manifest.get("first_run_protocol", {}).get(
        "output_directory", "first_run"
    )
    try:
        preserved = verify_preserved_run(run_dir)
    except Exception as exc:
        preserved = {"status": "FAIL", "error": type(exc).__name__}
        errors.append("PRESERVED_RUN_INTEGRITY_FAILED")

    diagnostic_path = run_dir / "first_run_diagnostic.json"
    diagnostic = read_json(diagnostic_path) if diagnostic_path.exists() else {}
    if diagnostic.get("status") != "FIRST_RUN_COMPLETED":
        errors.append("FIRST_RUN_NOT_COMPLETED")
    if diagnostic.get("return_code") not in diagnostic.get("allowed_return_codes", []):
        errors.append("FIRST_RUN_EXIT_CODE_NOT_ALLOWED")
    if diagnostic.get("contract_validation_status") != "PASS":
        errors.append("FIRST_RUN_CONTRACT_NOT_VALIDATED")
    if diagnostic.get("pipeline_status") not in {"RESEARCH_INPUT_REQUIRED", "DELIVERY_READY"}:
        errors.append("UNEXPECTED_UNIFIED_PIPELINE_STATUS")

    contract_relative = diagnostic.get("contract_relative_path")
    contract_path = run_dir / "builder_output" / str(contract_relative or "")
    contract: dict[str, Any] = {}
    if not contract_relative or not contract_path.exists():
        errors.append("HELD_OUT_CONTRACT_MISSING")
    else:
        contract = read_json(contract_path)
        errors.extend(contract_boundary_errors(contract, run_dir))

    return {
        "schema_version": "1.0.0",
        "document_type": "s17_held_out_acceptance_result",
        "status": "S17_HELD_OUT_ACCEPTED" if not errors else "S17_SHARED_FIX_REQUIRED",
        "attempt": manifest.get("attempt"),
        "selected_issuer": manifest.get("selected_issuer"),
        "pre_run_commit": manifest.get("pre_run_commit"),
        "selection_integrity": selection_integrity,
        "preserved_run_integrity": preserved,
        "diagnostic_summary": {
            "return_code": diagnostic.get("return_code"),
            "pipeline_status": diagnostic.get("pipeline_status"),
            "data_gate": diagnostic.get("data_gate"),
            "contract_validation_status": diagnostic.get("contract_validation_status"),
            "hard_stop_count": diagnostic.get("hard_stop_count"),
            "warning_count": diagnostic.get("warning_count"),
        },
        "contract_summary": {
            "report_id": contract.get("report_id"),
            "contract_hash": contract.get("contract_hash"),
            "schema_version": contract.get("schema_version"),
            "data_gate": contract.get("data_gate", {}).get("level"),
            "evidence_records": len(contract.get("evidence_records", [])),
            "source_records": len(contract.get("source_registry", [])),
            "warnings": len(contract.get("warnings", [])),
            "hard_stops": len(contract.get("hard_stops", [])),
        },
        "errors": sorted(set(errors)),
        "requires_second_company_after_fix": bool(errors),
        "automatic_investment_approval": False,
        "automatic_trade_execution": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_s17_run(args.manifest)
    serialized = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if result["status"] == "S17_HELD_OUT_ACCEPTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
