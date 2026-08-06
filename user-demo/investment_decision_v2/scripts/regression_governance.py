#!/usr/bin/env python3
"""Shared governance for cross-company regression and safe-failure tests."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
INVESTMENT_ROOT = SCRIPT_DIR.parent
REPO_ROOT = INVESTMENT_ROOT.parents[1]
REGRESSION_ROOT = INVESTMENT_ROOT / "regression"
MATRIX_PATH = REGRESSION_ROOT / "cross_industry_matrix.json"
MATRIX_SCHEMA_PATH = REGRESSION_ROOT / "cross_industry_matrix.schema.json"
TAXONOMY_PATH = REGRESSION_ROOT / "safe_failure_taxonomy.json"
TAXONOMY_SCHEMA_PATH = REGRESSION_ROOT / "safe_failure_taxonomy.schema.json"

REQUIRED_SAFE_OUTCOMES = {
    "VALIDATED_RESULT",
    "MISSING",
    "NOT_APPLICABLE",
    "SUPPRESSED",
    "WARNING",
    "HARD_STOP",
}
IDENTITY_NAMES = {
    "company",
    "company_name",
    "issuer",
    "issuer_name",
    "symbol",
    "ticker",
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one JSON object.")
    return payload


def schema_errors(payload: dict[str, Any], schema_path: Path) -> list[str]:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        return ["jsonschema is required to validate regression governance files."]

    schema = load_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[str] = []
    for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path)):
        locator = ".".join(str(part) for part in error.path) or "<root>"
        errors.append(f"{schema_path.name}:{locator}: {error.message}")
    return errors


def taxonomy_index(taxonomy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("outcome_id")): row
        for row in taxonomy.get("outcomes", [])
        if isinstance(row, dict)
    }


def validate_taxonomy(taxonomy: dict[str, Any]) -> dict[str, Any]:
    errors = schema_errors(taxonomy, TAXONOMY_SCHEMA_PATH)
    rows = taxonomy.get("outcomes", [])
    outcome_ids = [row.get("outcome_id") for row in rows if isinstance(row, dict)]
    if len(outcome_ids) != len(set(outcome_ids)):
        errors.append("Safe-failure outcome IDs must be unique.")
    missing = sorted(REQUIRED_SAFE_OUTCOMES - set(outcome_ids))
    extra = sorted(set(outcome_ids) - REQUIRED_SAFE_OUTCOMES)
    if missing:
        errors.append(f"Missing required safe outcomes: {', '.join(missing)}.")
    if extra:
        errors.append(f"Unknown safe outcomes: {', '.join(extra)}.")

    index = taxonomy_index(taxonomy)
    hard_stop = index.get("HARD_STOP", {})
    if hard_stop.get("blocks_formal_report") is not True:
        errors.append("HARD_STOP must block formal report generation.")
    if hard_stop.get("allows_research_to_continue") is not False:
        errors.append("HARD_STOP must stop the affected analytical path.")
    for outcome_id in REQUIRED_SAFE_OUTCOMES - {"HARD_STOP"}:
        if index.get(outcome_id, {}).get("blocks_formal_report") is not False:
            errors.append(f"{outcome_id} must not automatically block a formal report.")

    return {
        "status": "PASS" if not errors else "FAIL",
        "outcome_ids": sorted(set(outcome_ids)),
        "errors": errors,
    }


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def validate_matrix(
    matrix: dict[str, Any],
    taxonomy: dict[str, Any],
) -> dict[str, Any]:
    errors = schema_errors(matrix, MATRIX_SCHEMA_PATH)
    taxonomy_ids = set(taxonomy_index(taxonomy))
    stress_rows = matrix.get("stress_characteristics", [])
    stress_ids = [
        str(row.get("stress_id"))
        for row in stress_rows
        if isinstance(row, dict)
    ]
    case_rows = [row for row in matrix.get("cases", []) if isinstance(row, dict)]
    case_ids = [str(row.get("case_id")) for row in case_rows]
    active_cases = [row for row in case_rows if row.get("fixture_status") == "ACTIVE"]
    planned_cases = [row for row in case_rows if row.get("fixture_status") == "PLANNED"]
    active_tickers = [str(row.get("ticker")) for row in active_cases]

    for duplicate in _duplicates(stress_ids):
        errors.append(f"Duplicate stress characteristic: {duplicate}.")
    for duplicate in _duplicates(case_ids):
        errors.append(f"Duplicate regression case ID: {duplicate}.")
    for duplicate in _duplicates(active_tickers):
        errors.append(f"Duplicate active ticker: {duplicate}.")

    known_stress = set(stress_ids)
    coverage: dict[str, dict[str, list[str]]] = {
        stress_id: {"active_cases": [], "planned_cases": []}
        for stress_id in stress_ids
    }
    for case in case_rows:
        case_id = str(case.get("case_id"))
        fixture_status = case.get("fixture_status")
        for stress_id in case.get("stress_characteristics", []):
            if stress_id not in known_stress:
                errors.append(f"{case_id} references unknown stress characteristic {stress_id}.")
                continue
            bucket = "active_cases" if fixture_status == "ACTIVE" else "planned_cases"
            coverage[stress_id][bucket].append(case_id)
        for outcome_id in case.get("required_safe_outcomes", []):
            if outcome_id not in taxonomy_ids:
                errors.append(f"{case_id} references unknown safe outcome {outcome_id}.")
        if case.get("analytical_logic_hardcoding_allowed") is not False:
            errors.append(f"{case_id} must prohibit analytical hardcoding.")

    uncovered = [
        stress_id
        for stress_id, buckets in coverage.items()
        if not buckets["active_cases"] and not buckets["planned_cases"]
    ]
    if uncovered:
        errors.append(f"Uncovered stress characteristics: {', '.join(uncovered)}.")

    policy = matrix.get("coverage_policy", {})
    minimum_active_cases = int(policy.get("minimum_active_cases", 0))
    minimum_active_industries = int(policy.get("minimum_active_industries", 0))
    active_industries = {str(row.get("industry")) for row in active_cases}
    if len(active_cases) < minimum_active_cases:
        errors.append(
            f"Active cases {len(active_cases)} are below the minimum {minimum_active_cases}."
        )
    if len(active_industries) < minimum_active_industries:
        errors.append(
            f"Active industries {len(active_industries)} are below the minimum "
            f"{minimum_active_industries}."
        )

    required_outcomes = set(policy.get("required_safe_outcomes", []))
    if required_outcomes != REQUIRED_SAFE_OUTCOMES:
        errors.append("Coverage policy must require the complete safe-failure taxonomy.")
    synthetic_outcomes = {
        row.get("outcome_id")
        for row in matrix.get("synthetic_safety_cases", [])
        if isinstance(row, dict)
    }
    missing_synthetic = sorted(REQUIRED_SAFE_OUTCOMES - synthetic_outcomes)
    if missing_synthetic:
        errors.append(
            f"Synthetic safety cases do not cover: {', '.join(missing_synthetic)}."
        )

    active_coverage_gaps = sorted(
        stress_id
        for stress_id, buckets in coverage.items()
        if not buckets["active_cases"]
    )
    return {
        "status": "PASS" if not errors else "FAIL",
        "active_case_count": len(active_cases),
        "planned_case_count": len(planned_cases),
        "active_industry_count": len(active_industries),
        "stress_characteristic_count": len(stress_ids),
        "active_coverage_count": len(stress_ids) - len(active_coverage_gaps),
        "active_coverage_gaps": active_coverage_gaps,
        "coverage": coverage,
        "errors": errors,
    }


def _expression_identity_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id.lower())
        elif isinstance(child, ast.Attribute):
            names.add(child.attr.lower())
    return names & IDENTITY_NAMES


def _string_constants(node: ast.AST) -> set[str]:
    return {
        child.value.casefold()
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }


class FixtureBranchVisitor(ast.NodeVisitor):
    def __init__(self, fixture_values: set[str]) -> None:
        self.fixture_values = fixture_values
        self.findings: list[dict[str, Any]] = []

    def _inspect_condition(self, node: ast.AST, kind: str) -> None:
        identity_names = _expression_identity_names(node)
        matched_values = sorted(_string_constants(node) & self.fixture_values)
        if identity_names and matched_values:
            self.findings.append(
                {
                    "line": getattr(node, "lineno", None),
                    "kind": kind,
                    "identity_names": sorted(identity_names),
                    "fixture_values": matched_values,
                }
            )

    def visit_If(self, node: ast.If) -> None:
        self._inspect_condition(node.test, "if")
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._inspect_condition(node.test, "conditional_expression")
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self._inspect_condition(node.test, "assert")
        self.generic_visit(node)

    def _inspect_configuration(self, node: ast.AST) -> None:
        if not isinstance(node, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
            return
        matched_values = sorted(_string_constants(node) & self.fixture_values)
        if matched_values:
            self.findings.append(
                {
                    "line": getattr(node, "lineno", None),
                    "kind": "fixture_configuration",
                    "identity_names": [],
                    "fixture_values": matched_values,
                }
            )

    def visit_Assign(self, node: ast.Assign) -> None:
        self._inspect_configuration(node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._inspect_configuration(node.value)
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        identity_names = _expression_identity_names(node.subject)
        matched_values = sorted(_string_constants(node) & self.fixture_values)
        if identity_names and matched_values:
            self.findings.append(
                {
                    "line": getattr(node, "lineno", None),
                    "kind": "match",
                    "identity_names": sorted(identity_names),
                    "fixture_values": matched_values,
                }
            )
        self.generic_visit(node)


def scan_fixture_specific_branches(
    matrix: dict[str, Any],
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    active_cases = [
        row
        for row in matrix.get("cases", [])
        if isinstance(row, dict) and row.get("fixture_status") == "ACTIVE"
    ]
    fixture_values = {
        str(value).casefold()
        for row in active_cases
        for value in (row.get("ticker"), row.get("company_name"))
        if value
    }
    findings: list[dict[str, Any]] = []
    for relative_path in matrix.get("shared_analytical_files", []):
        path = repo_root / relative_path
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            findings.append(
                {
                    "file": relative_path,
                    "line": None,
                    "kind": "scan_error",
                    "message": str(exc),
                }
            )
            continue
        visitor = FixtureBranchVisitor(fixture_values)
        visitor.visit(tree)
        for finding in visitor.findings:
            findings.append({"file": relative_path, **finding})
    return {
        "status": "PASS" if not findings else "FAIL",
        "files_scanned": len(matrix.get("shared_analytical_files", [])),
        "fixture_value_count": len(fixture_values),
        "findings": findings,
    }


def _contains_exact_status(value: Any, target: str) -> bool:
    if isinstance(value, str):
        return value == target
    if isinstance(value, dict):
        return any(_contains_exact_status(item, target) for item in value.values())
    if isinstance(value, list):
        return any(_contains_exact_status(item, target) for item in value)
    return False


def classify_contract_outcomes(contract: dict[str, Any]) -> set[str]:
    outcomes: set[str] = set()
    if contract.get("contract_validation", {}).get("status") == "PASS":
        outcomes.add("VALIDATED_RESULT")
    if contract.get("hard_stops"):
        outcomes.add("HARD_STOP")
    if contract.get("warnings"):
        outcomes.add("WARNING")
    if _contains_exact_status(contract, "MISSING"):
        outcomes.add("MISSING")
    if _contains_exact_status(contract, "NOT_APPLICABLE"):
        outcomes.add("NOT_APPLICABLE")

    prohibited = set(contract.get("data_gate", {}).get("prohibited_outputs", []))
    suppressed_fields = {
        "expected_return": contract.get("probability_weighted_return"),
        "target_price": contract.get("target_price"),
        "position_sizing": contract.get("position_sizing"),
    }
    if any(
        field in prohibited and suppressed_fields[field] is None
        for field in suppressed_fields
    ):
        outcomes.add("SUPPRESSED")
    return outcomes


def _all_validation_issues(contract: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("validation_issues", "hard_stops", "warnings"):
        rows.extend(
            row
            for row in contract.get(key, [])
            if isinstance(row, dict)
        )
    return rows


def assert_contract_safety(
    contract: dict[str, Any],
    case: dict[str, Any],
) -> list[str]:
    ticker = str(case.get("ticker"))
    errors: list[str] = []
    assertions = set(case.get("required_assertions", []))
    if contract.get("contract_validation", {}).get("status") != "PASS":
        errors.append("contract validation failed")
    if contract.get("supported_universe", {}).get("status") != "SUPPORTED_CORE":
        errors.append("issuer unexpectedly outside supported core")
    if contract.get("hard_stops"):
        errors.append(f"active hard stops: {len(contract.get('hard_stops', []))}")

    if "public_only_gating" in assertions:
        for field in ("probability_weighted_return", "target_price", "position_sizing"):
            if contract.get(field) is not None:
                errors.append(f"public-only {field} was not suppressed")
        if contract.get("portfolio_context", {}).get("status") != "DISABLED":
            errors.append("public-only portfolio context was not disabled")

    records = [
        row
        for row in contract.get("evidence_records", [])
        if isinstance(row, dict)
    ]
    evidence_ids = {row.get("evidence_id") for row in records}
    if "evidence_lineage" in assertions:
        if None in evidence_ids or len(evidence_ids) != len(records):
            errors.append("evidence IDs are missing or duplicated")
        for row in records:
            if row.get("evidence_class") == "CALC" and (
                not row.get("formula") or not row.get("input_evidence_ids")
            ):
                errors.append(
                    f"calculation lineage missing for {row.get('metric_name')}"
                )
            for input_id in row.get("input_evidence_ids", []):
                if input_id not in evidence_ids:
                    errors.append(f"unknown calculation input {input_id}")

    if "period_integrity" in assertions:
        for row in records:
            if row.get("period_type") in {"quarter", "derived-quarter"}:
                duration = row.get("duration_days")
                if isinstance(duration, int) and duration > 130:
                    errors.append(
                        f"YTD mislabeled as quarter: {row.get('metric_name')} "
                        f"{duration} days"
                    )

    if "share_date_not_after_price" in assertions:
        price_date = contract.get("report_dates", {}).get("market_price_date")
        share_date = contract.get("report_dates", {}).get("share_count_date")
        if price_date and share_date and share_date > price_date:
            errors.append("share count date is after market price date")

    opportunity = contract.get("opportunity_cost", {})
    if opportunity.get("status") == "PASS":
        if not opportunity.get("start_date") or not opportunity.get("end_date"):
            errors.append("aligned return dates missing")
        if (
            opportunity.get("return_basis")
            != "adjusted close on exact common trading dates"
        ):
            errors.append("return basis is not exact-date adjusted close")

    issues = _all_validation_issues(contract)
    if "working_capital_partial_coverage" in assertions:
        matching = [
            row
            for row in issues
            if row.get("check_id") == "P1-working-capital-component-coverage"
        ]
        if not matching:
            errors.append("partial working-capital coverage was not disclosed")
        elif not any(
            "No absent component is assumed to be zero"
            in str(row.get("message") or row.get("evidence") or "")
            for row in matching
        ):
            errors.append("working-capital coverage did not prohibit assumed zeros")

    if "facility_reconciliation" in assertions:
        matching = [
            row
            for row in issues
            if row.get("check_id") == "P0-facility-reconciliation"
        ]
        if not matching or not any(
            row.get("status", row.get("result")) == "PASS"
            for row in matching
        ):
            errors.append("facility commitment and availability did not reconcile")

    observed_outcomes = classify_contract_outcomes(contract)
    missing_outcomes = sorted(
        set(case.get("required_safe_outcomes", [])) - observed_outcomes
    )
    if missing_outcomes:
        errors.append(
            f"required safe outcomes not observed: {', '.join(missing_outcomes)}"
        )
    return [f"{ticker}: {error}" for error in errors]


def build_governance_report(
    matrix: dict[str, Any],
    taxonomy: dict[str, Any],
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    taxonomy_report = validate_taxonomy(taxonomy)
    matrix_report = validate_matrix(matrix, taxonomy)
    hardcoding_report = scan_fixture_specific_branches(matrix, repo_root)
    errors = (
        taxonomy_report["errors"]
        + matrix_report["errors"]
        + [
            (
                f"{row.get('file')}:{row.get('line')}: "
                f"fixture-specific {row.get('kind')} branch"
            )
            for row in hardcoding_report["findings"]
        ]
    )
    return {
        "status": "PASS" if not errors else "FAIL",
        "taxonomy": taxonomy_report,
        "matrix": matrix_report,
        "anti_hardcoding": hardcoding_report,
        "errors": errors,
    }
