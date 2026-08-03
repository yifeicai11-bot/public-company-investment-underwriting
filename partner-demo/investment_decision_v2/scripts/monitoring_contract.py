#!/usr/bin/env python3
"""Shared S15 monitoring contracts, hashing, and validation rules."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - dependency diagnostic path
    Draft202012Validator = None
    FormatChecker = None


SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_DIR = SCRIPT_DIR.parent / "monitoring" / "schemas"
POLICY_SCHEMA_PATH = SCHEMA_DIR / "monitoring_policy.schema.json"
OUTPUT_SCHEMA_PATH = SCHEMA_DIR / "monitoring_output.schema.json"

MONITORING_POLICY_VERSION = "1.0.0"
MONITORING_OUTPUT_CONTRACT_VERSION = "1.0.0"
MONITORING_ENGINE_VERSION = "1.0.0"

MONITORING_STATUSES = {"MONITORING_COMPLETE", "MONITORING_BLOCKED"}
SYSTEM_THESIS_ASSESSMENTS = {
    "STRENGTHENING",
    "UNCHANGED",
    "WEAKENING",
    "MIXED",
    "POTENTIALLY_BROKEN",
    "NOT_EVALUATED",
}
FORMAL_THESIS_STATUSES = {
    "ACTIVE",
    "STRENGTHENED",
    "UNCHANGED",
    "WEAKENED",
    "BROKEN",
    "NOT_REVIEWED",
}
KPI_TRIGGER_TYPES = {"UPGRADE", "DOWNGRADE", "THESIS_BREAK", "MONITOR"}
KPI_ASSESSMENT_STATUSES = {
    "TRIGGERED",
    "NOT_TRIGGERED",
    "MISSING",
    "NOT_COMPARABLE",
    "EXPIRED",
}
PROBABILITY_MONITORING_STATUSES = {
    "NOT_PROVIDED",
    "CURRENT",
    "EXPIRING_SOON",
    "EXPIRED",
    "REVIEW_REQUIRED",
    "INVALID",
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: Any, length: int = 14) -> str:
    digest = canonical_hash(list(parts))[:length].upper()
    return f"{prefix}-{digest}"


def parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _validation_path(error: Any) -> str:
    parts = [str(value) for value in error.absolute_path]
    if error.validator == "required" and isinstance(error.validator_value, list):
        missing = [
            str(field)
            for field in error.validator_value
            if not isinstance(error.instance, dict) or field not in error.instance
        ]
        if missing:
            parts.append(",".join(sorted(missing)))
    return ".".join(parts) or "<document>"


def _schema_errors(payload: dict[str, Any], schema_path: Path) -> list[str]:
    if Draft202012Validator is None or FormatChecker is None:
        return ["<dependency>:jsonschema"]
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [f"<schema>:{schema_path.name}"]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return sorted({_validation_path(error) for error in validator.iter_errors(payload)})


def validate_monitoring_policy(policy: dict[str, Any]) -> list[str]:
    errors = _schema_errors(policy, POLICY_SCHEMA_PATH)
    if policy.get("monitoring_policy_version") != MONITORING_POLICY_VERSION:
        errors.append("monitoring_policy_version")

    effective = parse_iso_date(policy.get("effective_date"))
    expiration = parse_iso_date(policy.get("expiration_date"))
    if effective and expiration and expiration < effective:
        errors.append("expiration_date_before_effective_date")

    rule_ids: list[str] = []
    for row in policy.get("kpi_rules", []):
        if not isinstance(row, dict):
            continue
        rule_id = str(row.get("kpi_id") or "")
        rule_ids.append(rule_id)
        if row.get("trigger_type") not in KPI_TRIGGER_TYPES:
            errors.append(f"invalid_trigger_type:{rule_id or 'missing'}")
        if finite_number(row.get("threshold")) is None:
            errors.append(f"non_numeric_threshold:{rule_id or 'missing'}")
        rule_effective = parse_iso_date(row.get("effective_date"))
        rule_expiration = parse_iso_date(row.get("expiration_date"))
        if rule_effective and rule_expiration and rule_expiration < rule_effective:
            errors.append(f"rule_expiration_before_effective:{rule_id or 'missing'}")
    if len(rule_ids) != len(set(rule_ids)):
        errors.append("duplicate_kpi_ids")
    return sorted(set(errors))


def monitoring_hash_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "monitoring_hash", "contract_validation"}
    }


def calculate_monitoring_hash(payload: dict[str, Any]) -> str:
    return canonical_hash(monitoring_hash_payload(payload))


def validate_monitoring_output(payload: dict[str, Any]) -> list[str]:
    errors = _schema_errors(payload, OUTPUT_SCHEMA_PATH)
    if payload.get("monitoring_output_contract_version") != MONITORING_OUTPUT_CONTRACT_VERSION:
        errors.append("monitoring_output_contract_version")
    if payload.get("monitoring_engine_version") != MONITORING_ENGINE_VERSION:
        errors.append("monitoring_engine_version")
    if payload.get("status") not in MONITORING_STATUSES:
        errors.append("status")

    system_assessment = payload.get("system_thesis_assessment", {})
    if system_assessment.get("assessment") not in SYSTEM_THESIS_ASSESSMENTS:
        errors.append("system_thesis_assessment.assessment")
    if system_assessment.get("is_formal_thesis_status") is not False:
        errors.append("system_thesis_assessment.is_formal_thesis_status")

    formal = payload.get("formal_thesis_status", {})
    if formal.get("status") != "PENDING_HUMAN_REVIEW":
        errors.append("formal_thesis_status.status")
    if formal.get("selected_status") is not None:
        errors.append("formal_thesis_status.selected_status")
    if set(formal.get("allowed_human_statuses", [])) != FORMAL_THESIS_STATUSES:
        errors.append("formal_thesis_status.allowed_human_statuses")

    if payload.get("automatic_trade_execution") is not False:
        errors.append("automatic_trade_execution")

    for row in payload.get("kpi_assessments", []):
        if row.get("status") not in KPI_ASSESSMENT_STATUSES:
            errors.append(f"kpi_assessments.status:{row.get('kpi_id')}")
        if row.get("trigger_type") not in KPI_TRIGGER_TYPES:
            errors.append(f"kpi_assessments.trigger_type:{row.get('kpi_id')}")

    input_validation = payload.get("input_validation", {})
    failed_checks = [
        row
        for row in input_validation.get("checks", [])
        if isinstance(row, dict) and row.get("status") == "FAIL"
    ]
    expected_monitoring_status = (
        "MONITORING_BLOCKED" if failed_checks else "MONITORING_COMPLETE"
    )
    if payload.get("status") != expected_monitoring_status:
        errors.append("status_not_reconciled_to_input_validation")
    if input_validation.get("status") != ("FAIL" if failed_checks else "PASS"):
        errors.append("input_validation.status")
    if input_validation.get("hard_stop_count") != len(failed_checks):
        errors.append("input_validation.hard_stop_count")

    all_change_ids: list[str] = []
    for field in (
        "fact_changes",
        "calculation_changes",
        "judgment_changes",
        "warning_changes",
        "hard_stop_changes",
    ):
        for row in payload.get(field, []):
            change_id = str(row.get("change_id") or "")
            if not change_id:
                errors.append(f"{field}.change_id")
            all_change_ids.append(change_id)
    evidence_changes = payload.get("evidence_changes", {})
    for field in (
        "metric_source_changes",
        "source_registry_changes",
        "missing_evidence_changes",
    ):
        for row in evidence_changes.get(field, []):
            change_id = str(row.get("change_id") or "")
            if not change_id:
                errors.append(f"evidence_changes.{field}.change_id")
            all_change_ids.append(change_id)
    if len(all_change_ids) != len(set(all_change_ids)):
        errors.append("change_ids_not_unique")

    fact_changes = payload.get("fact_changes", [])
    calculation_changes = payload.get("calculation_changes", [])
    if any(row.get("evidence_class") != "FACT" for row in fact_changes):
        errors.append("fact_changes.evidence_class")
    if any(row.get("evidence_class") != "CALC" for row in calculation_changes):
        errors.append("calculation_changes.evidence_class")
    summary = payload.get("change_summary", {})
    fact_counts = summary.get("fact_metrics", {})
    calc_counts = summary.get("calculation_metrics", {})
    for label, rows, counts in (
        ("fact", fact_changes, fact_counts),
        ("calculation", calculation_changes, calc_counts),
    ):
        for change_type in ("ADDED", "REMOVED", "CHANGED"):
            if counts.get(change_type.lower()) != sum(
                row.get("change_type") == change_type for row in rows
            ):
                errors.append(f"change_summary.{label}.{change_type.lower()}")
        expected_compared = sum(
            int(counts.get(field, 0) or 0)
            for field in ("added", "removed", "changed", "unchanged")
        )
        if counts.get("compared") != expected_compared:
            errors.append(f"change_summary.{label}.compared")
    if summary.get("judgment_change_count") != len(payload.get("judgment_changes", [])):
        errors.append("change_summary.judgment_change_count")
    if summary.get("warning_change_count") != len(payload.get("warning_changes", [])):
        errors.append("change_summary.warning_change_count")
    if summary.get("hard_stop_change_count") != len(payload.get("hard_stop_changes", [])):
        errors.append("change_summary.hard_stop_change_count")
    triggered_kpis = [
        row for row in payload.get("kpi_assessments", []) if row.get("status") == "TRIGGERED"
    ]
    if summary.get("kpi_trigger_count") != len(triggered_kpis):
        errors.append("change_summary.kpi_trigger_count")

    operator_functions = {
        "LT": lambda value, threshold: value < threshold,
        "LTE": lambda value, threshold: value <= threshold,
        "GT": lambda value, threshold: value > threshold,
        "GTE": lambda value, threshold: value >= threshold,
        "EQ": lambda value, threshold: math.isclose(value, threshold, rel_tol=0, abs_tol=1e-12),
        "NEQ": lambda value, threshold: not math.isclose(value, threshold, rel_tol=0, abs_tol=1e-12),
    }
    for row in payload.get("kpi_assessments", []):
        if row.get("status") not in {"TRIGGERED", "NOT_TRIGGERED"}:
            continue
        value = finite_number(row.get("evaluated_value"))
        threshold = finite_number(row.get("threshold"))
        operator = operator_functions.get(str(row.get("operator")))
        if value is None or threshold is None or operator is None:
            errors.append(f"kpi_assessments.not_reproducible:{row.get('kpi_id')}")
            continue
        reproduced = operator(value, threshold)
        if (row.get("status") == "TRIGGERED") != reproduced:
            errors.append(f"kpi_assessments.status_not_reproducible:{row.get('kpi_id')}")

    breach_summary = payload.get("kpi_breach_summary", {})
    breaches = [
        row
        for row in triggered_kpis
        if row.get("trigger_type") in {"DOWNGRADE", "THESIS_BREAK"}
    ]
    upgrades = [row for row in triggered_kpis if row.get("trigger_type") == "UPGRADE"]
    unresolved = [
        row
        for row in payload.get("kpi_assessments", [])
        if row.get("status") in {"MISSING", "NOT_COMPARABLE", "EXPIRED"}
    ]
    if breach_summary.get("triggered_breach_count") != len(breaches):
        errors.append("kpi_breach_summary.triggered_breach_count")
    if breach_summary.get("upgrade_trigger_count") != len(upgrades):
        errors.append("kpi_breach_summary.upgrade_trigger_count")
    if breach_summary.get("missing_or_not_comparable_count") != len(unresolved):
        errors.append("kpi_breach_summary.missing_or_not_comparable_count")
    if breach_summary.get("breach_assessment_ids") != [row.get("assessment_id") for row in breaches]:
        errors.append("kpi_breach_summary.breach_assessment_ids")

    evidence_summary = evidence_changes.get("summary", {})
    if evidence_summary:
        expected_evidence_counts = {
            "added_evidence_count": len(evidence_changes.get("added_evidence_ids", [])),
            "removed_evidence_count": len(evidence_changes.get("removed_evidence_ids", [])),
            "metric_source_change_count": len(evidence_changes.get("metric_source_changes", [])),
            "source_registry_change_count": len(evidence_changes.get("source_registry_changes", [])),
            "missing_evidence_change_count": len(evidence_changes.get("missing_evidence_changes", [])),
        }
        for field, expected in expected_evidence_counts.items():
            if evidence_summary.get(field) != expected:
                errors.append(f"evidence_changes.summary.{field}")

    probability = payload.get("probability_expiration", {})
    if probability.get("status") not in PROBABILITY_MONITORING_STATUSES:
        errors.append("probability_expiration.status")
    monitoring_date = parse_iso_date(payload.get("monitoring_as_of_date"))
    probability_expiration = parse_iso_date(
        probability.get("probability_expiration_review_date")
    )
    if monitoring_date and probability_expiration:
        expected_days = (probability_expiration - monitoring_date).days
        if probability.get("days_to_expiration") != expected_days:
            errors.append("probability_expiration.days_to_expiration")
    expected_probability_eligibility = (
        probability.get("contract_probability_status") == "VALIDATED"
        and probability.get("contract_probability_approval_status") == "APPROVED"
        and probability.get("status") in {"CURRENT", "EXPIRING_SOON"}
    )
    if probability.get("formal_probability_outputs_remain_eligible") is not expected_probability_eligibility:
        errors.append("probability_expiration.formal_probability_outputs_remain_eligible")

    scenario = payload.get("scenario_impact", {})
    if scenario.get("status") == "EVALUATED":
        threshold = finite_number(scenario.get("materiality_threshold_pct"))
        base = next(
            (row for row in scenario.get("rows", []) if row.get("scenario") == "Base"),
            None,
        )
        base_change = finite_number(base.get("implied_price_change_pct")) if base else None
        if threshold is None:
            expected_impact = "NOT_EVALUATED"
        elif base_change is None:
            expected_impact = "NOT_COMPARABLE"
        elif base_change <= -threshold:
            expected_impact = "MATERIAL_DOWNSIDE_SHIFT"
        elif base_change >= threshold:
            expected_impact = "MATERIAL_UPSIDE_SHIFT"
        else:
            signs = {
                1 if (finite_number(row.get("implied_price_change_pct")) or 0) >= threshold else -1
                for row in scenario.get("rows", [])
                if abs(finite_number(row.get("implied_price_change_pct")) or 0) >= threshold
            }
            expected_impact = "MIXED" if len(signs) > 1 else "NO_MATERIAL_BASE_SHIFT"
        if scenario.get("overall_impact") != expected_impact:
            errors.append("scenario_impact.overall_impact")
        if scenario.get("formal_expected_return_recalculated") is not False:
            errors.append("scenario_impact.formal_expected_return_recalculated")

    current_hard_stop_count = int(summary.get("current_active_hard_stop_count", 0) or 0)
    if current_hard_stop_count:
        expected_system_assessment = "NOT_EVALUATED"
    else:
        thesis_breaks = [row for row in triggered_kpis if row.get("trigger_type") == "THESIS_BREAK"]
        downgrades = [row for row in triggered_kpis if row.get("trigger_type") == "DOWNGRADE"]
        if thesis_breaks:
            expected_system_assessment = "POTENTIALLY_BROKEN"
        elif upgrades and downgrades:
            expected_system_assessment = "MIXED"
        elif downgrades:
            expected_system_assessment = "WEAKENING"
        elif upgrades:
            expected_system_assessment = "STRENGTHENING"
        else:
            evaluable = [
                row
                for row in payload.get("kpi_assessments", [])
                if row.get("status") in {"TRIGGERED", "NOT_TRIGGERED"}
            ]
            expected_system_assessment = "UNCHANGED" if evaluable else "NOT_EVALUATED"
        if payload.get("policy_identity", {}).get("scenario_changes_affect_system_assessment") is True:
            scenario_direction = {
                "MATERIAL_DOWNSIDE_SHIFT": "WEAKENING",
                "MATERIAL_UPSIDE_SHIFT": "STRENGTHENING",
                "MIXED": "MIXED",
            }.get(str(scenario.get("overall_impact")))
            if scenario_direction:
                if expected_system_assessment == "UNCHANGED":
                    expected_system_assessment = scenario_direction
                elif expected_system_assessment not in {
                    scenario_direction,
                    "POTENTIALLY_BROKEN",
                    "NOT_EVALUATED",
                }:
                    expected_system_assessment = "MIXED"
    if system_assessment.get("assessment") != expected_system_assessment:
        errors.append("system_thesis_assessment.not_reproducible")

    stored_hash = str(payload.get("monitoring_hash") or "")
    if not stored_hash or stored_hash != calculate_monitoring_hash(payload):
        errors.append("monitoring_hash")

    if payload.get("status") == "MONITORING_BLOCKED":
        if system_assessment.get("assessment") != "NOT_EVALUATED":
            errors.append("blocked_monitoring_requires_not_evaluated")
        if payload.get("kpi_assessments"):
            errors.append("blocked_monitoring_must_suppress_kpi_assessments")
        if payload.get("scenario_impact", {}).get("status") != "NOT_EVALUATED":
            errors.append("blocked_monitoring_must_suppress_scenario_impact")

    return sorted(set(errors))
