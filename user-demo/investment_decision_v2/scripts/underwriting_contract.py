#!/usr/bin/env python3
"""Shared contracts and validation rules for public-company underwriting.

This module is deliberately company-agnostic. Data ingestion, investment
analysis, and rendering must exchange information through these contracts so
that a renderer cannot repair, replace, or independently recalculate an
analytical conclusion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Iterable

from equity_valuation_contract import (
    build_shared_valuation_contract,
    legacy_return_context,
    suppress_shared_valuation_outputs,
    validate_shared_valuation_contract,
)
from forward_operating_model import validate_forward_valuation_contract
from valuation_cross_checks import (
    build_valuation_cross_check_contract,
    validate_probability_governance,
    validate_valuation_cross_check_contract,
)

SCHEMA_VERSION = "5.1.0"
SUPPORTED_UNIVERSE_VERSION = "1.0.0"
GATE4_ELIGIBILITY_CONTRACT_VERSION = "1.0.0"
SUPPORTED_GATE3_SCHEMA_VERSIONS = {"5.0.0", SCHEMA_VERSION}

EVIDENCE_CLASSES = {"FACT", "CALC", "INFERENCE", "JUDGMENT", "MISSING"}
CONFIDENCE_LEVELS = {"High", "Medium", "Low"}
VALIDATION_STATUSES = {
    "PASS",
    "FAIL",
    "BLOCKED",
    "WARNING",
    "MISSING",
    "PROVISIONAL",
    "NOT_APPLICABLE",
}
ISSUE_CLASSES = {"HARD_STOP", "WARNING", "INFO"}

PROBABILITY_METHOD_TYPES = {
    "HISTORICAL_FREQUENCY",
    "MANAGEMENT_GUIDANCE_CONFIDENCE",
    "SCENARIO_JUDGMENT",
    "MONTE_CARLO",
    "BASE_RATE_ANALYSIS",
}
PROBABILITY_VALIDATION_STATUSES = {
    "NOT_PROVIDED",
    "ILLUSTRATIVE",
    "VALIDATED",
    "STALE",
    "INVALID",
}
PROBABILITY_FRESHNESS_STATUSES = {"NOT_APPLICABLE", "CURRENT", "EXPIRING_SOON", "STALE", "SUPERSEDED"}
PEER_COMPARABILITY_STATUSES = {"COMPARABLE", "LIMITED", "NOT_COMPARABLE"}
FCF_NORMALIZATION_STATUSES = {
    "UNADJUSTED_PUBLIC_BASE",
    "PARTIALLY_NORMALIZED",
    "FULLY_NORMALIZED",
}
RESEARCH_WORKFLOW_STATUSES = {
    "Data Review Required",
    "Underwriting In Progress",
    "Ready for Human Review",
}
PUBLIC_DATA_INVESTMENT_VIEWS = {
    "Continue Research",
    "Watch",
    "Stop Research",
    "Case Strengthening",
    "Case Weakening",
}
VALUATION_SCOPE_STATUSES = {"RANGE_ONLY", "PARTIALLY_VALIDATED", "MULTI_METHOD_VALIDATED"}
VALUATION_COMPONENT_STATUSES = {"MISSING", "NOT_COMPLETED", "PROVISIONAL", "COMPLETED"}
SHARE_COUNT_PROXY_STATUSES = {"CURRENT", "PROXY"}
SHARE_COUNT_BASIS_TYPES = {"POINT_IN_TIME", "FORWARD"}
KNOWN_SUBSEQUENT_EVENT_STATUSES = {
    "NOT_REVIEWED",
    "REVIEWED_NO_QUANTIFIED_CHANGE",
    "REVIEWED_CHANGE_REFLECTED",
    "REVIEWED_CHANGE_NOT_INCORPORATED",
}
GATE4_GATE3_ELIGIBILITY_STATUSES = {
    "GATE_4_PRIVATE_INPUTS_REQUIRED",
    "GATE_4_BLOCKED_STALE_GATE_3",
    "GATE_4_BLOCKED_INELIGIBLE_GATE_3",
}
GATE4_ELIGIBILITY_CHECK_STATUSES = {"PASS", "BLOCKED", "ESCALATED", "NOT_APPLICABLE"}

PROBABILITY_METHOD_REQUIRED_DETAILS: dict[str, set[str]] = {
    "HISTORICAL_FREQUENCY": {"reference_class", "sample_period", "sample_size", "event_definition"},
    "MANAGEMENT_GUIDANCE_CONFIDENCE": {"guidance_track_record", "assessment_rule"},
    "SCENARIO_JUDGMENT": {"allocation_rationale", "sensitivity_completed"},
    "MONTE_CARLO": {"model_version", "iterations", "input_distributions"},
    "BASE_RATE_ANALYSIS": {"reference_class", "sample_period", "sample_size", "event_definition"},
}

SOURCE_LEVELS: dict[int, dict[str, Any]] = {
    0: {
        "name": "Analyst-owned input or judgment",
        "examples": ["normalized metric", "scenario assumption", "variant perception"],
        "note": "Not an external source; reviewer ownership and linked external evidence are mandatory where applicable.",
    },
    1: {
        "name": "Primary regulatory and company filings",
        "examples": ["10-K", "10-Q", "20-F", "regulatory filing", "filed debt agreement"],
    },
    2: {
        "name": "Official company investor materials",
        "examples": ["earnings release", "investor presentation", "official guidance"],
    },
    3: {
        "name": "Approved market and reference data",
        "examples": ["approved price feed", "approved bond feed", "approved benchmark feed"],
    },
    4: {
        "name": "Institutional third-party research",
        "examples": ["consensus", "rating report", "sell-side research"],
    },
    5: {
        "name": "Other external sources",
        "examples": ["general financial website", "news", "unverified aggregator"],
    },
}


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def stable_id(prefix: str, *parts: Any, length: int = 14) -> str:
    payload = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length].upper()
    return f"{prefix}-{digest}"


@dataclass
class EvidenceRecord:
    evidence_id: str
    metric_name: str
    value: Any
    unit: str = ""
    currency: str = ""
    scale: float = 1.0
    period_start: str = ""
    period_end: str = ""
    period_type: str = ""
    duration_days: int | str = ""
    as_of_date: str = ""
    measurement_basis: str = "reported"
    fiscal_period: str = ""
    filing_type: str = ""
    publication_date: str = ""
    retrieval_date: str = ""
    source_level: int = 1
    source_type: str = "regulatory_filing"
    source_name: str = ""
    source_locator: str = ""
    source_tag: str = ""
    source_url: str = ""
    evidence_class: str = "FACT"
    reported_or_calculated: str = "reported"
    formula: str = ""
    input_evidence_ids: list[str] = field(default_factory=list)
    confidence: str = "High"
    validation_status: str = "PASS"
    subsequent_event_status: str = "NOT_APPLICABLE"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationIssue:
    check_id: str
    category: str
    status: str
    issue_class: str
    severity: str
    message: str
    decision_impact: str
    remediation: str
    evidence_ids: list[str] = field(default_factory=list)
    scope: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Gate4EligibilityCheck:
    check_id: str
    category: str
    status: str
    blocking_class: str
    detail: str
    decision_impact: str
    remediation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CashFlowLedgerLine:
    line_id: str
    label: str
    amount: float | None
    period_start: str
    period_end: str
    treatment: str
    embedded_in_cfo: bool
    separately_modeled: bool
    evidence_ids: list[str] = field(default_factory=list)
    reversal_id: str = ""
    double_count_status: str = "PASS"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_evidence_id(
    company_key: str,
    metric_name: str,
    period_start: str,
    period_end: str,
    source_tag: str,
    source_locator: str,
) -> str:
    return stable_id(
        "EV",
        company_key.upper(),
        metric_name,
        period_start,
        period_end,
        source_tag,
        source_locator,
    )


def assess_supported_universe(
    *,
    forms: Iterable[str],
    taxonomies: Iterable[str],
    sic: str | int | None,
) -> dict[str, Any]:
    form_set = {str(form).upper() for form in forms}
    taxonomy_set = {str(taxonomy).lower() for taxonomy in taxonomies}
    try:
        sic_number = int(str(sic)) if sic not in (None, "") else None
    except ValueError:
        sic_number = None

    reasons: list[str] = []
    status = "SUPPORTED_CORE"
    overlay = "none"

    if "10-K" not in form_set and form_set.intersection({"20-F", "40-F"}):
        status = "SPECIALIZED_OVERLAY_REQUIRED"
        overlay = "foreign_private_issuer"
        reasons.append("Foreign private issuer reporting requires 20-F/6-K period and taxonomy rules.")
    elif "10-K" not in form_set:
        status = "UNSUPPORTED"
        reasons.append("No recent 10-K was identified.")

    if "us-gaap" not in taxonomy_set:
        status = "SPECIALIZED_OVERLAY_REQUIRED" if status != "UNSUPPORTED" else status
        overlay = "non_us_gaap"
        reasons.append("The current normalized metric map is built for US GAAP taxonomy.")

    if sic_number is not None and 6000 <= sic_number <= 6799:
        status = "SPECIALIZED_OVERLAY_REQUIRED"
        overlay = "financial_institution"
        reasons.append("Banks, insurers, brokers, and other financial firms require specialized liquidity and capital rules.")

    if status == "SUPPORTED_CORE":
        reasons.append("SEC 10-K/10-Q, US GAAP, non-financial public-company core is supported.")

    return {
        "version": SUPPORTED_UNIVERSE_VERSION,
        "status": status,
        "overlay_required": overlay,
        "reasons": reasons,
        "supported_core_definition": "SEC-reporting, US GAAP, non-financial issuer using 10-K/10-Q filings",
    }


def periods_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = ("period_start", "period_end", "period_type", "duration_days")
    return all(left.get(key) == right.get(key) for key in keys)


def detect_material_conflicts(records: Iterable[dict[str, Any]]) -> list[ValidationIssue]:
    """Detect unresolved values at the same metric grain.

    Source priority is applied only after metric definition, period, as-of date,
    measurement basis, unit, and currency match. A higher source level never
    silently overrides a non-comparable value.
    """

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in records:
        key = (
            row.get("metric_name"),
            row.get("period_start"),
            row.get("period_end"),
            row.get("period_type"),
            row.get("as_of_date"),
            row.get("measurement_basis"),
            row.get("unit"),
            row.get("currency"),
        )
        groups.setdefault(key, []).append(row)

    issues: list[ValidationIssue] = []
    for key, rows in groups.items():
        if len(rows) < 2:
            continue
        numeric: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            try:
                numeric.append((float(row.get("value")), row))
            except (TypeError, ValueError):
                continue
        if len(numeric) < 2:
            continue
        values = [item[0] for item in numeric]
        tolerance = max(1.0, max(abs(value) for value in values) * 0.001)
        if max(values) - min(values) <= tolerance:
            continue
        ids = [str(item[1].get("evidence_id", "")) for item in numeric]
        issues.append(
            ValidationIssue(
                check_id=stable_id("VAL", "source-conflict", *key),
                category="source_conflict",
                status="FAIL",
                issue_class="HARD_STOP",
                severity="Critical",
                message=f"Conflicting values exist for {key[0]} at the same metric grain.",
                decision_impact="The system cannot know which value is valid without reconciliation.",
                remediation="Reconcile definition, filing version, source priority, and amendment status; document any override.",
                evidence_ids=ids,
            )
        )
    return issues


def validate_cash_flow_ledger(lines: Iterable[CashFlowLedgerLine]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for line in lines:
        if line.embedded_in_cfo and line.separately_modeled and not line.reversal_id:
            line.double_count_status = "FAIL"
            issues.append(
                ValidationIssue(
                    check_id=stable_id("VAL", "double-count", line.line_id),
                    category="double_counting",
                    status="FAIL",
                    issue_class="HARD_STOP",
                    severity="Critical",
                    message=f"{line.label} is embedded in CFO and also modeled separately without an explicit reversal.",
                    decision_impact="FCF or liquidity is misstated by double counting the same cash movement.",
                    remediation="Remove the separate line or add a sourced reversal with a linked reversal_id.",
                    evidence_ids=line.evidence_ids,
                )
            )
        else:
            line.double_count_status = "PASS"
    return issues


def active_hard_stops(issues: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in issues
        if issue.get("issue_class") == "HARD_STOP" and issue.get("status") in {"FAIL", "BLOCKED"}
    ]


def active_warnings(issues: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in issues
        if issue.get("issue_class") == "WARNING"
        and issue.get("status") in {"WARNING", "MISSING", "PROVISIONAL", "FAIL", "BLOCKED"}
    ]


def validation_issue_identifier(issue: dict[str, Any]) -> str:
    """Return the shared stable identifier used by Gate 4 warning escalation."""
    for field in ("check_id", "id", "code"):
        value = issue.get(field)
        if value not in (None, ""):
            return str(value)
    return ""


def parse_iso_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def assess_gate3_for_gate4(
    contract: dict[str, Any],
    *,
    policy: dict[str, Any] | None,
    freshness_attestation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assess whether an immutable Gate 3 contract may enter Gate 4.

    The caller must provide explicit age limits and a public-data freshness
    attestation. This function never refreshes issuer data, invents a policy
    default, or treats a Data Integrity Hard Stop as an escalation.
    """

    policy = dict(policy or {})
    attestation = dict(freshness_attestation or {})
    checks: list[Gate4EligibilityCheck] = []

    def is_missing(value: Any) -> bool:
        return value is None or value == ""

    def add(
        check_id: str,
        category: str,
        status: str,
        blocking_class: str,
        detail: str,
        decision_impact: str,
        remediation: str,
    ) -> None:
        checks.append(
            Gate4EligibilityCheck(
                check_id=check_id,
                category=category,
                status=status,
                blocking_class=blocking_class,
                detail=detail,
                decision_impact=decision_impact,
                remediation=remediation,
            )
        )

    schema_version = str(contract.get("schema_version") or "")
    add(
        "G4E-contract-version",
        "contract",
        "PASS" if schema_version in SUPPORTED_GATE3_SCHEMA_VERSIONS else "BLOCKED",
        "" if schema_version in SUPPORTED_GATE3_SCHEMA_VERSIONS else "INELIGIBLE",
        f"schema_version={schema_version or 'missing'}; supported={sorted(SUPPORTED_GATE3_SCHEMA_VERSIONS)}",
        "Gate 4 must consume a supported, versioned Gate 3 contract.",
        "Rebuild or migrate the issuer contract with a supported shared schema.",
    )

    try:
        current_contract_errors = validate_output_contract(contract)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        current_contract_errors = [f"Contract validator could not parse the object: {exc}"]
    stored_validation_status = contract.get("contract_validation", {}).get("status")
    contract_valid = stored_validation_status == "PASS" and not current_contract_errors
    add(
        "G4E-contract-validation",
        "contract",
        "PASS" if contract_valid else "BLOCKED",
        "" if contract_valid else "INELIGIBLE",
        (
            f"stored_status={stored_validation_status or 'missing'}; "
            f"current_error_count={len(current_contract_errors)}"
        ),
        "An invalid shared contract cannot support a portfolio assessment.",
        "Resolve shared contract validation errors before Gate 4.",
    )

    stored_contract_hash = str(contract.get("contract_hash") or "")
    hash_input = {
        key: value
        for key, value in contract.items()
        if key not in {"contract_hash", "contract_validation"}
    }
    calculated_contract_hash = hashlib.sha256(
        canonical_json(hash_input).encode("utf-8")
    ).hexdigest()
    contract_hash_valid = bool(stored_contract_hash) and stored_contract_hash == calculated_contract_hash
    add(
        "G4E-contract-hash",
        "contract",
        "PASS" if contract_hash_valid else "BLOCKED",
        "" if contract_hash_valid else "INELIGIBLE",
        (
            f"stored_hash={stored_contract_hash or 'missing'}; "
            f"calculated_hash={calculated_contract_hash}"
        ),
        "Gate 4 must consume the exact validated Gate 3 object, not a modified copy with stale validation metadata.",
        "Rebuild and independently validate the Gate 3 contract before Gate 4.",
    )

    gate_level = contract.get("data_gate", {}).get("level")
    try:
        gate3_or_above = float(gate_level) >= 3
    except (TypeError, ValueError):
        gate3_or_above = False
    add(
        "G4E-data-gate",
        "contract",
        "PASS" if gate3_or_above else "BLOCKED",
        "" if gate3_or_above else "INELIGIBLE",
        f"data_gate={gate_level}",
        "Issuer underwriting, valuation, and scenario prices must reach Gate 3 before portfolio use.",
        "Complete and validate Gate 3 first.",
    )

    issue_rows = list(contract.get("validation_issues", []))
    hard_stops = list(contract.get("hard_stops", []))
    known_hard_stop_ids = {
        validation_issue_identifier(row)
        for row in hard_stops + active_hard_stops(issue_rows)
        if validation_issue_identifier(row)
    }
    add(
        "G4E-data-hard-stops",
        "data_integrity",
        "PASS" if not known_hard_stop_ids else "BLOCKED",
        "" if not known_hard_stop_ids else "INELIGIBLE",
        f"active_hard_stop_ids={sorted(known_hard_stop_ids)}",
        "Data Integrity Hard Stops cannot be escalated into Gate 4.",
        "Correct and revalidate every active Hard Stop; escalation is not permitted.",
    )

    required_policy_fields = {
        "max_report_age_days",
        "max_financial_data_age_days",
        "max_market_data_age_days",
        "max_public_source_check_lag_days",
        "eligible_valuation_statuses",
        "require_validated_probabilities",
        "allow_warning_escalation",
    }
    missing_policy_fields = sorted(
        field for field in required_policy_fields if field not in policy or is_missing(policy.get(field))
    )
    numeric_policy_fields = (
        "max_report_age_days",
        "max_financial_data_age_days",
        "max_market_data_age_days",
        "max_public_source_check_lag_days",
    )
    invalid_numeric_policy_fields: list[str] = []
    for field in numeric_policy_fields:
        if field not in policy or is_missing(policy.get(field)):
            continue
        try:
            if isinstance(policy[field], bool) or int(policy[field]) < 0:
                invalid_numeric_policy_fields.append(field)
        except (TypeError, ValueError):
            invalid_numeric_policy_fields.append(field)
    eligible_valuation_statuses = policy.get("eligible_valuation_statuses")
    policy_types_valid = (
        isinstance(eligible_valuation_statuses, list)
        and bool(eligible_valuation_statuses)
        and set(eligible_valuation_statuses).issubset(VALUATION_SCOPE_STATUSES)
        and isinstance(policy.get("require_validated_probabilities"), bool)
        and isinstance(policy.get("allow_warning_escalation"), bool)
    )
    policy_complete = not missing_policy_fields and not invalid_numeric_policy_fields and policy_types_valid
    add(
        "G4E-policy-completeness",
        "policy",
        "PASS" if policy_complete else "BLOCKED",
        "" if policy_complete else "INELIGIBLE",
        (
            f"missing={missing_policy_fields}; invalid_numeric={invalid_numeric_policy_fields}; "
            f"types_valid={policy_types_valid}"
        ),
        "Gate 4 cannot invent age limits, valuation eligibility, probability requirements, or escalation rules.",
        "Complete the Gate 4 eligibility policy with explicit, reviewed values.",
    )

    required_attestation_fields = {
        "gate3_report_id",
        "gate3_contract_hash",
        "as_of_date",
        "latest_earnings_checked_through",
        "latest_known_financial_filing_date",
        "newer_earnings_filing_known",
        "subsequent_events_checked_through",
        "unreviewed_material_subsequent_event_known",
        "reviewed_by",
        "reviewed_at",
    }
    missing_attestation_fields = sorted(
        field
        for field in required_attestation_fields
        if field not in attestation or is_missing(attestation.get(field))
    )
    attestation_as_of_date = parse_iso_date(attestation.get("as_of_date"))
    reviewed_at_date = parse_iso_date(attestation.get("reviewed_at"))
    attestation_boolean_types_valid = (
        isinstance(attestation.get("newer_earnings_filing_known"), bool)
        and isinstance(attestation.get("unreviewed_material_subsequent_event_known"), bool)
    )
    attestation_dates_valid = (
        attestation_as_of_date is not None
        and reviewed_at_date is not None
        and reviewed_at_date <= attestation_as_of_date
    )
    attestation_complete = (
        not missing_attestation_fields
        and attestation_boolean_types_valid
        and attestation_dates_valid
    )
    add(
        "G4E-freshness-attestation",
        "freshness",
        "PASS" if attestation_complete else "BLOCKED",
        "" if attestation_complete else "STALE",
        (
            f"missing={missing_attestation_fields}; "
            f"boolean_types_valid={attestation_boolean_types_valid}; "
            f"dates_valid={attestation_dates_valid}"
        ),
        "Gate 4 requires a dated, reviewer-owned check for newer earnings and material events.",
        "Refresh public-source checks and record the reviewer, dates, and explicit event answers.",
    )

    attested_identity_valid = (
        attestation.get("gate3_report_id") == contract.get("report_id")
        and attestation.get("gate3_contract_hash") == contract.get("contract_hash")
    )
    add(
        "G4E-attestation-contract-identity",
        "contract",
        "PASS" if attested_identity_valid else "BLOCKED",
        "" if attested_identity_valid else "INELIGIBLE",
        (
            f"report_id_match={attestation.get('gate3_report_id') == contract.get('report_id')}; "
            f"contract_hash_match={attestation.get('gate3_contract_hash') == contract.get('contract_hash')}"
        ),
        "A freshness attestation is valid only for the exact Gate 3 contract it reviewed.",
        "Repeat the freshness review and bind it to the current report ID and contract hash.",
    )

    as_of_date = attestation_as_of_date
    report_dates = contract.get("report_dates", {})
    report_date = parse_iso_date(report_dates.get("analysis_generated_at"))
    financial_date = parse_iso_date(report_dates.get("financial_statement_date"))
    market_date = parse_iso_date(report_dates.get("market_price_date"))
    contract_date_fields_present = all((report_date, financial_date, market_date))
    add(
        "G4E-required-report-dates",
        "freshness",
        "PASS" if contract_date_fields_present else "BLOCKED",
        "" if contract_date_fields_present else "INELIGIBLE",
        (
            f"report={report_dates.get('analysis_generated_at')}; "
            f"financial={report_dates.get('financial_statement_date')}; "
            f"market={report_dates.get('market_price_date')}"
        ),
        "Report, financial-data, and market-data dates are required for freshness controls.",
        "Rebuild the Gate 3 contract with complete report dates.",
    )

    attestation_after_report = (
        report_date is not None
        and reviewed_at_date is not None
        and reviewed_at_date >= report_date
    )
    add(
        "G4E-attestation-chronology",
        "freshness",
        "PASS" if attestation_after_report else "BLOCKED",
        "" if attestation_after_report else "STALE",
        f"report_date={report_date}; attestation_reviewed_at={reviewed_at_date}",
        "A Gate 4 freshness attestation cannot predate the Gate 3 report it reviews.",
        "Repeat the freshness review after the Gate 3 contract is generated.",
    )

    def age_check(
        check_id: str,
        label: str,
        source_date: date | None,
        threshold_field: str,
    ) -> None:
        threshold = policy.get(threshold_field)
        if not as_of_date or not source_date or threshold is None:
            add(
                check_id,
                "freshness",
                "BLOCKED",
                "STALE",
                f"{label}_date={source_date}; as_of_date={as_of_date}; {threshold_field}={threshold}",
                f"{label} freshness cannot be established.",
                "Provide valid dates and an explicit nonnegative age limit.",
            )
            return
        try:
            max_age = int(threshold)
        except (TypeError, ValueError):
            max_age = -1
        age_days = (as_of_date - source_date).days
        passed = 0 <= age_days <= max_age
        add(
            check_id,
            "freshness",
            "PASS" if passed else "BLOCKED",
            "" if passed else "STALE",
            f"{label}_date={source_date}; as_of_date={as_of_date}; age_days={age_days}; max_age_days={max_age}",
            f"Stale or future-dated {label} cannot be used silently in Gate 4.",
            f"Refresh the {label} and rebuild or re-attest Gate 3 before portfolio assessment.",
        )

    age_check("G4E-report-age", "report", report_date, "max_report_age_days")
    age_check("G4E-financial-data-age", "financial_data", financial_date, "max_financial_data_age_days")
    age_check("G4E-market-data-age", "market_data", market_date, "max_market_data_age_days")

    max_check_lag = policy.get("max_public_source_check_lag_days")
    earnings_checked = parse_iso_date(attestation.get("latest_earnings_checked_through"))
    events_checked = parse_iso_date(attestation.get("subsequent_events_checked_through"))

    def public_check_lag(
        check_id: str,
        label: str,
        checked_through: date | None,
    ) -> None:
        if not as_of_date or not checked_through or max_check_lag is None:
            passed = False
            lag_days = None
            max_lag = None
        else:
            try:
                max_lag = int(max_check_lag)
            except (TypeError, ValueError):
                max_lag = -1
            lag_days = (as_of_date - checked_through).days
            passed = 0 <= lag_days <= max_lag
        add(
            check_id,
            "freshness",
            "PASS" if passed else "BLOCKED",
            "" if passed else "STALE",
            f"{label}_checked_through={checked_through}; as_of_date={as_of_date}; lag_days={lag_days}; max_lag_days={max_lag}",
            f"The {label} review must be current enough for Gate 4.",
            f"Refresh the {label} review and update the attestation.",
        )

    public_check_lag("G4E-earnings-check-lag", "earnings", earnings_checked)
    public_check_lag("G4E-subsequent-event-check-lag", "subsequent_events", events_checked)

    newer_earnings_known = attestation.get("newer_earnings_filing_known")
    latest_known_filing = parse_iso_date(attestation.get("latest_known_financial_filing_date"))
    contract_filing = parse_iso_date(report_dates.get("latest_financial_filing_date"))
    filing_date_consistent = (
        newer_earnings_known is False
        and latest_known_filing is not None
        and contract_filing is not None
        and latest_known_filing == contract_filing
    )
    add(
        "G4E-newer-earnings",
        "freshness",
        "PASS" if filing_date_consistent else "BLOCKED",
        "" if filing_date_consistent else "STALE",
        (
            f"newer_earnings_filing_known={newer_earnings_known}; "
            f"latest_known_filing={latest_known_filing}; contract_filing={contract_filing}"
        ),
        "A known newer earnings filing makes the current Gate 3 contract stale.",
        "Rebuild Gate 3 from the newer filing before portfolio assessment.",
    )

    unreviewed_event_known = attestation.get("unreviewed_material_subsequent_event_known")
    add(
        "G4E-unreviewed-material-event",
        "freshness",
        "PASS" if unreviewed_event_known is False else "BLOCKED",
        "" if unreviewed_event_known is False else "STALE",
        f"unreviewed_material_subsequent_event_known={unreviewed_event_known}",
        "A known unreviewed material event can invalidate the issuer and valuation view.",
        "Review and incorporate the event in Gate 3 before portfolio assessment.",
    )

    valuation_status = contract.get("valuation_status", {}).get("status")
    valuation_eligible = (
        isinstance(eligible_valuation_statuses, list)
        and valuation_status in eligible_valuation_statuses
    )
    add(
        "G4E-valuation-eligibility",
        "valuation",
        "PASS" if valuation_eligible else "BLOCKED",
        "" if valuation_eligible else "INELIGIBLE",
        f"valuation_status={valuation_status}; eligible={eligible_valuation_statuses}",
        "Gate 4 may use only valuation states explicitly allowed by the reviewed policy.",
        "Complete the required valuation work or revise the policy through human review.",
    )

    probability = contract.get("probability_validation", {})
    probability_status = probability.get("status")
    probability_freshness = probability.get("freshness_status")
    probability_as_of_date = parse_iso_date(probability.get("as_of_date"))
    probability_expiration = parse_iso_date(probability.get("expiration_review_date"))
    probability_not_provided = probability_status == "NOT_PROVIDED"
    probability_dates_missing = (
        not probability_not_provided
        and (probability_as_of_date is None or probability_expiration is None)
    )
    probability_dates_invalid = (
        not probability_not_provided
        and probability_as_of_date is not None
        and probability_expiration is not None
        and (
            probability_as_of_date > probability_expiration
            or (as_of_date is not None and probability_as_of_date > as_of_date)
        )
    )
    probability_freshness_unknown = (
        not probability_not_provided
        and probability_freshness not in {"CURRENT", "EXPIRING_SOON", "STALE", "SUPERSEDED"}
    )
    probability_expired = (
        probability_status == "STALE"
        or probability_freshness in {"STALE", "SUPERSEDED"}
        or (
            as_of_date is not None
            and probability_expiration is not None
            and probability_expiration < as_of_date
        )
    )
    probability_required = policy.get("require_validated_probabilities")
    probability_validated = (
        probability_status == "VALIDATED"
        and probability_freshness in {"CURRENT", "EXPIRING_SOON"}
        and not probability_expired
        and probability.get("approval", {}).get("status") == "APPROVED"
    )
    if probability_not_provided and probability_required is False:
        probability_check_status = "NOT_APPLICABLE"
        probability_blocking_class = ""
    elif probability_status == "INVALID" or probability_dates_invalid:
        probability_check_status = "BLOCKED"
        probability_blocking_class = "INELIGIBLE"
    elif probability_dates_missing:
        probability_check_status = "BLOCKED"
        probability_blocking_class = "STALE"
    elif probability_freshness_unknown:
        probability_check_status = "BLOCKED"
        probability_blocking_class = "STALE"
    elif probability_expired:
        probability_check_status = "BLOCKED"
        probability_blocking_class = "STALE"
    elif probability_required is True and not probability_validated:
        probability_check_status = "BLOCKED"
        probability_blocking_class = "INELIGIBLE"
    else:
        probability_check_status = "PASS"
        probability_blocking_class = ""
    add(
        "G4E-probability-freshness",
        "probability",
        probability_check_status,
        probability_blocking_class,
        (
            f"required={probability_required}; status={probability_status}; "
            f"freshness={probability_freshness}; as_of={probability_as_of_date}; "
            f"expiration={probability_expiration}"
        ),
        "Expired probabilities cannot enter Gate 4; validated probabilities are required only when policy says so.",
        "Refresh, validate, and approve probabilities, or mark them not required under the reviewed policy.",
    )

    warning_rows = active_warnings(issue_rows) + active_warnings(contract.get("warnings", []))
    issuer_warning_map: dict[tuple[str, str], dict[str, Any]] = {}
    for row in warning_rows:
        if row.get("category") == "portfolio":
            continue
        key = (validation_issue_identifier(row), str(row.get("category") or ""))
        issuer_warning_map.setdefault(key, row)
    issuer_warnings = list(issuer_warning_map.values())
    escalations = {
        str(row.get("check_id")): row
        for row in attestation.get("warning_escalations", [])
        if isinstance(row, dict) and row.get("check_id")
    }
    allow_escalation = policy.get("allow_warning_escalation") is True
    escalated_warning_ids: set[str] = set()
    for warning in issuer_warnings:
        warning_id = validation_issue_identifier(warning)
        escalation = escalations.get(warning_id, {})
        escalation_date = parse_iso_date(escalation.get("review_date"))
        escalation_valid = (
            allow_escalation
            and bool(escalation.get("reviewed_by"))
            and bool(escalation.get("rationale"))
            and escalation_date is not None
            and report_date is not None
            and escalation_date >= report_date
            and as_of_date is not None
            and escalation_date <= as_of_date
        )
        if escalation_valid:
            escalated_warning_ids.add(warning_id)
        add(
            f"G4E-warning:{warning_id or 'missing-id'}",
            "warning_escalation",
            "ESCALATED" if escalation_valid else "BLOCKED",
            "" if escalation_valid else "INELIGIBLE",
            (
                f"warning={warning_id}; escalation_allowed={allow_escalation}; "
                f"reviewer={escalation.get('reviewed_by', 'missing')}; review_date={escalation.get('review_date', 'missing')}"
            ),
            "Material issuer warnings must be resolved or explicitly escalated before Gate 4.",
            "Resolve the warning or record a dated reviewer-owned escalation rationale.",
        )

    invalid_blocks = [
        check.check_id
        for check in checks
        if check.status == "BLOCKED" and check.blocking_class == "INELIGIBLE"
    ]
    stale_blocks = [
        check.check_id
        for check in checks
        if check.status == "BLOCKED" and check.blocking_class == "STALE"
    ]
    if invalid_blocks:
        status = "GATE_4_BLOCKED_INELIGIBLE_GATE_3"
    elif stale_blocks:
        status = "GATE_4_BLOCKED_STALE_GATE_3"
    else:
        status = "GATE_4_PRIVATE_INPUTS_REQUIRED"
    return {
        "eligibility_contract_version": GATE4_ELIGIBILITY_CONTRACT_VERSION,
        "status": status,
        "eligible": status == "GATE_4_PRIVATE_INPUTS_REQUIRED",
        "warning_escalation_used": bool(escalated_warning_ids),
        "evaluated_at": utc_now(),
        "as_of_date": attestation.get("as_of_date"),
        "gate3_identity": {
            "schema_version": contract.get("schema_version"),
            "report_id": contract.get("report_id"),
            "contract_hash": contract.get("contract_hash"),
            "company": contract.get("company"),
        },
        "contract_validation_errors": current_contract_errors,
        "policy": policy,
        "freshness_attestation": attestation,
        "blocking_check_ids": invalid_blocks + stale_blocks,
        "stale_check_ids": stale_blocks,
        "ineligible_check_ids": invalid_blocks,
        "escalated_warning_ids": sorted(escalated_warning_ids),
        "checks": [check.to_dict() for check in checks],
        "next_action": (
            "Provide validated private portfolio inputs."
            if status == "GATE_4_PRIVATE_INPUTS_REQUIRED"
            else (
                "Refresh and rebuild or re-attest Gate 3 before Gate 4."
                if status == "GATE_4_BLOCKED_STALE_GATE_3"
                else "Resolve Gate 3 eligibility failures before Gate 4."
            )
        ),
    }


