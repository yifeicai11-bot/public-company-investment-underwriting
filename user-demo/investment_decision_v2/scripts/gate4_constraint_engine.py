#!/usr/bin/env python3
"""Shared S13 portfolio-constraint calculations.

The engine consumes only a validated Gate 3 contract and a validated local
Gate 4 bundle. It calculates constraint ceilings, not a recommended position,
portfolio action, approval, or trade.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - dependency diagnostic path
    Draft202012Validator = None
    FormatChecker = None

from gate4_private_contract import (
    PrivateInputBundle,
    clean_text,
    parse_date,
    parse_integer,
    parse_number,
    parse_ratio,
)


CONSTRAINT_ENGINE_VERSION = "1.0.0"
CONSTRAINT_OUTPUT_CONTRACT_VERSION = "1.0.0"
CALCULATED_STATUS = "GATE_4_CONSTRAINTS_CALCULATED"
INCOMPLETE_STATUS = "GATE_4_CONSTRAINTS_INCOMPLETE"
BLOCKED_CHANGED_STATUS = "GATE_4_BLOCKED_GATE_3_CHANGED_DURING_RECHECK"
EPSILON = 1e-12
CONSTRAINT_OUTPUT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "gate4"
    / "schemas"
    / "portfolio_constraint_output.schema.json"
)


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _finite_ratio(value: Any) -> float | None:
    parsed = parse_ratio(value)
    if parsed is None or not math.isfinite(parsed):
        return None
    return float(parsed)


def _weight(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(1.0, value)), 12)


def validate_constraint_output(payload: dict[str, Any]) -> list[str]:
    if Draft202012Validator is None or FormatChecker is None:
        return ["<dependency>:jsonschema"]
    try:
        schema = json.loads(
            CONSTRAINT_OUTPUT_SCHEMA_PATH.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return ["<schema>:portfolio_constraint_output"]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return sorted(
        ".".join(str(part) for part in error.absolute_path) or "<document>"
        for error in validator.iter_errors(payload)
    )


def privacy_safe_gate3_check(eligibility: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": eligibility.get("status"),
        "eligible": eligibility.get("eligible") is True,
        "evaluated_at": eligibility.get("evaluated_at"),
        "gate3_identity": eligibility.get("gate3_identity"),
        "blocking_check_ids": list(eligibility.get("blocking_check_ids", [])),
        "stale_check_ids": list(eligibility.get("stale_check_ids", [])),
        "ineligible_check_ids": list(eligibility.get("ineligible_check_ids", [])),
        "escalated_warning_ids": list(
            eligibility.get("escalated_warning_ids", [])
        ),
        "checks": [
            {
                "check_id": row.get("check_id"),
                "category": row.get("category"),
                "status": row.get("status"),
                "blocking_class": row.get("blocking_class"),
                "decision_impact": row.get("decision_impact"),
                "remediation": row.get("remediation"),
            }
            for row in eligibility.get("checks", [])
            if isinstance(row, dict)
        ],
        "private_policy_included": False,
        "private_attestation_included": False,
    }


def suppressed_constraint_result(
    *,
    status: str,
    input_mode: str,
    private_input_status: str,
    gate3_precheck: dict[str, Any] | None,
    gate3_recheck: dict[str, Any] | None,
    missing_items: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "constraint_engine_version": CONSTRAINT_ENGINE_VERSION,
        "constraint_output_contract_version": CONSTRAINT_OUTPUT_CONTRACT_VERSION,
        "generated_at": utc_now(),
        "status": status,
        "input_mode": input_mode,
        "private_input_status": private_input_status,
        "gate3_precheck": (
            privacy_safe_gate3_check(gate3_precheck)
            if gate3_precheck is not None
            else {"status": "NOT_EVALUATED", "eligible": False}
        ),
        "gate3_recheck": (
            privacy_safe_gate3_check(gate3_recheck)
            if gate3_recheck is not None
            else {"status": "NOT_EVALUATED", "eligible": False}
        ),
        "constraints": [],
        "formula_registry": {},
        "missing_items": sorted(set(missing_items or [])),
        "tightest_known_constraint": None,
        "binding_constraints": [],
        "maximum_constraint_based_incremental_position_weight": None,
        "maximum_constraint_based_total_position_weight": None,
        "maximum_constraint_based_position_is_recommendation": False,
        "system_portfolio_assessment": {
            "status": "NOT_EVALUATED",
            "assessment": None,
            "position_range": None,
        },
        "partner_decision": {
            "workflow_status": "PARTNER_APPROVAL_PENDING",
            "decision": "PENDING",
            "approved_position_range": None,
        },
        "automatic_trade_execution": False,
        "external_transmission": "DENIED",
        "raw_private_values_included": False,
        "next_action": (
            "Complete missing S13 inputs locally."
            if status == INCOMPLETE_STATUS
            else "Resolve the named Gate 3 or private-input block before S13."
        ),
    }


def _constraint(
    *,
    constraint_id: str,
    label_en: str,
    label_zh: str,
    status: str,
    required_for_ceiling: bool,
    limit_value: float | int | None,
    current_value: float | int | None,
    candidate_value: float | int | None,
    remaining_capacity: float | None,
    maximum_incremental_position_weight: float | None,
    formula: str,
    formula_inputs: dict[str, Any],
    source_fields: list[str],
    missing_fields: list[str] | None = None,
    escalation_threshold: float | None = None,
    escalation_triggered: bool | None = None,
    notes_en: str,
    notes_zh: str,
) -> dict[str, Any]:
    return {
        "constraint_id": constraint_id,
        "label_en": label_en,
        "label_zh": label_zh,
        "status": status,
        "required_for_ceiling": required_for_ceiling,
        "limit_value": limit_value,
        "current_value": current_value,
        "candidate_value": candidate_value,
        "remaining_capacity": remaining_capacity,
        "maximum_incremental_position_weight": maximum_incremental_position_weight,
        "formula": formula,
        "formula_inputs": formula_inputs,
        "source_fields": source_fields,
        "missing_fields": sorted(set(missing_fields or [])),
        "escalation_threshold": escalation_threshold,
        "escalation_triggered": escalation_triggered,
        "binding": False,
        "notes_en": notes_en,
        "notes_zh": notes_zh,
    }


def _exposure_from_rows(
    rows: list[dict[str, Any]],
    *,
    exposure_type: str,
    exposure_key: str,
) -> tuple[float | None, list[str]]:
    matching = [
        row
        for row in rows
        if row.get("exposure_type") == exposure_type
        and row.get("exposure_key") == exposure_key
    ]
    if len(matching) != 1:
        return None, [f"exposures:{exposure_type}:{exposure_key}"]
    value = _finite_ratio(matching[0].get("exposure_weight"))
    if value is None:
        return None, [f"exposures:{exposure_type}:{exposure_key}.exposure_weight"]
    return max(0.0, value), []


def _exposure_from_holdings(
    rows: list[dict[str, Any]],
    *,
    field: str,
    key: str,
) -> tuple[float, list[str]]:
    value = sum(
        max(0.0, _finite_ratio(row.get("position_weight")) or 0.0)
        for row in rows
        if row.get("position_side") == "LONG" and row.get(field) == key
    )
    return value, []


def _current_exposures(
    bundle: PrivateInputBundle,
) -> tuple[dict[str, float | None], dict[str, list[str]], str]:
    candidate = bundle.constraint_inputs.get("candidate", {})
    dimensions = {
        "issuer": ("issuer_identifier", "ISSUER"),
        "sector": ("sector", "SECTOR"),
        "country": ("country", "COUNTRY"),
        "correlation": ("correlation_bucket", "CORRELATION_BUCKET"),
    }
    values: dict[str, float | None] = {}
    missing: dict[str, list[str]] = {}
    mode = bundle.manifest.get("input_mode")
    if mode == "EXPOSURE_ONLY":
        basis = "REVIEWED_EXPOSURE_ROWS"
        for name, (candidate_field, exposure_type) in dimensions.items():
            key = clean_text(candidate.get(candidate_field))
            if key is None:
                values[name] = None
                missing[name] = [f"constraints:candidate.{candidate_field}"]
                continue
            values[name], missing[name] = _exposure_from_rows(
                bundle.exposures,
                exposure_type=exposure_type,
                exposure_key=key,
            )
    else:
        basis = (
            "COMPLETE_SECURITY_LEVEL_HOLDINGS"
            if mode == "FULL_HOLDINGS"
            else "COMPLETE_AGGREGATED_ISSUER_HOLDINGS"
        )
        for name, (candidate_field, _) in dimensions.items():
            key = clean_text(candidate.get(candidate_field))
            if key is None:
                values[name] = None
                missing[name] = [f"constraints:candidate.{candidate_field}"]
                continue
            values[name], missing[name] = _exposure_from_holdings(
                bundle.holdings,
                field=candidate_field,
                key=key,
            )
    return values, missing, basis


def _limit_constraint(
    *,
    constraint_id: str,
    label_en: str,
    label_zh: str,
    limit: float | None,
    current: float | None,
    source_field: str,
    current_source: str,
    missing_fields: list[str],
    escalation_threshold: float | None,
) -> dict[str, Any]:
    missing = list(missing_fields)
    if limit is None:
        missing.append(f"policy:{source_field}")
    if current is None:
        missing.append(current_source)
    if missing:
        return _constraint(
            constraint_id=constraint_id,
            label_en=label_en,
            label_zh=label_zh,
            status="MISSING",
            required_for_ceiling=True,
            limit_value=limit,
            current_value=current,
            candidate_value=None,
            remaining_capacity=None,
            maximum_incremental_position_weight=None,
            formula=f"max(0, {source_field} - current_gross_long_weight)",
            formula_inputs={},
            source_fields=[f"policy.{source_field}", current_source],
            missing_fields=missing,
            escalation_threshold=escalation_threshold,
            escalation_triggered=None,
            notes_en="A required exposure or policy limit is unavailable; no zero exposure is inferred.",
            notes_zh="必要敞口或政策上限缺失；系统不会把缺失敞口当作零。",
        )
    assert limit is not None and current is not None
    remaining = limit - current
    utilization = current / limit if limit > 0 else None
    escalation = (
        utilization is not None
        and escalation_threshold is not None
        and utilization >= escalation_threshold
    )
    return _constraint(
        constraint_id=constraint_id,
        label_en=label_en,
        label_zh=label_zh,
        status="PASS" if remaining >= -EPSILON else "BREACH",
        required_for_ceiling=True,
        limit_value=limit,
        current_value=current,
        candidate_value=None,
        remaining_capacity=max(0.0, remaining),
        maximum_incremental_position_weight=_weight(remaining),
        formula=f"max(0, {source_field} - current_gross_long_weight)",
        formula_inputs={
            source_field: limit,
            "current_gross_long_weight": current,
            "current_limit_utilization": utilization,
        },
        source_fields=[f"policy.{source_field}", current_source],
        escalation_threshold=escalation_threshold,
        escalation_triggered=escalation,
        notes_en="The result is an incremental concentration ceiling, not a position recommendation.",
        notes_zh="该结果是新增集中度上限，不是建议仓位。",
    )


def _binary_constraint(
    *,
    constraint_id: str,
    label_en: str,
    label_zh: str,
    passed: bool | None,
    limit_value: float | int | None,
    candidate_value: float | int | None,
    formula: str,
    formula_inputs: dict[str, Any],
    source_fields: list[str],
    missing_fields: list[str],
    escalation_threshold: float | None,
    escalation_triggered: bool | None,
    notes_en: str,
    notes_zh: str,
) -> dict[str, Any]:
    status = "MISSING" if passed is None else ("PASS" if passed else "BREACH")
    ceiling = None if passed is None else (1.0 if passed else 0.0)
    return _constraint(
        constraint_id=constraint_id,
        label_en=label_en,
        label_zh=label_zh,
        status=status,
        required_for_ceiling=True,
        limit_value=limit_value,
        current_value=None,
        candidate_value=candidate_value,
        remaining_capacity=None,
        maximum_incremental_position_weight=ceiling,
        formula=formula,
        formula_inputs=formula_inputs,
        source_fields=source_fields,
        missing_fields=missing_fields,
        escalation_threshold=escalation_threshold,
        escalation_triggered=escalation_triggered,
        notes_en=notes_en,
        notes_zh=notes_zh,
    )


def _public_expected_return_is_valid(
    contract: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    if expected.get("basis") != "PUBLIC_PROBABILITY_WEIGHTED_RETURN":
        return True
    valuation = contract.get("valuation_contract", {})
    output = (
        valuation.get("outputs", {}).get("probability_weighted_return", {})
        if isinstance(valuation, dict)
        else {}
    )
    holding = output.get("holding_period", {}) if isinstance(output, dict) else {}
    return (
        output.get("status") == "VALIDATED"
        and valuation.get("formal_return_language_allowed") is True
        and _finite_ratio(output.get("total_return")) is not None
        and _finite_ratio(expected.get("value")) is not None
        and math.isclose(
            float(_finite_ratio(output.get("total_return"))),
            float(_finite_ratio(expected.get("value"))),
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        and output.get("valuation_as_of_date") == expected.get("as_of_date")
        and output.get("target_date") == expected.get("target_date")
        and parse_integer(holding.get("calendar_days"))
        == parse_integer(expected.get("holding_period_days"))
    )


def _formal_downside_is_valid(
    contract: dict[str, Any],
    downside: dict[str, Any],
) -> bool:
    if downside.get("basis") != "FORMAL_BEAR_CASE_RETURN":
        return True
    formal_rows = (
        contract.get("valuation_contract", {})
        .get("outputs", {})
        .get("formal_scenario_returns", {})
    )
    bear = formal_rows.get("Bear", {}) if isinstance(formal_rows, dict) else {}
    return (
        bear.get("status") == "VALIDATED"
        and _finite_ratio(bear.get("total_return")) is not None
        and _finite_ratio(downside.get("value")) is not None
        and math.isclose(
            float(_finite_ratio(bear.get("total_return"))),
            float(_finite_ratio(downside.get("value"))),
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        and bear.get("valuation_as_of_date") == downside.get("as_of_date")
        and bear.get("target_date") == downside.get("target_date")
        and parse_integer(bear.get("holding_period_days"))
        == parse_integer(downside.get("holding_period_days"))
    )


def calculate_portfolio_constraints(
    *,
    bundle: PrivateInputBundle,
    gate3_contract: dict[str, Any],
    gate3_precheck: dict[str, Any],
    gate3_recheck: dict[str, Any],
    private_input_status: str,
) -> dict[str, Any]:
    """Calculate S13 constraints after the caller's second Gate 3 check."""

    if gate3_recheck.get("eligible") is not True:
        return suppressed_constraint_result(
            status=str(gate3_recheck.get("status") or "GATE_4_BLOCKED_INELIGIBLE_GATE_3"),
            input_mode=str(bundle.manifest.get("input_mode")),
            private_input_status=private_input_status,
            gate3_precheck=gate3_precheck,
            gate3_recheck=gate3_recheck,
        )

    binding = bundle.constraint_inputs.get("gate3_binding", {})
    candidate = bundle.constraint_inputs.get("candidate", {})
    company = gate3_contract.get("company", {})
    gate3_identity_matches = (
        binding.get("report_id") == gate3_contract.get("report_id")
        and binding.get("contract_hash") == gate3_contract.get("contract_hash")
    )
    candidate_identity_matches = (
        isinstance(company, dict)
        and candidate.get("issuer_identifier") == company.get("cik")
        and (
            candidate.get("security_type") != "EQUITY"
            or candidate.get("security_identifier") == company.get("ticker")
        )
    )
    if not gate3_identity_matches or not candidate_identity_matches:
        return suppressed_constraint_result(
            status="GATE_4_BLOCKED_INELIGIBLE_GATE_3",
            input_mode=str(bundle.manifest.get("input_mode")),
            private_input_status=private_input_status,
            gate3_precheck=gate3_precheck,
            gate3_recheck=gate3_recheck,
            missing_items=(
                ["constraints.gate3_binding"]
                if not gate3_identity_matches
                else ["constraints.candidate.gate3_company_identity"]
            ),
        )

    policy = bundle.policy
    portfolio_state = bundle.constraint_inputs.get("portfolio_state", {})
    thresholds = policy.get("escalation_thresholds", {})
    exposures, exposure_missing, exposure_basis = _current_exposures(bundle)
    constraints: list[dict[str, Any]] = []

    existing_issuer = exposures.get("issuer")
    constraints.append(
        _constraint(
            constraint_id="existing_issuer_exposure",
            label_en="Existing issuer exposure",
            label_zh="现有发行人敞口",
            status="PASS" if existing_issuer is not None else "MISSING",
            required_for_ceiling=False,
            limit_value=None,
            current_value=existing_issuer,
            candidate_value=None,
            remaining_capacity=None,
            maximum_incremental_position_weight=None,
            formula="sum(gross long weights with candidate issuer_identifier)",
            formula_inputs={"exposure_basis": exposure_basis},
            source_fields=[
                "constraint_inputs.candidate.issuer_identifier",
                "holdings or exposure_summary",
            ],
            missing_fields=exposure_missing.get("issuer", []),
            notes_en="Zero is used only when complete holdings or an explicit zero issuer exposure row supports it.",
            notes_zh="只有完整持仓或明确的零发行人敞口行支持时，系统才使用零。",
        )
    )

    limits = (
        (
            "single_name",
            "Single-name concentration",
            "单一标的集中度",
            "single_name_position_limit",
            "issuer",
            "single_name_limit_utilization",
        ),
        (
            "sector",
            "Sector concentration",
            "行业集中度",
            "sector_concentration_limit",
            "sector",
            "sector_limit_utilization",
        ),
        (
            "correlated_exposure",
            "Correlated exposure",
            "相关性敞口",
            "correlated_exposure_limit",
            "correlation",
            "correlated_exposure_limit_utilization",
        ),
    )
    for (
        constraint_id,
        label_en,
        label_zh,
        policy_field,
        exposure_name,
        threshold_field,
    ) in limits:
        constraints.append(
            _limit_constraint(
                constraint_id=constraint_id,
                label_en=label_en,
                label_zh=label_zh,
                limit=_finite_ratio(policy.get(policy_field)),
                current=exposures.get(exposure_name),
                source_field=policy_field,
                current_source=f"{exposure_basis}:{exposure_name}",
                missing_fields=exposure_missing.get(exposure_name, []),
                escalation_threshold=_finite_ratio(thresholds.get(threshold_field)),
            )
        )

    if policy.get("country_limit_status") == "NOT_APPLICABLE":
        constraints.append(
            _constraint(
                constraint_id="country",
                label_en="Country concentration",
                label_zh="国家集中度",
                status="NOT_APPLICABLE",
                required_for_ceiling=False,
                limit_value=None,
                current_value=exposures.get("country"),
                candidate_value=None,
                remaining_capacity=None,
                maximum_incremental_position_weight=None,
                formula="not applicable under reviewed policy",
                formula_inputs={},
                source_fields=[
                    "policy.country_limit_status",
                    "policy.country_limit_rationale",
                ],
                notes_en="The reviewed policy explicitly marks the country limit not applicable.",
                notes_zh="经复核的政策明确将国家上限标记为不适用。",
            )
        )
    else:
        constraints.append(
            _limit_constraint(
                constraint_id="country",
                label_en="Country concentration",
                label_zh="国家集中度",
                limit=_finite_ratio(policy.get("country_concentration_limit")),
                current=exposures.get("country"),
                source_field="country_concentration_limit",
                current_source=f"{exposure_basis}:country",
                missing_fields=exposure_missing.get("country", []),
                escalation_threshold=_finite_ratio(
                    thresholds.get("country_limit_utilization")
                ),
            )
        )

    expected = candidate.get("expected_return", {})
    expected_value = (
        _finite_ratio(expected.get("value"))
        if expected.get("status") == "VALIDATED"
        and _public_expected_return_is_valid(gate3_contract, expected)
        else None
    )
    target_return = _finite_ratio(policy.get("target_return"))
    return_missing: list[str] = []
    if expected_value is None:
        return_missing.append("constraint_inputs.candidate.expected_return")
    if target_return is None:
        return_missing.append("policy.target_return")
    return_passed = (
        None
        if return_missing
        else expected_value is not None
        and target_return is not None
        and expected_value >= target_return
    )
    constraints.append(
        _binary_constraint(
            constraint_id="target_return",
            label_en="Target-return hurdle",
            label_zh="目标回报门槛",
            passed=return_passed,
            limit_value=target_return,
            candidate_value=expected_value,
            formula="candidate_validated_return >= policy_target_return",
            formula_inputs={
                "candidate_validated_return": expected_value,
                "policy_target_return": target_return,
            },
            source_fields=[
                "constraint_inputs.candidate.expected_return",
                "policy.target_return",
            ],
            missing_fields=return_missing,
            escalation_threshold=None,
            escalation_triggered=None,
            notes_en="Public price sensitivity is not accepted as expected return.",
            notes_zh="公开的价格敏感性不能作为预期回报。",
        )
    )

    holding_days = (
        parse_integer(expected.get("holding_period_days"))
        if expected_value is not None
        else None
    )
    holding_limit = parse_integer(policy.get("holding_period_days"))
    holding_missing: list[str] = []
    if holding_days is None:
        holding_missing.append(
            "constraint_inputs.candidate.expected_return.holding_period_days"
        )
    if holding_limit is None:
        holding_missing.append("policy.holding_period_days")
    holding_passed = (
        None
        if holding_missing
        else holding_days is not None
        and holding_limit is not None
        and holding_days <= holding_limit
    )
    constraints.append(
        _binary_constraint(
            constraint_id="holding_period",
            label_en="Holding-period limit",
            label_zh="持有期上限",
            passed=holding_passed,
            limit_value=holding_limit,
            candidate_value=holding_days,
            formula="candidate_holding_period_days <= policy_holding_period_days",
            formula_inputs={
                "candidate_holding_period_days": holding_days,
                "policy_holding_period_days": holding_limit,
            },
            source_fields=[
                "constraint_inputs.candidate.expected_return.holding_period_days",
                "policy.holding_period_days",
            ],
            missing_fields=holding_missing,
            escalation_threshold=None,
            escalation_triggered=None,
            notes_en="The expected-return and downside horizons must already match.",
            notes_zh="预期回报与下行情景的期限必须已经一致。",
        )
    )

    downside = candidate.get("downside_return", {})
    downside_value = (
        _finite_ratio(downside.get("value"))
        if downside.get("status") == "VALIDATED"
        and _formal_downside_is_valid(gate3_contract, downside)
        else None
    )
    downside_limit = _finite_ratio(policy.get("downside_tolerance"))
    downside_missing: list[str] = []
    if downside_value is None:
        downside_missing.append("constraint_inputs.candidate.downside_return")
    if downside_limit is None:
        downside_missing.append("policy.downside_tolerance")
    downside_passed = (
        None
        if downside_missing
        else downside_value is not None
        and downside_limit is not None
        and downside_value >= downside_limit
    )
    downside_utilization = (
        abs(downside_value) / abs(downside_limit)
        if downside_value is not None
        and downside_limit is not None
        and downside_limit != 0
        else None
    )
    downside_escalation_threshold = _finite_ratio(
        thresholds.get("downside_limit_utilization")
    )
    constraints.append(
        _binary_constraint(
            constraint_id="downside",
            label_en="Downside tolerance",
            label_zh="下行容忍度",
            passed=downside_passed,
            limit_value=downside_limit,
            candidate_value=downside_value,
            formula="candidate_formal_downside_return >= policy_downside_tolerance",
            formula_inputs={
                "candidate_formal_downside_return": downside_value,
                "policy_downside_tolerance": downside_limit,
                "downside_limit_utilization": downside_utilization,
            },
            source_fields=[
                "constraint_inputs.candidate.downside_return",
                "policy.downside_tolerance",
            ],
            missing_fields=downside_missing,
            escalation_threshold=downside_escalation_threshold,
            escalation_triggered=(
                downside_utilization >= downside_escalation_threshold
                if downside_utilization is not None
                and downside_escalation_threshold is not None
                else None
            ),
            notes_en="Only a validated dated-horizon downside return is accepted; Bear price sensitivity is excluded.",
            notes_zh="只接受经验证、具有明确期限的下行回报；Bear 价格敏感性被排除。",
        )
    )

    liquidity_policy = policy.get("liquidity_requirement", {})
    liquid_state = portfolio_state.get("current_liquid_portfolio_weight", {})
    liquid_weight = (
        _finite_ratio(liquid_state.get("value"))
        if liquid_state.get("status") == "VALIDATED"
        else None
    )
    liquid_floor = _finite_ratio(
        liquidity_policy.get("minimum_liquid_portfolio_weight")
    )
    liquid_missing: list[str] = []
    if liquid_weight is None:
        liquid_missing.append(
            "constraint_inputs.portfolio_state.current_liquid_portfolio_weight"
        )
    if liquid_floor is None:
        liquid_missing.append(
            "policy.liquidity_requirement.minimum_liquid_portfolio_weight"
        )
    liquid_floor_passed = (
        None
        if liquid_missing
        else liquid_weight is not None
        and liquid_floor is not None
        and liquid_weight >= liquid_floor
    )
    constraints.append(
        _binary_constraint(
            constraint_id="liquidity_portfolio_floor",
            label_en="Portfolio liquidity floor",
            label_zh="组合流动性下限",
            passed=liquid_floor_passed,
            limit_value=liquid_floor,
            candidate_value=liquid_weight,
            formula="current_liquid_portfolio_weight >= minimum_liquid_portfolio_weight",
            formula_inputs={
                "current_liquid_portfolio_weight": liquid_weight,
                "minimum_liquid_portfolio_weight": liquid_floor,
            },
            source_fields=[
                "constraint_inputs.portfolio_state.current_liquid_portfolio_weight",
                "policy.liquidity_requirement.minimum_liquid_portfolio_weight",
            ],
            missing_fields=liquid_missing,
            escalation_threshold=None,
            escalation_triggered=None,
            notes_en="A pre-existing liquidity-floor breach conservatively blocks incremental exposure.",
            notes_zh="若组合已低于流动性下限，系统将保守地阻止新增敞口。",
        )
    )

    liquidity = candidate.get("liquidity", {})
    advt = (
        parse_number(liquidity.get("average_daily_value_traded"))
        if liquidity.get("status") == "VALIDATED"
        else None
    )
    nav = parse_number(bundle.manifest.get("portfolio_nav"))
    max_days = parse_integer(liquidity_policy.get("maximum_days_to_exit"))
    minimum_advt = parse_number(
        liquidity_policy.get("minimum_average_daily_value_traded")
    )
    participation = _finite_ratio(
        liquidity_policy.get("maximum_daily_volume_participation")
    )
    maximum_advt_age = parse_integer(
        liquidity_policy.get("maximum_advt_age_days")
    )
    manifest_date = parse_date(bundle.manifest.get("as_of_date"))
    advt_date = parse_date(liquidity.get("source_as_of_date"))
    advt_age = (
        (manifest_date - advt_date).days
        if manifest_date is not None and advt_date is not None
        else None
    )
    liquidity_capacity_missing: list[str] = []
    for value, field in (
        (advt, "constraint_inputs.candidate.liquidity.average_daily_value_traded"),
        (nav, "manifest.portfolio_nav"),
        (max_days, "policy.liquidity_requirement.maximum_days_to_exit"),
        (
            minimum_advt,
            "policy.liquidity_requirement.minimum_average_daily_value_traded",
        ),
        (
            participation,
            "policy.liquidity_requirement.maximum_daily_volume_participation",
        ),
        (
            maximum_advt_age,
            "policy.liquidity_requirement.maximum_advt_age_days",
        ),
        (
            advt_age,
            "constraint_inputs.candidate.liquidity.source_as_of_date",
        ),
    ):
        if value is None:
            liquidity_capacity_missing.append(field)
    if liquidity_capacity_missing:
        liquidity_capacity = None
        liquidity_capacity_status = "MISSING"
        liquidity_capacity_ceiling = None
    else:
        assert (
            advt is not None
            and nav is not None
            and nav > 0
            and max_days is not None
            and minimum_advt is not None
            and participation is not None
        )
        advt_current = 0 <= int(advt_age) <= int(maximum_advt_age)
        minimum_advt_passed = advt >= minimum_advt
        liquidity_capacity = advt * participation * max_days / nav
        liquidity_capacity_status = (
            "PASS" if minimum_advt_passed and advt_current else "BREACH"
        )
        liquidity_capacity_ceiling = (
            _weight(liquidity_capacity)
            if minimum_advt_passed and advt_current
            else 0.0
        )
    constraints.append(
        _constraint(
            constraint_id="liquidity_exit_capacity",
            label_en="Candidate exit-capacity ceiling",
            label_zh="候选标的退出容量上限",
            status=liquidity_capacity_status,
            required_for_ceiling=True,
            limit_value=max_days,
            current_value=None,
            candidate_value=advt,
            remaining_capacity=liquidity_capacity,
            maximum_incremental_position_weight=liquidity_capacity_ceiling,
            formula=(
                "ADVT * maximum_daily_volume_participation * "
                "maximum_days_to_exit / portfolio_NAV"
            ),
            formula_inputs={
                "average_daily_value_traded": advt,
                "minimum_average_daily_value_traded": minimum_advt,
                "maximum_daily_volume_participation": participation,
                "maximum_days_to_exit": max_days,
                "portfolio_nav": nav,
                "maximum_advt_age_days": maximum_advt_age,
                "advt_age_days": advt_age,
            },
            source_fields=[
                "constraint_inputs.candidate.liquidity",
                "manifest.portfolio_nav",
                "policy.liquidity_requirement",
            ],
            missing_fields=liquidity_capacity_missing,
            escalation_threshold=_finite_ratio(
                thresholds.get("liquidity_days_utilization")
            ),
            escalation_triggered=None,
            notes_en="Exposure-only mode cannot calculate this ceiling when NAV is intentionally unavailable.",
            notes_zh="若 exposure-only 模式未提供 NAV，则无法计算该上限。",
        )
    )

    risk_state = portfolio_state.get("current_risk_budget_usage", {})
    current_risk = (
        _finite_ratio(risk_state.get("value"))
        if risk_state.get("status") == "VALIDATED"
        else None
    )
    risk_limit = _finite_ratio(policy.get("risk_budget_limit"))
    risk_missing: list[str] = []
    if current_risk is None:
        risk_missing.append(
            "constraint_inputs.portfolio_state.current_risk_budget_usage"
        )
    if risk_limit is None:
        risk_missing.append("policy.risk_budget_limit")
    if downside_value is None:
        risk_missing.append("constraint_inputs.candidate.downside_return")
    if risk_missing:
        risk_remaining = None
        risk_ceiling = None
        risk_status = "MISSING"
        risk_utilization = None
    else:
        assert (
            current_risk is not None
            and risk_limit is not None
            and downside_value is not None
            and downside_value < 0
        )
        risk_remaining = risk_limit - current_risk
        risk_ceiling = _weight(risk_remaining / abs(downside_value))
        risk_status = "PASS" if risk_remaining >= -EPSILON else "BREACH"
        risk_utilization = current_risk / risk_limit if risk_limit > 0 else None
    risk_threshold = _finite_ratio(thresholds.get("risk_budget_utilization"))
    constraints.append(
        _constraint(
            constraint_id="risk_budget",
            label_en="Downside-loss risk budget",
            label_zh="下行损失风险预算",
            status=risk_status,
            required_for_ceiling=True,
            limit_value=risk_limit,
            current_value=current_risk,
            candidate_value=downside_value,
            remaining_capacity=(
                max(0.0, risk_remaining) if risk_remaining is not None else None
            ),
            maximum_incremental_position_weight=risk_ceiling,
            formula=(
                "max(0, risk_budget_limit - current_risk_budget_usage) "
                "/ abs(candidate_validated_downside_return)"
            ),
            formula_inputs={
                "risk_budget_limit": risk_limit,
                "current_risk_budget_usage": current_risk,
                "candidate_validated_downside_return": downside_value,
                "current_risk_budget_utilization": risk_utilization,
            },
            source_fields=[
                "policy.risk_budget_limit",
                "policy.risk_budget_method",
                "constraint_inputs.portfolio_state.current_risk_budget_usage",
                "constraint_inputs.candidate.downside_return",
            ],
            missing_fields=risk_missing,
            escalation_threshold=risk_threshold,
            escalation_triggered=(
                risk_utilization >= risk_threshold
                if risk_utilization is not None and risk_threshold is not None
                else None
            ),
            notes_en="The formula assumes the policy-defined downside-loss budget and does not net an unvalidated hedge.",
            notes_zh="该公式采用政策定义的下行损失预算，且不会扣除未经验证的对冲效果。",
        )
    )

    opportunity_policy = policy.get("opportunity_cost_requirement", {})
    minimum_count = parse_integer(
        opportunity_policy.get("minimum_comparable_opportunities")
    )
    maximum_mismatch = parse_integer(
        opportunity_policy.get("maximum_holding_period_mismatch_days")
    )
    minimum_excess = _finite_ratio(
        opportunity_policy.get("minimum_excess_return")
    )
    comparable = [
        row
        for row in bundle.opportunities
        if row.get("opportunity_status") == "ACTIVE"
        and row.get("return_status") == "VALIDATED"
        and row.get("security_type") == candidate.get("security_type")
        and row.get("security_identifier") != candidate.get("security_identifier")
        and _finite_ratio(row.get("expected_return")) is not None
        and holding_days is not None
        and maximum_mismatch is not None
        and parse_integer(row.get("holding_period_days")) is not None
        and abs(
            int(parse_integer(row.get("holding_period_days")) or 0) - holding_days
        )
        <= maximum_mismatch
    ]
    comparable_returns = [
        _finite_ratio(row.get("expected_return")) for row in comparable
    ]
    comparable_returns = [
        value for value in comparable_returns if value is not None
    ]
    best_alternative = max(comparable_returns) if comparable_returns else None
    opportunity_missing: list[str] = []
    if expected_value is None:
        opportunity_missing.append("constraint_inputs.candidate.expected_return")
    if minimum_count is None or len(comparable_returns) < minimum_count:
        opportunity_missing.append("opportunity_set.comparable_validated_alternatives")
    if minimum_excess is None:
        opportunity_missing.append(
            "policy.opportunity_cost_requirement.minimum_excess_return"
        )
    if maximum_mismatch is None:
        opportunity_missing.append(
            "policy.opportunity_cost_requirement.maximum_holding_period_mismatch_days"
        )
    excess_return = (
        expected_value - best_alternative
        if expected_value is not None and best_alternative is not None
        else None
    )
    opportunity_passed = (
        None
        if opportunity_missing
        else excess_return is not None
        and minimum_excess is not None
        and excess_return >= minimum_excess
    )
    constraints.append(
        _binary_constraint(
            constraint_id="opportunity_cost",
            label_en="Opportunity-cost hurdle",
            label_zh="机会成本门槛",
            passed=opportunity_passed,
            limit_value=minimum_excess,
            candidate_value=excess_return,
            formula=(
                "candidate_validated_return - highest comparable validated "
                "alternative return >= minimum_excess_return"
            ),
            formula_inputs={
                "candidate_validated_return": expected_value,
                "highest_comparable_validated_alternative_return": best_alternative,
                "minimum_excess_return": minimum_excess,
                "comparable_count": len(comparable_returns),
                "minimum_comparable_opportunities": minimum_count,
                "maximum_holding_period_mismatch_days": maximum_mismatch,
            },
            source_fields=[
                "constraint_inputs.candidate.expected_return",
                "opportunity_set",
                "policy.opportunity_cost_requirement",
            ],
            missing_fields=opportunity_missing,
            escalation_threshold=None,
            escalation_triggered=None,
            notes_en="Only active, validated, same-security-type alternatives within the reviewed horizon tolerance are compared.",
            notes_zh="仅比较处于 active 状态、已验证、证券类型相同且期限差在政策范围内的备选标的。",
        )
    )

    hedge = candidate.get("proposed_hedge", {})
    if hedge.get("status") == "NONE":
        constraints.append(
            _constraint(
                constraint_id="hedge",
                label_en="Applicable hedge constraints",
                label_zh="适用对冲约束",
                status="NOT_APPLICABLE",
                required_for_ceiling=False,
                limit_value=_finite_ratio(policy.get("maximum_hedge_ratio")),
                current_value=None,
                candidate_value=None,
                remaining_capacity=None,
                maximum_incremental_position_weight=None,
                formula="no proposed hedge; no hedge relief credited",
                formula_inputs={},
                source_fields=[
                    "constraint_inputs.candidate.proposed_hedge",
                    "policy.permitted_hedge_instruments",
                    "policy.maximum_hedge_ratio",
                ],
                notes_en="The unhedged constraint ceiling remains authoritative.",
                notes_zh="未对冲的约束上限仍为权威结果。",
            )
        )
    else:
        instrument = clean_text(hedge.get("instrument"))
        hedge_ratio = _finite_ratio(hedge.get("hedge_ratio"))
        maximum_hedge_ratio = _finite_ratio(policy.get("maximum_hedge_ratio"))
        permitted = set(policy.get("permitted_hedge_instruments", []))
        effectiveness_valid = hedge.get("effectiveness_status") == "VALIDATED"
        required = hedge.get("required_for_candidate") is True
        hedge_valid = (
            instrument in permitted
            and hedge_ratio is not None
            and maximum_hedge_ratio is not None
            and hedge_ratio <= maximum_hedge_ratio
            and effectiveness_valid
        )
        constraints.append(
            _constraint(
                constraint_id="hedge",
                label_en="Applicable hedge constraints",
                label_zh="适用对冲约束",
                status=(
                    "PASS"
                    if hedge_valid
                    else ("BREACH" if required else "WARNING")
                ),
                required_for_ceiling=required,
                limit_value=maximum_hedge_ratio,
                current_value=None,
                candidate_value=hedge_ratio,
                remaining_capacity=None,
                maximum_incremental_position_weight=(
                    1.0 if required and hedge_valid else (0.0 if required else None)
                ),
                formula=(
                    "instrument permitted AND hedge_ratio <= maximum_hedge_ratio "
                    "AND effectiveness_status = VALIDATED"
                ),
                formula_inputs={
                    "instrument_permitted": instrument in permitted,
                    "hedge_ratio": hedge_ratio,
                    "maximum_hedge_ratio": maximum_hedge_ratio,
                    "effectiveness_validated": effectiveness_valid,
                    "required_for_candidate": required,
                    "hedge_relief_credited": False,
                },
                source_fields=[
                    "constraint_inputs.candidate.proposed_hedge",
                    "policy.permitted_hedge_instruments",
                    "policy.maximum_hedge_ratio",
                ],
                notes_en="S13 validates the hedge terms but never increases the unhedged ceiling for assumed hedge relief.",
                notes_zh="S13 只验证对冲条款，不会因假设的对冲效果提高未对冲仓位上限。",
            )
        )

    required_constraints = [
        row for row in constraints if row["required_for_ceiling"]
    ]
    missing_items = sorted(
        {
            field
            for row in required_constraints
            if row["status"] == "MISSING"
            for field in row["missing_fields"]
        }
    )
    known_ceilings = [
        row
        for row in required_constraints
        if row["maximum_incremental_position_weight"] is not None
    ]
    tightest_known = (
        min(
            known_ceilings,
            key=lambda row: float(row["maximum_incremental_position_weight"]),
        )
        if known_ceilings
        else None
    )
    complete = not missing_items and len(known_ceilings) == len(required_constraints)
    if complete:
        maximum_incremental = min(
            float(row["maximum_incremental_position_weight"])
            for row in known_ceilings
        )
        binding_rows = [
            row
            for row in known_ceilings
            if abs(
                float(row["maximum_incremental_position_weight"])
                - maximum_incremental
            )
            <= EPSILON
        ]
        for row in binding_rows:
            row["binding"] = True
        binding_constraints = [
            {
                "constraint_id": row["constraint_id"],
                "maximum_incremental_position_weight": row[
                    "maximum_incremental_position_weight"
                ],
            }
            for row in binding_rows
        ]
        maximum_total = _weight((existing_issuer or 0.0) + maximum_incremental)
        status = CALCULATED_STATUS
    else:
        maximum_incremental = None
        maximum_total = None
        binding_constraints = []
        status = INCOMPLETE_STATUS

    formula_registry = {
        row["constraint_id"]: row["formula"] for row in constraints
    }
    return {
        "constraint_engine_version": CONSTRAINT_ENGINE_VERSION,
        "constraint_output_contract_version": CONSTRAINT_OUTPUT_CONTRACT_VERSION,
        "generated_at": utc_now(),
        "status": status,
        "data_classification": bundle.manifest.get("data_classification"),
        "input_mode": bundle.manifest.get("input_mode"),
        "private_input_status": private_input_status,
        "measurement_basis": "GROSS_LONG_WEIGHT",
        "gate3_precheck": privacy_safe_gate3_check(gate3_precheck),
        "gate3_recheck": privacy_safe_gate3_check(gate3_recheck),
        "gate3_identity": {
            "report_id": gate3_contract.get("report_id"),
            "contract_hash": gate3_contract.get("contract_hash"),
            "company": gate3_contract.get("company"),
        },
        "candidate_identity": {
            "security_identifier": candidate.get("security_identifier"),
            "issuer_identifier": candidate.get("issuer_identifier"),
            "issuer_name": candidate.get("issuer_name"),
            "security_type": candidate.get("security_type"),
            "sector": candidate.get("sector"),
            "country": candidate.get("country"),
            "correlation_bucket": candidate.get("correlation_bucket"),
        },
        "constraints": constraints,
        "formula_registry": formula_registry,
        "missing_items": missing_items,
        "tightest_known_constraint": (
            {
                "constraint_id": tightest_known["constraint_id"],
                "maximum_incremental_position_weight": tightest_known[
                    "maximum_incremental_position_weight"
                ],
                "not_final_while_inputs_missing": not complete,
            }
            if tightest_known is not None
            else None
        ),
        "binding_constraints": binding_constraints,
        "maximum_constraint_based_incremental_position_weight": maximum_incremental,
        "maximum_constraint_based_total_position_weight": maximum_total,
        "maximum_constraint_based_position_is_recommendation": False,
        "constraint_ceiling_disclosure_en": (
            "The calculated maximum is a policy-and-input constraint ceiling. "
            "It is not a suggested position, approved range, portfolio action, or trade."
        ),
        "constraint_ceiling_disclosure_zh": (
            "计算出的最大值仅为基于政策和输入的约束上限，不是建议仓位、"
            "批准区间、组合行动或交易指令。"
        ),
        "system_portfolio_assessment": {
            "status": "NOT_EVALUATED",
            "assessment": None,
            "position_range": None,
        },
        "partner_decision": {
            "workflow_status": "PARTNER_APPROVAL_PENDING",
            "decision": "PENDING",
            "approved_position_range": None,
        },
        "automatic_trade_execution": False,
        "external_transmission": "DENIED",
        "local_private_output_only": True,
        "raw_private_values_included": True,
        "next_action": (
            "Proceed to S14 assessment and approval logic."
            if status == CALCULATED_STATUS
            else "Complete the named S13 inputs locally and rerun the constraint engine."
        ),
    }
