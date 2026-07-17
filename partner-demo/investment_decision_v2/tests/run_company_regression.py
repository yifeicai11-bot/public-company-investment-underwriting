#!/usr/bin/env python3
"""Run network-backed regression and unseen-company forward tests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = TEST_DIR.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_public_company_investment_layer import build_investment_layer  # noqa: E402
from render_public_company_artifacts import render  # noqa: E402


REGRESSION_COMPANIES = ["CROX", "AAPL", "PFGC"]
BLIND_FORWARD_COMPANY = "ADBE"


def assert_contract(contract: dict[str, object], ticker: str) -> list[str]:
    errors: list[str] = []
    if contract.get("contract_validation", {}).get("status") != "PASS":
        errors.append("contract validation failed")
    if contract.get("supported_universe", {}).get("status") != "SUPPORTED_CORE":
        errors.append("issuer unexpectedly outside supported core")
    if contract.get("hard_stops"):
        errors.append(f"active hard stops: {len(contract.get('hard_stops', []))}")
    if contract.get("probability_weighted_return") is not None:
        errors.append("public-only expected return was not suppressed")
    if contract.get("target_price") is not None:
        errors.append("public-only target price was not suppressed")
    if contract.get("position_sizing") is not None:
        errors.append("public-only position sizing was not suppressed")

    records = contract.get("evidence_records", [])
    evidence_ids = {row.get("evidence_id") for row in records}
    if None in evidence_ids or len(evidence_ids) != len(records):
        errors.append("evidence IDs are missing or duplicated")
    for row in records:
        if row.get("evidence_class") == "CALC" and (not row.get("formula") or not row.get("input_evidence_ids")):
            errors.append(f"calculation lineage missing for {row.get('metric_name')}")
        if row.get("period_type") in {"quarter", "derived-quarter"}:
            duration = row.get("duration_days")
            if isinstance(duration, int) and duration > 130:
                errors.append(f"YTD mislabeled as quarter: {row.get('metric_name')} {duration} days")
        for input_id in row.get("input_evidence_ids", []):
            if input_id not in evidence_ids:
                errors.append(f"unknown calculation input {input_id}")

    opportunity = contract.get("opportunity_cost", {})
    if opportunity.get("status") == "PASS":
        if not opportunity.get("start_date") or not opportunity.get("end_date"):
            errors.append("aligned return dates missing")
        if opportunity.get("return_basis") != "adjusted close on exact common trading dates":
            errors.append("return basis is not exact-date adjusted close")

    price_date = contract.get("report_dates", {}).get("market_price_date")
    share_date = contract.get("report_dates", {}).get("share_count_date")
    if price_date and share_date and share_date > price_date:
        errors.append("share count date is after price date")

    return [f"{ticker}: {error}" for error in errors]


def run(out_root: Path) -> dict[str, object]:
    results: list[dict[str, object]] = []
    all_errors: list[str] = []
    companies = REGRESSION_COMPANIES + [BLIND_FORWARD_COMPANY]
    for ticker in companies:
        step3_dir = build_investment_layer(ticker, out_root)
        contract_path = step3_dir / "underwriting_output_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        errors = assert_contract(contract, ticker)
        all_errors.extend(errors)
        render_dir = out_root.parent / "regression_render" / ticker.lower()
        manifest = render(contract_path, render_dir)
        if manifest.get("formal_report_blocked"):
            all_errors.append(f"{ticker}: formal rendering unexpectedly blocked")
        results.append(
            {
                "ticker": ticker,
                "test_type": "forward_blind" if ticker == BLIND_FORWARD_COMPANY else "regression",
                "report_id": contract.get("report_id"),
                "data_gate": contract.get("data_gate"),
                "decision_confidence": contract.get("decision_confidence"),
                "evidence_count": len(contract.get("evidence_records", [])),
                "warning_count": len(contract.get("warnings", [])),
                "errors": errors,
                "render_manifest": manifest,
            }
        )
    return {
        "status": "PASS" if not all_errors else "FAIL",
        "regression_companies": REGRESSION_COMPANIES,
        "blind_forward_company": BLIND_FORWARD_COMPANY,
        "results": results,
        "errors": all_errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report = run(Path(args.out_root))
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
