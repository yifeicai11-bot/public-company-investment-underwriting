#!/usr/bin/env python3
"""Run the frozen S08 cross-company acceptance protocol."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import locale
import os
import platform
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
INVESTMENT_ROOT = SCRIPT_DIR.parent
REPO_ROOT = INVESTMENT_ROOT.parents[1]
REGRESSION_ROOT = INVESTMENT_ROOT / "regression"
DEFAULT_MANIFEST = REGRESSION_ROOT / "s08_cross_company_acceptance_manifest.json"
MATRIX_PATH = REGRESSION_ROOT / "cross_industry_matrix.json"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_public_company_investment_layer import (  # noqa: E402
    build_evidence_presentation,
    build_investment_layer,
)
from notes_events_controls import build_notes_and_events_assessment  # noqa: E402
from regression_governance import (  # noqa: E402
    TAXONOMY_PATH,
    assert_contract_safety,
    build_governance_report,
    classify_contract_outcomes,
    load_json,
)
from render_public_company_artifacts import render  # noqa: E402
from underwriting_contract import (  # noqa: E402
    determine_data_gate,
    finalize_output_contract,
)


SHARED_LOGIC_PATHS = (
    "partner-demo/investment_decision_v2/scripts/build_public_company_decision_pack.py",
    "partner-demo/investment_decision_v2/scripts/notes_events_controls.py",
    "partner-demo/investment_decision_v2/scripts/build_public_company_investment_layer.py",
    "partner-demo/investment_decision_v2/scripts/underwriting_contract.py",
    "partner-demo/investment_decision_v2/scripts/render_public_company_artifacts.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
    ).strip()


def validate_s07_shared_logic(commit: str) -> dict[str, Any]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    for relative_path in SHARED_LOGIC_PATHS:
        current_path = REPO_ROOT / relative_path
        try:
            frozen = subprocess.check_output(
                ["git", "show", f"{commit}:{relative_path}"],
                cwd=REPO_ROOT,
            )
        except subprocess.CalledProcessError as exc:
            errors.append(f"Could not read {relative_path} from {commit}: {exc}.")
            continue
        current = current_path.read_bytes()
        matched = current == frozen
        rows.append(
            {
                "path": relative_path,
                "matches_s07_commit": matched,
                "current_sha256": sha256_bytes(current),
                "s07_sha256": sha256_bytes(frozen),
            }
        )
        if not matched:
            errors.append(f"Shared logic changed after the frozen S07 commit: {relative_path}.")
    return {
        "status": "PASS" if not errors else "FAIL",
        "s07_commit": commit,
        "files": rows,
        "errors": errors,
    }


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("phase") != "B" or manifest.get("session") != "S08":
        errors.append("Manifest must identify Phase B / S08.")
    if manifest.get("source_scope") != "PUBLIC_DATA_ONLY":
        errors.append("S08 accepts only PUBLIC_DATA_ONLY live cases.")
    tickers = [
        str(row.get("ticker"))
        for row in manifest.get("cases", [])
        if isinstance(row, dict)
    ]
    if tickers != ["CROX", "AZO", "ODFL"]:
        errors.append("Frozen S08 case order must be CROX, AZO, ODFL.")
    modules = manifest.get("required_note_event_modules", [])
    if len(modules) != 9 or len(modules) != len(set(modules)):
        errors.append("Manifest must contain nine unique note/event modules.")
    allowed = set(manifest.get("allowed_module_statuses", []))
    if allowed != {
        "VALIDATED",
        "MISSING",
        "NOT_APPLICABLE",
        "WARNING",
        "HARD_STOP",
    }:
        errors.append("Manifest safe module statuses are incomplete.")
    commit = str(manifest.get("s07_implementation_commit") or "")
    if len(commit) != 40:
        errors.append("Manifest requires the full frozen S07 commit hash.")
    return errors


def validate_note_event_assessment(
    assessment: dict[str, Any],
    *,
    required_modules: list[str],
    allowed_statuses: set[str],
    evidence_ids: set[str],
    allow_hard_stop: bool,
) -> list[str]:
    errors: list[str] = []
    if assessment.get("control_version") != "1.0.0":
        errors.append("notes/events control version is not 1.0.0")
    modules = assessment.get("modules", {})
    if list(modules) != required_modules:
        errors.append(
            f"note/event modules differ from frozen order: {list(modules)}"
        )
    for module_id in required_modules:
        module = modules.get(module_id)
        if not isinstance(module, dict):
            errors.append(f"{module_id}: module is missing")
            continue
        status = module.get("status")
        if status not in allowed_statuses:
            errors.append(f"{module_id}: unsupported status {status}")
        if status == "HARD_STOP" and not allow_hard_stop:
            errors.append(f"{module_id}: unexpected live Hard Stop")
        if status == "MISSING" and not module.get("missing_information"):
            errors.append(f"{module_id}: MISSING lacks explicit missing information")
        for evidence_id in module.get("evidence_ids", []):
            if evidence_id not in evidence_ids:
                errors.append(f"{module_id}: unknown evidence ID {evidence_id}")

    expected_controls = {
        ("leases", "carrying_value_separated_from_contractual_payments"): "ENFORCED",
        ("covenants", "compliance_not_equated_to_headroom"): "ENFORCED",
        ("bad_debt", "missing_allowance_not_zero"): "ENFORCED",
        ("supplier_finance", "absence_not_assumed_not_applicable"): "ENFORCED",
        (
            "subsequent_events",
            "events_not_mixed_into_historical_balances",
        ): "ENFORCED",
    }
    for (module_id, field), expected in expected_controls.items():
        value = (
            modules.get(module_id, {})
            .get("required_elements", {})
            .get(field)
        )
        if value != expected:
            errors.append(f"{module_id}.{field}: expected {expected}, found {value}")
    return errors


def synthetic_submissions(
    *,
    event_form: str | None = None,
    event_items: str = "",
    event_accession: str = "",
) -> dict[str, Any]:
    rows = [
        {
            "form": "10-Q",
            "filingDate": "2026-05-01",
            "reportDate": "2026-03-31",
            "accessionNumber": "0000000000-26-000001",
            "primaryDocument": "base.htm",
            "items": "",
        }
    ]
    if event_form:
        rows.append(
            {
                "form": event_form,
                "filingDate": "2026-05-15",
                "reportDate": "2026-05-15",
                "accessionNumber": event_accession,
                "primaryDocument": "event.htm",
                "items": event_items,
            }
        )
    keys = (
        "form",
        "filingDate",
        "reportDate",
        "accessionNumber",
        "primaryDocument",
        "items",
    )
    return {
        "cik": "0000000000",
        "filings": {
            "recent": {
                key: [row[key] for row in rows]
                for key in keys
            }
        },
    }


def build_synthetic_safe_failure_results() -> dict[str, Any]:
    selected = {
        "form": "10-Q",
        "filed": "2026-05-01",
        "period": "2026-03-31",
        "accession": "0000000000-26-000001",
        "url": "https://www.sec.gov/synthetic-base.htm",
    }
    empty_facts = {"facts": {}}
    missing = build_notes_and_events_assessment(
        submissions=synthetic_submissions(),
        companyfacts=empty_facts,
        selected_filing=selected,
        filing_text="",
        metric_names=set(),
    )
    not_applicable = build_notes_and_events_assessment(
        submissions=synthetic_submissions(),
        companyfacts=empty_facts,
        selected_filing=selected,
        filing_text="We do not have any supplier finance programs.",
        metric_names=set(),
    )
    warning = build_notes_and_events_assessment(
        submissions=synthetic_submissions(),
        companyfacts=empty_facts,
        selected_filing=selected,
        filing_text="Long-term debt includes a revolving credit facility.",
        metric_names={"current_debt", "long_term_debt"},
    )
    hard_accession = "0000000000-26-000099"
    hard_stop = build_notes_and_events_assessment(
        submissions=synthetic_submissions(
            event_form="8-K",
            event_items="4.02",
            event_accession=hard_accession,
        ),
        companyfacts=empty_facts,
        selected_filing=selected,
        filing_text="",
        metric_names=set(),
        document_texts={
            hard_accession: (
                "The audit committee concluded that previously issued financial "
                "statements should no longer be relied upon."
            )
        },
    )
    observed = {
        status
        for assessment in (missing, not_applicable, warning, hard_stop)
        for status in assessment.get("safe_outcomes_observed", [])
    }
    required = {
        "MISSING",
        "NOT_APPLICABLE",
        "WARNING",
        "HARD_STOP",
    }
    errors = []
    if not required.issubset(observed):
        errors.append(f"Synthetic safe statuses missing: {sorted(required - observed)}")
    hard_modules = [
        module_id
        for module_id, module in hard_stop["modules"].items()
        if module.get("status") == "HARD_STOP"
    ]
    if "subsequent_events" not in hard_modules or "restatements" not in hard_modules:
        errors.append("Item 4.02 did not Hard Stop subsequent events and restatements.")
    return {
        "status": "PASS" if not errors else "FAIL",
        "observed_statuses": sorted(observed),
        "required_statuses": sorted(required),
        "hard_stop_modules": hard_modules,
        "hard_stop_assessment": hard_stop,
        "errors": errors,
    }


def build_hard_stop_contract(
    live_contract: dict[str, Any],
    hard_stop_assessment: dict[str, Any],
) -> dict[str, Any]:
    contract = copy.deepcopy(live_contract)
    contract.pop("contract_hash", None)
    contract.pop("contract_validation", None)
    contract.pop("render_blockers", None)
    hard_stop_issues = [
        row
        for row in hard_stop_assessment.get("validation_issues", [])
        if row.get("issue_class") == "HARD_STOP"
    ]
    contract["notes_and_events_assessment"] = hard_stop_assessment
    contract["validation_issues"] = [
        *contract.get("validation_issues", []),
        *hard_stop_issues,
    ]
    contract["hard_stops"] = hard_stop_issues
    contract["validation_status"] = "FAIL"
    contract["data_gate"] = determine_data_gate(
        issues=contract["validation_issues"],
        core_data_validated=False,
        issuer_underwriting_complete=False,
        valuation_validated=False,
        scenarios_validated=False,
        portfolio_inputs_validated=False,
        human_approval=False,
        probabilities_validated=False,
    )
    suppressed_rows = [
        row
        for row in contract.get("evidence_records", [])
        if str(row.get("metric_name", "")).startswith("scenario_")
        and str(row.get("metric_name", "")).endswith(
            ("_implied_price", "_price_change_vs_current")
        )
    ]
    suppressed_ids = {
        str(row.get("evidence_id"))
        for row in suppressed_rows
        if row.get("evidence_id")
    }
    contract["evidence_records"] = [
        row
        for row in contract.get("evidence_records", [])
        if row.get("evidence_id") not in suppressed_ids
    ]
    for field in ("known_facts", "calculated_metrics"):
        contract[field] = [
            evidence_id
            for evidence_id in contract.get(field, [])
            if evidence_id not in suppressed_ids
        ]
    display_index, bundles = build_evidence_presentation(contract)
    contract["evidence_display_index"] = display_index
    contract["evidence_bundles"] = bundles
    return finalize_output_contract(contract)


def has_chinese_text(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def case_acceptance(
    *,
    case: dict[str, Any],
    matrix_case: dict[str, Any],
    out_root: Path,
    render_root: Path,
    required_modules: list[str],
    allowed_statuses: set[str],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    ticker = str(case["ticker"])
    errors: list[str] = []
    step3_dir = build_investment_layer(ticker, out_root)
    contract_path = step3_dir / "underwriting_output_contract.json"
    step2_path = step3_dir.parent / "data" / "data_evidence_pack.json"
    contract = load_json(contract_path)
    step2 = load_json(step2_path)

    errors.extend(assert_contract_safety(contract, matrix_case))
    if step2.get("notes_and_events_control_version") != "1.0.0":
        errors.append(f"{ticker}: Data pack lacks S07 control version")
    if contract.get("notes_and_events_control_version") != "1.0.0":
        errors.append(f"{ticker}: output contract lacks S07 control version")
    assessment = step2.get("notes_and_events_assessment", {})
    evidence_ids = {
        str(row.get("evidence_id"))
        for row in step2.get("evidence_records", [])
        if row.get("evidence_id")
    }
    errors.extend(
        f"{ticker}: {error}"
        for error in validate_note_event_assessment(
            assessment,
            required_modules=required_modules,
            allowed_statuses=allowed_statuses,
            evidence_ids=evidence_ids,
            allow_hard_stop=False,
        )
    )
    if contract.get("notes_and_events_assessment") != assessment:
        errors.append(f"{ticker}: Gate 3 contract changed the Data Layer note/event object")
    if contract.get("portfolio_context", {}).get("status") != "DISABLED":
        errors.append(f"{ticker}: public-only portfolio overlay is not disabled")
    for field in (
        "probability_weighted_return",
        "target_price",
        "position_sizing",
    ):
        if contract.get(field) is not None:
            errors.append(f"{ticker}: public-only {field} is not suppressed")
    if contract.get("portfolio_action") != "Not Evaluated":
        errors.append(f"{ticker}: public-only portfolio action is not Not Evaluated")

    render_manifest = render(contract_path, render_root / ticker.lower())
    if render_manifest.get("formal_report_blocked"):
        errors.append(f"{ticker}: formal public-data rendering was unexpectedly blocked")
    expected_outputs = {
        "one_page_html",
        "full_report_html",
        "evidence_appendix_html",
        "qa_summary_html",
    }
    if set(render_manifest.get("outputs", {})) != expected_outputs:
        errors.append(f"{ticker}: formal bilingual output set is incomplete")
    for output_name, output_path in render_manifest.get("outputs", {}).items():
        path = Path(output_path)
        if not path.exists() or path.stat().st_size == 0:
            errors.append(f"{ticker}: {output_name} is missing or empty")
        elif not has_chinese_text(path):
            errors.append(f"{ticker}: {output_name} has no Chinese text")

    output_hashes = {
        name: sha256_file(Path(path))
        for name, path in render_manifest.get("outputs", {}).items()
        if Path(path).exists()
    }
    result = {
        "ticker": ticker,
        "role": case.get("role"),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "report_id": contract.get("report_id"),
        "contract_hash": contract.get("contract_hash"),
        "contract_validation": contract.get("contract_validation", {}).get("status"),
        "data_gate": contract.get("data_gate"),
        "financial_statement_date": contract.get("report_dates", {}).get(
            "financial_statement_date"
        ),
        "latest_financial_filing_date": contract.get("report_dates", {}).get(
            "latest_financial_filing_date"
        ),
        "market_price_date": contract.get("report_dates", {}).get(
            "market_price_date"
        ),
        "notes_and_events_status": assessment.get("status"),
        "module_statuses": {
            module_id: module.get("status")
            for module_id, module in assessment.get("modules", {}).items()
        },
        "safe_outcomes": sorted(classify_contract_outcomes(contract)),
        "hard_stop_count": len(contract.get("hard_stops", [])),
        "warning_count": len(contract.get("warnings", [])),
        "evidence_count": len(contract.get("evidence_records", [])),
        "contract_sha256": sha256_file(contract_path),
        "data_pack_sha256": sha256_file(step2_path),
        "render_output_sha256": output_hashes,
    }
    return result, contract


def run_acceptance(
    *,
    manifest_path: Path,
    out_root: Path,
    render_root: Path,
    diagnostic_root: Path,
) -> dict[str, Any]:
    started = datetime.now(UTC)
    manifest = load_json(manifest_path)
    errors = validate_manifest(manifest)
    shared_logic = validate_s07_shared_logic(
        str(manifest.get("s07_implementation_commit", ""))
    )
    errors.extend(shared_logic["errors"])

    matrix = load_json(MATRIX_PATH)
    taxonomy = load_json(TAXONOMY_PATH)
    governance = build_governance_report(matrix, taxonomy, REPO_ROOT)
    errors.extend(governance["errors"])
    matrix_by_ticker = {
        str(row.get("ticker")): row
        for row in matrix.get("cases", [])
        if isinstance(row, dict) and row.get("fixture_status") == "ACTIVE"
    }
    required_modules = list(manifest.get("required_note_event_modules", []))
    allowed_statuses = set(manifest.get("allowed_module_statuses", []))

    results: list[dict[str, Any]] = []
    first_live_contract: dict[str, Any] | None = None
    for case in manifest.get("cases", []):
        ticker = str(case.get("ticker"))
        if ticker not in matrix_by_ticker:
            case_errors = [f"{ticker}: no active cross-industry matrix case"]
            results.append(
                {
                    "ticker": ticker,
                    "role": case.get("role"),
                    "status": "FAIL",
                    "errors": case_errors,
                }
            )
            errors.extend(case_errors)
            continue
        try:
            result, contract = case_acceptance(
                case=case,
                matrix_case=matrix_by_ticker[ticker],
                out_root=out_root,
                render_root=render_root,
                required_modules=required_modules,
                allowed_statuses=allowed_statuses,
            )
            results.append(result)
            errors.extend(result["errors"])
            if first_live_contract is None:
                first_live_contract = contract
        except Exception as exc:  # Preserve the complete first-run failure.
            case_errors = [
                f"{ticker}: {type(exc).__name__}: {exc}",
            ]
            results.append(
                {
                    "ticker": ticker,
                    "role": case.get("role"),
                    "status": "FAIL",
                    "errors": case_errors,
                    "traceback": traceback.format_exc(),
                }
            )
            errors.extend(case_errors)

    synthetic = build_synthetic_safe_failure_results()
    errors.extend(synthetic["errors"])
    diagnostic_result: dict[str, Any] = {
        "status": "FAIL",
        "errors": ["No live contract was available for diagnostic rendering."],
    }
    if first_live_contract is not None:
        hard_contract = build_hard_stop_contract(
            first_live_contract,
            synthetic["hard_stop_assessment"],
        )
        diagnostic_root.mkdir(parents=True, exist_ok=True)
        hard_contract_path = diagnostic_root / "synthetic_hard_stop_contract.json"
        hard_contract_path.write_text(
            json.dumps(hard_contract, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        diagnostic_manifest = render(
            hard_contract_path,
            diagnostic_root / "render",
        )
        diagnostic_errors: list[str] = []
        if not diagnostic_manifest.get("formal_report_blocked"):
            diagnostic_errors.append("Hard Stop did not block formal rendering.")
        if set(diagnostic_manifest.get("outputs", {})) != {"diagnostic_html"}:
            diagnostic_errors.append("Hard Stop renderer produced a formal artifact.")
        diagnostic_value = diagnostic_manifest.get("outputs", {}).get(
            "diagnostic_html"
        )
        diagnostic_path = Path(diagnostic_value) if diagnostic_value else None
        if diagnostic_path is None or not diagnostic_path.is_file():
            diagnostic_errors.append("Hard Stop diagnostic HTML is missing.")
        else:
            diagnostic_text = diagnostic_path.read_text(encoding="utf-8")
            if "P1-subsequent-event-review" not in diagnostic_text:
                diagnostic_errors.append("Diagnostic omits the subsequent-event Hard Stop.")
            if "One_Page" in diagnostic_text or "Full_Report" in diagnostic_text:
                diagnostic_errors.append("Diagnostic references a formal report artifact.")
        diagnostic_result = {
            "status": "PASS" if not diagnostic_errors else "FAIL",
            "errors": diagnostic_errors,
            "formal_report_blocked": diagnostic_manifest.get(
                "formal_report_blocked"
            ),
            "outputs": sorted(diagnostic_manifest.get("outputs", {})),
            "contract_validation": hard_contract.get(
                "contract_validation",
                {},
            ).get("status"),
            "data_gate": hard_contract.get("data_gate"),
            "hard_stop_ids": [
                row.get("check_id")
                for row in hard_contract.get("hard_stops", [])
            ],
            "contract_sha256": sha256_file(hard_contract_path),
            "diagnostic_sha256": sha256_file(diagnostic_path)
            if diagnostic_path is not None and diagnostic_path.is_file()
            else None,
        }
        errors.extend(diagnostic_errors)

    synthetic.pop("hard_stop_assessment", None)
    completed = datetime.now(UTC)
    return {
        "schema_version": "1.0.0",
        "document_type": "s08_cross_company_acceptance_report",
        "phase": "B",
        "session": "S08",
        "status": "PASS" if not errors else "FAIL",
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "elapsed_seconds": round((completed - started).total_seconds(), 3),
        "manifest_path": str(manifest_path.relative_to(REPO_ROOT)),
        "manifest_sha256": sha256_file(manifest_path),
        "git": {
            "head": git_output("rev-parse", "HEAD"),
            "branch": git_output("branch", "--show-current"),
            "s07_shared_logic": shared_logic,
        },
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "locale": locale.setlocale(locale.LC_ALL, None),
            "timezone": os.environ.get("TZ") or datetime.now().astimezone().tzname(),
        },
        "governance": governance,
        "live_case_results": results,
        "synthetic_safe_failure_results": synthetic,
        "hard_stop_rendering": diagnostic_result,
        "errors": errors,
        "warnings": [
            "Live SEC filings and market observations are dated and may change after this acceptance run.",
            "MISSING and WARNING outcomes are acceptable only when the affected conclusion remains qualified and the remediation is explicit.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--render-root", type=Path, required=True)
    parser.add_argument("--diagnostic-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = run_acceptance(
        manifest_path=args.manifest,
        out_root=args.out_root,
        render_root=args.render_root,
        diagnostic_root=args.diagnostic_root,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
