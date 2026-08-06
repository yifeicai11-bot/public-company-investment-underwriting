#!/usr/bin/env python3
"""Shared S15 contract-to-contract monitoring engine.

The engine compares two validated issuer contracts. It records analytical
changes and produces a provisional system thesis assessment, but it never
sets the formal thesis status or executes a trade.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import UTC, date, datetime
from typing import Any

from monitoring_contract import (
    FORMAL_THESIS_STATUSES,
    MONITORING_ENGINE_VERSION,
    MONITORING_OUTPUT_CONTRACT_VERSION,
    calculate_monitoring_hash,
    canonical_hash,
    canonical_json,
    finite_number,
    parse_iso_date,
    stable_id,
    validate_monitoring_output,
    validate_monitoring_policy,
)
from underwriting_contract import validate_output_contract


COMPARISON_FIELDS = (
    "value",
    "unit",
    "currency",
    "scale",
    "period_start",
    "period_end",
    "period_type",
    "as_of_date",
    "measurement_basis",
    "fiscal_period",
    "evidence_class",
    "reported_or_calculated",
    "formula",
    "input_evidence_ids",
    "confidence",
    "validation_status",
    "subsequent_event_status",
)
SOURCE_FIELDS = (
    "source_id",
    "source_level",
    "source_type",
    "source_name",
    "source_locator",
    "source_tag",
    "source_url",
    "publication_date",
    "retrieval_date",
)
CHRONOLOGY_FIELDS = (
    "financial_statement_date",
    "latest_financial_filing_date",
    "market_price_date",
    "subsequent_event_index_review_through",
)
JUDGMENT_PATHS = (
    "investment_question",
    "research_workflow_status",
    "public_data_investment_view",
    "decision_confidence",
    "current_action",
    "core_investment_view",
    "what_is_priced_in",
    "key_debates",
    "decision_rules",
    "thesis_breaks",
    "capital_allocation_status",
    "management_guidance_status",
    "valuation_status",
)
OPERATORS = {
    "LT": lambda value, threshold: value < threshold,
    "LTE": lambda value, threshold: value <= threshold,
    "GT": lambda value, threshold: value > threshold,
    "GTE": lambda value, threshold: value >= threshold,
    "EQ": lambda value, threshold: math.isclose(value, threshold, rel_tol=0, abs_tol=1e-12),
    "NEQ": lambda value, threshold: not math.isclose(value, threshold, rel_tol=0, abs_tol=1e-12),
}

ASSESSMENT_LABELS = {
    "STRENGTHENING": ("Strengthening", "正在强化"),
    "UNCHANGED": ("Unchanged", "未发现触发性变化"),
    "WEAKENING": ("Weakening", "正在转弱"),
    "MIXED": ("Mixed", "信号混合"),
    "POTENTIALLY_BROKEN": ("Potentially Broken", "可能已经失效"),
    "NOT_EVALUATED": ("Not Evaluated", "未完成评估"),
}


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check(
    check_id: str,
    passed: bool,
    detail: str,
    remediation: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "PASS" if passed else "FAIL",
        "severity": "INFO" if passed else "HARD_STOP",
        "detail": detail,
        "remediation": remediation,
    }


def _contract_hash_valid(contract: dict[str, Any]) -> tuple[bool, str]:
    stored = str(contract.get("contract_hash") or "")
    payload = {
        key: value
        for key, value in contract.items()
        if key not in {"contract_hash", "contract_validation"}
    }
    calculated = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return bool(stored) and stored == calculated, calculated


def _contract_checks(label: str, contract: Any) -> list[dict[str, Any]]:
    if not isinstance(contract, dict):
        return [
            _check(
                f"S15-{label}-mapping",
                False,
                "Input is not a JSON object.",
                "Provide the exact validated underwriting_output_contract.json.",
            )
        ]
    try:
        validation_errors = validate_output_contract(contract)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        validation_errors = [f"validator_exception:{exc}"]
    stored_status = contract.get("contract_validation", {}).get("status")
    hash_valid, calculated = _contract_hash_valid(contract)
    records = contract.get("evidence_records", [])
    metric_keys = [
        str(row.get("metric_name") or "")
        for row in records
        if isinstance(row, dict)
    ]
    unique_metrics = all(metric_keys) and len(metric_keys) == len(set(metric_keys))
    identity_sets = {
        "source_id": [
            str(row.get("source_id") or "")
            for row in contract.get("source_registry", [])
            if isinstance(row, dict)
        ],
        "warning_id": [
            str(row.get("check_id") or row.get("id") or "")
            for row in contract.get("warnings", [])
            if isinstance(row, dict)
        ],
        "hard_stop_id": [
            str(row.get("check_id") or row.get("id") or "")
            for row in contract.get("hard_stops", [])
            if isinstance(row, dict)
        ],
        "scenario_name": [
            str(row.get("name") or "")
            for row in contract.get("scenarios", [])
            if isinstance(row, dict)
        ],
    }
    stable_identities = all(
        all(values) and len(values) == len(set(values))
        for values in identity_sets.values()
        if values
    )
    return [
        _check(
            f"S15-{label}-contract-validation",
            stored_status == "PASS" and not validation_errors,
            f"stored_status={stored_status}; current_error_count={len(validation_errors)}",
            "Rebuild and validate the issuer contract before monitoring.",
        ),
        _check(
            f"S15-{label}-contract-hash",
            hash_valid,
            f"stored={contract.get('contract_hash')}; calculated={calculated}",
            "Use the immutable validated contract; do not edit a completed contract in place.",
        ),
        _check(
            f"S15-{label}-metric-identity",
            unique_metrics,
            f"evidence_record_count={len(metric_keys)}; unique_metric_count={len(set(metric_keys))}",
            "Resolve duplicate or missing evidence class/metric identities in the shared issuer contract.",
        ),
        _check(
            f"S15-{label}-comparison-identities",
            stable_identities,
            "; ".join(
                f"{name}={len(values)}/{len(set(values))}"
                for name, values in identity_sets.items()
            ),
            "Resolve duplicate or missing source, issue, or scenario identities before monitoring.",
        ),
    ]


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _identity(contract: dict[str, Any]) -> dict[str, Any]:
    company = contract.get("company", {})
    dates = contract.get("report_dates", {})
    return {
        "schema_version": contract.get("schema_version"),
        "report_id": contract.get("report_id"),
        "contract_hash": contract.get("contract_hash"),
        "cik": company.get("cik"),
        "ticker": company.get("ticker"),
        "financial_statement_date": dates.get("financial_statement_date"),
        "latest_financial_filing_date": dates.get("latest_financial_filing_date"),
        "market_price_date": dates.get("market_price_date"),
        "subsequent_event_index_review_through": dates.get(
            "subsequent_event_index_review_through"
        ),
        "analysis_generated_at": dates.get("analysis_generated_at"),
        "data_gate": contract.get("data_gate", {}).get("level"),
    }


def _snapshot_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": row.get("evidence_id"),
        "metric_name": row.get("metric_name"),
        **{field: copy.deepcopy(row.get(field)) for field in COMPARISON_FIELDS},
        **{field: copy.deepcopy(row.get(field)) for field in SOURCE_FIELDS},
    }


def _metric_index(contract: dict[str, Any], evidence_class: str | None = None) -> dict[str, dict[str, Any]]:
    rows = [
        row
        for row in contract.get("evidence_records", [])
        if isinstance(row, dict)
        and (evidence_class is None or row.get("evidence_class") == evidence_class)
    ]
    return {str(row.get("metric_name")): row for row in rows}


def _numeric_delta(
    previous: dict[str, Any], current: dict[str, Any]
) -> tuple[str, float | None, float | None, str]:
    previous_value = finite_number(previous.get("value"))
    current_value = finite_number(current.get("value"))
    dimensions_match = all(
        previous.get(field) == current.get(field)
        for field in ("unit", "currency", "scale")
    )
    if previous_value is None or current_value is None:
        return "NOT_COMPARABLE", None, None, "Values are not both finite numbers."
    if not dimensions_match:
        return "NOT_COMPARABLE", None, None, "Unit, currency, or scale changed."
    absolute = current_value - previous_value
    if previous_value <= 0:
        return (
            "COMPARABLE_ABSOLUTE_ONLY",
            absolute,
            None,
            "Percent change suppressed because the prior denominator is zero or negative.",
        )
    return "COMPARABLE", absolute, absolute / previous_value, ""


def _compare_record_class(
    previous_contract: dict[str, Any],
    current_contract: dict[str, Any],
    evidence_class: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    previous = _metric_index(previous_contract, evidence_class)
    current = _metric_index(current_contract, evidence_class)
    changes: list[dict[str, Any]] = []
    counts = {"compared": len(set(previous) | set(current)), "added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    for metric_name in sorted(set(previous) | set(current)):
        old = previous.get(metric_name)
        new = current.get(metric_name)
        if old is None:
            change_type = "ADDED"
            counts["added"] += 1
        elif new is None:
            change_type = "REMOVED"
            counts["removed"] += 1
        else:
            changed_fields = [
                field
                for field in COMPARISON_FIELDS + SOURCE_FIELDS
                if canonical_json(old.get(field)) != canonical_json(new.get(field))
            ]
            change_type = "CHANGED" if changed_fields else "UNCHANGED"
            counts[change_type.lower()] += 1
            if change_type == "UNCHANGED":
                continue
        changed_fields = [] if old is None or new is None else [
            field
            for field in COMPARISON_FIELDS + SOURCE_FIELDS
            if canonical_json(old.get(field)) != canonical_json(new.get(field))
        ]
        comparability = "NOT_APPLICABLE"
        absolute_change = None
        percent_change = None
        limitation = ""
        if old is not None and new is not None:
            comparability, absolute_change, percent_change, limitation = _numeric_delta(old, new)
        changes.append(
            {
                "change_id": stable_id("MON-CHANGE", evidence_class, metric_name, change_type, old and old.get("evidence_id"), new and new.get("evidence_id")),
                "evidence_class": evidence_class,
                "metric_name": metric_name,
                "change_type": change_type,
                "changed_fields": changed_fields,
                "previous": _snapshot_record(old) if old else None,
                "current": _snapshot_record(new) if new else None,
                "comparability_status": comparability,
                "absolute_change": absolute_change,
                "percent_change": percent_change,
                "comparison_limitation": limitation,
            }
        )
    return changes, counts


def _compare_judgments(
    previous_contract: dict[str, Any], current_contract: dict[str, Any]
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for path in JUDGMENT_PATHS:
        old = previous_contract.get(path)
        new = current_contract.get(path)
        if canonical_json(old) == canonical_json(new):
            continue
        changes.append(
            {
                "change_id": stable_id("MON-JUDGMENT", path, canonical_hash(old), canonical_hash(new)),
                "field_path": path,
                "change_type": "CHANGED" if old is not None and new is not None else ("ADDED" if old is None else "REMOVED"),
                "evidence_class": "JUDGMENT",
                "previous_value": copy.deepcopy(old),
                "current_value": copy.deepcopy(new),
                "previous_hash": canonical_hash(old),
                "current_hash": canonical_hash(new),
                "requires_human_interpretation": True,
            }
        )
    for evidence_class in ("INFERENCE", "JUDGMENT"):
        record_changes, _ = _compare_record_class(
            previous_contract, current_contract, evidence_class
        )
        for row in record_changes:
            row["field_path"] = f"evidence_records.{row['metric_name']}"
            row["requires_human_interpretation"] = True
        changes.extend(record_changes)
    return changes


def _source_index(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("source_id")): row
        for row in contract.get("source_registry", [])
        if isinstance(row, dict) and row.get("source_id")
    }


def _compare_evidence(
    previous_contract: dict[str, Any], current_contract: dict[str, Any]
) -> dict[str, Any]:
    previous_records = _metric_index(previous_contract)
    current_records = _metric_index(current_contract)
    metric_source_changes: list[dict[str, Any]] = []
    for metric in sorted(set(previous_records) & set(current_records)):
        old = previous_records[metric]
        new = current_records[metric]
        old_source = {field: old.get(field) for field in SOURCE_FIELDS}
        new_source = {field: new.get(field) for field in SOURCE_FIELDS}
        if canonical_json(old_source) != canonical_json(new_source):
            metric_source_changes.append(
                {
                    "change_id": stable_id("MON-EVIDENCE", metric, old.get("evidence_id"), new.get("evidence_id")),
                    "metric_name": metric,
                    "previous_evidence_id": old.get("evidence_id"),
                    "current_evidence_id": new.get("evidence_id"),
                    "previous_source": old_source,
                    "current_source": new_source,
                }
            )

    previous_sources = _source_index(previous_contract)
    current_sources = _source_index(current_contract)
    source_changes: list[dict[str, Any]] = []
    for source_id in sorted(set(previous_sources) | set(current_sources)):
        old = previous_sources.get(source_id)
        new = current_sources.get(source_id)
        if canonical_json(old) == canonical_json(new):
            continue
        source_changes.append(
            {
                "change_id": stable_id("MON-SOURCE", source_id, canonical_hash(old), canonical_hash(new)),
                "source_id": source_id,
                "change_type": "ADDED" if old is None else ("REMOVED" if new is None else "CHANGED"),
                "previous": copy.deepcopy(old),
                "current": copy.deepcopy(new),
            }
        )

    previous_ids = {
        str(row.get("evidence_id"))
        for row in previous_contract.get("evidence_records", [])
        if isinstance(row, dict) and row.get("evidence_id")
    }
    current_ids = {
        str(row.get("evidence_id"))
        for row in current_contract.get("evidence_records", [])
        if isinstance(row, dict) and row.get("evidence_id")
    }
    missing_changes, missing_counts = _compare_record_class(
        previous_contract, current_contract, "MISSING"
    )
    return {
        "added_evidence_ids": sorted(current_ids - previous_ids),
        "removed_evidence_ids": sorted(previous_ids - current_ids),
        "metric_source_changes": metric_source_changes,
        "source_registry_changes": source_changes,
        "missing_evidence_changes": missing_changes,
        "summary": {
            "added_evidence_count": len(current_ids - previous_ids),
            "removed_evidence_count": len(previous_ids - current_ids),
            "metric_source_change_count": len(metric_source_changes),
            "source_registry_change_count": len(source_changes),
            "missing_evidence_change_count": len(missing_changes),
            "missing_evidence_compared_count": missing_counts["compared"],
        },
    }


def _issue_snapshot(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        key: copy.deepcopy(row.get(key))
        for key in (
            "check_id",
            "category",
            "status",
            "issue_class",
            "severity",
            "message",
            "decision_impact",
            "remediation",
            "evidence_ids",
            "scope",
        )
    }


def _compare_issues(
    previous_contract: dict[str, Any],
    current_contract: dict[str, Any],
    field: str,
) -> list[dict[str, Any]]:
    previous = {
        str(row.get("check_id") or row.get("id")): row
        for row in previous_contract.get(field, [])
        if isinstance(row, dict) and (row.get("check_id") or row.get("id"))
    }
    current = {
        str(row.get("check_id") or row.get("id")): row
        for row in current_contract.get(field, [])
        if isinstance(row, dict) and (row.get("check_id") or row.get("id"))
    }
    changes: list[dict[str, Any]] = []
    for check_id in sorted(set(previous) | set(current)):
        old = previous.get(check_id)
        new = current.get(check_id)
        if canonical_json(old) == canonical_json(new):
            continue
        change_type = "ADDED" if old is None else ("RESOLVED" if new is None else "CHANGED")
        changes.append(
            {
                "change_id": stable_id("MON-ISSUE", field, check_id, change_type, canonical_hash(old), canonical_hash(new)),
                "check_id": check_id,
                "change_type": change_type,
                "previous": _issue_snapshot(old),
                "current": _issue_snapshot(new),
            }
        )
    return changes


def _rule_active(rule: dict[str, Any], as_of: date) -> bool:
    effective = parse_iso_date(rule.get("effective_date"))
    expiration = parse_iso_date(rule.get("expiration_date"))
    return bool(effective and expiration and effective <= as_of <= expiration)


def _dimensions_match(rule: dict[str, Any], record: dict[str, Any]) -> bool:
    expected_unit = str(rule.get("unit") or "")
    expected_currency = str(rule.get("currency") or "")
    return (
        (not expected_unit or expected_unit == str(record.get("unit") or ""))
        and (not expected_currency or expected_currency == str(record.get("currency") or ""))
    )


def _evaluate_kpis(
    previous_contract: dict[str, Any],
    current_contract: dict[str, Any],
    policy: dict[str, Any],
    as_of: date,
) -> list[dict[str, Any]]:
    previous = _metric_index(previous_contract)
    current = _metric_index(current_contract)
    assessments: list[dict[str, Any]] = []
    for rule in policy.get("kpi_rules", []):
        metric_name = str(rule.get("metric_name"))
        old = previous.get(metric_name)
        new = current.get(metric_name)
        status = "NOT_TRIGGERED"
        evaluated_value = None
        limitation = ""
        if not _rule_active(rule, as_of):
            status = "EXPIRED"
            limitation = "The reviewer-approved KPI rule is not active on the monitoring date."
        elif new is None or new.get("evidence_class") != rule.get("evidence_class"):
            status = "MISSING"
            limitation = "The current contract lacks the required class/metric identity."
        elif not _dimensions_match(rule, new):
            status = "NOT_COMPARABLE"
            limitation = "The current metric unit or currency does not match the approved KPI rule."
        else:
            current_value = finite_number(new.get("value"))
            previous_value = finite_number(old.get("value")) if old else None
            basis = rule.get("comparison_basis")
            if current_value is None:
                status = "NOT_COMPARABLE"
                limitation = "The current KPI value is not a finite number."
            elif basis == "CURRENT_VALUE":
                evaluated_value = current_value
            elif old is None or previous_value is None or not _dimensions_match(rule, old):
                status = "MISSING" if old is None else "NOT_COMPARABLE"
                limitation = "The prior comparable KPI value is unavailable."
            elif basis == "ABSOLUTE_CHANGE":
                evaluated_value = current_value - previous_value
            elif basis == "PERCENT_CHANGE":
                if previous_value <= 0:
                    status = "NOT_COMPARABLE"
                    limitation = "Percent-change KPI suppressed because the prior denominator is zero or negative."
                else:
                    evaluated_value = (current_value - previous_value) / previous_value
            else:
                status = "NOT_COMPARABLE"
                limitation = "Unsupported KPI comparison basis."
            if evaluated_value is not None:
                operator = OPERATORS.get(str(rule.get("operator")))
                threshold = finite_number(rule.get("threshold"))
                if operator is None or threshold is None:
                    status = "NOT_COMPARABLE"
                    limitation = "The KPI operator or threshold is invalid."
                else:
                    status = "TRIGGERED" if operator(evaluated_value, threshold) else "NOT_TRIGGERED"
        assessments.append(
            {
                "assessment_id": stable_id("MON-KPI", rule.get("kpi_id"), old and old.get("evidence_id"), new and new.get("evidence_id"), status),
                "kpi_id": rule.get("kpi_id"),
                "metric_name": metric_name,
                "evidence_class": rule.get("evidence_class"),
                "comparison_basis": rule.get("comparison_basis"),
                "operator": rule.get("operator"),
                "threshold": rule.get("threshold"),
                "unit": rule.get("unit"),
                "currency": rule.get("currency"),
                "trigger_type": rule.get("trigger_type"),
                "status": status,
                "evaluated_value": evaluated_value,
                "previous_value": old.get("value") if old else None,
                "current_value": new.get("value") if new else None,
                "previous_evidence_id": old.get("evidence_id") if old else None,
                "current_evidence_id": new.get("evidence_id") if new else None,
                "rationale": rule.get("rationale"),
                "reviewed_by": rule.get("reviewed_by"),
                "limitation": limitation,
            }
        )
    return assessments


def _scenario_impact(
    previous_contract: dict[str, Any],
    current_contract: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    threshold = finite_number(policy.get("scenario_materiality_threshold_pct"))
    previous = {
        str(row.get("name")): row
        for row in previous_contract.get("scenarios", [])
        if isinstance(row, dict) and row.get("name")
    }
    current = {
        str(row.get("name")): row
        for row in current_contract.get("scenarios", [])
        if isinstance(row, dict) and row.get("name")
    }
    rows: list[dict[str, Any]] = []
    for name in sorted(set(previous) | set(current)):
        old = previous.get(name)
        new = current.get(name)
        if old is None or new is None:
            rows.append(
                {
                    "scenario": name,
                    "status": "ADDED" if old is None else "REMOVED",
                    "previous_implied_price": old and old.get("implied_price"),
                    "current_implied_price": new and new.get("implied_price"),
                    "implied_price_change": None,
                    "implied_price_change_pct": None,
                    "changed_assumption_fields": [],
                    "probability_change": None,
                    "limitation": "A scenario was added or removed and is not directly comparable.",
                }
            )
            continue
        comparable = (
            old.get("metric") == new.get("metric")
            and previous_contract.get("market_snapshot", {}).get("currency")
            == current_contract.get("market_snapshot", {}).get("currency")
            and previous_contract.get("return_context", {}).get("target_date")
            == current_contract.get("return_context", {}).get("target_date")
        )
        old_price = finite_number(old.get("implied_price"))
        new_price = finite_number(new.get("implied_price"))
        price_change = None
        price_change_pct = None
        limitation = ""
        status = "UNCHANGED"
        if not comparable or old_price is None or new_price is None or old_price <= 0:
            status = "NOT_COMPARABLE"
            limitation = "Scenario metric, currency, horizon, or positive implied-price basis is not comparable."
        else:
            price_change = new_price - old_price
            price_change_pct = price_change / old_price
            status = "CHANGED" if not math.isclose(price_change, 0, rel_tol=0, abs_tol=1e-12) else "UNCHANGED"
        assumption_fields = (
            "metric_per_share",
            "growth_assumption",
            "exit_multiple_factor",
            "exit_multiple",
            "key_driver",
            "falsification_trigger",
        )
        rows.append(
            {
                "scenario": name,
                "status": status,
                "previous_implied_price": old.get("implied_price"),
                "current_implied_price": new.get("implied_price"),
                "implied_price_change": price_change,
                "implied_price_change_pct": price_change_pct,
                "changed_assumption_fields": [
                    field
                    for field in assumption_fields
                    if canonical_json(old.get(field)) != canonical_json(new.get(field))
                ],
                "probability_change": (
                    finite_number(new.get("probability")) - finite_number(old.get("probability"))
                    if finite_number(new.get("probability")) is not None
                    and finite_number(old.get("probability")) is not None
                    else None
                ),
                "limitation": limitation,
            }
        )
    base = next((row for row in rows if row.get("scenario") == "Base"), None)
    base_change = base and finite_number(base.get("implied_price_change_pct"))
    if threshold is None:
        overall = "NOT_EVALUATED"
    elif base_change is None:
        overall = "NOT_COMPARABLE"
    elif base_change <= -threshold:
        overall = "MATERIAL_DOWNSIDE_SHIFT"
    elif base_change >= threshold:
        overall = "MATERIAL_UPSIDE_SHIFT"
    else:
        signs = {
            1 if (finite_number(row.get("implied_price_change_pct")) or 0) >= threshold else -1
            for row in rows
            if abs(finite_number(row.get("implied_price_change_pct")) or 0) >= threshold
        }
        overall = "MIXED" if len(signs) > 1 else "NO_MATERIAL_BASE_SHIFT"
    return {
        "status": "EVALUATED",
        "overall_impact": overall,
        "materiality_threshold_pct": threshold,
        "rows": rows,
        "formal_expected_return_recalculated": False,
        "probabilities_used_for_thesis_assessment": False,
        "disclosure": "Scenario impact compares disclosed scenario sensitivities. It is not a formal return or an automatically approved thesis change. / 情景影响比较已披露的情景敏感性，不属于正式回报或自动获批的 thesis 变更。",
    }


def _probability_expiration(
    previous_contract: dict[str, Any],
    current_contract: dict[str, Any],
    policy: dict[str, Any],
    as_of: date,
) -> dict[str, Any]:
    probability = current_contract.get("probability_validation") or {}
    probability_status = str(probability.get("status") or "NOT_PROVIDED")
    as_of_date = parse_iso_date(probability.get("as_of_date"))
    expiration = parse_iso_date(probability.get("expiration_review_date"))
    declared_triggers = set(probability.get("review_triggers") or [])
    observed_triggers: list[str] = []
    previous_dates = previous_contract.get("report_dates", {})
    current_dates = current_contract.get("report_dates", {})
    if any(
        parse_iso_date(current_dates.get(field))
        and parse_iso_date(previous_dates.get(field))
        and parse_iso_date(current_dates.get(field)) > parse_iso_date(previous_dates.get(field))
        for field in ("financial_statement_date", "latest_financial_filing_date")
    ) or canonical_json(previous_contract.get("management_guidance_status")) != canonical_json(
        current_contract.get("management_guidance_status")
    ):
        observed_triggers.append("NEW_EARNINGS_OR_GUIDANCE")
    if canonical_json(previous_contract.get("capital_allocation_status")) != canonical_json(
        current_contract.get("capital_allocation_status")
    ):
        observed_triggers.append("MATERIAL_CAPITAL_ALLOCATION")
    if any(
        canonical_json(previous_contract.get(field)) != canonical_json(current_contract.get(field))
        for field in ("credit_constraint_status", "liquidity_status")
    ):
        observed_triggers.append("COVENANT_OR_REFINANCING_CHANGE")
    triggered_review_events = sorted(declared_triggers.intersection(observed_triggers))

    days_to_expiration = (expiration - as_of).days if expiration else None
    warning_days = int(policy.get("probability_review_warning_days", 0))
    if probability_status in {"", "NOT_PROVIDED"}:
        status = "NOT_PROVIDED"
    elif as_of_date is None or expiration is None or expiration < as_of_date:
        status = "INVALID"
    elif triggered_review_events:
        status = "REVIEW_REQUIRED"
    elif expiration < as_of or probability.get("freshness_status") in {"STALE", "SUPERSEDED"}:
        status = "EXPIRED"
    elif days_to_expiration is not None and days_to_expiration <= warning_days:
        status = "EXPIRING_SOON"
    else:
        status = "CURRENT"
    formal_eligible = (
        probability_status == "VALIDATED"
        and status in {"CURRENT", "EXPIRING_SOON"}
        and probability.get("approval", {}).get("status") == "APPROVED"
    )
    return {
        "status": status,
        "contract_probability_status": probability_status,
        "contract_probability_approval_status": probability.get("approval", {}).get("status"),
        "probability_as_of_date": probability.get("as_of_date"),
        "probability_expiration_review_date": probability.get("expiration_review_date"),
        "days_to_expiration": days_to_expiration,
        "warning_window_days": warning_days,
        "declared_review_triggers": sorted(declared_triggers),
        "observed_update_events": sorted(observed_triggers),
        "triggered_review_events": triggered_review_events,
        "formal_probability_outputs_remain_eligible": formal_eligible,
        "requires_human_probability_review": status in {"EXPIRING_SOON", "EXPIRED", "REVIEW_REQUIRED", "INVALID"},
    }


def _system_thesis_assessment(
    kpis: list[dict[str, Any]],
    hard_stop_changes: list[dict[str, Any]],
    current_contract: dict[str, Any],
    scenario_impact: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    current_hard_stops = current_contract.get("hard_stops", [])
    reasons: list[dict[str, Any]] = []
    supporting_ids: list[str] = []
    if current_hard_stops:
        assessment = "NOT_EVALUATED"
        reasons.append(
            {
                "reason_code": "CURRENT_HARD_STOP",
                "message_en": "A current data-integrity Hard Stop blocks thesis reassessment.",
                "message_zh": "当前数据完整性 Hard Stop 阻止 thesis 重新评估。",
            }
        )
        supporting_ids.extend(
            row["change_id"]
            for row in hard_stop_changes
            if row.get("change_type") in {"ADDED", "CHANGED"}
        )
    else:
        triggered = [row for row in kpis if row.get("status") == "TRIGGERED"]
        thesis_breaks = [row for row in triggered if row.get("trigger_type") == "THESIS_BREAK"]
        upgrades = [row for row in triggered if row.get("trigger_type") == "UPGRADE"]
        downgrades = [row for row in triggered if row.get("trigger_type") == "DOWNGRADE"]
        if thesis_breaks:
            assessment = "POTENTIALLY_BROKEN"
        elif upgrades and downgrades:
            assessment = "MIXED"
        elif downgrades:
            assessment = "WEAKENING"
        elif upgrades:
            assessment = "STRENGTHENING"
        else:
            evaluable = [row for row in kpis if row.get("status") in {"TRIGGERED", "NOT_TRIGGERED"}]
            assessment = "UNCHANGED" if evaluable else "NOT_EVALUATED"
        for row in thesis_breaks + downgrades + upgrades:
            reasons.append(
                {
                    "reason_code": f"KPI_{row.get('trigger_type')}_TRIGGERED",
                    "message_en": f"Approved KPI rule {row.get('kpi_id')} was triggered.",
                    "message_zh": f"已审批 KPI 规则 {row.get('kpi_id')} 被触发。",
                }
            )
            supporting_ids.append(str(row.get("assessment_id")))

        if policy.get("scenario_changes_affect_system_assessment") is True:
            impact = scenario_impact.get("overall_impact")
            scenario_direction = {
                "MATERIAL_DOWNSIDE_SHIFT": "WEAKENING",
                "MATERIAL_UPSIDE_SHIFT": "STRENGTHENING",
                "MIXED": "MIXED",
            }.get(str(impact))
            if scenario_direction:
                if assessment == "UNCHANGED":
                    assessment = scenario_direction
                elif assessment not in {scenario_direction, "POTENTIALLY_BROKEN", "NOT_EVALUATED"}:
                    assessment = "MIXED"
                reasons.append(
                    {
                        "reason_code": f"SCENARIO_{impact}",
                        "message_en": "The reviewer-approved policy permits a material scenario shift to inform the provisional system assessment.",
                        "message_zh": "经复核批准的 policy 允许重大情景变化影响 provisional system assessment。",
                    }
                )
    if not reasons:
        reasons.append(
            {
                "reason_code": "NO_APPROVED_TRIGGER",
                "message_en": "No approved KPI or scenario trigger changed the provisional system view.",
                "message_zh": "没有已审批的 KPI 或情景触发条件改变 provisional system view。",
            }
        )
    label_en, label_zh = ASSESSMENT_LABELS[assessment]
    return {
        "assessment": assessment,
        "label_en": label_en,
        "label_zh": label_zh,
        "is_formal_thesis_status": False,
        "requires_human_review": True,
        "reasons": reasons,
        "supporting_change_ids": sorted(set(supporting_ids)),
        "disclosure": "This is a rules-based system assessment, not a formal thesis decision. / 这是基于规则的系统评估，不是正式 thesis 决策。",
    }


def _finalize(payload: dict[str, Any]) -> dict[str, Any]:
    payload["contract_validation"] = {"status": "PENDING", "errors": []}
    payload["monitoring_hash"] = calculate_monitoring_hash(payload)
    errors = validate_monitoring_output(payload)
    payload["contract_validation"] = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    return payload


def _empty_change_summary() -> dict[str, Any]:
    return {
        "fact_metrics": {"compared": 0, "added": 0, "removed": 0, "changed": 0, "unchanged": 0},
        "calculation_metrics": {"compared": 0, "added": 0, "removed": 0, "changed": 0, "unchanged": 0},
        "judgment_change_count": 0,
        "warning_change_count": 0,
        "hard_stop_change_count": 0,
        "current_active_hard_stop_count": 0,
        "kpi_trigger_count": 0,
    }


def build_monitoring_update(
    previous_contract: dict[str, Any],
    current_contract: dict[str, Any],
    policy: dict[str, Any],
    monitoring_as_of_date: str,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compare two immutable issuer contracts and return the S15 output."""

    generated_at = generated_at or utc_now()
    as_of = parse_iso_date(monitoring_as_of_date)
    checks = _contract_checks("previous", previous_contract)
    checks.extend(_contract_checks("current", current_contract))
    policy_errors = validate_monitoring_policy(policy) if isinstance(policy, dict) else ["policy_not_mapping"]
    checks.append(
        _check(
            "S15-policy-validation",
            not policy_errors,
            f"error_count={len(policy_errors)}; errors={policy_errors}",
            "Provide a current reviewer-approved monitoring policy with explicit KPI and scenario controls.",
        )
    )
    checks.append(
        _check(
            "S15-monitoring-date",
            as_of is not None,
            f"monitoring_as_of_date={monitoring_as_of_date}",
            "Provide an explicit ISO monitoring as-of date.",
        )
    )

    previous_company = previous_contract.get("company", {}) if isinstance(previous_contract, dict) else {}
    current_company = current_contract.get("company", {}) if isinstance(current_contract, dict) else {}
    same_issuer = bool(previous_company.get("cik")) and previous_company.get("cik") == current_company.get("cik")
    checks.append(
        _check(
            "S15-issuer-identity",
            same_issuer,
            f"previous_cik={previous_company.get('cik')}; current_cik={current_company.get('cik')}",
            "Compare contracts for the same SEC issuer identity; ticker text alone is insufficient.",
        )
    )
    policy_identity_match = bool(current_company.get("cik")) and str(policy.get("issuer_identifier")) == str(current_company.get("cik"))
    checks.append(
        _check(
            "S15-policy-issuer-identity",
            policy_identity_match,
            f"policy_issuer={policy.get('issuer_identifier')}; contract_cik={current_company.get('cik')}",
            "Use a reviewer-approved policy for the exact SEC issuer identity.",
        )
    )

    previous_dates = previous_contract.get("report_dates", {}) if isinstance(previous_contract, dict) else {}
    current_dates = current_contract.get("report_dates", {}) if isinstance(current_contract, dict) else {}
    chronology_errors: list[str] = []
    for field in CHRONOLOGY_FIELDS:
        old = parse_iso_date(previous_dates.get(field))
        new = parse_iso_date(current_dates.get(field))
        if old is None or new is None:
            chronology_errors.append(f"missing_or_invalid:{field}")
        elif new < old:
            chronology_errors.append(f"regressed:{field}")
    previous_generated = _parse_iso_datetime(previous_dates.get("analysis_generated_at"))
    current_generated = _parse_iso_datetime(current_dates.get("analysis_generated_at"))
    if previous_generated is None or current_generated is None:
        chronology_errors.append("missing_or_invalid:analysis_generated_at")
    elif current_generated < previous_generated:
        chronology_errors.append("regressed:analysis_generated_at")
    current_relevant_dates = [
        value
        for value in (parse_iso_date(current_dates.get(field)) for field in CHRONOLOGY_FIELDS)
        if value is not None
    ]
    if as_of and current_relevant_dates and as_of < max(current_relevant_dates):
        chronology_errors.append("monitoring_date_precedes_current_contract")
    checks.append(
        _check(
            "S15-contract-chronology",
            not chronology_errors,
            f"errors={chronology_errors}",
            "Correct regressed or future-dated report periods before monitoring.",
        )
    )
    policy_effective = parse_iso_date(policy.get("effective_date"))
    policy_expiration = parse_iso_date(policy.get("expiration_date"))
    policy_current = bool(as_of and policy_effective and policy_expiration and policy_effective <= as_of <= policy_expiration)
    checks.append(
        _check(
            "S15-policy-freshness",
            policy_current,
            f"effective={policy.get('effective_date')}; expiration={policy.get('expiration_date')}; as_of={monitoring_as_of_date}",
            "Obtain a fresh reviewer-approved monitoring policy; do not extend dates automatically.",
        )
    )

    blocked = any(row["status"] == "FAIL" for row in checks)
    base_payload: dict[str, Any] = {
        "monitoring_output_contract_version": MONITORING_OUTPUT_CONTRACT_VERSION,
        "monitoring_engine_version": MONITORING_ENGINE_VERSION,
        "generated_at": generated_at,
        "requested_monitoring_as_of_date": monitoring_as_of_date,
        "monitoring_as_of_date": as_of.isoformat() if as_of else None,
        "status": "MONITORING_BLOCKED" if blocked else "MONITORING_COMPLETE",
        "issuer_identity": copy.deepcopy(current_company),
        "previous_contract_identity": _identity(previous_contract) if isinstance(previous_contract, dict) else {},
        "current_contract_identity": _identity(current_contract) if isinstance(current_contract, dict) else {},
        "policy_identity": {
            "policy_id": policy.get("policy_id") if isinstance(policy, dict) else None,
            "policy_hash": canonical_hash(policy) if isinstance(policy, dict) else None,
            "issuer_identifier": policy.get("issuer_identifier") if isinstance(policy, dict) else None,
            "effective_date": policy.get("effective_date") if isinstance(policy, dict) else None,
            "expiration_date": policy.get("expiration_date") if isinstance(policy, dict) else None,
            "reviewed_by": policy.get("reviewed_by") if isinstance(policy, dict) else None,
            "review_status": policy.get("review_status") if isinstance(policy, dict) else None,
            "probability_review_warning_days": policy.get("probability_review_warning_days") if isinstance(policy, dict) else None,
            "scenario_materiality_threshold_pct": policy.get("scenario_materiality_threshold_pct") if isinstance(policy, dict) else None,
            "scenario_changes_affect_system_assessment": policy.get("scenario_changes_affect_system_assessment") if isinstance(policy, dict) else None,
        },
        "input_validation": {
            "status": "FAIL" if blocked else "PASS",
            "checks": checks,
            "hard_stop_count": sum(row["status"] == "FAIL" for row in checks),
        },
        "change_summary": _empty_change_summary(),
        "fact_changes": [],
        "calculation_changes": [],
        "judgment_changes": [],
        "evidence_changes": {
            "added_evidence_ids": [],
            "removed_evidence_ids": [],
            "metric_source_changes": [],
            "source_registry_changes": [],
            "missing_evidence_changes": [],
            "summary": {},
        },
        "warning_changes": [],
        "hard_stop_changes": [],
        "kpi_assessments": [],
        "kpi_breach_summary": {
            "triggered_breach_count": 0,
            "upgrade_trigger_count": 0,
            "missing_or_not_comparable_count": 0,
            "breach_assessment_ids": [],
        },
        "scenario_impact": {
            "status": "NOT_EVALUATED",
            "overall_impact": "NOT_EVALUATED",
            "materiality_threshold_pct": None,
            "rows": [],
            "formal_expected_return_recalculated": False,
            "probabilities_used_for_thesis_assessment": False,
            "disclosure": "Suppressed because monitoring inputs did not pass validation. / 因监控输入未通过验证而被抑制。",
        },
        "probability_expiration": {
            "status": "INVALID" if blocked else "NOT_PROVIDED",
            "contract_probability_status": None,
            "contract_probability_approval_status": None,
            "probability_as_of_date": None,
            "probability_expiration_review_date": None,
            "days_to_expiration": None,
            "warning_window_days": policy.get("probability_review_warning_days") if isinstance(policy, dict) else None,
            "declared_review_triggers": [],
            "observed_update_events": [],
            "triggered_review_events": [],
            "formal_probability_outputs_remain_eligible": False,
            "requires_human_probability_review": True,
        },
        "system_thesis_assessment": {
            "assessment": "NOT_EVALUATED",
            "label_en": "Not Evaluated",
            "label_zh": "未完成评估",
            "is_formal_thesis_status": False,
            "requires_human_review": True,
            "reasons": [
                {
                    "reason_code": "INPUT_VALIDATION_BLOCKED",
                    "message_en": "Monitoring inputs did not pass the S15 validation gate.",
                    "message_zh": "监控输入未通过 S15 validation gate。",
                }
            ],
            "supporting_change_ids": [],
            "disclosure": "This is a rules-based system assessment, not a formal thesis decision. / 这是基于规则的系统评估，不是正式 thesis 决策。",
        },
        "formal_thesis_status": {
            "status": "PENDING_HUMAN_REVIEW",
            "selected_status": None,
            "allowed_human_statuses": sorted(FORMAL_THESIS_STATUSES),
            "reviewed_by": None,
            "reviewed_at": None,
            "review_rationale": None,
            "automatic_status_change_allowed": False,
        },
        "automatic_trade_execution": False,
    }
    if blocked:
        return _finalize(base_payload)

    fact_changes, fact_counts = _compare_record_class(previous_contract, current_contract, "FACT")
    calculation_changes, calculation_counts = _compare_record_class(previous_contract, current_contract, "CALC")
    judgment_changes = _compare_judgments(previous_contract, current_contract)
    evidence_changes = _compare_evidence(previous_contract, current_contract)
    warning_changes = _compare_issues(previous_contract, current_contract, "warnings")
    hard_stop_changes = _compare_issues(previous_contract, current_contract, "hard_stops")
    kpis = _evaluate_kpis(previous_contract, current_contract, policy, as_of)
    scenario = _scenario_impact(previous_contract, current_contract, policy)
    probability = _probability_expiration(previous_contract, current_contract, policy, as_of)
    assessment = _system_thesis_assessment(kpis, hard_stop_changes, current_contract, scenario, policy)
    breaches = [
        row
        for row in kpis
        if row.get("status") == "TRIGGERED"
        and row.get("trigger_type") in {"DOWNGRADE", "THESIS_BREAK"}
    ]
    upgrade_triggers = [
        row
        for row in kpis
        if row.get("status") == "TRIGGERED" and row.get("trigger_type") == "UPGRADE"
    ]
    unresolved_kpis = [
        row
        for row in kpis
        if row.get("status") in {"MISSING", "NOT_COMPARABLE", "EXPIRED"}
    ]

    base_payload.update(
        {
            "change_summary": {
                "fact_metrics": fact_counts,
                "calculation_metrics": calculation_counts,
                "judgment_change_count": len(judgment_changes),
                "warning_change_count": len(warning_changes),
                "hard_stop_change_count": len(hard_stop_changes),
                "current_active_hard_stop_count": len(current_contract.get("hard_stops", [])),
                "kpi_trigger_count": sum(row.get("status") == "TRIGGERED" for row in kpis),
            },
            "fact_changes": fact_changes,
            "calculation_changes": calculation_changes,
            "judgment_changes": judgment_changes,
            "evidence_changes": evidence_changes,
            "warning_changes": warning_changes,
            "hard_stop_changes": hard_stop_changes,
            "kpi_assessments": kpis,
            "kpi_breach_summary": {
                "triggered_breach_count": len(breaches),
                "upgrade_trigger_count": len(upgrade_triggers),
                "missing_or_not_comparable_count": len(unresolved_kpis),
                "breach_assessment_ids": [row["assessment_id"] for row in breaches],
            },
            "scenario_impact": scenario,
            "probability_expiration": probability,
            "system_thesis_assessment": assessment,
        }
    )
    return _finalize(base_payload)