def determine_data_gate(
    *,
    issues: list[dict[str, Any]],
    core_data_validated: bool,
    issuer_underwriting_complete: bool,
    valuation_validated: bool,
    scenarios_validated: bool,
    portfolio_inputs_validated: bool,
    human_approval: bool,
    probabilities_validated: bool = False,
) -> dict[str, Any]:
    hard_stops = active_hard_stops(issues)
    if hard_stops or not core_data_validated:
        level = 0
        label = "Gate 0 - Data not validated"
        allowed = ["diagnostic_validation_report", "missing_information", "source_status"]
    elif not issuer_underwriting_complete:
        level = 1
        label = "Gate 1 - Core data validated"
        allowed = ["preliminary_company_screen", "basic_financial_description", "major_missing_information"]
    elif not valuation_validated or not scenarios_validated:
        level = 2.5
        label = "Gate 2.5 - Valuation or scenario work incomplete"
        allowed = ["continue_research", "watch", "need_more_work", "unresolved_valuation_question"]
    elif not probabilities_validated or not portfolio_inputs_validated or not human_approval:
        level = 3
        label = "Gate 3 - Valuation and scenarios validated"
        allowed = ["scenario_prices", "valuation_range", "equity_action_view", "thesis_assessment"]
        if probabilities_validated:
            allowed.append("public_data_expected_return")
        else:
            allowed.append("probability_methodology_required")
    else:
        level = 4
        label = "Gate 4 - Portfolio inputs validated and human reviewed"
        allowed = ["position_range", "portfolio_action", "opportunity_cost_comparison"]

    prohibited: list[str] = []
    if level < 2:
        prohibited.extend(["issuer_risk_judgment", "credit_constraint_conclusion"])
    if level < 3:
        prohibited.extend(["expected_return", "target_price", "final_investment_action"])
    elif not probabilities_validated:
        prohibited.append("expected_return")
    if level < 4:
        prohibited.extend(["position_sizing", "portfolio_action"])
    prohibited.append("automatic_trade")

    return {
        "level": level,
        "label": label,
        "allowed_outputs": allowed,
        "prohibited_outputs": sorted(set(prohibited)),
        "hard_stop_ids": [issue.get("check_id") for issue in hard_stops],
        "probabilities_validated": probabilities_validated,
    }


