#!/usr/bin/env python3
"""Run network-backed cases from the cross-industry regression matrix."""

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
from regression_governance import (  # noqa: E402
    MATRIX_PATH,
    REPO_ROOT,
    TAXONOMY_PATH,
    assert_contract_safety,
    build_governance_report,
    classify_contract_outcomes,
    load_json,
)
from render_public_company_artifacts import render  # noqa: E402


def select_active_cases(
    matrix: dict[str, object],
    tickers: set[str] | None,
) -> tuple[list[dict[str, object]], list[str]]:
    active = [
        row
        for row in matrix.get("cases", [])
        if isinstance(row, dict) and row.get("fixture_status") == "ACTIVE"
    ]
    known_tickers = {str(row.get("ticker")) for row in active}
    unknown = sorted((tickers or set()) - known_tickers)
    selected = [
        row
        for row in active
        if tickers is None or row.get("ticker") in tickers
    ]
    return selected, unknown


def run(
    out_root: Path,
    matrix_path: Path = MATRIX_PATH,
    taxonomy_path: Path = TAXONOMY_PATH,
    tickers: set[str] | None = None,
    render_artifacts: bool = True,
) -> dict[str, object]:
    matrix = load_json(matrix_path)
    taxonomy = load_json(taxonomy_path)
    governance = build_governance_report(matrix, taxonomy, REPO_ROOT)
    if governance["status"] != "PASS":
        return {
            "status": "FAIL",
            "governance": governance,
            "results": [],
            "errors": governance["errors"],
        }

    results: list[dict[str, object]] = []
    all_errors: list[str] = []
    active_cases, unknown_tickers = select_active_cases(matrix, tickers)
    if unknown_tickers:
        errors = [
            f"Requested ticker is not an active matrix case: {ticker}"
            for ticker in unknown_tickers
        ]
        return {
            "status": "FAIL",
            "matrix_session": matrix.get("session"),
            "matrix_as_of_date": matrix.get("as_of_date"),
            "active_case_count": 0,
            "active_tickers": [],
            "governance": governance,
            "results": [],
            "errors": errors,
        }

    for case in active_cases:
        ticker = str(case["ticker"])
        step3_dir = build_investment_layer(ticker, out_root)
        contract_path = step3_dir / "underwriting_output_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        errors = assert_contract_safety(contract, case)
        manifest: dict[str, object] | None = None
        if render_artifacts:
            render_dir = out_root.parent / "regression_render" / ticker.lower()
            manifest = render(contract_path, render_dir)
            if manifest.get("formal_report_blocked"):
                errors.append(f"{ticker}: formal rendering unexpectedly blocked")
        all_errors.extend(errors)
        results.append(
            {
                "case_id": case.get("case_id"),
                "ticker": ticker,
                "test_type": case.get("fixture_role"),
                "industry": case.get("industry"),
                "business_model": case.get("business_model"),
                "stress_characteristics": case.get("stress_characteristics"),
                "observed_safe_outcomes": sorted(
                    classify_contract_outcomes(contract)
                ),
                "required_safe_outcomes": case.get("required_safe_outcomes"),
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
        "matrix_session": matrix.get("session"),
        "matrix_as_of_date": matrix.get("as_of_date"),
        "active_case_count": len(active_cases),
        "active_tickers": [row.get("ticker") for row in active_cases],
        "governance": governance,
        "results": results,
        "errors": all_errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--matrix", type=Path, default=MATRIX_PATH)
    parser.add_argument("--taxonomy", type=Path, default=TAXONOMY_PATH)
    parser.add_argument(
        "--tickers",
        help="Optional comma-separated subset of active matrix tickers.",
    )
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()
    tickers = (
        {ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()}
        if args.tickers
        else None
    )
    report = run(
        Path(args.out_root),
        matrix_path=args.matrix,
        taxonomy_path=args.taxonomy,
        tickers=tickers,
        render_artifacts=not args.skip_render,
    )
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
