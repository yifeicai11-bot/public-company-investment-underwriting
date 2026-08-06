#!/usr/bin/env python3
"""Auditable, company-agnostic valuation cross-checks and probability governance.

S11 keeps peer, historical, reverse-valuation, independent DCF, and probability
governance calculations outside renderers. Unsupported or incomparable inputs
are suppressed rather than coerced into a ranking or fair-value conclusion.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from copy import deepcopy
from datetime import date
from math import isclose, isfinite
from typing import Any


VALUATION_CROSS_CHECK_CONTRACT_VERSION = "1.0.0"
PROBABILITY_GOVERNANCE_VERSION = "1.0.0"
VALUATION_CROSS_CHECK_STATUSES = {
    "NOT_PROVIDED",
    "INVALID",
    "PARTIALLY_VALIDATED",
    "MULTI_METHOD_VALIDATED",
}
COMPONENT_STATUSES = {
    "NOT_PROVIDED",
    "INVALID",
    "SUPPRESSED_INCOMPARABLE",
    "PARTIALLY_VALIDATED",
    "VALIDATED",
}
PEER_COMPARABILITY_STATUSES = {"COMPARABLE", "LIMITED", "NOT_COMPARABLE"}
SUPPORTED_VALUATION_METRICS = {
    "EV/SALES",
    "EV/EBITDA",
    "P/E",
    "P/FCF",
    "FCF_YIELD",
}
DENOMINATOR_POSITIVE_METRICS = {"EV/SALES", "EV/EBITDA", "P/E", "P/FCF", "FCF_YIELD"}
REVERSE_METHODS = {
    "EQUITY_FCF_MULTIPLE": ("MARKET_CAP", "P/FCF", "DIVIDE"),
    "EQUITY_EARNINGS_MULTIPLE": ("MARKET_CAP", "P/E", "DIVIDE"),
    "ENTERPRISE_VALUE_EBITDA_MULTIPLE": (
        "ENTERPRISE_VALUE",
        "EV/EBITDA",
        "DIVIDE",
    ),
    "ENTERPRISE_VALUE_REVENUE_MULTIPLE": (
        "ENTERPRISE_VALUE",
        "EV/SALES",
        "DIVIDE",
    ),
    "EQUITY_FCF_YIELD": ("MARKET_CAP", "FCF_YIELD", "MULTIPLY"),
}
PROBABILITY_METHOD_TYPES = {
    "HISTORICAL_FREQUENCY",
    "MANAGEMENT_GUIDANCE_CONFIDENCE",
    "SCENARIO_JUDGMENT",
    "MONTE_CARLO",
    "BASE_RATE_ANALYSIS",
}
PROBABILITY_METHOD_REQUIRED_DETAILS: dict[str, set[str]] = {
    "HISTORICAL_FREQUENCY": {
        "reference_class",
        "sample_period",
        "sample_size",
        "event_definition",
    },
    "MANAGEMENT_GUIDANCE_CONFIDENCE": {
        "guidance_track_record",
        "assessment_rule",
    },
    "SCENARIO_JUDGMENT": {
        "allocation_rationale",
        "sensitivity_completed",
    },
    "MONTE_CARLO": {
        "model_version",
        "iterations",
        "input_distributions",
    },
    "BASE_RATE_ANALYSIS": {
        "reference_class",
        "sample_period",
        "sample_size",
        "event_definition",
    },
}
PROBABILITY_STATUSES = {
    "NOT_PROVIDED",
    "ILLUSTRATIVE",
    "VALIDATED",
    "STALE",
    "INVALID",
}
INDEPENDENT_APPROVAL_SCOPE = "PROBABILITY_METHODOLOGY_AND_WEIGHTS"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _iso_date(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _same_number(
    actual: Any,
    expected: Any,
    *,
    relative: float = 1e-9,
    absolute: float = 1e-9,
) -> bool:
    actual_number = _number(actual)
    expected_number = _number(expected)
    return (
        actual_number is not None
        and expected_number is not None
        and isclose(
            actual_number,
            expected_number,
            rel_tol=relative,
            abs_tol=absolute,
        )
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _unique(values: Any) -> list[str]:
    return list(
        dict.fromkeys(
            str(value)
            for value in _as_list(values)
            if value not in (None, "")
        )
    )


def _metric_name(value: Any) -> str:
    metric = str(value or "").upper().replace(" ", "_")
    aliases = {
        "EV/REVENUE": "EV/SALES",
        "EV_REVENUE": "EV/SALES",
        "EV_SALES": "EV/SALES",
        "EV_EBITDA": "EV/EBITDA",
        "P_E": "P/E",
        "P_FCF": "P/FCF",
    }
    return aliases.get(metric, metric)


def _issue(
    code: str,
    message: str,
    path: str,
    *,
    status: str = "FAIL",
    issue_class: str = "WARNING",
    decision_impact: str = (
        "The affected valuation comparison or probability-weighted output remains unavailable."
    ),
) -> dict[str, str]:
    return {
        "code": code,
        "status": status,
        "issue_class": issue_class,
        "message": message,
        "path": path,
        "decision_impact": decision_impact,
        "remediation": "Correct the cited input, evidence, date, or governance field and rerun the shared S11 engine.",
        "scope": "shared_valuation_cross_check_engine",
    }


def _evidence_index(records: Any) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("evidence_id")): row
        for row in _as_list(records)
        if isinstance(row, dict) and row.get("evidence_id")
    }


def _record_date(record: dict[str, Any]) -> str | None:
    for field in ("as_of_date", "period_end", "publication_date", "period_start"):
        value = record.get(field)
        if _iso_date(value):
            return str(value)
    return None


def _availability_date(record: dict[str, Any]) -> str | None:
    for field in (
        "publication_date",
        "retrieval_date",
        "as_of_date",
        "period_end",
    ):
        value = record.get(field)
        if _iso_date(value):
            return str(value)
    return None


def _canonical_record_value(record: dict[str, Any]) -> float | None:
    value = _number(record.get("value"))
    scale = _number(record.get("scale"))
    if value is None:
        return None
    return value * (scale if scale is not None else 1.0)


def _record_passes(record: dict[str, Any]) -> bool:
    return str(record.get("validation_status") or "").upper() == "PASS"


def _exact_evidence_match(
    record: dict[str, Any],
    *,
    value: float,
    currency: str | None = None,
    unit: str | None = None,
    evidence_classes: set[str] | None = None,
) -> bool:
    evidence_class = str(
        record.get("evidence_class") or record.get("evidence_type") or ""
    ).upper()
    source_level = _number(record.get("source_level"))
    source_level_valid = (
        source_level is not None
        and int(source_level) == source_level
        and (
            int(source_level) in {1, 2, 3, 4}
            if evidence_class == "FACT"
            else int(source_level) in {0, 1, 2, 3, 4}
        )
    )
    if (
        not _record_passes(record)
        or not source_level_valid
        or (evidence_classes is not None and evidence_class not in evidence_classes)
        or not _same_number(_canonical_record_value(record), value)
        or _record_date(record) is None
    ):
        return False
    record_currency = str(record.get("currency") or "").upper()
    record_unit = str(record.get("unit") or "").upper()
    if (
        currency
        and currency.upper() != "SHARES"
        and record_currency != currency.upper()
    ):
        return False
    if unit and record_unit != unit.upper():
        return False
    return True


def _context_evidence_valid(
    evidence_ids: list[str],
    known: dict[str, dict[str, Any]],
    *,
    as_of_date: str | None = None,
) -> tuple[list[str], list[str], list[str]]:
    valid: list[str] = []
    unknown: list[str] = []
    future: list[str] = []
    for evidence_id in evidence_ids:
        record = known.get(evidence_id)
        if record is None:
            unknown.append(evidence_id)
            continue
        record_date = _record_date(record)
        availability_date = _availability_date(record)
        if (
            as_of_date
            and _iso_date(as_of_date)
            and availability_date
            and availability_date > as_of_date
        ):
            future.append(evidence_id)
            continue
        source_level = _number(record.get("source_level"))
        if (
            _record_passes(record)
            and record_date
            and source_level is not None
            and int(source_level) == source_level
            and int(source_level) in {0, 1, 2, 3, 4}
        ):
            valid.append(evidence_id)
    return valid, unknown, future


def _exact_binding_ids(
    evidence_ids: list[str],
    known: dict[str, dict[str, Any]],
    *,
    value: float | None,
    currency: str,
    allowed_units: set[str],
) -> list[str]:
    if value is None:
        return []
    return [
        evidence_id
        for evidence_id in evidence_ids
        if evidence_id in known
        and any(
            _exact_evidence_match(
                known[evidence_id],
                value=value,
                currency=currency,
                unit=unit,
                evidence_classes={"FACT", "CALC"},
            )
            for unit in allowed_units
        )
    ]


def _quantile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _observation_value(metric: str, capital: float, fundamental: float) -> float:
    if metric == "FCF_YIELD":
        return fundamental / capital
    return capital / fundamental


def _observation_flags(
    supplied: Any,
    *,
    known: dict[str, dict[str, Any]],
    path: str,
    subject: dict[str, Any] | None = None,
    historical: bool = False,
    valuation_as_of_date: str | None = None,
) -> dict[str, Any]:
    row = _as_dict(supplied)
    metric = _metric_name(row.get("metric"))
    capital_value = _number(row.get("capital_value"))
    fundamental_value = _number(row.get("fundamental_value"))
    supplied_value = _number(row.get("value"))
    currency = str(row.get("currency") or "").upper()
    as_of_date = str(row.get("as_of_date") or "")
    fiscal_period_end = str(row.get("fiscal_period_end") or "")
    capital_ids = _unique(row.get("capital_evidence_ids"))
    fundamental_ids = _unique(row.get("fundamental_evidence_ids"))
    flags: list[str] = []
    if metric not in SUPPORTED_VALUATION_METRICS:
        flags.append("unsupported_metric")
    if capital_value is None or capital_value <= 0:
        flags.append("missing_or_nonpositive_capital_value")
    if fundamental_value is None:
        flags.append("missing_denominator")
    elif metric in DENOMINATOR_POSITIVE_METRICS and fundamental_value <= 0:
        flags.append(
            "negative_ebitda"
            if metric == "EV/EBITDA"
            else "negative_fcf"
            if metric in {"P/FCF", "FCF_YIELD"}
            else "negative_earnings"
            if metric == "P/E"
            else "negative_revenue"
        )
    calculated_value = (
        _observation_value(metric, capital_value, fundamental_value)
        if metric in SUPPORTED_VALUATION_METRICS
        and capital_value is not None
        and capital_value > 0
        and fundamental_value is not None
        and fundamental_value > 0
        else None
    )
    if supplied_value is not None and not _same_number(
        supplied_value,
        calculated_value,
        relative=1e-7,
        absolute=1e-9,
    ):
        flags.append("value_formula_mismatch")
    if not currency:
        flags.append("currency_missing")
    capital_matches = _exact_binding_ids(
        capital_ids,
        known,
        value=capital_value,
        currency=currency,
        allowed_units={currency},
    )
    fundamental_matches = _exact_binding_ids(
        fundamental_ids,
        known,
        value=fundamental_value,
        currency=currency,
        allowed_units={currency},
    )
    capital_matches = [
        evidence_id
        for evidence_id in capital_matches
        if str(known[evidence_id].get("as_of_date") or "") == as_of_date
        and (
            _availability_date(known[evidence_id]) is not None
            and str(_availability_date(known[evidence_id])) <= as_of_date
        )
    ]
    fundamental_matches = [
        evidence_id
        for evidence_id in fundamental_matches
        if str(known[evidence_id].get("period_end") or "") == fiscal_period_end
        and (
            _availability_date(known[evidence_id]) is not None
            and str(_availability_date(known[evidence_id])) <= as_of_date
        )
    ]
    if not capital_matches or not fundamental_matches:
        flags.append("missing_or_mismatched_evidence")
    if not _iso_date(as_of_date):
        flags.append("as_of_date_missing")
    elif valuation_as_of_date and as_of_date > valuation_as_of_date:
        flags.append("look_ahead_date")
    if not _iso_date(fiscal_period_end):
        flags.append("fiscal_period_missing")
    period_basis = str(row.get("period_basis") or "").upper()
    if period_basis not in {"LTM", "NTM", "FY", "FY1"}:
        flags.append("period_basis_invalid")
    definition = str(row.get("accounting_definition") or "").strip()
    if not definition:
        flags.append("accounting_definition_missing")
    period_bridge_ids = _unique(row.get("period_alignment_evidence_ids"))
    valid_period_bridge_ids, unknown_period_bridge_ids, future_period_bridge_ids = (
        _context_evidence_valid(
            period_bridge_ids,
            known,
            as_of_date=valuation_as_of_date,
        )
    )
    period_bridge_valid = (
        str(row.get("period_alignment_status") or "").upper()
        == "VALIDATED_BRIDGE"
        and bool(valid_period_bridge_ids)
        and not unknown_period_bridge_ids
        and not future_period_bridge_ids
        and bool(str(row.get("period_alignment_rationale") or "").strip())
        and bool(str(row.get("period_alignment_reviewed_by") or "").strip())
    )
    currency_bridge_ids = _unique(
        row.get("currency_normalization_evidence_ids")
    )
    (
        valid_currency_bridge_ids,
        unknown_currency_bridge_ids,
        future_currency_bridge_ids,
    ) = _context_evidence_valid(
        currency_bridge_ids,
        known,
        as_of_date=valuation_as_of_date,
    )
    currency_bridge_valid = (
        str(row.get("currency_normalization_status") or "").upper()
        == "VALIDATED"
        and bool(valid_currency_bridge_ids)
        and not unknown_currency_bridge_ids
        and not future_currency_bridge_ids
        and bool(
            str(row.get("currency_normalization_rationale") or "").strip()
        )
        and bool(
            str(row.get("currency_normalization_reviewed_by") or "").strip()
        )
    )

    if subject:
        if not historical:
            same_period = (
                as_of_date == subject.get("as_of_date")
                and fiscal_period_end == subject.get("fiscal_period_end")
            )
            if not same_period and not period_bridge_valid:
                flags.append("different_fiscal_period")
            elif not same_period:
                flags.append("controlled_period_bridge")
        elif period_basis != subject.get("period_basis"):
            flags.append("different_fiscal_period_basis")
        if currency != subject.get("currency"):
            if not currency_bridge_valid:
                flags.append("currency_mismatch")
            else:
                flags.append("controlled_currency_normalization")
        if definition != subject.get("accounting_definition"):
            flags.append("accounting_definition_mismatch")
        if not historical:
            business_model_fit = str(
                row.get("business_model_fit") or ""
            ).upper()
            if business_model_fit == "LIMITED":
                flags.append("limited_business_model_fit")
            elif business_model_fit != "COMPARABLE":
                flags.append("business_model_fit_missing_or_invalid")

    blocking = {
        "unsupported_metric",
        "missing_or_nonpositive_capital_value",
        "missing_denominator",
        "negative_ebitda",
        "negative_fcf",
        "negative_earnings",
        "negative_revenue",
        "value_formula_mismatch",
        "currency_missing",
        "missing_or_mismatched_evidence",
        "as_of_date_missing",
        "look_ahead_date",
        "fiscal_period_missing",
        "period_basis_invalid",
        "accounting_definition_missing",
        "different_fiscal_period",
        "different_fiscal_period_basis",
        "currency_mismatch",
        "accounting_definition_mismatch",
        "business_model_fit_missing_or_invalid",
    }
    unique_flags = sorted(set(flags))
    if set(unique_flags).intersection(blocking):
        comparability = "NOT_COMPARABLE"
    elif "limited_business_model_fit" in unique_flags:
        comparability = "LIMITED"
    else:
        comparability = "COMPARABLE"
    return {
        "metric": metric,
        "value": calculated_value,
        "supplied_value": supplied_value,
        "formula": (
            "fundamental_value / capital_value"
            if metric == "FCF_YIELD"
            else "capital_value / fundamental_value"
        ),
        "capital_value": capital_value,
        "fundamental_value": fundamental_value,
        "currency": currency or None,
        "as_of_date": as_of_date or None,
        "fiscal_period_end": fiscal_period_end or None,
        "period_basis": period_basis or None,
        "accounting_definition": definition or None,
        "comparability_status": comparability,
        "comparability_flags": unique_flags,
        "auto_rank_allowed": comparability == "COMPARABLE",
        "capital_evidence_ids": capital_ids,
        "fundamental_evidence_ids": fundamental_ids,
        "matching_capital_evidence_ids": capital_matches,
        "matching_fundamental_evidence_ids": fundamental_matches,
        "period_alignment": {
            "status": row.get("period_alignment_status"),
            "evidence_ids": period_bridge_ids,
            "matching_evidence_ids": valid_period_bridge_ids,
            "rationale": row.get("period_alignment_rationale"),
            "reviewed_by": row.get("period_alignment_reviewed_by"),
            "validated": period_bridge_valid,
        },
        "currency_normalization": {
            "status": row.get("currency_normalization_status"),
            "evidence_ids": currency_bridge_ids,
            "matching_evidence_ids": valid_currency_bridge_ids,
            "rationale": row.get("currency_normalization_rationale"),
            "reviewed_by": row.get("currency_normalization_reviewed_by"),
            "validated": currency_bridge_valid,
        },
        "path": path,
    }


def build_peer_comparison(
    supplied: Any,
    evidence_records: Any,
    valuation_as_of_date: str,
) -> dict[str, Any]:
    source = _as_dict(supplied)
    requested = str(source.get("status") or "NOT_PROVIDED").upper()
    if requested == "NOT_PROVIDED" and not any(
        value not in (None, "", [], {}) for value in source.values()
    ):
        return {
            "status": "NOT_PROVIDED",
            "as_of_date": None,
            "selection_rationale": None,
            "reviewed_by": None,
            "subject_rows": [],
            "rows": [],
            "metric_summaries": [],
            "suppressed_row_count": 0,
            "limitations": ["No controlled peer comparison was supplied."],
            "validation_issues": [],
        }
    known = _evidence_index(evidence_records)
    subject_rows = [
        _observation_flags(
            row,
            known=known,
            path=f"peer_comparison.subject_metrics[{index}]",
            valuation_as_of_date=valuation_as_of_date,
        )
        for index, row in enumerate(_as_list(source.get("subject_metrics")))
        if isinstance(row, dict)
    ]
    subject_metric_counts: dict[str, int] = {}
    for row in subject_rows:
        metric = str(row.get("metric") or "")
        subject_metric_counts[metric] = subject_metric_counts.get(metric, 0) + 1
    for row in subject_rows:
        if subject_metric_counts.get(str(row.get("metric") or ""), 0) > 1:
            row["comparability_flags"] = sorted(
                set(
                    row.get("comparability_flags", [])
                    + ["duplicate_subject_metric"]
                )
            )
            row["comparability_status"] = "NOT_COMPARABLE"
            row["auto_rank_allowed"] = False
    subject_by_metric = {
        row["metric"]: row
        for row in subject_rows
        if row.get("comparability_status") == "COMPARABLE"
    }
    rows: list[dict[str, Any]] = []
    for peer_index, peer in enumerate(_as_list(source.get("peers"))):
        if not isinstance(peer, dict):
            continue
        for metric_index, metric_row in enumerate(_as_list(peer.get("metrics"))):
            if not isinstance(metric_row, dict):
                continue
            candidate = dict(metric_row)
            candidate.setdefault("business_model_fit", peer.get("business_model_fit"))
            normalized = _observation_flags(
                candidate,
                known=known,
                path=f"peer_comparison.peers[{peer_index}].metrics[{metric_index}]",
                subject=subject_by_metric.get(_metric_name(metric_row.get("metric"))),
                valuation_as_of_date=valuation_as_of_date,
            )
            normalized.update(
                {
                    "ticker": peer.get("ticker"),
                    "company_name": peer.get("company_name"),
                    "industry_fit": peer.get("industry_fit"),
                    "business_model_fit": peer.get("business_model_fit"),
                }
            )
            if not str(peer.get("ticker") or "").strip():
                normalized["comparability_flags"] = sorted(
                    set(
                        normalized["comparability_flags"]
                        + ["missing_peer_identity"]
                    )
                )
                normalized["comparability_status"] = "NOT_COMPARABLE"
                normalized["auto_rank_allowed"] = False
            if normalized["metric"] not in subject_by_metric:
                normalized["comparability_flags"] = sorted(
                    set(normalized["comparability_flags"] + ["subject_metric_not_validated"])
                )
                normalized["comparability_status"] = "NOT_COMPARABLE"
                normalized["auto_rank_allowed"] = False
            rows.append(normalized)
    peer_metric_counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (
            str(row.get("ticker") or "").strip().upper(),
            str(row.get("metric") or ""),
        )
        peer_metric_counts[key] = peer_metric_counts.get(key, 0) + 1
    for row in rows:
        key = (
            str(row.get("ticker") or "").strip().upper(),
            str(row.get("metric") or ""),
        )
        if key[0] and peer_metric_counts.get(key, 0) > 1:
            row["comparability_flags"] = sorted(
                set(
                    row.get("comparability_flags", [])
                    + ["duplicate_peer_metric"]
                )
            )
            row["comparability_status"] = "NOT_COMPARABLE"
            row["auto_rank_allowed"] = False

    minimum_peers = int(_number(source.get("minimum_comparable_peers")) or 3)
    minimum_peers = max(3, minimum_peers)
    summaries: list[dict[str, Any]] = []
    for metric in sorted(subject_by_metric):
        usable = [
            row
            for row in rows
            if row.get("metric") == metric and row.get("auto_rank_allowed")
        ]
        values = [float(row["value"]) for row in usable if row.get("value") is not None]
        subject_value = _number(subject_by_metric[metric].get("value"))
        enough = len(values) >= minimum_peers
        median = statistics.median(values) if enough else None
        percentile = (
            sum(value <= float(subject_value) for value in values) / len(values)
            if enough and subject_value is not None
            else None
        )
        summaries.append(
            {
                "metric": metric,
                "subject_value": subject_value,
                "currency": subject_by_metric[metric].get("currency"),
                "as_of_date": subject_by_metric[metric].get("as_of_date"),
                "fiscal_period_end": subject_by_metric[metric].get(
                    "fiscal_period_end"
                ),
                "period_basis": subject_by_metric[metric].get("period_basis"),
                "accounting_definition": subject_by_metric[metric].get(
                    "accounting_definition"
                ),
                "comparable_peer_count": len(values),
                "minimum_required": minimum_peers,
                "minimum": min(values) if enough else None,
                "first_quartile": _quantile(values, 0.25) if enough else None,
                "median": median,
                "third_quartile": _quantile(values, 0.75) if enough else None,
                "maximum": max(values) if enough else None,
                "subject_percentile": percentile,
                "ranking_status": (
                    "AVAILABLE"
                    if enough
                    else "SUPPRESSED_INSUFFICIENT_COMPARABLE_PEERS"
                ),
                "formula": "controlled median and empirical subject percentile",
                "input_evidence_ids": _unique(
                    [
                        evidence_id
                        for row in [subject_by_metric[metric], *usable]
                        for evidence_id in (
                            row.get("capital_evidence_ids", [])
                            + row.get("fundamental_evidence_ids", [])
                        )
                    ]
                ),
            }
        )
    reviewer = str(source.get("reviewed_by") or "").strip()
    rationale = str(source.get("selection_rationale") or "").strip()
    dated = (
        _iso_date(source.get("as_of_date"))
        and str(source.get("as_of_date")) == valuation_as_of_date
    )
    validated_summary = any(
        row.get("ranking_status") == "AVAILABLE" for row in summaries
    )
    valid = (
        requested == "VALIDATED"
        and bool(reviewer)
        and bool(rationale)
        and dated
        and validated_summary
    )
    status = (
        "VALIDATED"
        if valid
        else "SUPPRESSED_INCOMPARABLE"
        if rows or subject_rows
        else "INVALID"
    )
    issues: list[dict[str, str]] = []
    if requested == "VALIDATED" and not valid:
        issues.append(
            _issue(
                "S11_PEER_COMPARISON_NOT_VALIDATED",
                "Peer comparison was submitted as VALIDATED but lacks a dated reviewer-owned peer set with at least three comparable rows for one metric.",
                "valuation_cross_checks.peer_comparison",
            )
        )
    return {
        "status": status,
        "as_of_date": source.get("as_of_date"),
        "selection_rationale": rationale or None,
        "reviewed_by": reviewer or None,
        "subject_rows": subject_rows,
        "rows": rows,
        "metric_summaries": summaries,
        "suppressed_row_count": sum(
            row.get("comparability_status") != "COMPARABLE" for row in rows
        ),
        "limitations": [
            "Negative denominators, period mismatch, currency mismatch, accounting-definition mismatch, missing evidence, or formula mismatch suppress the affected row.",
            *[str(value) for value in _as_list(source.get("limitations")) if value],
        ],
        "validation_issues": issues,
    }


def build_historical_valuation(
    supplied: Any,
    evidence_records: Any,
    valuation_as_of_date: str,
) -> dict[str, Any]:
    source = _as_dict(supplied)
    requested = str(source.get("status") or "NOT_PROVIDED").upper()
    if requested == "NOT_PROVIDED" and not any(
        value not in (None, "", [], {}) for value in source.values()
    ):
        return {
            "status": "NOT_PROVIDED",
            "metric": None,
            "current_observation": None,
            "observations": [],
            "summary": {},
            "reviewed_by": None,
            "limitations": ["No controlled historical valuation series was supplied."],
            "validation_issues": [],
        }
    known = _evidence_index(evidence_records)
    current = _observation_flags(
        source.get("current_observation"),
        known=known,
        path="historical_valuation.current_observation",
        valuation_as_of_date=valuation_as_of_date,
    )
    observations: list[dict[str, Any]] = []
    for index, row in enumerate(_as_list(source.get("observations"))):
        if not isinstance(row, dict):
            continue
        normalized = _observation_flags(
            row,
            known=known,
            path=f"historical_valuation.observations[{index}]",
            subject=current,
            historical=True,
            valuation_as_of_date=valuation_as_of_date,
        )
        if normalized.get("metric") != current.get("metric"):
            normalized["comparability_flags"] = sorted(
                set(normalized["comparability_flags"] + ["metric_mismatch"])
            )
            normalized["comparability_status"] = "NOT_COMPARABLE"
            normalized["auto_rank_allowed"] = False
        observations.append(normalized)
    usable = [row for row in observations if row.get("auto_rank_allowed")]
    distinct_dates = sorted(
        {str(row.get("as_of_date")) for row in usable if _iso_date(row.get("as_of_date"))}
    )
    minimum_observations = int(_number(source.get("minimum_observations")) or 5)
    minimum_observations = max(5, minimum_observations)
    minimum_span_days = int(_number(source.get("minimum_span_days")) or 365)
    minimum_span_days = max(365, minimum_span_days)
    span_days = (
        (date.fromisoformat(distinct_dates[-1]) - date.fromisoformat(distinct_dates[0])).days
        if len(distinct_dates) >= 2
        else 0
    )
    values = [float(row["value"]) for row in usable if row.get("value") is not None]
    enough = (
        current.get("comparability_status") == "COMPARABLE"
        and len(values) >= minimum_observations
        and len(distinct_dates) >= minimum_observations
        and span_days >= minimum_span_days
    )
    current_value = _number(current.get("value"))
    summary = {
        "metric": current.get("metric"),
        "currency": current.get("currency"),
        "as_of_date": current.get("as_of_date"),
        "fiscal_period_end": current.get("fiscal_period_end"),
        "period_basis": current.get("period_basis"),
        "accounting_definition": current.get("accounting_definition"),
        "comparable_observation_count": len(values),
        "distinct_observation_dates": len(distinct_dates),
        "minimum_required": minimum_observations,
        "span_days": span_days,
        "minimum_span_days": minimum_span_days,
        "minimum": min(values) if enough else None,
        "first_quartile": _quantile(values, 0.25) if enough else None,
        "median": statistics.median(values) if enough else None,
        "third_quartile": _quantile(values, 0.75) if enough else None,
        "maximum": max(values) if enough else None,
        "current_percentile": (
            sum(value <= float(current_value) for value in values) / len(values)
            if enough and current_value is not None
            else None
        ),
        "comparison_status": (
            "AVAILABLE"
            if enough
            else "SUPPRESSED_INSUFFICIENT_OR_INCOMPARABLE_HISTORY"
        ),
        "formula": "controlled historical distribution and empirical current percentile",
        "input_evidence_ids": _unique(
            [
                evidence_id
                for row in [current, *usable]
                for evidence_id in (
                    row.get("capital_evidence_ids", [])
                    + row.get("fundamental_evidence_ids", [])
                )
            ]
        ),
    }
    reviewer = str(source.get("reviewed_by") or "").strip()
    rationale = str(source.get("comparability_rationale") or "").strip()
    dated = (
        _iso_date(source.get("as_of_date"))
        and str(source.get("as_of_date")) == valuation_as_of_date
    )
    valid = (
        requested == "VALIDATED"
        and bool(reviewer)
        and bool(rationale)
        and dated
        and enough
    )
    status = (
        "VALIDATED"
        if valid
        else "SUPPRESSED_INCOMPARABLE"
        if observations
        else "INVALID"
    )
    issues: list[dict[str, str]] = []
    if requested == "VALIDATED" and not valid:
        issues.append(
            _issue(
                "S11_HISTORICAL_VALUATION_NOT_VALIDATED",
                "Historical valuation was submitted as VALIDATED but the series is too short, look-ahead affected, incomparable, or lacks dated reviewer ownership.",
                "valuation_cross_checks.historical_valuation",
            )
        )
    return {
        "status": status,
        "as_of_date": source.get("as_of_date"),
        "metric": current.get("metric"),
        "current_observation": current,
        "observations": observations,
        "summary": summary,
        "comparability_rationale": rationale or None,
        "reviewed_by": reviewer or None,
        "limitations": [
            "Historical observations must use the same metric definition, currency, period basis, and only information available by the valuation date.",
            *[str(value) for value in _as_list(source.get("limitations")) if value],
        ],
        "validation_issues": issues,
    }


def _find_exact_parent_evidence(
    parent: dict[str, Any],
    *,
    value: float | None,
    currency: str,
    metric_names: set[str],
    supplied_ids: list[str],
    as_of_date: str,
) -> list[str]:
    known = _evidence_index(parent.get("evidence_records"))
    candidates = supplied_ids or [
        evidence_id
        for evidence_id, record in known.items()
        if str(record.get("metric_name") or "") in metric_names
    ]
    return [
        evidence_id
        for evidence_id in _exact_binding_ids(
            candidates,
            known,
            value=value,
            currency=currency,
            allowed_units={currency},
        )
        if str(known[evidence_id].get("metric_name") or "") in metric_names
        and str(known[evidence_id].get("as_of_date") or "") == as_of_date
        and _availability_date(known[evidence_id]) is not None
        and str(_availability_date(known[evidence_id])) <= as_of_date
    ]


def _reference_support(
    selected_reference: float,
    metric: str,
    peer: dict[str, Any],
    historical: dict[str, Any],
    reference_basis: dict[str, Any],
) -> dict[str, Any]:
    ranges: list[dict[str, Any]] = []
    incompatible_sources: list[dict[str, Any]] = []

    def compatible(summary: dict[str, Any]) -> bool:
        return (
            summary.get("metric") == metric
            and summary.get("currency") == reference_basis.get("currency")
            and summary.get("period_basis")
            == reference_basis.get("period_basis")
            and summary.get("accounting_definition")
            == reference_basis.get("accounting_definition")
        )

    for summary in peer.get("metric_summaries", []):
        if (
            summary.get("metric") == metric
            and summary.get("ranking_status") == "AVAILABLE"
        ):
            target = ranges if compatible(summary) else incompatible_sources
            target.append(
                {
                    "source": "PEER_COMPARISON",
                    "minimum": summary.get("minimum"),
                    "maximum": summary.get("maximum"),
                    "median": summary.get("median"),
                    "currency": summary.get("currency"),
                    "period_basis": summary.get("period_basis"),
                    "accounting_definition": summary.get(
                        "accounting_definition"
                    ),
                }
            )
    historical_summary = _as_dict(historical.get("summary"))
    if (
        historical.get("metric") == metric
        and historical_summary.get("comparison_status") == "AVAILABLE"
    ):
        target = (
            ranges
            if compatible(historical_summary)
            else incompatible_sources
        )
        target.append(
            {
                "source": "HISTORICAL_VALUATION",
                "minimum": historical_summary.get("minimum"),
                "maximum": historical_summary.get("maximum"),
                "median": historical_summary.get("median"),
                "currency": historical_summary.get("currency"),
                "period_basis": historical_summary.get("period_basis"),
                "accounting_definition": historical_summary.get(
                    "accounting_definition"
                ),
            }
        )
    supporting = [
        row
        for row in ranges
        if _number(row.get("minimum")) is not None
        and _number(row.get("maximum")) is not None
        and float(row["minimum"]) <= selected_reference <= float(row["maximum"])
    ]
    return {
        "status": "SUPPORTED" if supporting else "NOT_SUPPORTED",
        "metric": metric,
        "selected_reference": selected_reference,
        "reference_basis": reference_basis,
        "reference_ranges": ranges,
        "incompatible_reference_ranges": incompatible_sources,
        "supporting_sources": [row["source"] for row in supporting],
    }


def build_reverse_valuation(
    supplied: Any,
    parent: dict[str, Any],
    peer: dict[str, Any],
    historical: dict[str, Any],
    valuation_as_of_date: str,
) -> dict[str, Any]:
    source = _as_dict(supplied)
    requested = str(source.get("status") or "NOT_PROVIDED").upper()
    if requested == "NOT_PROVIDED" and not any(
        value not in (None, "", [], {}) for value in source.values()
    ):
        return {
            "status": "NOT_PROVIDED",
            "method": None,
            "required_metric_value": None,
            "reference_support": {"status": "NOT_EVALUATED"},
            "limitations": ["No controlled reverse valuation was supplied."],
            "validation_issues": [],
        }
    method = str(source.get("method") or "").upper()
    method_spec = REVERSE_METHODS.get(method)
    currency = str(parent.get("valuation", {}).get("price_currency") or "").upper()
    valuation = _as_dict(parent.get("valuation"))
    capital_basis = method_spec[0] if method_spec else None
    capital_value = (
        _number(valuation.get("market_cap"))
        if capital_basis == "MARKET_CAP"
        else _number(valuation.get("enterprise_value_proxy"))
        if capital_basis == "ENTERPRISE_VALUE"
        else None
    )
    capital_ids = _unique(source.get("capital_evidence_ids"))
    capital_matches = _find_exact_parent_evidence(
        parent,
        value=capital_value,
        currency=currency,
        metric_names=(
            {"market_cap_point_in_time"}
            if capital_basis == "MARKET_CAP"
            else {"enterprise_value_point_in_time", "enterprise_value_proxy"}
        ),
        supplied_ids=capital_ids,
        as_of_date=valuation_as_of_date,
    )
    reference = _as_dict(source.get("selected_reference"))
    reference_value = _number(reference.get("value"))
    reference_ids = _unique(reference.get("evidence_ids"))
    known = _evidence_index(parent.get("evidence_records"))
    valid_context_ids, unknown_ids, future_ids = _context_evidence_valid(
        reference_ids,
        known,
        as_of_date=valuation_as_of_date,
    )
    valid_context_ids = [
        evidence_id
        for evidence_id in valid_context_ids
        if known[evidence_id].get("source_level") in {1, 2, 3, 4}
    ]
    reviewer = str(reference.get("reviewed_by") or source.get("reviewed_by") or "").strip()
    rationale = str(reference.get("rationale") or "").strip()
    selected_valid = (
        reference_value is not None
        and reference_value > 0
        and bool(valid_context_ids)
        and not unknown_ids
        and not future_ids
        and bool(reviewer)
        and bool(rationale)
        and str(reference.get("evidence_class") or "").upper() == "JUDGMENT"
    )
    required_metric = None
    formula = None
    if (
        method_spec
        and capital_value is not None
        and capital_value > 0
        and reference_value is not None
        and reference_value > 0
    ):
        if method_spec[2] == "DIVIDE":
            required_metric = capital_value / reference_value
            formula = "authoritative_capital_value / selected_reference_multiple"
        else:
            required_metric = capital_value * reference_value
            formula = "authoritative_market_cap * selected_fcf_yield"
    metric = method_spec[1] if method_spec else None
    reference_basis_input = _as_dict(source.get("reference_basis"))
    reference_basis = {
        "metric": _metric_name(reference_basis_input.get("metric")),
        "currency": str(
            reference_basis_input.get("currency") or ""
        ).upper(),
        "period_basis": str(
            reference_basis_input.get("period_basis") or ""
        ).upper(),
        "accounting_definition": str(
            reference_basis_input.get("accounting_definition") or ""
        ).strip(),
    }
    reference_basis_valid = (
        reference_basis["metric"] == metric
        and reference_basis["currency"] == currency
        and reference_basis["period_basis"] in {"NTM", "FY1"}
        and bool(reference_basis["accounting_definition"])
    )
    metric_period = _as_dict(source.get("metric_period"))
    period_valid = (
        metric_period.get("status") == "VALIDATED"
        and metric_period.get("period_type") == "FORWARD_METRIC"
        and _iso_date(metric_period.get("start_date"))
        and _iso_date(metric_period.get("end_date"))
        and str(metric_period.get("start_date"))
        <= str(metric_period.get("end_date"))
        and str(metric_period.get("start_date")) > valuation_as_of_date
    )
    support = (
        _reference_support(
            reference_value,
            metric,
            peer,
            historical,
            reference_basis,
        )
        if reference_value is not None
        and metric
        and reference_basis_valid
        else {"status": "NOT_EVALUATED"}
    )
    comparison = _as_dict(source.get("comparison_metric"))
    comparison_value = _number(comparison.get("value"))
    comparison_ids = _unique(comparison.get("evidence_ids"))
    comparison_metric_name = str(comparison.get("metric_name") or "")
    comparison_basis = {
        "currency": str(comparison.get("currency") or "").upper(),
        "period_basis": str(
            comparison.get("period_basis") or ""
        ).upper(),
        "accounting_definition": str(
            comparison.get("accounting_definition") or ""
        ).strip(),
    }
    comparison_basis_matches = comparison_basis == reference_basis
    comparison_matches = [
        evidence_id
        for evidence_id in _exact_binding_ids(
            comparison_ids,
            known,
            value=comparison_value,
            currency=currency,
            allowed_units={currency},
        )
        if comparison_metric_name
        and str(known[evidence_id].get("metric_name") or "")
        == comparison_metric_name
        and _availability_date(known[evidence_id]) is not None
        and str(_availability_date(known[evidence_id]))
        <= valuation_as_of_date
        and comparison_basis_matches
    ]
    required_change = (
        required_metric / comparison_value - 1.0
        if required_metric is not None
        and comparison_value is not None
        and comparison_value > 0
        and comparison_matches
        else None
    )
    as_of_valid = (
        _iso_date(source.get("as_of_date"))
        and str(source.get("as_of_date")) == valuation_as_of_date
    )
    calculation_valid = (
        requested == "VALIDATED"
        and method_spec is not None
        and bool(currency)
        and capital_value is not None
        and capital_value > 0
        and bool(capital_matches)
        and selected_valid
        and required_metric is not None
        and reference_basis_valid
        and period_valid
        and as_of_valid
    )
    fully_valid = calculation_valid and support.get("status") == "SUPPORTED"
    status = (
        "VALIDATED"
        if fully_valid
        else "PARTIALLY_VALIDATED"
        if calculation_valid
        else "INVALID"
    )
    issues: list[dict[str, str]] = []
    if requested == "VALIDATED" and not fully_valid:
        issues.append(
            _issue(
                "S11_REVERSE_VALUATION_NOT_FULLY_VALIDATED",
                "Reverse valuation lacks a reproducible capital basis, dated metric period, supported reference multiple or yield, exact evidence, or reviewer-owned rationale.",
                "valuation_cross_checks.reverse_valuation",
            )
        )
    return {
        "status": status,
        "as_of_date": source.get("as_of_date"),
        "method": method or None,
        "valuation_metric": metric,
        "capital_basis": capital_basis,
        "capital_value": capital_value,
        "capital_currency": currency or None,
        "capital_evidence_ids": capital_matches,
        "selected_reference": {
            "value": reference_value,
            "evidence_class": reference.get("evidence_class"),
            "evidence_ids": reference_ids,
            "matching_context_evidence_ids": valid_context_ids,
            "rationale": rationale or None,
            "reviewed_by": reviewer or None,
        },
        "reference_basis": reference_basis,
        "metric_period": metric_period,
        "required_metric_value": required_metric,
        "required_metric_currency": currency or None,
        "formula": formula,
        "comparison_metric": {
            "value": comparison_value,
            "metric_name": comparison_metric_name or None,
            **comparison_basis,
            "evidence_ids": comparison_ids,
            "matching_evidence_ids": comparison_matches,
        },
        "required_change_vs_comparison_metric": required_change,
        "reference_support": support,
        "conditional_conclusion": (
            "The dated market capital basis requires the displayed metric under the selected, independently contextualized reference. This is an implied expectation, not a fair-value conclusion."
            if calculation_valid
            else "Not Evaluated"
        ),
        "limitations": [
            "Reverse valuation answers what the market requires under a selected reference; it does not prove that the selected reference is fair.",
            *[str(value) for value in _as_list(source.get("limitations")) if value],
        ],
        "validation_issues": issues,
    }


def _normalize_model_line(
    supplied: Any,
    *,
    known: dict[str, dict[str, Any]],
    path: str,
    currency: str,
    unit: str,
    kind: str,
    as_of_date: str,
    nonnegative: bool = False,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    source = _as_dict(supplied)
    value = _number(source.get("value"))
    evidence_class = str(source.get("evidence_class") or "MISSING").upper()
    evidence_ids = _unique(source.get("evidence_ids"))
    reviewer = str(source.get("reviewed_by") or "").strip()
    rationale = str(source.get("rationale") or "").strip()
    formula = str(source.get("formula") or "").strip()
    supplied_currency = str(source.get("currency") or "").upper()
    supplied_unit = str(source.get("unit") or "").upper()
    issues: list[dict[str, str]] = []
    if value is None:
        issues.append(_issue("S11_MODEL_VALUE_MISSING", "A finite value is required.", path))
    if evidence_class not in {"FACT", "CALC", "JUDGMENT"}:
        issues.append(
            _issue(
                "S11_MODEL_EVIDENCE_CLASS_INVALID",
                "Model lines must be FACT, CALC, or JUDGMENT.",
                path,
            )
        )
    valid_context, unknown, future = _context_evidence_valid(
        evidence_ids,
        known,
        as_of_date=as_of_date,
    )
    matching: list[str] = []
    if evidence_class in {"FACT", "CALC"} and value is not None:
        valid_context_set = set(valid_context)
        matching = [
            evidence_id
            for evidence_id in _exact_binding_ids(
                evidence_ids,
                known,
                value=value,
                currency=currency if kind in {"AMOUNT", "SHARES"} else "",
                allowed_units={unit},
            )
            if evidence_id in valid_context_set
            if str(
                known[evidence_id].get("evidence_class")
                or known[evidence_id].get("evidence_type")
                or ""
            ).upper()
            == evidence_class
        ]
        if not matching:
            issues.append(
                _issue(
                    "S11_MODEL_EVIDENCE_BINDING_FAILED",
                    "FACT/CALC line must match a dated PASS evidence record by class, value, currency, and unit.",
                    path,
                )
            )
        if unknown or future:
            issues.append(
                _issue(
                    "S11_MODEL_EVIDENCE_UNRESOLVED_OR_FUTURE",
                    "FACT/CALC evidence must exist and must have been available by the valuation as-of date.",
                    path,
                )
            )
    elif evidence_class == "JUDGMENT":
        if not valid_context or unknown or future or not rationale:
            issues.append(
                _issue(
                    "S11_MODEL_JUDGMENT_NOT_SUPPORTED",
                    "JUDGMENT line requires current contextual evidence and an explicit rationale.",
                    path,
                )
            )
    if not evidence_ids:
        issues.append(
            _issue(
                "S11_MODEL_EVIDENCE_MISSING",
                "Every model line requires linked evidence.",
                path,
            )
        )
    if not reviewer:
        issues.append(
            _issue(
                "S11_MODEL_REVIEWER_MISSING",
                "Every model line requires a named reviewer.",
                path,
            )
        )
    if evidence_class == "CALC" and not formula:
        issues.append(
            _issue(
                "S11_MODEL_FORMULA_MISSING",
                "CALC line requires a reproducible formula.",
                path,
            )
        )
    if kind == "RATIO":
        if supplied_unit != "RATIO":
            issues.append(
                _issue(
                    "S11_MODEL_UNIT_MISMATCH",
                    "Rate inputs must use unit RATIO.",
                    path,
                )
            )
    elif supplied_currency != currency or supplied_unit != unit:
        issues.append(
            _issue(
                "S11_MODEL_UNIT_MISMATCH",
                f"Input must use currency={currency} and unit={unit}.",
                path,
            )
        )
    if value is not None and nonnegative and value < 0:
        issues.append(
            _issue(
                "S11_MODEL_NEGATIVE_NOT_ALLOWED",
                "This model line cannot be negative.",
                path,
            )
        )
    return (
        {
            "value": value,
            "currency": currency if kind != "RATIO" else None,
            "unit": unit,
            "evidence_class": evidence_class,
            "evidence_ids": evidence_ids,
            "matching_evidence_ids": matching,
            "context_evidence_ids": valid_context,
            "rationale": rationale or None,
            "formula": formula or None,
            "reviewed_by": reviewer or None,
            "validation_status": "PASS" if not issues else "FAIL",
        },
        issues,
    )


def _dcf_value(
    cash_flows: list[float],
    discount_rate: float,
    terminal_growth: float,
    *,
    net_debt: float,
    non_operating_assets: float,
    minority_interest: float,
    shares: float,
) -> dict[str, float] | None:
    if (
        not cash_flows
        or discount_rate <= terminal_growth
        or discount_rate <= 0
        or shares <= 0
        or cash_flows[-1] <= 0
    ):
        return None
    pv_forecast = sum(
        cash_flow / ((1.0 + discount_rate) ** year_index)
        for year_index, cash_flow in enumerate(cash_flows, start=1)
    )
    terminal_value = (
        cash_flows[-1]
        * (1.0 + terminal_growth)
        / (discount_rate - terminal_growth)
    )
    pv_terminal = terminal_value / ((1.0 + discount_rate) ** len(cash_flows))
    enterprise_value = pv_forecast + pv_terminal
    equity_value = (
        enterprise_value
        - net_debt
        + non_operating_assets
        - minority_interest
    )
    return {
        "pv_forecast_cash_flows": pv_forecast,
        "terminal_value": terminal_value,
        "pv_terminal_value": pv_terminal,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "implied_price": equity_value / shares,
    }


def build_independent_cross_check(
    supplied: Any,
    parent: dict[str, Any],
    valuation_as_of_date: str,
) -> dict[str, Any]:
    source = _as_dict(supplied)
    requested = str(source.get("status") or "NOT_PROVIDED").upper()
    if requested == "NOT_PROVIDED" and not any(
        value not in (None, "", [], {}) for value in source.values()
    ):
        return {
            "status": "NOT_PROVIDED",
            "method": None,
            "central_case": {},
            "sensitivity_table": [],
            "implied_price_range": {},
            "limitations": ["No independent valuation cross-check was supplied."],
            "validation_issues": [],
        }
    method = str(source.get("method") or "").upper()
    cash_flow_basis = str(
        source.get("cash_flow_basis") or ""
    ).upper()
    discount_rate_basis = str(
        source.get("discount_rate_basis") or ""
    ).upper()
    currency = str(parent.get("valuation", {}).get("price_currency") or "").upper()
    known = _evidence_index(parent.get("evidence_records"))
    issues: list[dict[str, str]] = []
    reviewer = str(source.get("reviewed_by") or "").strip()
    as_of_valid = (
        _iso_date(source.get("as_of_date"))
        and str(source.get("as_of_date")) == valuation_as_of_date
    )
    forecasts: list[dict[str, Any]] = []
    supplied_forecasts = _as_list(source.get("forecast_cash_flows"))
    for index, row in enumerate(supplied_forecasts):
        if not isinstance(row, dict):
            issues.append(
                _issue(
                    "S11_DCF_FORECAST_ROW_INVALID",
                    "Forecast cash-flow rows must be objects.",
                    f"independent_cross_check.forecast_cash_flows[{index}]",
                )
            )
            continue
        normalized, row_issues = _normalize_model_line(
            row,
            known=known,
            path=f"independent_cross_check.forecast_cash_flows[{index}]",
            currency=currency,
            unit=currency,
            kind="AMOUNT",
            as_of_date=valuation_as_of_date,
        )
        year_index = int(_number(row.get("year_index")) or 0)
        period_end = str(row.get("period_end") or "")
        if year_index != index + 1 or not _iso_date(period_end):
            row_issues.append(
                _issue(
                    "S11_DCF_FORECAST_PERIOD_INVALID",
                    "Forecast rows require consecutive year_index values and ISO period-end dates.",
                    f"independent_cross_check.forecast_cash_flows[{index}]",
                )
            )
        normalized.update({"year_index": year_index, "period_end": period_end or None})
        normalized["validation_status"] = "PASS" if not row_issues else "FAIL"
        forecasts.append(normalized)
        issues.extend(row_issues)
    if not 3 <= len(forecasts) <= 10:
        issues.append(
            _issue(
                "S11_DCF_FORECAST_LENGTH_INVALID",
                "Independent DCF requires three to ten annual forecast cash-flow periods.",
                "independent_cross_check.forecast_cash_flows",
            )
        )
    period_dates = [
        str(row.get("period_end"))
        for row in forecasts
        if _iso_date(row.get("period_end"))
    ]
    if period_dates != sorted(set(period_dates)):
        issues.append(
            _issue(
                "S11_DCF_FORECAST_DATES_NOT_UNIQUE",
                "Forecast period-end dates must be unique and increasing.",
                "independent_cross_check.forecast_cash_flows",
            )
        )
    if _iso_date(valuation_as_of_date) and len(period_dates) == len(forecasts):
        interval_dates = [
            date.fromisoformat(valuation_as_of_date),
            *[date.fromisoformat(value) for value in period_dates],
        ]
        interval_days = [
            (end - start).days
            for start, end in zip(interval_dates, interval_dates[1:])
        ]
        if any(days < 300 or days > 430 for days in interval_days):
            issues.append(
                _issue(
                    "S11_DCF_FORECAST_INTERVAL_INVALID",
                    "Each annual DCF period must end after the valuation date and span 300 to 430 days, allowing a 53-week fiscal year.",
                    "independent_cross_check.forecast_cash_flows",
                )
            )

    discount_rate, discount_issues = _normalize_model_line(
        source.get("discount_rate"),
        known=known,
        path="independent_cross_check.discount_rate",
        currency=currency,
        unit="RATIO",
        kind="RATIO",
        as_of_date=valuation_as_of_date,
    )
    terminal_growth, growth_issues = _normalize_model_line(
        source.get("terminal_growth"),
        known=known,
        path="independent_cross_check.terminal_growth",
        currency=currency,
        unit="RATIO",
        kind="RATIO",
        as_of_date=valuation_as_of_date,
    )
    net_debt, net_debt_issues = _normalize_model_line(
        source.get("net_debt"),
        known=known,
        path="independent_cross_check.net_debt",
        currency=currency,
        unit=currency,
        kind="AMOUNT",
        as_of_date=valuation_as_of_date,
    )
    non_operating_assets, asset_issues = _normalize_model_line(
        source.get("non_operating_assets"),
        known=known,
        path="independent_cross_check.non_operating_assets",
        currency=currency,
        unit=currency,
        kind="AMOUNT",
        as_of_date=valuation_as_of_date,
        nonnegative=True,
    )
    minority_interest, minority_issues = _normalize_model_line(
        source.get("minority_interest"),
        known=known,
        path="independent_cross_check.minority_interest",
        currency=currency,
        unit=currency,
        kind="AMOUNT",
        as_of_date=valuation_as_of_date,
        nonnegative=True,
    )
    shares, share_issues = _normalize_model_line(
        source.get("shares"),
        known=known,
        path="independent_cross_check.shares",
        currency="SHARES",
        unit="SHARES",
        kind="SHARES",
        as_of_date=valuation_as_of_date,
        nonnegative=True,
    )
    share_basis_source = _as_dict(source.get("share_basis"))
    share_basis_type = str(
        share_basis_source.get("basis_type") or ""
    ).upper()
    share_basis_date = str(share_basis_source.get("basis_date") or "")
    share_basis_reviewer = str(
        share_basis_source.get("reviewed_by") or ""
    ).strip()
    share_basis_rationale = str(
        share_basis_source.get("rationale") or ""
    ).strip()
    allowed_share_metrics = {
        "POINT_IN_TIME_OUTSTANDING": {
            "shares_outstanding_point_in_time",
        },
        "POINT_IN_TIME_DILUTED": {
            "diluted_share_count_point_in_time",
            "diluted_shares_point_in_time",
        },
        "FORWARD_DILUTED": {
            "forward_share_count_basis",
            "forward_diluted_share_count",
        },
    }
    share_basis_matching_ids = [
        evidence_id
        for evidence_id in shares.get("matching_evidence_ids", [])
        if str(known[evidence_id].get("metric_name") or "")
        in allowed_share_metrics.get(share_basis_type, set())
        and share_basis_date
        in {
            str(known[evidence_id].get("as_of_date") or ""),
            str(known[evidence_id].get("period_end") or ""),
        }
    ]
    share_date_direction_valid = (
        _iso_date(share_basis_date)
        and (
            (
                share_basis_type
                in {
                    "POINT_IN_TIME_OUTSTANDING",
                    "POINT_IN_TIME_DILUTED",
                }
                and share_basis_date <= valuation_as_of_date
            )
            or (
                share_basis_type == "FORWARD_DILUTED"
                and share_basis_date > valuation_as_of_date
            )
        )
    )
    share_basis_valid = (
        share_basis_source.get("status") == "VALIDATED"
        and share_basis_type in allowed_share_metrics
        and share_date_direction_valid
        and bool(share_basis_matching_ids)
        and bool(share_basis_reviewer)
        and bool(share_basis_rationale)
    )
    if not share_basis_valid:
        share_issues.append(
            _issue(
                "S11_DCF_SHARE_BASIS_NOT_VALIDATED",
                "DCF shares require an explicit current-outstanding, current-diluted, or forward-diluted basis with a matching date, exact share evidence, rationale, and reviewer.",
                "independent_cross_check.share_basis",
            )
        )
    sensitivity = _as_dict(source.get("sensitivity"))
    rate_step = _number(sensitivity.get("discount_rate_step"))
    growth_step = _number(sensitivity.get("terminal_growth_step"))
    sensitivity_evidence_ids = _unique(sensitivity.get("evidence_ids"))
    (
        valid_sensitivity_evidence_ids,
        unknown_sensitivity_evidence_ids,
        future_sensitivity_evidence_ids,
    ) = _context_evidence_valid(
        sensitivity_evidence_ids,
        known,
        as_of_date=valuation_as_of_date,
    )
    sensitivity_valid = (
        rate_step is not None
        and 0 < rate_step <= 0.05
        and growth_step is not None
        and 0 < growth_step <= 0.03
        and str(sensitivity.get("evidence_class") or "").upper()
        == "JUDGMENT"
        and bool(valid_sensitivity_evidence_ids)
        and not unknown_sensitivity_evidence_ids
        and not future_sensitivity_evidence_ids
        and bool(str(sensitivity.get("rationale") or "").strip())
        and bool(sensitivity.get("reviewed_by"))
    )
    if not sensitivity_valid:
        issues.append(
            _issue(
                "S11_DCF_SENSITIVITY_NOT_VALIDATED",
                "DCF requires explicit, evidenced, rationale-supported, and reviewed discount-rate and terminal-growth sensitivity steps.",
                "independent_cross_check.sensitivity",
            )
        )
    issues.extend(
        discount_issues
        + growth_issues
        + net_debt_issues
        + asset_issues
        + minority_issues
        + share_issues
    )
    rate = _number(discount_rate.get("value"))
    growth = _number(terminal_growth.get("value"))
    if rate is not None and not 0 < rate <= 0.50:
        issues.append(
            _issue(
                "S11_DCF_DISCOUNT_RATE_OUT_OF_RANGE",
                "Discount rate must be greater than zero and no more than 50%.",
                "independent_cross_check.discount_rate",
            )
        )
    if growth is not None and not -0.20 <= growth <= 0.10:
        issues.append(
            _issue(
                "S11_DCF_TERMINAL_GROWTH_OUT_OF_RANGE",
                "Terminal growth must be between -20% and 10%.",
                "independent_cross_check.terminal_growth",
            )
        )
    if rate is not None and growth is not None and rate <= growth:
        issues.append(
            _issue(
                "S11_DCF_RATE_NOT_ABOVE_GROWTH",
                "Discount rate must exceed terminal growth.",
                "independent_cross_check",
            )
        )
    if method != "DISCOUNTED_CASH_FLOW_GORDON_GROWTH":
        issues.append(
            _issue(
                "S11_INDEPENDENT_METHOD_UNSUPPORTED",
                "S11 V1 independent cross-check supports DISCOUNTED_CASH_FLOW_GORDON_GROWTH.",
                "independent_cross_check.method",
            )
        )
    if cash_flow_basis != "UNLEVERED_FCFF":
        issues.append(
            _issue(
                "S11_DCF_CASH_FLOW_BASIS_INVALID",
                "Enterprise-value DCF requires UNLEVERED_FCFF; CFO-minus-capex or other levered FCF cannot be used before subtracting net debt.",
                "independent_cross_check.cash_flow_basis",
            )
        )
    if discount_rate_basis != "WACC":
        issues.append(
            _issue(
                "S11_DCF_DISCOUNT_RATE_BASIS_INVALID",
                "UNLEVERED_FCFF must be discounted using an explicitly identified WACC.",
                "independent_cross_check.discount_rate_basis",
            )
        )
    if not reviewer:
        issues.append(
            _issue(
                "S11_INDEPENDENT_REVIEWER_MISSING",
                "Independent cross-check requires a named reviewer.",
                "independent_cross_check.reviewed_by",
            )
        )
    if not as_of_valid:
        issues.append(
            _issue(
                "S11_INDEPENDENT_AS_OF_DATE_INVALID",
                "Independent cross-check as-of date must equal the authoritative market-price date.",
                "independent_cross_check.as_of_date",
            )
        )

    cash_flows = [
        float(row["value"])
        for row in forecasts
        if row.get("value") is not None
    ]
    central = (
        _dcf_value(
            cash_flows,
            float(rate),
            float(growth),
            net_debt=float(net_debt["value"]),
            non_operating_assets=float(non_operating_assets["value"]),
            minority_interest=float(minority_interest["value"]),
            shares=float(shares["value"]),
        )
        if not issues
        and rate is not None
        and growth is not None
        and net_debt.get("value") is not None
        and non_operating_assets.get("value") is not None
        and minority_interest.get("value") is not None
        and shares.get("value") is not None
        else None
    )
    sensitivity_table: list[dict[str, Any]] = []
    if central and rate_step is not None and growth_step is not None:
        for rate_delta in (-rate_step, 0.0, rate_step):
            for growth_delta in (-growth_step, 0.0, growth_step):
                test_rate = rate + rate_delta
                test_growth = growth + growth_delta
                result = _dcf_value(
                    cash_flows,
                    test_rate,
                    test_growth,
                    net_debt=float(net_debt["value"]),
                    non_operating_assets=float(non_operating_assets["value"]),
                    minority_interest=float(minority_interest["value"]),
                    shares=float(shares["value"]),
                )
                sensitivity_table.append(
                    {
                        "discount_rate": test_rate,
                        "terminal_growth": test_growth,
                        "implied_price": result.get("implied_price") if result else None,
                        "formula": "DCF with explicit discount-rate and terminal-growth sensitivity",
                    }
                )
    sensitivity_prices = [
        float(row["implied_price"])
        for row in sensitivity_table
        if row.get("implied_price") is not None
    ]
    valid = (
        requested == "VALIDATED"
        and central is not None
        and len(sensitivity_prices) == 9
        and not issues
    )
    status = "VALIDATED" if valid else "INVALID"
    if requested == "VALIDATED" and not valid and not issues:
        issues.append(
            _issue(
                "S11_INDEPENDENT_CROSS_CHECK_NOT_VALIDATED",
                "Independent DCF did not produce a complete central case and 3x3 sensitivity table.",
                "valuation_cross_checks.independent_cross_check",
            )
        )
    return {
        "status": status,
        "as_of_date": source.get("as_of_date"),
        "method": method or None,
        "cash_flow_basis": cash_flow_basis or None,
        "discount_rate_basis": discount_rate_basis or None,
        "currency": currency or None,
        "forecast_cash_flows": forecasts,
        "discount_rate": discount_rate,
        "terminal_growth": terminal_growth,
        "net_debt": net_debt,
        "non_operating_assets": non_operating_assets,
        "minority_interest": minority_interest,
        "shares": shares,
        "share_basis": {
            "status": (
                "VALIDATED" if share_basis_valid else "INVALID"
            ),
            "basis_type": share_basis_type or None,
            "basis_date": share_basis_date or None,
            "matching_evidence_ids": share_basis_matching_ids,
            "rationale": share_basis_rationale or None,
            "reviewed_by": share_basis_reviewer or None,
        },
        "central_case": central or {},
        "sensitivity": {
            "discount_rate_step": rate_step,
            "terminal_growth_step": growth_step,
            "evidence_class": sensitivity.get("evidence_class"),
            "evidence_ids": sensitivity_evidence_ids,
            "matching_context_evidence_ids": (
                valid_sensitivity_evidence_ids
            ),
            "rationale": sensitivity.get("rationale"),
            "reviewed_by": sensitivity.get("reviewed_by"),
        },
        "sensitivity_table": sensitivity_table if valid else [],
        "implied_price_range": (
            {
                "minimum": min(sensitivity_prices),
                "central": central.get("implied_price"),
                "maximum": max(sensitivity_prices),
                "currency": currency,
                "status": "VALIDATED_CROSS_CHECK_RANGE",
            }
            if valid
            else {
                "minimum": None,
                "central": None,
                "maximum": None,
                "currency": currency or None,
                "status": "SUPPRESSED",
            }
        ),
        "formula": (
            "Enterprise value = PV(explicit FCF) + PV(Gordon-growth terminal value); "
            "equity value = enterprise value - net debt + non-operating assets - minority interest; "
            "implied price = equity value / shares."
        ),
        "reviewed_by": reviewer or None,
        "limitations": [
            "The DCF is an independent cross-check range, not a target price or portfolio action.",
            *[str(value) for value in _as_list(source.get("limitations")) if value],
        ],
        "validation_issues": issues,
    }


def _agreement(
    supplied: Any,
    parent: dict[str, Any],
    independent: dict[str, Any],
    known: dict[str, dict[str, Any]],
    valuation_as_of_date: str,
) -> dict[str, Any]:
    source = _as_dict(supplied)
    base_scenario = next(
        (
            row
            for row in _as_list(parent.get("scenarios"))
            if isinstance(row, dict) and row.get("name") == "Base"
        ),
        {},
    )
    base_price = _number(
        base_scenario.get("implied_price")
        if base_scenario.get("implied_price") is not None
        else base_scenario.get("target_price")
    )
    currency = str(
        parent.get("valuation", {}).get("price_currency") or ""
    ).upper()
    base_price_evidence_ids = [
        evidence_id
        for evidence_id, record in known.items()
        if str(record.get("metric_name") or "")
        == "scenario_base_implied_price"
        and str(record.get("as_of_date") or "") == valuation_as_of_date
        and base_price is not None
        and _exact_evidence_match(
            record,
            value=base_price,
            currency=currency,
            unit=f"{currency}/SHARE",
            evidence_classes={"CALC"},
        )
        and _availability_date(record) is not None
        and str(_availability_date(record)) <= valuation_as_of_date
    ]
    dcf_price = _number(
        independent.get("implied_price_range", {}).get("central")
    )
    if (
        independent.get("status") != "VALIDATED"
        or base_price is None
        or not any(
            value not in (None, "", [], {}) for value in source.values()
        )
    ):
        return {
            "status": "NOT_EVALUATED",
            "s09_base_implied_price": None,
            "s09_base_implied_price_evidence_ids": [],
            "independent_cross_check_central_price": None,
            "absolute_relative_difference": None,
            "tolerance": {
                "value": None,
                "currency": None,
                "unit": "RATIO",
                "evidence_class": "MISSING",
                "evidence_ids": [],
                "matching_evidence_ids": [],
                "context_evidence_ids": [],
                "rationale": None,
                "formula": None,
                "reviewed_by": None,
                "validation_status": "NOT_EVALUATED",
            },
            "interpretation": (
                "Method agreement is not evaluated because a validated S09 Base price, "
                "independent DCF, or explicit tolerance is missing."
            ),
            "validation_issues": [],
        }
    tolerance, tolerance_issues = _normalize_model_line(
        source.get("tolerance"),
        known=known,
        path="valuation_cross_checks.method_agreement.tolerance",
        currency=currency,
        unit="RATIO",
        kind="RATIO",
        as_of_date=valuation_as_of_date,
    )
    if not base_price_evidence_ids:
        tolerance_issues.append(
            _issue(
                "S11_AGREEMENT_BASE_PRICE_EVIDENCE_MISSING",
                "Method agreement requires the exact dated S09 Base implied-price CALC evidence.",
                "valuation_cross_checks.method_agreement",
            )
        )
    tolerance_value = _number(tolerance.get("value"))
    if tolerance_value is not None and not 0 < tolerance_value <= 1:
        tolerance_issues.append(
            _issue(
                "S11_AGREEMENT_TOLERANCE_INVALID",
                "Method-agreement tolerance must be greater than zero and no more than 100%.",
                "valuation_cross_checks.method_agreement.tolerance",
            )
        )
    difference = (
        abs(base_price - dcf_price) / abs(dcf_price)
        if base_price is not None and dcf_price not in (None, 0)
        else None
    )
    if (
        base_price is None
        or dcf_price is None
        or tolerance_value is None
        or tolerance_issues
    ):
        status = "NOT_EVALUATED"
    elif difference <= tolerance_value:
        status = "WITHIN_TOLERANCE"
    else:
        status = "DIVERGENT"
    return {
        "status": status,
        "s09_base_implied_price": base_price,
        "s09_base_implied_price_evidence_ids": (
            base_price_evidence_ids
        ),
        "independent_cross_check_central_price": dcf_price,
        "absolute_relative_difference": difference,
        "tolerance": tolerance,
        "interpretation": (
            "The methods are numerically close under the explicit tolerance."
            if status == "WITHIN_TOLERANCE"
            else "The methods diverge; retain both ranges and investigate the assumptions."
            if status == "DIVERGENT"
            else "Method agreement is not evaluated because a validated price or explicit tolerance is missing."
        ),
        "validation_issues": tolerance_issues,
    }


def _nested_evidence_ids(value: Any) -> list[str]:
    output: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.endswith("evidence_ids") and isinstance(child, list):
                output.extend(str(item) for item in child if item)
            else:
                output.extend(_nested_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            output.extend(_nested_evidence_ids(child))
    return _unique(output)


def valuation_cross_check_calculation_records(
    contract: dict[str, Any],
    parent: dict[str, Any],
) -> list[dict[str, Any]]:
    """Create stable CALC evidence for every material displayed S11 result."""

    as_of_date = str(contract.get("as_of_date") or "")
    currency = str(parent.get("valuation", {}).get("price_currency") or "").upper()
    ticker = str(parent.get("company", {}).get("ticker") or "UNKNOWN").upper()
    records: list[dict[str, Any]] = []

    def add(
        metric_name: str,
        value: Any,
        *,
        unit: str,
        formula: str,
        input_ids: Any,
        measurement_basis: str,
    ) -> str | None:
        number = _number(value)
        evidence_ids = _unique(input_ids)
        if number is None or not evidence_ids or not _iso_date(as_of_date):
            return None
        digest = hashlib.sha256(
            json.dumps(
                {
                    "ticker": ticker,
                    "metric_name": metric_name,
                    "as_of_date": as_of_date,
                    "value": number,
                    "input_evidence_ids": evidence_ids,
                    "formula": formula,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:14].upper()
        evidence_id = f"EV-S11-{digest}"
        records.append(
            {
                "evidence_id": evidence_id,
                "metric_name": metric_name,
                "value": number,
                "scale": 1.0,
                "currency": currency if unit in {currency, f"{currency}/SHARE"} else "",
                "unit": unit,
                "period_start": "",
                "period_end": as_of_date,
                "as_of_date": as_of_date,
                "publication_date": as_of_date,
                "retrieval_date": as_of_date,
                "evidence_class": "CALC",
                "evidence_type": "CALC",
                "validation_status": "PASS",
                "source_id": "SRC-S11-SHARED-CALC",
                "source_level": 0,
                "source_type": "shared_valuation_cross_check_calculation",
                "source_name": "Shared S11 valuation cross-check engine",
                "source_locator": (
                    f"valuation_cross_check_contract.{metric_name}"
                ),
                "source_location": (
                    f"valuation_cross_check_contract.{metric_name}"
                ),
                "source_tag": "calculation",
                "source_url": "",
                "measurement_basis": measurement_basis,
                "formula": formula,
                "input_evidence_ids": evidence_ids,
                "confidence": "Medium",
                "subsequent_event_status": "NOT_APPLICABLE",
                "reviewed_by": contract.get("reviewed_by"),
                "notes": (
                    "S11 calculated output; reproducibility does not establish fair value."
                ),
            }
        )
        return evidence_id

    peer = contract.get("peer_comparison", {})
    for summary in peer.get("metric_summaries", []):
        if summary.get("ranking_status") != "AVAILABLE":
            continue
        metric_slug = str(summary.get("metric") or "metric").lower().replace(
            "/",
            "_",
        )
        add(
            f"s11_peer_{metric_slug}_median",
            summary.get("median"),
            unit=(
                "RATIO"
                if summary.get("metric") == "FCF_YIELD"
                else "PURE"
            ),
            formula="median(controlled comparable peer metric values)",
            input_ids=summary.get("input_evidence_ids", []),
            measurement_basis="CONTROLLED_PEER_MEDIAN",
        )

    historical = contract.get("historical_valuation", {})
    historical_summary = historical.get("summary", {})
    if historical_summary.get("comparison_status") == "AVAILABLE":
        historical_inputs = historical_summary.get("input_evidence_ids", [])
        add(
            "s11_historical_valuation_median",
            historical_summary.get("median"),
            unit=(
                "RATIO"
                if historical.get("metric") == "FCF_YIELD"
                else "PURE"
            ),
            formula="median(controlled comparable historical metric values)",
            input_ids=historical_inputs,
            measurement_basis="CONTROLLED_HISTORICAL_MEDIAN",
        )
        add(
            "s11_historical_current_percentile",
            historical_summary.get("current_percentile"),
            unit="RATIO",
            formula="count(historical_value <= current_value) / comparable_observation_count",
            input_ids=historical_inputs,
            measurement_basis="CONTROLLED_HISTORICAL_PERCENTILE",
        )

    reverse = contract.get("reverse_valuation", {})
    if reverse.get("status") in {"VALIDATED", "PARTIALLY_VALIDATED"}:
        add(
            "s11_reverse_required_metric",
            reverse.get("required_metric_value"),
            unit=currency,
            formula=str(reverse.get("formula") or ""),
            input_ids=(
                reverse.get("capital_evidence_ids", [])
                + reverse.get("selected_reference", {}).get("evidence_ids", [])
            ),
            measurement_basis=str(reverse.get("method") or ""),
        )

    independent = contract.get("independent_cross_check", {})
    dcf_ids: dict[str, str | None] = {}
    if independent.get("status") == "VALIDATED":
        dcf_inputs = _nested_evidence_ids(independent)
        for label in ("minimum", "central", "maximum"):
            dcf_ids[label] = add(
                f"s11_independent_dcf_{label}_price",
                independent.get("implied_price_range", {}).get(label),
                unit=f"{currency}/SHARE",
                formula=str(independent.get("formula") or ""),
                input_ids=dcf_inputs,
                measurement_basis="INDEPENDENT_DCF_GORDON_GROWTH",
            )

    agreement = contract.get("method_agreement", {})
    if agreement.get("status") in {"WITHIN_TOLERANCE", "DIVERGENT"}:
        base_scenario = next(
            (
                row
                for row in _as_list(parent.get("scenarios"))
                if isinstance(row, dict) and row.get("name") == "Base"
            ),
            {},
        )
        add(
            "s11_method_relative_difference",
            agreement.get("absolute_relative_difference"),
            unit="RATIO",
            formula="abs(s09_base_implied_price - independent_dcf_central_price) / abs(independent_dcf_central_price)",
            input_ids=(
                agreement.get(
                    "s09_base_implied_price_evidence_ids",
                    [],
                )
                + _unique(base_scenario.get("evidence_ids"))
                + ([dcf_ids["central"]] if dcf_ids.get("central") else [])
                + agreement.get("tolerance", {}).get("evidence_ids", [])
            ),
            measurement_basis="VALUATION_METHOD_AGREEMENT",
        )
    return records


def _cross_check_core(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(contract.get(key))
        for key in (
            "contract_version",
            "status",
            "as_of_date",
            "reviewed_by",
            "components",
            "peer_comparison",
            "historical_valuation",
            "reverse_valuation",
            "independent_cross_check",
            "method_agreement",
            "calculation_evidence_ids",
            "limitations",
            "validation_issues",
            "input_snapshot",
        )
    }


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def build_valuation_cross_check_contract(
    parent: dict[str, Any],
    supplied: Any,
) -> dict[str, Any]:
    """Build the authoritative S11 cross-check contract."""

    source = deepcopy(_as_dict(supplied))
    valuation_as_of_date = str(
        parent.get("valuation", {}).get("price_date")
        or parent.get("report_dates", {}).get("market_price_date")
        or ""
    )
    evidence_records = parent.get("evidence_records", [])
    peer = build_peer_comparison(
        source.get("peer_comparison"),
        evidence_records,
        valuation_as_of_date,
    )
    historical = build_historical_valuation(
        source.get("historical_valuation"),
        evidence_records,
        valuation_as_of_date,
    )
    reverse = build_reverse_valuation(
        source.get("reverse_valuation"),
        parent,
        peer,
        historical,
        valuation_as_of_date,
    )
    independent = build_independent_cross_check(
        source.get("independent_cross_check"),
        parent,
        valuation_as_of_date,
    )
    agreement = _agreement(
        source.get("method_agreement"),
        parent,
        independent,
        _evidence_index(evidence_records),
        valuation_as_of_date,
    )
    components = {
        "peer_comparison": peer.get("status"),
        "historical_valuation": historical.get("status"),
        "reverse_valuation": reverse.get("status"),
        "independent_cross_check": independent.get("status"),
    }
    requested = str(source.get("status") or "NOT_PROVIDED").upper()
    all_validated = all(value == "VALIDATED" for value in components.values())
    any_validated = any(
        value in {"VALIDATED", "PARTIALLY_VALIDATED"} for value in components.values()
    )
    reviewer = str(source.get("reviewed_by") or "").strip()
    as_of_valid = (
        _iso_date(source.get("as_of_date"))
        and str(source.get("as_of_date")) == valuation_as_of_date
    )
    if (
        requested == "VALIDATED"
        and reviewer
        and as_of_valid
        and all_validated
    ):
        status = "MULTI_METHOD_VALIDATED"
    elif any_validated:
        status = "PARTIALLY_VALIDATED"
    elif requested == "NOT_PROVIDED":
        status = "NOT_PROVIDED"
    else:
        status = "INVALID"
    issues = (
        peer.get("validation_issues", [])
        + historical.get("validation_issues", [])
        + reverse.get("validation_issues", [])
        + independent.get("validation_issues", [])
        + agreement.get("validation_issues", [])
    )
    if requested == "VALIDATED" and status != "MULTI_METHOD_VALIDATED":
        issues.append(
            _issue(
                "S11_MULTI_METHOD_CONTRACT_NOT_VALIDATED",
                "S11 was submitted as VALIDATED but peer, historical, reverse, and independent cross-check components did not all validate.",
                "valuation_cross_checks",
            )
        )
    contract = {
        "contract_version": VALUATION_CROSS_CHECK_CONTRACT_VERSION,
        "status": status,
        "as_of_date": source.get("as_of_date") or None,
        "reviewed_by": reviewer or None,
        "components": components,
        "peer_comparison": peer,
        "historical_valuation": historical,
        "reverse_valuation": reverse,
        "independent_cross_check": independent,
        "method_agreement": agreement,
        "limitations": [
            "A multi-method validated status means the methods are reproducible and governed; it does not mean they agree, establish fair value, or authorize a trade.",
            *[str(value) for value in _as_list(source.get("limitations")) if value],
        ],
        "validation_issues": issues,
        "input_snapshot": source,
    }
    calculation_records = valuation_cross_check_calculation_records(
        contract,
        parent,
    )
    contract["calculation_evidence_ids"] = [
        row["evidence_id"] for row in calculation_records
    ]
    contract["recalculation_fingerprint"] = _fingerprint(_cross_check_core(contract))
    return contract


def validate_valuation_cross_check_contract(parent: dict[str, Any]) -> list[str]:
    """Rebuild persisted S11 output and detect analytical or status tampering."""

    persisted = parent.get("valuation_cross_check_contract")
    if persisted is None:
        return []
    if not isinstance(persisted, dict):
        return ["valuation_cross_check_contract must be an object."]
    if (
        persisted.get("contract_version")
        != VALUATION_CROSS_CHECK_CONTRACT_VERSION
    ):
        return ["Unsupported valuation cross-check contract version."]
    rebuilt_parent = dict(parent)
    rebuilt_parent.pop("valuation_cross_check_contract", None)
    rebuilt = build_valuation_cross_check_contract(
        rebuilt_parent,
        persisted.get("input_snapshot"),
    )
    errors: list[str] = []
    if _cross_check_core(persisted) != _cross_check_core(rebuilt):
        errors.append(
            "Persisted valuation cross-check output does not reconcile to its input snapshot and authoritative parent data."
        )
    if persisted.get("recalculation_fingerprint") != rebuilt.get(
        "recalculation_fingerprint"
    ):
        errors.append("Valuation cross-check recalculation fingerprint mismatch.")
    expected_records = valuation_cross_check_calculation_records(
        rebuilt,
        rebuilt_parent,
    )
    parent_evidence = _evidence_index(parent.get("evidence_records"))
    expected_ids = {
        str(record.get("evidence_id"))
        for record in expected_records
        if record.get("evidence_id")
    }
    actual_s11_ids = {
        str(record.get("evidence_id"))
        for record in _as_list(parent.get("evidence_records"))
        if isinstance(record, dict)
        and record.get("evidence_id")
        and (
            str(record.get("metric_name") or "").startswith("s11_")
            or record.get("source_id") == "SRC-S11-SHARED-CALC"
        )
    }
    unexpected_ids = sorted(actual_s11_ids - expected_ids)
    if unexpected_ids:
        errors.append(
            "Unexpected S11 CALC evidence records are present: "
            + ", ".join(unexpected_ids)
            + "."
        )
    for expected in expected_records:
        actual = parent_evidence.get(str(expected.get("evidence_id")))
        fields = (
            "metric_name",
            "value",
            "scale",
            "currency",
            "unit",
            "period_end",
            "as_of_date",
            "publication_date",
            "retrieval_date",
            "evidence_class",
            "validation_status",
            "source_id",
            "source_level",
            "source_type",
            "source_locator",
            "measurement_basis",
            "formula",
            "input_evidence_ids",
            "reviewed_by",
        )
        if actual is None or any(
            actual.get(field) != expected.get(field) for field in fields
        ):
            errors.append(
                f"Missing or inconsistent S11 CALC evidence: {expected.get('evidence_id')}."
            )
    return errors


def _scenario_probability_map(scenarios: Any) -> dict[str, float | None]:
    result: dict[str, float | None] = {"Bear": None, "Base": None, "Bull": None}
    for scenario in _as_list(scenarios):
        if isinstance(scenario, dict):
            name = str(scenario.get("name") or "")
            if name in result:
                result[name] = _number(scenario.get("probability"))
        else:
            name = str(getattr(scenario, "name", "") or "")
            if name in result:
                result[name] = _number(getattr(scenario, "probability", None))
    return result


def _scenario_price_map(scenarios: Any) -> dict[str, float | None]:
    result: dict[str, float | None] = {"Bear": None, "Base": None, "Bull": None}
    for scenario in _as_list(scenarios):
        if isinstance(scenario, dict):
            name = str(scenario.get("name") or "")
            value = (
                scenario.get("implied_price")
                if scenario.get("implied_price") is not None
                else scenario.get("target_price")
            )
        else:
            name = str(getattr(scenario, "name", "") or "")
            value = getattr(scenario, "target_price", None)
        if name in result:
            result[name] = _number(value)
    return result


def _probability_method_details_valid(
    method_type: str,
    details: dict[str, Any],
) -> bool:
    required = PROBABILITY_METHOD_REQUIRED_DETAILS.get(method_type, set())
    if any(details.get(field) in (None, "", [], {}) for field in required):
        return False
    if method_type in {"HISTORICAL_FREQUENCY", "BASE_RATE_ANALYSIS"}:
        sample_size = _number(details.get("sample_size"))
        return sample_size is not None and sample_size >= 10
    if method_type == "MONTE_CARLO":
        iterations = _number(details.get("iterations"))
        return (
            iterations is not None
            and iterations >= 1000
            and isinstance(details.get("input_distributions"), (dict, list))
            and bool(details.get("input_distributions"))
        )
    if method_type == "SCENARIO_JUDGMENT":
        return details.get("sensitivity_completed") is True
    return True


def _scenario_probability_rationales(
    supplied: dict[str, Any],
    scenarios: Any,
) -> dict[str, str]:
    raw = _as_dict(supplied.get("scenario_rationales"))
    result: dict[str, str] = {}
    for name in ("Bear", "Base", "Bull"):
        value = raw.get(name)
        if isinstance(value, dict):
            value = value.get("rationale")
        if value:
            result[name] = str(value)
    for scenario in _as_list(scenarios):
        name = (
            str(scenario.get("name") or "")
            if isinstance(scenario, dict)
            else str(getattr(scenario, "name", "") or "")
        )
        rationale = (
            scenario.get("probability_rationale")
            if isinstance(scenario, dict)
            else getattr(scenario, "probability_rationale", None)
        )
        if name in {"Bear", "Base", "Bull"} and rationale and name not in result:
            result[name] = str(rationale)
    return result


def _sensitivity_classification(
    cases: list[dict[str, Any]],
    central: dict[str, float],
    scenario_prices: dict[str, float | None],
) -> tuple[list[dict[str, Any]], set[str]]:
    normalized: list[dict[str, Any]] = []
    categories: set[str] = set()
    for index, row in enumerate(cases):
        weights = _as_dict(row.get("probabilities"))
        values = {name: _number(weights.get(name)) for name in ("Bear", "Base", "Bull")}
        if (
            any(value is None or value < 0 or value > 1 for value in values.values())
            or not isclose(sum(float(value) for value in values.values()), 1.0, abs_tol=1e-9)
        ):
            continue
        numeric = {name: float(value) for name, value in values.items()}
        if all(_same_number(numeric[name], central[name]) for name in central):
            category = "CENTRAL"
        elif (
            numeric["Bear"] > central["Bear"]
            and numeric["Bear"] > numeric["Bull"]
        ):
            category = "DOWNSIDE_HEAVY"
        elif (
            numeric["Bull"] > central["Bull"]
            and numeric["Bull"] > numeric["Bear"]
        ):
            category = "UPSIDE_HEAVY"
        else:
            category = "OTHER"
        categories.add(category)
        weighted_price = (
            sum(
                numeric[name] * float(scenario_prices[name])
                for name in ("Bear", "Base", "Bull")
            )
            if all(
                scenario_prices.get(name) is not None
                for name in ("Bear", "Base", "Bull")
            )
            else None
        )
        normalized.append(
            {
                "label": row.get("label") or f"Sensitivity {index + 1}",
                "classification": category,
                "probabilities": numeric,
                "weighted_implied_price_sensitivity": weighted_price,
                "formal_weighted_expected_return": None,
                "formula": "sum(scenario_probability * scenario_implied_price)",
            }
        )
    return normalized, categories


def build_probability_governance(
    supplied: Any,
    scenarios: Any,
    evidence_records: Any,
    analysis_date: str,
) -> dict[str, Any]:
    """Validate scenario probabilities independently from scenario-price math."""

    source = deepcopy(_as_dict(supplied))
    probabilities = _scenario_probability_map(scenarios)
    scenario_prices = _scenario_price_map(scenarios)
    provided = any(value is not None for value in probabilities.values())
    if not provided:
        return {
            "governance_version": PROBABILITY_GOVERNANCE_VERSION,
            "status": "NOT_PROVIDED",
            "probability_governance_valid": False,
            "weighted_return_allowed": False,
            "method_type": None,
            "methodology": None,
            "method_details": {},
            "method_evidence_ids": [],
            "scenario_rationales": {},
            "as_of_date": None,
            "expiration_review_date": None,
            "freshness_status": "NOT_APPLICABLE",
            "review_triggers": [],
            "reviewed_by": None,
            "approval": {
                "status": "NOT_APPROVED",
                "approved_by": None,
                "independent_research_review": False,
            },
            "sensitivity_table": [],
            "limitations": [
                "Scenario prices may be shown, but no probability-weighted return is available."
            ],
            "validation_issues": [],
            "input_snapshot": source,
        }
    method_type = str(source.get("method_type") or "").upper()
    methodology = str(source.get("methodology") or "").strip()
    details = _as_dict(source.get("method_details"))
    method_valid = (
        method_type in PROBABILITY_METHOD_TYPES
        and methodology.lower()
        not in {"", "analyst judgment", "scenario judgment", "judgment"}
        and _probability_method_details_valid(method_type, details)
    )
    probability_math_valid = (
        all(
            value is not None and 0 <= value <= 1
            for value in probabilities.values()
        )
        and isclose(
            sum(float(value) for value in probabilities.values() if value is not None),
            1.0,
            abs_tol=1e-9,
        )
    )
    known = _evidence_index(evidence_records)
    evidence_ids = _unique(source.get("evidence_ids"))
    valid_evidence, unknown_evidence, future_evidence = _context_evidence_valid(
        evidence_ids,
        known,
        as_of_date=str(source.get("as_of_date") or ""),
    )
    valid_evidence = [
        evidence_id
        for evidence_id in valid_evidence
        if known[evidence_id].get("source_level") in {1, 2, 3, 4}
    ]
    rationales = _scenario_probability_rationales(source, scenarios)
    rationales_valid = all(rationales.get(name) for name in ("Bear", "Base", "Bull"))
    as_of_date = str(source.get("as_of_date") or "")
    expiration = str(
        source.get("probability_expiration_review_date")
        or source.get("expiration_review_date")
        or ""
    )
    dates_valid = (
        _iso_date(analysis_date)
        and _iso_date(as_of_date)
        and _iso_date(expiration)
        and as_of_date <= analysis_date
        and as_of_date <= expiration
    )
    freshness = "NOT_APPLICABLE"
    if dates_valid:
        freshness = "STALE" if analysis_date > expiration else "CURRENT"
        if (
            freshness == "CURRENT"
            and (date.fromisoformat(expiration) - date.fromisoformat(analysis_date)).days
            <= 30
        ):
            freshness = "EXPIRING_SOON"
        triggers = {
            str(value).upper() for value in _as_list(source.get("review_triggers")) if value
        }
        if "NEW_EARNINGS_OR_GUIDANCE" in triggers:
            later_primary = [
                record
                for record in known.values()
                if record.get("source_level") in {1, 2}
                and _iso_date(record.get("publication_date"))
                and str(record.get("publication_date")) > as_of_date
                and str(record.get("publication_date")) <= analysis_date
            ]
            if later_primary:
                freshness = "SUPERSEDED"
    review_triggers = {
        str(value).upper() for value in _as_list(source.get("review_triggers")) if value
    }
    triggers_valid = "NEW_EARNINGS_OR_GUIDANCE" in review_triggers
    reviewed_by = str(source.get("reviewed_by") or "").strip()
    approval = _as_dict(source.get("approval"))
    approved_by = str(approval.get("approved_by") or "").strip()
    approval_date = str(approval.get("approval_date") or "")
    approval_valid = (
        approval.get("status") == "APPROVED"
        and bool(approved_by)
        and approved_by.casefold() != reviewed_by.casefold()
        and approval.get("independent_research_review") is True
        and approval.get("approval_scope") == INDEPENDENT_APPROVAL_SCOPE
        and _iso_date(approval_date)
        and dates_valid
        and as_of_date <= approval_date <= analysis_date
    )
    central = {
        name: float(value)
        for name, value in probabilities.items()
        if value is not None
    }
    sensitivity_table, sensitivity_categories = (
        _sensitivity_classification(
            [row for row in _as_list(source.get("sensitivity_cases")) if isinstance(row, dict)],
            central,
            scenario_prices,
        )
        if len(central) == 3
        else ([], set())
    )
    sensitivity_valid = {
        "DOWNSIDE_HEAVY",
        "CENTRAL",
        "UPSIDE_HEAVY",
    }.issubset(sensitivity_categories)
    requested = str(source.get("status") or "ILLUSTRATIVE").upper()
    formal_valid = all(
        (
            requested == "VALIDATED",
            method_valid,
            probability_math_valid,
            bool(valid_evidence),
            not unknown_evidence,
            not future_evidence,
            rationales_valid,
            dates_valid,
            freshness in {"CURRENT", "EXPIRING_SOON"},
            triggers_valid,
            bool(reviewed_by),
            approval_valid,
            sensitivity_valid,
        )
    )
    if freshness in {"STALE", "SUPERSEDED"}:
        status = "STALE"
    elif formal_valid:
        status = "VALIDATED"
    elif requested == "VALIDATED":
        status = "INVALID"
    else:
        status = "ILLUSTRATIVE"
    limitations: list[str] = []
    if not method_valid:
        limitations.append("Probability method or method-specific details are incomplete.")
    if not probability_math_valid:
        limitations.append("Scenario probabilities must be within [0,1] and total 100%.")
    if not valid_evidence or unknown_evidence or future_evidence:
        limitations.append("Probability evidence is missing, unresolved, or dated after the probability as-of date.")
    if not rationales_valid:
        limitations.append("Bear, Base, and Bull probability rationales are incomplete.")
    if not dates_valid or freshness not in {"CURRENT", "EXPIRING_SOON"}:
        limitations.append("Probability dates are invalid, expired, or superseded.")
    if not triggers_valid:
        limitations.append("New earnings or guidance is not configured as a mandatory review trigger.")
    if not approval_valid:
        limitations.append("Independent research approval is incomplete, same-owner, out of date, or has the wrong scope.")
    if not sensitivity_valid:
        limitations.append("Sensitivity must include downside-heavy, central, and upside-heavy weight sets.")
    issues: list[dict[str, str]] = []
    if status != "VALIDATED":
        issues.append(
            _issue(
                "S11_PROBABILITY_GOVERNANCE_NOT_VALIDATED",
                f"Probability status={status}; method={method_type or 'MISSING'}; freshness={freshness}.",
                "probability_framework",
                status="WARNING" if status in {"ILLUSTRATIVE", "STALE"} else "FAIL",
            )
        )
    return {
        "governance_version": PROBABILITY_GOVERNANCE_VERSION,
        "status": status,
        "probability_governance_valid": status == "VALIDATED",
        "weighted_return_allowed": status == "VALIDATED",
        "method_type": method_type or None,
        "methodology": methodology or None,
        "method_details": details,
        "method_evidence_ids": evidence_ids,
        "matching_method_evidence_ids": valid_evidence,
        "unknown_evidence_ids": unknown_evidence,
        "future_evidence_ids": future_evidence,
        "scenario_rationales": rationales,
        "as_of_date": as_of_date or None,
        "expiration_review_date": expiration or None,
        "freshness_status": freshness,
        "review_triggers": sorted(review_triggers),
        "reviewed_by": reviewed_by or None,
        "approval": {
            "status": approval.get("status", "NOT_APPROVED"),
            "approved_by": approved_by or None,
            "approval_date": approval_date or None,
            "approval_scope": approval.get("approval_scope"),
            "independent_research_review": approval.get(
                "independent_research_review"
            )
            is True,
        },
        "sensitivity_table": sensitivity_table,
        "sensitivity_categories": sorted(sensitivity_categories),
        "limitations": limitations,
        "validation_issues": issues,
        "input_snapshot": source,
    }


def validate_probability_governance(parent: dict[str, Any]) -> list[str]:
    persisted = parent.get("probability_validation")
    if not isinstance(persisted, dict) or not persisted.get("governance_version"):
        return []
    if persisted.get("governance_version") != PROBABILITY_GOVERNANCE_VERSION:
        return ["Unsupported probability-governance version."]
    rebuilt = build_probability_governance(
        persisted.get("input_snapshot"),
        parent.get("scenarios"),
        parent.get("evidence_records"),
        str(
            parent.get("valuation", {}).get("price_date")
            or parent.get("report_dates", {}).get("market_price_date")
            or ""
        ),
    )
    valuation_outputs = (
        parent.get("valuation_contract", {}).get("outputs", {})
        if isinstance(parent.get("valuation_contract"), dict)
        else {}
    )
    formal_output = valuation_outputs.get("probability_weighted_return")
    if isinstance(formal_output, dict):
        formal_allowed = formal_output.get("status") == "VALIDATED"
        rebuilt["weighted_return_allowed"] = formal_allowed
        rebuilt[
            "formal_probability_weighted_expected_return_status"
        ] = "VALIDATED" if formal_allowed else "NOT_EVALUATED"
    fields = (
        "governance_version",
        "status",
        "probability_governance_valid",
        "weighted_return_allowed",
        "method_type",
        "methodology",
        "method_details",
        "method_evidence_ids",
        "matching_method_evidence_ids",
        "unknown_evidence_ids",
        "future_evidence_ids",
        "scenario_rationales",
        "as_of_date",
        "expiration_review_date",
        "freshness_status",
        "review_triggers",
        "reviewed_by",
        "approval",
        "sensitivity_table",
        "sensitivity_categories",
        "limitations",
        "validation_issues",
        "input_snapshot",
        "formal_probability_weighted_expected_return_status",
    )
    if any(persisted.get(field) != rebuilt.get(field) for field in fields):
        return [
            "Persisted probability governance does not reconcile to its input snapshot, scenarios, dates, and evidence."
        ]
    return []