def determine_decision_confidence(
    *,
    gate_level: float,
    issues: list[dict[str, Any]],
    investment_question_defined: bool,
    critical_assumptions_transparent: bool,
    disconfirming_evidence_considered: bool,
) -> dict[str, Any]:
    limitations: list[str] = []
    supports: list[str] = []
    evidence_to_increase: list[str] = []
    events_to_reduce: list[str] = []
    hard_stops = active_hard_stops(issues)
    warnings = active_warnings(issues)
    if hard_stops:
        limitations.append("One or more Hard Stops remain active.")
    else:
        supports.append("No active Hard Stop remains in the validated contract. / 已验证contract中不存在当前Hard Stop。")
    if gate_level < 2:
        limitations.append("Issuer underwriting is incomplete.")
    else:
        supports.append("Issuer-level underwriting modules are complete enough for the current Data Gate. / 发行人分析模块已达到当前数据门禁要求。")
    if not investment_question_defined:
        limitations.append("Investment Question is not defined or not analyst-approved.")
    else:
        supports.append("The Investment Question is explicitly defined and reviewer-owned. / 投资问题已明确定义并有复核责任人。")
    if not critical_assumptions_transparent:
        limitations.append("Critical valuation or scenario assumptions are incomplete or not reproducible.")
        evidence_to_increase.append("Complete and reproduce the unresolved valuation, horizon, and scenario assumptions. / 完成并复算尚未解决的估值、期限与情景假设。")
    else:
        supports.append("Displayed scenario prices are reproducible from disclosed assumptions. / 展示的情景价格可由披露假设复算。")
    if not disconfirming_evidence_considered:
        limitations.append("Disconfirming evidence has not been sufficiently tested.")
        evidence_to_increase.append("Add disconfirming evidence and measurable thesis-break tests. / 补充反证及可衡量的投资逻辑失效测试。")
    else:
        supports.append("Disconfirming evidence and thesis-break conditions are explicitly considered. / 已明确考虑反证与投资逻辑失效条件。")
    if warnings:
        limitations.append(f"{len(warnings)} material warning(s) remain.")
        evidence_to_increase.append("Resolve or quantify the active warnings shown in the validation section. / 解决或量化验证部分列示的当前警告。")

    events_to_reduce.extend(
        [
            "A new filing or subsequent event contradicts a material displayed fact. / 新申报文件或后续事项与报告中的重要事实冲突。",
            "A period, unit, source, share-count, or calculation reconciliation fails. / 期间、单位、来源、股数或计算对账失败。",
            "Liquidity, covenant, refinancing, or cash-conversion evidence weakens materially. / 流动性、契约、再融资或现金转化证据实质转弱。",
        ]
    )
    if not evidence_to_increase:
        evidence_to_increase.append("Obtain independent valuation cross-checks and a validated forward share-count bridge. / 补充独立估值交叉验证及已验证的前瞻股数桥接。")
    if not supports:
        supports.append(
            "The current Data Gate and missing evidence are explicit, so unsupported conclusions remain blocked. / "
            "当前数据门禁与缺失证据已明确，因此不受支持的结论仍被阻止。"
        )

    if hard_stops or gate_level < 2 or not investment_question_defined:
        level = "Low"
    elif gate_level >= 3 and not warnings and critical_assumptions_transparent and disconfirming_evidence_considered:
        level = "High"
    else:
        level = "Medium"
    constraints = limitations or ["No material confidence constraint identified within the current scope. / 当前范围内未识别重大可信度约束。"]
    return {
        "level": level,
        "supports": supports,
        "constraints": constraints,
        "evidence_to_increase": evidence_to_increase,
        "events_to_reduce": events_to_reduce,
        "limitations": limitations,
    }


