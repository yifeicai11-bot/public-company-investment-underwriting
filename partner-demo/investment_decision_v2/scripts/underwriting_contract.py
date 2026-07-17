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


SCHEMA_VERSION = "5.0.0"
SUPPORTED_UNIVERSE_VERSION = "1.0.0"

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
    if gate_level < 3:
        contract["probability_weighted_expected_return"] = None
        contract["probability_weighted_return"] = None
        contract["target_price"] = None
        for scenario in contract.get("scenarios", []):
            scenario["implied_price"] = None
            scenario["price_change_vs_current"] = None
            scenario.pop("target_price", None)
            scenario.pop("total_return", None)
        contract["final_investment_action"] = "Not Evaluated"
    if probability_status != "VALIDATED" or not return_language_allowed:
        contract["probability_weighted_expected_return"] = None
        contract["probability_weighted_return"] = None
        contract["target_price"] = None
    if gate_level < 4:
        contract["position_sizing"] = None
        contract["portfolio_action"] = "Not Evaluated"
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
    if gate_level >= 3 and priced_in.get("multiple_status") != "ANALYST_OWNED_REFERENCE":
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
    if gate_level < 4 and contract.get("position_sizing") is not None:
        errors.append("Position sizing must be suppressed below Gate 4.")

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
        ):
            errors.append(f"Legacy or misleading evidence metric name is prohibited in Friday V1: {metric_name}.")
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