def suppress_disallowed_outputs(contract: dict[str, Any]) -> dict[str, Any]:
    gate_level = float(contract.get("data_gate", {}).get("level", 0))
    probability_status = contract.get("probability_validation", {}).get("status", "NOT_PROVIDED")
    return_language_allowed = bool(contract.get("return_context", {}).get("formal_return_language_allowed"))
    if str(contract.get("schema_version") or "") != "5.0.0":
        contract["probability_weighted_expected_return"] = None
        contract["probability_weighted_return"] = None
        contract["target_price"] = None
    if gate_level < 3:
        contract["probability_weighted_expected_return"] = None
        contract["probability_weighted_return"] = None
        contract["target_price"] = None
        for scenario in contract.get("scenarios", []):
            scenario["implied_price"] = None
            scenario["price_change_vs_current"] = None
            scenario.pop("target_price", None)
            scenario.pop("total_return", None)
        s11 = contract.get("valuation_cross_check_contract", {})
        suppressed_s11_ids = {
            str(value)
            for value in (
                s11.get("calculation_evidence_ids", [])
                if isinstance(s11, dict)
                else []
            )
            if value
        }
        for record in contract.get("evidence_records", []):
            if (
                str(record.get("metric_name") or "").startswith("s11_")
                or record.get("source_id") == "SRC-S11-SHARED-CALC"
            ):
                evidence_id = str(record.get("evidence_id") or "")
                if evidence_id:
                    suppressed_s11_ids.add(evidence_id)
        if suppressed_s11_ids:
            retained_records = [
                record
                for record in contract.get("evidence_records", [])
                if str(record.get("evidence_id") or "")
                not in suppressed_s11_ids
            ]
            contract["evidence_records"] = retained_records
            retained_by_id = {
                str(record.get("evidence_id")): record
                for record in retained_records
                if record.get("evidence_id")
            }
            retained_display = [
                row
                for row in contract.get("evidence_display_index", [])
                if str(row.get("evidence_id") or "") in retained_by_id
            ]
            contract["evidence_display_index"] = retained_display
            display_by_id = {
                str(row.get("evidence_id")): row.get("display_id")
                for row in retained_display
            }
            retained_bundles: list[dict[str, Any]] = []
            for bundle in contract.get("evidence_bundles", []):
                evidence_ids = [
                    str(evidence_id)
                    for evidence_id in bundle.get("evidence_ids", [])
                    if str(evidence_id) in retained_by_id
                ]
                if not evidence_ids:
                    continue
                updated = dict(bundle)
                updated["evidence_ids"] = evidence_ids
                updated["display_ids"] = [
                    display_by_id[evidence_id]
                    for evidence_id in evidence_ids
                    if display_by_id.get(evidence_id)
                ]
                updated["source_ids"] = sorted(
                    {
                        str(retained_by_id[evidence_id].get("source_id"))
                        for evidence_id in evidence_ids
                        if retained_by_id[evidence_id].get("source_id")
                    }
                )
                updated["record_count"] = len(evidence_ids)
                retained_bundles.append(updated)
            contract["evidence_bundles"] = retained_bundles
            for evidence_list_field in (
                "known_facts",
                "calculated_metrics",
            ):
                if isinstance(contract.get(evidence_list_field), list):
                    contract[evidence_list_field] = [
                        evidence_id
                        for evidence_id in contract[evidence_list_field]
                        if str(evidence_id) not in suppressed_s11_ids
                    ]
            if not any(
                record.get("source_id") == "SRC-S11-SHARED-CALC"
                for record in retained_records
            ):
                contract["source_registry"] = [
                    source
                    for source in contract.get("source_registry", [])
                    if source.get("source_id") != "SRC-S11-SHARED-CALC"
                ]
                if isinstance(contract.get("source_log_references"), list):
                    contract["source_log_references"] = [
                        source_id
                        for source_id in contract["source_log_references"]
                        if source_id != "SRC-S11-SHARED-CALC"
                    ]
        contract["valuation_cross_check_contract"] = (
            build_valuation_cross_check_contract(contract, {})
        )
        contract["what_is_priced_in"] = {
            "status": "NOT_VALIDATED",
            "selected_reference": None,
            "required_metric_value": None,
            "comparison_metric_value": None,
            "conditional_conclusion": "Not Evaluated",
            "evidence_ids": [],
        }
        contract["peer_valuation_context"] = {
            "status": "UNAVAILABLE",
            "rows": [],
            "metric_summaries": [],
            "interpretation": (
                "Peer valuation is suppressed below Gate 3."
            ),
        }
        contract["valuation_framework"] = {
            "status": "NOT_VALIDATED",
            "reverse_valuation": {"status": "NOT_VALIDATED"},
            "sensitivity_completed": False,
            "sensitivity_table": [],
            "reviewed_by": None,
        }
        valuation_status = contract.get("valuation_status")
        if isinstance(valuation_status, dict):
            valuation_status["status"] = "RANGE_ONLY"
            valuation_status["valuation_cross_check_contract_status"] = (
                "NOT_PROVIDED"
            )
            for component in valuation_status.get("components", {}):
                valuation_status["components"][component] = "NOT_COMPLETED"
        contract["final_investment_action"] = "Not Evaluated"
    if probability_status != "VALIDATED" or not return_language_allowed:
        contract["probability_weighted_expected_return"] = None
        contract["probability_weighted_return"] = None
        contract["target_price"] = None
    if gate_level < 4:
        contract["position_sizing"] = None
        contract["portfolio_action"] = "Not Evaluated"
    suppress_shared_valuation_outputs(contract)
    return contract


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def validate_output_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version",
        "report_id",
        "company",
        "investment_question",
        "report_dates",
        "data_gate",
        "validation_status",
        "product_positioning",
        "research_workflow_status",
        "public_data_investment_view",
        "decision_confidence",
        "current_action",
        "key_debates",
        "return_context",
        "fcf_underwriting_base",
        "valuation_status",
        "share_count_basis",
        "what_is_priced_in",
        "probability_validation",
        "peer_valuation_context",
        "fcf_quality_assessment",
        "investment_decision_summary",
        "evidence_display_index",
        "evidence_bundles",
        "evidence_records",
        "hard_stops",
        "warnings",
        "missing_information",
    }
    schema_version = str(contract.get("schema_version") or "")
    if schema_version not in SUPPORTED_GATE3_SCHEMA_VERSIONS:
        errors.append(
            f"Unsupported output-contract schema version: {schema_version or 'missing'}."
        )
    if schema_version != "5.0.0":
        required.add("valuation_contract")
        required.add("valuation_cross_check_contract")
    missing = sorted(required - set(contract))
    if missing:
        errors.append("Missing required output-contract fields: " + ", ".join(missing))

    gate_level = float(contract.get("data_gate", {}).get("level", 0))
    probability = contract.get("probability_validation", {})
    probability_status = probability.get("status", "NOT_PROVIDED")
    if probability_status not in PROBABILITY_VALIDATION_STATUSES:
        errors.append(f"Invalid probability-validation status: {probability_status}.")
    weighted_expected_return = contract.get("probability_weighted_expected_return")
    if weighted_expected_return is not None and (
        probability_status != "VALIDATED" or not contract.get("return_context", {}).get("formal_return_language_allowed")
    ):
        errors.append("Probability-weighted expected return requires validated probability and return methodologies.")
    if probability_status == "VALIDATED":
        method_type = probability.get("method_type")
        details = probability.get("method_details", {})
        required_details = PROBABILITY_METHOD_REQUIRED_DETAILS.get(str(method_type), set())
        if method_type not in PROBABILITY_METHOD_TYPES:
            errors.append(f"Invalid probability method type: {method_type}.")
        if not probability.get("methodology") or not isinstance(details, dict):
            errors.append("Validated probability requires a non-empty methodology and method details.")
        elif any(details.get(key) in (None, "", [], {}) for key in required_details):
            errors.append(f"Validated probability method {method_type} lacks required method details.")
        if not _is_iso_date(probability.get("as_of_date")) or not _is_iso_date(
            probability.get("expiration_review_date")
        ):
            errors.append("Validated probability requires ISO as-of and expiration review dates.")
        elif probability["expiration_review_date"] < probability["as_of_date"]:
            errors.append("Probability expiration review date cannot precede its as-of date.")
        if probability.get("freshness_status") not in {"CURRENT", "EXPIRING_SOON"}:
            errors.append("Validated probability must have CURRENT or EXPIRING_SOON freshness status.")
        approval = probability.get("approval", {})
        if approval.get("status") != "APPROVED" or not approval.get("approved_by"):
            errors.append("Validated probability requires named human approval.")
        rationales = probability.get("scenario_rationales", {})
        if not isinstance(rationales, dict) or any(not rationales.get(name) for name in ("Bear", "Base", "Bull")):
            errors.append("Validated probability requires Bear, Base, and Bull probability rationales.")
        values = [scenario.get("probability") for scenario in contract.get("scenarios", [])]
        try:
            numeric_values = [float(value) for value in values]
        except (TypeError, ValueError):
            numeric_values = []
        if len(numeric_values) != 3 or any(value < 0 or value > 1 for value in numeric_values) or abs(sum(numeric_values) - 1.0) > 1e-9:
            errors.append("Validated scenario probabilities must be in [0, 1] and total 100 percent.")

    workflow_status = contract.get("research_workflow_status")
    if workflow_status not in RESEARCH_WORKFLOW_STATUSES:
        errors.append(f"Invalid Research Workflow Status: {workflow_status}.")
    public_view = contract.get("public_data_investment_view")
    if public_view not in PUBLIC_DATA_INVESTMENT_VIEWS:
        errors.append(f"Invalid Public-Data Investment View: {public_view}.")

    return_context = contract.get("return_context", {})
    return_fields = (
        "valuation_as_of_date",
        "target_date",
        "holding_period",
        "metric_period",
        "dividend_assumption",
        "share_count_basis",
    )
    if schema_version != "5.0.0":
        return_fields = (
            "valuation_as_of_date",
            "target_date",
            "holding_period",
            "forecast_period",
            "metric_period",
            "dividend_assumption",
            "share_count_basis",
            "exit_basis",
        )
    return_fields_complete = all(return_context.get(field) not in (None, "", [], {}) for field in return_fields)
    if return_context.get("formal_return_language_allowed") and not (
        return_context.get("status") == "VALIDATED" and return_fields_complete
    ):
        errors.append("Formal return language requires a VALIDATED return context with every required field.")
    if not return_context.get("formal_return_language_allowed"):
        if contract.get("probability_weighted_expected_return") is not None:
            errors.append("Expected return must be suppressed when no validated valuation horizon exists.")
        if contract.get("target_price") is not None:
            errors.append("Target price must be suppressed when no validated valuation horizon exists.")
        for scenario in contract.get("scenarios", []):
            if "target_price" in scenario or "total_return" in scenario:
                errors.append("Scenario rows without a validated horizon must use implied_price and price_change_vs_current.")
                break

    fcf_base = contract.get("fcf_underwriting_base", {})
    normalization_status = fcf_base.get("normalization_status")
    if normalization_status not in FCF_NORMALIZATION_STATUSES:
        errors.append(f"Invalid FCF Normalization Status: {normalization_status}.")
    if gate_level >= 2.5 and fcf_base.get("calculation_validation_status") != "VALIDATED":
        errors.append("The public-data FCF underwriting base must state calculation validation status.")
    if normalization_status == "UNADJUSTED_PUBLIC_BASE" and fcf_base.get("bridge_lines"):
        errors.append("UNADJUSTED_PUBLIC_BASE cannot contain normalization adjustment lines.")
    if normalization_status == "PARTIALLY_NORMALIZED" and not fcf_base.get("bridge_lines"):
        errors.append("PARTIALLY_NORMALIZED requires at least one reproducible adjustment line.")
    if normalization_status == "FULLY_NORMALIZED" and fcf_base.get("unresolved_items"):
        errors.append("FULLY_NORMALIZED cannot retain unresolved material normalization items.")

    valuation_status = contract.get("valuation_status", {})
    if valuation_status.get("status") not in VALUATION_SCOPE_STATUSES:
        errors.append(f"Invalid Valuation Status: {valuation_status.get('status')}.")
    for component in (
        "peer_valuation",
        "historical_valuation",
        "dcf_cross_check",
        "driver_based_forward_forecast",
        "forward_share_count_bridge",
    ):
        if valuation_status.get("components", {}).get(component) not in VALUATION_COMPONENT_STATUSES:
            errors.append(f"Invalid valuation component status for {component}.")
    if valuation_status.get("status") == "MULTI_METHOD_VALIDATED" and not all(
        valuation_status.get("components", {}).get(component) == "COMPLETED"
        for component in (
            "peer_valuation",
            "historical_valuation",
            "dcf_cross_check",
            "driver_based_forward_forecast",
            "forward_share_count_bridge",
        )
    ):
        errors.append("MULTI_METHOD_VALIDATED requires all valuation components to be completed.")
    if "reverse_valuation" in valuation_status.get("components", {}):
        if (
            valuation_status.get("components", {}).get("reverse_valuation")
            not in VALUATION_COMPONENT_STATUSES
        ):
            errors.append("Invalid valuation component status for reverse_valuation.")
        if (
            valuation_status.get("status") == "MULTI_METHOD_VALIDATED"
            and valuation_status.get("components", {}).get("reverse_valuation")
            != "COMPLETED"
        ):
            errors.append(
                "S11 MULTI_METHOD_VALIDATED requires completed reverse valuation."
            )

    share_basis = contract.get("share_count_basis", {})
    if gate_level >= 3 and share_basis.get("point_in_time_or_forward") not in SHARE_COUNT_BASIS_TYPES:
        errors.append("Share-count basis must be POINT_IN_TIME or FORWARD.")
    if gate_level >= 3 and share_basis.get("proxy_status") not in SHARE_COUNT_PROXY_STATUSES:
        errors.append("Share-count proxy status must be CURRENT or PROXY.")
    if gate_level >= 3 and share_basis.get("known_subsequent_event_status") not in KNOWN_SUBSEQUENT_EVENT_STATUSES:
        errors.append("Invalid known subsequent-event status for share count.")
    if gate_level >= 3 and (not share_basis.get("share_count_value") or not _is_iso_date(share_basis.get("share_count_date"))):
        errors.append("Every per-share output requires a sourced share-count value and ISO date.")
    if gate_level >= 3 and (not share_basis.get("share_count_type") or not share_basis.get("share_count_source")):
        errors.append("Share-count type and source are required.")
    price_date = contract.get("report_dates", {}).get("market_price_date")
    if (
        gate_level >= 3
        and share_basis.get("share_count_date") != price_date
        and share_basis.get("forward_share_count_bridge_status") != "COMPLETED"
        and share_basis.get("proxy_status") != "PROXY"
    ):
        errors.append("Per-share sensitivities must be marked PROXY when share-count and market-price dates differ.")

    priced_in = contract.get("what_is_priced_in", {})
    if gate_level >= 3 and (priced_in.get("status") != "VALIDATED" or not priced_in.get("conditional_conclusion")):
        errors.append("What Is Priced In must be validated, conditional, and reproducible.")
    if gate_level >= 3 and priced_in.get("multiple_status") not in {
        "ANALYST_OWNED_REFERENCE",
        "ANALYST_OWNED_REFERENCE_WITH_VALIDATED_CONTEXT",
    }:
        errors.append("What Is Priced In must identify the selected multiple as analyst-owned.")

    confidence = contract.get("decision_confidence", {})
    for field in ("supports", "constraints", "evidence_to_increase", "events_to_reduce"):
        if not confidence.get(field):
            errors.append(f"Decision Confidence requires non-empty {field}.")

    peer_context = contract.get("peer_valuation_context", {})
    for row in peer_context.get("rows", []):
        comparability = row.get("comparability_status")
        if comparability not in PEER_COMPARABILITY_STATUSES:
            errors.append(f"Invalid peer comparability status for {row.get('ticker')}: {comparability}.")
        blocking_flags = {
            "negative_ebitda",
            "negative_fcf",
            "different_fiscal_period",
            "currency_mismatch",
            "accounting_definition_mismatch",
        }
        flags = set(row.get("comparability_flags", []))
        if row.get("auto_rank_allowed") and (comparability != "COMPARABLE" or flags.intersection(blocking_flags)):
            errors.append(f"Peer {row.get('ticker')} cannot be auto-ranked with comparability failures.")
    if gate_level < 3:
        if contract.get("probability_weighted_expected_return") is not None:
            errors.append("Expected return must be suppressed below Gate 3.")
        if contract.get("target_price") is not None:
            errors.append("Target price must be suppressed below Gate 3.")
        for scenario in contract.get("scenarios", []):
            if scenario.get("implied_price") is not None or scenario.get("price_change_vs_current") is not None:
                errors.append("Scenario price sensitivity must be suppressed below Gate 3.")
                break
        leaked = [
            row.get("metric_name")
            for row in contract.get("evidence_records", [])
            if str(row.get("metric_name", "")).startswith("scenario_")
            and (
                str(row.get("metric_name", "")).endswith("_implied_price")
                or str(row.get("metric_name", "")).endswith("_price_change_vs_current")
            )
        ]
        if leaked:
            errors.append("Scenario price-sensitivity evidence must be absent below Gate 3: " + ", ".join(leaked))
        s11 = contract.get("valuation_cross_check_contract", {})
        if (
            not isinstance(s11, dict)
            or s11.get("status") != "NOT_PROVIDED"
            or s11.get("calculation_evidence_ids")
        ):
            errors.append(
                "S11 valuation cross-check outputs and calculation evidence "
                "must be suppressed below Gate 3."
            )
        leaked_s11_evidence = [
            str(row.get("evidence_id") or "")
            for row in contract.get("evidence_records", [])
            if (
                str(row.get("metric_name") or "").startswith("s11_")
                or row.get("source_id") == "SRC-S11-SHARED-CALC"
            )
        ]
        if leaked_s11_evidence:
            errors.append(
                "S11 calculation evidence must be absent below Gate 3: "
                + ", ".join(leaked_s11_evidence)
            )
    if gate_level < 4 and contract.get("position_sizing") is not None:
        errors.append("Position sizing must be suppressed below Gate 4.")
    if schema_version == "5.0.0" and "forward_valuation_contract" in contract:
        errors.append(
            "S10 forward_valuation_contract is not supported by frozen schema 5.0.0."
        )
    if schema_version == "5.0.0" and "valuation_cross_check_contract" in contract:
        errors.append(
            "S11 valuation_cross_check_contract is not supported by frozen schema 5.0.0."
        )
    if schema_version != "5.0.0":
        errors.extend(validate_shared_valuation_contract(contract))
        errors.extend(validate_forward_valuation_contract(contract))
        errors.extend(validate_valuation_cross_check_contract(contract))
        errors.extend(validate_probability_governance(contract))
        expected_return_context = legacy_return_context(contract.get("valuation_contract", {}))
        if contract.get("return_context") != expected_return_context:
            errors.append(
                "return_context must be an unchanged compatibility projection of valuation_contract."
            )
        if any(
            contract.get(field) is not None
            for field in (
                "probability_weighted_expected_return",
                "probability_weighted_return",
                "target_price",
            )
        ):
            errors.append(
                "Schema 5.1 legacy return scalars must remain null; use valuation_contract outputs."
            )
        for scenario in contract.get("scenarios", []):
            if "target_price" in scenario or "total_return" in scenario:
                errors.append(
                    "Schema 5.1 scenarios must retain implied-price sensitivity fields only."
                )
                break

    evidence_ids = [row.get("evidence_id") for row in contract.get("evidence_records", [])]
    if len(evidence_ids) != len(set(evidence_ids)):
        errors.append("Evidence IDs must be unique.")
    known_ids = {item for item in evidence_ids if item}
    display_rows = contract.get("evidence_display_index", [])
    display_ids = [row.get("display_id") for row in display_rows]
    displayed_evidence_ids = [row.get("evidence_id") for row in display_rows]
    if len(display_ids) != len(set(display_ids)) or len(displayed_evidence_ids) != len(set(displayed_evidence_ids)):
        errors.append("Evidence display aliases and mapped evidence IDs must be unique.")
    if set(displayed_evidence_ids) != known_ids:
        errors.append("Evidence display index must map every evidence record exactly once.")
    bundle_ids: list[str] = []
    for bundle in contract.get("evidence_bundles", []):
        bundle_id = bundle.get("bundle_id")
        bundle_ids.append(bundle_id)
        if not bundle_id or not bundle.get("section_key") or not bundle.get("label"):
            errors.append("Every evidence bundle requires an ID, section key, and label.")
        unresolved = set(bundle.get("evidence_ids", [])) - known_ids
        if unresolved:
            errors.append(f"Evidence bundle {bundle_id} contains unknown evidence IDs: {sorted(unresolved)}.")
        if not bundle.get("evidence_ids"):
            errors.append(f"Evidence bundle {bundle_id} cannot be empty.")
    if len(bundle_ids) != len(set(bundle_ids)):
        errors.append("Evidence bundle IDs must be unique.")
    source_registry = contract.get("source_registry", [])
    source_ids = {row.get("source_id") for row in source_registry if row.get("source_id")}
    for source in source_registry:
        if source.get("source_level") not in SOURCE_LEVELS:
            errors.append(f"Invalid source-registry level for {source.get('source_id')}: {source.get('source_level')}")
        if not source.get("source_name") or not source.get("retrieval_date"):
            errors.append(f"Source {source.get('source_id')} lacks source name or retrieval date.")
    for row in contract.get("evidence_records", []):
        metric_name = str(row.get("metric_name") or "")
        if (
            metric_name == "normalized_fcf_analyst_validated"
            or (metric_name.startswith("scenario_") and metric_name.endswith("_target_price"))
            or (metric_name.startswith("scenario_") and metric_name.endswith("_total_return"))
            or (
                schema_version != "5.0.0"
                and metric_name == "probability_weighted_expected_return"
            )
        ):
            errors.append(f"Legacy or misleading evidence metric name is prohibited in v1.0.0: {metric_name}.")
        if row.get("evidence_class") not in EVIDENCE_CLASSES:
            errors.append(f"Invalid evidence class for {row.get('evidence_id')}: {row.get('evidence_class')}")
        if row.get("source_level") not in SOURCE_LEVELS:
            errors.append(f"Invalid source level for {row.get('evidence_id')}: {row.get('source_level')}")
        if not row.get("source_id") or row.get("source_id") not in source_ids:
            errors.append(f"Evidence {row.get('evidence_id')} does not resolve to the source registry.")
        if not row.get("source_locator") or not row.get("retrieval_date") or not row.get("as_of_date"):
            errors.append(f"Evidence {row.get('evidence_id')} lacks locator, retrieval date, or as-of date.")
        if row.get("evidence_class") == "FACT" and not row.get("publication_date"):
            errors.append(f"FACT evidence {row.get('evidence_id')} lacks a publication date.")
        if row.get("evidence_class") == "CALC" and (not row.get("formula") or not row.get("input_evidence_ids")):
            errors.append(f"CALC evidence {row.get('evidence_id')} lacks a formula or upstream evidence IDs.")
        for input_id in row.get("input_evidence_ids", []):
            if input_id not in known_ids:
                errors.append(f"Unknown input evidence ID {input_id} in {row.get('evidence_id')}.")

    return errors


def finalize_output_contract(contract: dict[str, Any]) -> dict[str, Any]:
    contract["schema_version"] = SCHEMA_VERSION
    if not isinstance(contract.get("valuation_contract"), dict):
        contract["valuation_contract"] = build_shared_valuation_contract(contract, {})
    if (
        not isinstance(contract.get("valuation_cross_check_contract"), dict)
        or not contract.get("valuation_cross_check_contract", {}).get(
            "contract_version"
        )
    ):
        contract["valuation_cross_check_contract"] = (
            build_valuation_cross_check_contract(contract, {})
        )
    contract["return_context"] = legacy_return_context(contract["valuation_contract"])
    contract = suppress_disallowed_outputs(contract)
    contract["contract_hash"] = hashlib.sha256(
        canonical_json({key: value for key, value in contract.items() if key != "contract_hash"}).encode("utf-8")
    ).hexdigest()
    errors = validate_output_contract(contract)
    contract["contract_validation"] = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "validated_at": utc_now(),
    }
    return contract
