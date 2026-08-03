#!/usr/bin/env python3
"""Shared S14 Gate 4 assessment and Partner-decision engine.

The engine consumes a validated S13 result. It classifies portfolio eligibility,
validates a separately owned Partner decision, and never selects a position or
places a trade.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - dependency diagnostic path
    Draft202012Validator = None
    FormatChecker = None

from gate4_constraint_engine import (
    CALCULATED_STATUS,
    validate_constraint_output,
)


SCRIPT_DIR = Path(__file__).resolve().parent
ASSESSMENT_SCHEMA_PATH = (
    SCRIPT_DIR.parent / "gate4" / "schemas" / "gate4_assessment_output.schema.json"
)
ASSESSMENT_ENGINE_VERSION = "1.0.0"
ASSESSMENT_OUTPUT_CONTRACT_VERSION = "1.0.0"
READY_STATUS = "GATE_4_SYSTEM_ASSESSMENT_READY"
NOT_EVALUATED_STATUS = "GATE_4_SYSTEM_ASSESSMENT_NOT_EVALUATED"
INVALID_STATUS = "GATE_4_ASSESSMENT_OUTPUT_INVALID"
ASSESSMENTS = {
    "ELIGIBLE",
    "ELIGIBLE_WITH_ESCALATION",
    "REVIEW_REQUIRED",
    "NOT_ELIGIBLE",
    "NOT_EVALUATED",
}
APPROVAL_CAPABLE_ASSESSMENTS = {
    "ELIGIBLE",
    "ELIGIBLE_WITH_ESCALATION",
}
DECISIONS = {"PENDING", "APPROVED", "MODIFIED", "REJECTED", "DEFERRED"}
EPSILON = 1e-12

ASSESSMENT_LABELS = {
    "ELIGIBLE": ("Eligible", "符合条件"),
    "ELIGIBLE_WITH_ESCALATION": (
        "Eligible with Escalation",
        "符合条件但需升级复核",
    ),
    "REVIEW_REQUIRED": ("Review Required", "需要进一步复核"),
    "NOT_ELIGIBLE": ("Not Eligible", "不符合条件"),
    "NOT_EVALUATED": ("Not Evaluated", "未完成评估"),
}


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite_ratio(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or number > 1:
        return None
    return number


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


def validate_assessment_output(payload: dict[str, Any]) -> list[str]:
    if Draft202012Validator is None or FormatChecker is None:
        return ["<dependency>:jsonschema"]
    try:
        schema = json.loads(ASSESSMENT_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["<schema>:gate4_assessment_output"]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return sorted(
        {
            _validation_path(error)
            for error in validator.iter_errors(payload)
        }
    )


def _check(
    check_id: str,
    passed: bool,
    *,
    message_pass_en: str,
    message_pass_zh: str,
    message_fail_en: str,
    message_fail_zh: str,
    evidence_ids: list[str],
    fail_severity: str = "HARD_STOP",
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "PASS" if passed else ("WARNING" if fail_severity == "WARNING" else "FAIL"),
        "severity": "INFO" if passed else fail_severity,
        "message_en": message_pass_en if passed else message_fail_en,
        "message_zh": message_pass_zh if passed else message_fail_zh,
        "evidence_ids": evidence_ids,
    }


def _s13_hash_payload(result: dict[str, Any]) -> dict[str, Any]:
    gate3_recheck = dict(result.get("gate3_recheck") or {})
    # Runtime timestamps do not change the analytical state and must not
    # invalidate a Partner decision bound to otherwise identical inputs.
    gate3_recheck.pop("evaluated_at", None)
    return {
        "constraint_output_contract_version": result.get(
            "constraint_output_contract_version"
        ),
        "status": result.get("status"),
        "data_classification": result.get("data_classification"),
        "input_mode": result.get("input_mode"),
        "measurement_basis": result.get("measurement_basis"),
        "gate3_identity": result.get("gate3_identity"),
        "candidate_identity": result.get("candidate_identity"),
        "gate3_recheck": gate3_recheck,
        "constraints": result.get("constraints"),
        "formula_registry": result.get("formula_registry"),
        "missing_items": result.get("missing_items"),
        "binding_constraints": result.get("binding_constraints"),
        "maximum_constraint_based_incremental_position_weight": result.get(
            "maximum_constraint_based_incremental_position_weight"
        ),
        "maximum_constraint_based_total_position_weight": result.get(
            "maximum_constraint_based_total_position_weight"
        ),
        "maximum_constraint_based_position_is_recommendation": result.get(
            "maximum_constraint_based_position_is_recommendation"
        ),
    }


def s13_result_hash(result: dict[str, Any]) -> str:
    return _canonical_hash(_s13_hash_payload(result))


def _constraint_evidence_id(constraint_id: Any) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", "_", str(constraint_id).upper()).strip("_")
    return f"G4-EV-CONSTRAINT_{cleaned or 'UNKNOWN'}"


def _constraint_integrity(
    s13_result: dict[str, Any],
) -> tuple[bool, list[str]]:
    constraints = s13_result.get("constraints", [])
    if not isinstance(constraints, list):
        return False, ["constraints_not_array"]
    rows = [row for row in constraints if isinstance(row, dict)]
    constraint_ids = [str(row.get("constraint_id") or "") for row in rows]
    issues: list[str] = []
    if any(not value for value in constraint_ids):
        issues.append("constraint_id_missing")
    if len(constraint_ids) != len(set(constraint_ids)):
        issues.append("constraint_ids_not_unique")

    expected_formula_registry = {
        str(row.get("constraint_id")): row.get("formula") for row in rows
    }
    if s13_result.get("formula_registry") != expected_formula_registry:
        issues.append("formula_registry_not_reproducible")

    required = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("required_for_ceiling") is True
    ]
    if not required:
        issues.append("required_constraints_absent")
        return False, issues
    ceilings: list[tuple[str, float]] = []
    for row in required:
        constraint_id = str(row.get("constraint_id") or "unknown")
        if row.get("status") not in {"PASS", "BREACH"}:
            issues.append(f"required_constraint_status_invalid:{constraint_id}")
        value = _finite_ratio(row.get("maximum_incremental_position_weight"))
        if value is None:
            issues.append(f"missing_numeric_ceiling:{constraint_id}")
        else:
            ceilings.append((constraint_id, value))
    maximum = _finite_ratio(
        s13_result.get("maximum_constraint_based_incremental_position_weight")
    )
    if maximum is None:
        issues.append("final_incremental_ceiling_missing")
    if ceilings and maximum is not None:
        expected = min(value for _, value in ceilings)
        if not math.isclose(expected, maximum, rel_tol=0, abs_tol=EPSILON):
            issues.append("final_incremental_ceiling_not_reproducible")
        expected_binding = {
            constraint_id
            for constraint_id, value in ceilings
            if math.isclose(value, expected, rel_tol=0, abs_tol=EPSILON)
        }
        binding_rows = [
            row
            for row in s13_result.get("binding_constraints", [])
            if isinstance(row, dict)
        ]
        binding_ids = [str(row.get("constraint_id")) for row in binding_rows]
        actual_binding = set(binding_ids)
        if len(binding_ids) != len(actual_binding):
            issues.append("binding_constraint_ids_not_unique")
        if expected_binding != actual_binding:
            issues.append("binding_constraints_not_reproducible")
        row_binding = {
            str(row.get("constraint_id"))
            for row in rows
            if row.get("binding") is True
        }
        if expected_binding != row_binding:
            issues.append("constraint_row_binding_flags_not_reproducible")
        for row in binding_rows:
            binding_id = str(row.get("constraint_id"))
            binding_value = _finite_ratio(
                row.get("maximum_incremental_position_weight")
            )
            if (
                binding_id not in expected_binding
                or binding_value is None
                or not math.isclose(
                    binding_value,
                    expected,
                    rel_tol=0,
                    abs_tol=EPSILON,
                )
            ):
                issues.append(f"binding_constraint_value_invalid:{binding_id}")

        existing_rows = [
            row
            for row in rows
            if row.get("constraint_id") == "existing_issuer_exposure"
        ]
        if len(existing_rows) != 1:
            issues.append("existing_issuer_exposure_row_invalid")
        else:
            existing_weight = _finite_ratio(existing_rows[0].get("current_value"))
            total_ceiling = _finite_ratio(
                s13_result.get(
                    "maximum_constraint_based_total_position_weight"
                )
            )
            if existing_weight is None or total_ceiling is None:
                issues.append("total_issuer_ceiling_input_missing")
            else:
                expected_total = round(
                    max(0.0, min(1.0, existing_weight + maximum)),
                    12,
                )
                if not math.isclose(
                    expected_total,
                    total_ceiling,
                    rel_tol=0,
                    abs_tol=EPSILON,
                ):
                    issues.append("total_issuer_ceiling_not_reproducible")
    return not issues, issues


def _constraint_snapshot(s13_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "s13_status": str(s13_result.get("status") or "NOT_EVALUATED"),
        "s13_output_validation_status": str(
            s13_result.get("output_validation", {}).get("status")
            or "NOT_EVALUATED"
        ),
        "measurement_basis": s13_result.get("measurement_basis"),
        "constraints": list(s13_result.get("constraints", [])),
        "formula_registry": dict(s13_result.get("formula_registry", {})),
        "missing_items": list(s13_result.get("missing_items", [])),
        "binding_constraints": list(
            s13_result.get("binding_constraints", [])
        ),
        "maximum_constraint_based_incremental_position_weight": s13_result.get(
            "maximum_constraint_based_incremental_position_weight"
        ),
        "maximum_constraint_based_total_position_weight": s13_result.get(
            "maximum_constraint_based_total_position_weight"
        ),
        "maximum_constraint_based_position_is_recommendation": False,
        "ceiling_disclosure_en": (
            "This is the maximum allowed by the tested constraints. It is not an investment instruction or an approved range."
        ),
        "ceiling_disclosure_zh": (
            "该数值仅表示已测试约束允许的最大值，不构成投资指令或已批准区间。"
        ),
    }


def _not_evaluated_assessment(
    s13_result: dict[str, Any],
    reason_codes: list[str],
) -> dict[str, Any]:
    label_en, label_zh = ASSESSMENT_LABELS["NOT_EVALUATED"]
    return {
        "workflow_status": "NOT_EVALUATED",
        "assessment": "NOT_EVALUATED",
        "assessment_label_en": label_en,
        "assessment_label_zh": label_zh,
        "rationale_codes": sorted(set(reason_codes)),
        "rationale_en": [
            "The S13 constraint result is incomplete, stale, changed, or failed validation; no portfolio eligibility conclusion is permitted."
        ],
        "rationale_zh": [
            "S13 约束结果不完整、已过期、发生变化或未通过验证，因此不能形成组合资格结论。"
        ],
        "breach_ids": [],
        "review_ids": [],
        "escalation_ids": [],
        "can_support_partner_approval": False,
        "maximum_constraint_ceiling": {
            "incremental_weight": None,
            "total_issuer_weight": None,
            "measurement_basis": s13_result.get("measurement_basis"),
            "is_recommendation": False,
            "disclosure_en": "No current constraint ceiling may be used for a decision.",
            "disclosure_zh": "当前没有可用于决策的有效约束上限。",
        },
        "position_range": None,
        "system_generated_position_recommendation": False,
    }


def build_system_assessment(
    s13_result: dict[str, Any],
    *,
    private_bundle_unchanged: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    schema_errors = validate_constraint_output(s13_result)
    integrity_ok, integrity_issues = _constraint_integrity(s13_result)
    output_validation_passed = (
        s13_result.get("output_validation", {}).get("status") == "PASS"
    )
    gate3_eligible = s13_result.get("gate3_recheck", {}).get("eligible") is True
    s13_calculated = s13_result.get("status") == CALCULATED_STATUS
    ceiling_not_recommendation = (
        s13_result.get("maximum_constraint_based_position_is_recommendation")
        is False
    )
    checks = [
        _check(
            "S14-S13-CONTRACT",
            not schema_errors,
            message_pass_en="The S13 output matches the shared constraint contract.",
            message_pass_zh="S13 输出符合共享约束合同。",
            message_fail_en="The S13 output contract is invalid.",
            message_fail_zh="S13 输出合同无效。",
            evidence_ids=["G4-EV-S13"],
        ),
        _check(
            "S14-S13-STATUS",
            s13_calculated,
            message_pass_en="Every required S13 ceiling is available.",
            message_pass_zh="所有必要的 S13 上限均已获得。",
            message_fail_en="S13 is not complete; portfolio eligibility cannot be evaluated.",
            message_fail_zh="S13 尚未完成，不能评估组合资格。",
            evidence_ids=["G4-EV-S13"],
        ),
        _check(
            "S14-S13-OUTPUT-VALIDATION",
            output_validation_passed,
            message_pass_en="S13 output validation passed.",
            message_pass_zh="S13 输出验证通过。",
            message_fail_en="S13 output validation did not pass.",
            message_fail_zh="S13 输出验证未通过。",
            evidence_ids=["G4-EV-S13"],
        ),
        _check(
            "S14-GATE3-RECHECK",
            gate3_eligible,
            message_pass_en="The latest Gate 3 recheck remains eligible.",
            message_pass_zh="最新 Gate 3 复核仍符合资格。",
            message_fail_en="Gate 3 is not currently eligible for portfolio use.",
            message_fail_zh="Gate 3 当前不具备用于组合判断的资格。",
            evidence_ids=["G4-EV-GATE3"],
        ),
        _check(
            "S14-BUNDLE-STABILITY",
            private_bundle_unchanged,
            message_pass_en="The private input bundle did not change during the S14 run.",
            message_pass_zh="S14 运行期间私有输入包未发生变化。",
            message_fail_en="The private input bundle changed during assessment.",
            message_fail_zh="评估期间私有输入包发生变化。",
            evidence_ids=["G4-EV-BUNDLE"],
        ),
        _check(
            "S14-CEILING-REPRODUCIBILITY",
            integrity_ok,
            message_pass_en="The constraint IDs, formulas, incremental and total ceilings, and binding rows are reproducible from S13.",
            message_pass_zh="约束编号、公式、新增及总上限和 binding 行均可由 S13 复算。",
            message_fail_en=(
                "The S13 constraint result is not fully reproducible: "
                + ", ".join(integrity_issues)
            ),
            message_fail_zh="S13 约束结果无法完整复算。",
            evidence_ids=["G4-EV-S13"],
        ),
        _check(
            "S14-NO-SYSTEM-POSITION-SELECTION",
            ceiling_not_recommendation,
            message_pass_en="The S13 maximum remains classified only as a constraint ceiling.",
            message_pass_zh="S13 最大值仍仅被归类为约束上限。",
            message_fail_en="The S13 maximum was incorrectly classified as a position recommendation.",
            message_fail_zh="S13 最大值被错误归类为仓位投资意见。",
            evidence_ids=["G4-EV-S13"],
        ),
    ]
    hard_stop_ids = [
        check["check_id"] for check in checks if check["status"] == "FAIL"
    ]
    if hard_stop_ids:
        return _not_evaluated_assessment(s13_result, hard_stop_ids), checks

    constraints = [
        row for row in s13_result.get("constraints", []) if isinstance(row, dict)
    ]
    controlled_statuses = {
        "PASS",
        "BREACH",
        "MISSING",
        "WARNING",
        "NOT_APPLICABLE",
    }
    unknown_status_ids = [
        str(row.get("constraint_id"))
        for row in constraints
        if row.get("status") not in controlled_statuses
    ]
    if unknown_status_ids:
        checks.append(
            _check(
                "S14-CONSTRAINT-STATUS-CONTROL",
                False,
                message_pass_en="Constraint statuses are controlled.",
                message_pass_zh="约束状态受控。",
                message_fail_en="An unsupported constraint status is present.",
                message_fail_zh="存在不受支持的约束状态。",
                evidence_ids=["G4-EV-S13"],
            )
        )
        return _not_evaluated_assessment(
            s13_result,
            [f"UNKNOWN_CONSTRAINT_STATUS:{value}" for value in unknown_status_ids],
        ), checks

    breach_ids = sorted(
        str(row.get("constraint_id"))
        for row in constraints
        if row.get("required_for_ceiling") is True and row.get("status") == "BREACH"
    )
    review_ids = sorted(
        str(row.get("constraint_id"))
        for row in constraints
        if row.get("required_for_ceiling") is not True
        and row.get("status") in {"BREACH", "WARNING", "MISSING"}
    )
    constraint_escalations = {
        f"constraint:{row.get('constraint_id')}"
        for row in constraints
        if row.get("escalation_triggered") is True
    }
    gate3_escalations = {
        f"gate3:{value}"
        for value in s13_result.get("gate3_recheck", {}).get(
            "escalated_warning_ids", []
        )
    }
    escalation_ids = sorted(constraint_escalations | gate3_escalations)
    incremental_ceiling = _finite_ratio(
        s13_result.get("maximum_constraint_based_incremental_position_weight")
    )
    total_ceiling = _finite_ratio(
        s13_result.get("maximum_constraint_based_total_position_weight")
    )

    if breach_ids or incremental_ceiling is None or incremental_ceiling <= EPSILON:
        assessment = "NOT_ELIGIBLE"
        rationale_codes = [
            *[f"CONSTRAINT_BREACH:{value}" for value in breach_ids],
            *(
                ["NO_INCREMENTAL_CAPACITY"]
                if incremental_ceiling is not None and incremental_ceiling <= EPSILON
                else []
            ),
        ]
        rationale_en = [
            "At least one required condition fails or no incremental capacity remains under the tested constraints."
        ]
        rationale_zh = [
            "至少一项必要条件未通过，或在已测试约束下已无新增容量。"
        ]
    elif review_ids:
        assessment = "REVIEW_REQUIRED"
        rationale_codes = [f"UNRESOLVED_REVIEW:{value}" for value in review_ids]
        rationale_en = [
            "A non-required but decision-relevant warning remains unresolved; approval is blocked until it is reviewed."
        ]
        rationale_zh = [
            "仍有虽非必要但与决策相关的警告未解决；完成复核前不能批准。"
        ]
    elif escalation_ids:
        assessment = "ELIGIBLE_WITH_ESCALATION"
        rationale_codes = [f"ESCALATION:{value}" for value in escalation_ids]
        rationale_en = [
            "Required constraints pass, but one or more reviewed escalation thresholds or Gate 3 warning escalations are active."
        ]
        rationale_zh = [
            "必要约束均通过，但一项或多项升级阈值或 Gate 3 警告升级仍处于有效状态。"
        ]
    else:
        assessment = "ELIGIBLE"
        rationale_codes = ["ALL_REQUIRED_CONSTRAINTS_PASS"]
        rationale_en = [
            "All required tested constraints pass with positive incremental capacity and no unresolved review item."
        ]
        rationale_zh = [
            "所有已测试的必要约束均通过，存在正的新增容量，且没有未解决的复核事项。"
        ]

    label_en, label_zh = ASSESSMENT_LABELS[assessment]
    for escalation_id in escalation_ids:
        checks.append(
            _check(
                f"S14-ESCALATION:{escalation_id}",
                False,
                message_pass_en="No escalation is active.",
                message_pass_zh="没有有效升级项。",
                message_fail_en=f"Active escalation requires Partner acknowledgement: {escalation_id}.",
                message_fail_zh=f"有效升级项需要 Partner 明确认可：{escalation_id}。",
                evidence_ids=["G4-EV-SYSTEM-ASSESSMENT"],
                fail_severity="WARNING",
            )
        )
    return {
        "workflow_status": READY_STATUS,
        "assessment": assessment,
        "assessment_label_en": label_en,
        "assessment_label_zh": label_zh,
        "rationale_codes": sorted(set(rationale_codes)),
        "rationale_en": rationale_en,
        "rationale_zh": rationale_zh,
        "breach_ids": breach_ids,
        "review_ids": review_ids,
        "escalation_ids": escalation_ids,
        "can_support_partner_approval": assessment in APPROVAL_CAPABLE_ASSESSMENTS,
        "maximum_constraint_ceiling": {
            "incremental_weight": incremental_ceiling,
            "total_issuer_weight": total_ceiling,
            "measurement_basis": s13_result.get("measurement_basis"),
            "is_recommendation": False,
            "disclosure_en": (
                "This is the maximum allowed by the tested constraints. It is not an investment instruction or an approved range."
            ),
            "disclosure_zh": (
                "该数值仅表示已测试约束允许的最大值，不构成投资指令或已批准区间。"
            ),
        },
        "position_range": None,
        "system_generated_position_recommendation": False,
    }, checks


def _assessment_hash_payload(
    *,
    s13_hash: str,
    assessment_input_fingerprint: str | None,
    gate3_identity: dict[str, Any],
    candidate_identity: dict[str, Any],
    system_assessment: dict[str, Any],
) -> dict[str, Any]:
    return {
        "assessment_output_contract_version": ASSESSMENT_OUTPUT_CONTRACT_VERSION,
        "s13_result_hash": s13_hash,
        "assessment_input_fingerprint": assessment_input_fingerprint,
        "gate3_identity": gate3_identity,
        "candidate_identity": candidate_identity,
        "system_portfolio_assessment": system_assessment,
    }


def build_partner_decision(
    approval_config: dict[str, Any],
    *,
    system_assessment: dict[str, Any],
    assessment_hash: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    submitted = approval_config.get("partner_decision", {})
    submitted_status = str(submitted.get("status") or "PENDING")
    if submitted_status not in DECISIONS:
        submitted_status = "PENDING"
    approved_by = submitted.get("approved_by")
    approved_at = submitted.get("approved_at")
    rationale = submitted.get("decision_rationale")
    submitted_hash = submitted.get("assessment_hash")
    minimum = _finite_ratio(submitted.get("approved_position_min"))
    maximum = _finite_ratio(submitted.get("approved_position_max"))
    basis = submitted.get("approved_position_basis")
    acknowledgements = submitted.get("acknowledged_escalation_ids", [])
    if not isinstance(acknowledgements, list):
        acknowledgements = []
    acknowledgements = sorted({str(value) for value in acknowledgements})
    blocking: list[str] = []
    checks: list[dict[str, Any]] = []

    if submitted_status == "PENDING":
        return {
            "workflow_status": "PARTNER_APPROVAL_PENDING",
            "submitted_decision": "PENDING",
            "decision": "PENDING",
            "validation_status": "PENDING",
            "approved_by": None,
            "approved_at": None,
            "decision_rationale": None,
            "approved_position_range": None,
            "acknowledged_escalation_ids": [],
            "assessment_hash_binding": None,
            "decision_hash": None,
            "blocking_reason_codes": [],
            "system_generated": False,
            "automatic_trade_execution": False,
        }, checks

    designated_partner = approval_config.get("designated_partner")
    if not approved_by or approved_by != designated_partner:
        blocking.append("DESIGNATED_PARTNER_MISMATCH")
    if not approved_at:
        blocking.append("APPROVAL_TIMESTAMP_MISSING")
    if not isinstance(rationale, str) or not rationale.strip():
        blocking.append("DECISION_RATIONALE_MISSING")

    if submitted_status in {"APPROVED", "MODIFIED"}:
        if system_assessment.get("assessment") not in APPROVAL_CAPABLE_ASSESSMENTS:
            blocking.append("SYSTEM_ASSESSMENT_NOT_APPROVAL_CAPABLE")
        if assessment_hash is None or submitted_hash != assessment_hash:
            blocking.append("ASSESSMENT_HASH_MISMATCH")
        if basis != "TOTAL_ISSUER_GROSS_LONG_WEIGHT":
            blocking.append("APPROVED_POSITION_BASIS_INVALID")
        if minimum is None or maximum is None or minimum > maximum:
            blocking.append("APPROVED_POSITION_RANGE_INVALID")
        ceiling = _finite_ratio(
            system_assessment.get("maximum_constraint_ceiling", {}).get(
                "total_issuer_weight"
            )
        )
        if maximum is not None and (ceiling is None or maximum > ceiling + EPSILON):
            blocking.append("APPROVED_POSITION_EXCEEDS_CONSTRAINT_CEILING")
        required_acknowledgements = set(
            system_assessment.get("escalation_ids", [])
        )
        if set(acknowledgements) != required_acknowledgements:
            blocking.append("ESCALATION_ACKNOWLEDGEMENT_MISMATCH")
    else:
        if any(value is not None for value in (minimum, maximum, basis)):
            blocking.append("NON_APPROVAL_POSITION_RANGE_PRESENT")
        if assessment_hash is None or submitted_hash != assessment_hash:
            blocking.append("ASSESSMENT_HASH_MISMATCH")
        if acknowledgements:
            blocking.append("NON_APPROVAL_ESCALATION_ACKNOWLEDGEMENT_PRESENT")

    valid = not blocking
    checks.append(
        _check(
            "S14-PARTNER-DECISION",
            valid,
            message_pass_en="The recorded Partner decision is complete and consistent with the current assessment.",
            message_pass_zh="已记录的 Partner 决策完整且与当前评估一致。",
            message_fail_en=(
                "The recorded Partner decision is blocked: " + ", ".join(blocking)
            ),
            message_fail_zh="已记录的 Partner 决策未通过验证。",
            evidence_ids=["G4-EV-PARTNER-DECISION"],
        )
    )
    if not valid:
        return {
            "workflow_status": "PARTNER_DECISION_BLOCKED",
            "submitted_decision": submitted_status,
            "decision": "PENDING",
            "validation_status": "BLOCKED",
            "approved_by": approved_by,
            "approved_at": approved_at,
            "decision_rationale": rationale,
            "approved_position_range": None,
            "acknowledged_escalation_ids": acknowledgements,
            "assessment_hash_binding": submitted_hash,
            "decision_hash": None,
            "blocking_reason_codes": sorted(set(blocking)),
            "system_generated": False,
            "automatic_trade_execution": False,
        }, checks

    workflow = {
        "APPROVED": "GATE_4_APPROVED",
        "MODIFIED": "GATE_4_MODIFIED",
        "REJECTED": "GATE_4_REJECTED",
        "DEFERRED": "GATE_4_DEFERRED",
    }[submitted_status]
    approved_range = (
        {
            "minimum": minimum,
            "maximum": maximum,
            "basis": "TOTAL_ISSUER_GROSS_LONG_WEIGHT",
            "is_system_recommendation": False,
        }
        if submitted_status in {"APPROVED", "MODIFIED"}
        else None
    )
    decision_payload = {
        "submitted_decision": submitted_status,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "decision_rationale": rationale,
        "approved_position_range": approved_range,
        "acknowledged_escalation_ids": acknowledgements,
        "assessment_hash_binding": submitted_hash,
    }
    return {
        "workflow_status": workflow,
        "submitted_decision": submitted_status,
        "decision": submitted_status,
        "validation_status": "VALIDATED",
        "approved_by": approved_by,
        "approved_at": approved_at,
        "decision_rationale": rationale,
        "approved_position_range": approved_range,
        "acknowledged_escalation_ids": acknowledgements,
        "assessment_hash_binding": submitted_hash,
        "decision_hash": _canonical_hash(decision_payload),
        "blocking_reason_codes": [],
        "system_generated": False,
        "automatic_trade_execution": False,
    }, checks


def _evidence_ledger(
    s13_result: dict[str, Any],
    *,
    system_assessment: dict[str, Any],
    partner_decision: dict[str, Any],
    assessment_input_fingerprint: str | None,
    s13_hash: str,
) -> list[dict[str, Any]]:
    evidence = [
        {
            "evidence_id": "G4-EV-GATE3",
            "evidence_class": "CONTROL",
            "label_en": "Gate 3 identity and latest eligibility recheck",
            "label_zh": "Gate 3 标识与最新资格复核",
            "source_object": "s13_result.gate3_recheck",
            "source_fields": ["gate3_identity", "gate3_recheck"],
            "value": {
                "gate3_identity": s13_result.get("gate3_identity"),
                "eligible": s13_result.get("gate3_recheck", {}).get("eligible"),
                "escalated_warning_ids": s13_result.get("gate3_recheck", {}).get(
                    "escalated_warning_ids", []
                ),
            },
        },
        {
            "evidence_id": "G4-EV-BUNDLE",
            "evidence_class": "CONTROL",
            "label_en": "Assessment-input fingerprint excluding the Partner decision",
            "label_zh": "不含 Partner 决策的评估输入指纹",
            "source_object": "local_private_workspace",
            "source_fields": ["manifest", "referenced_input_files"],
            "value": assessment_input_fingerprint,
        },
        {
            "evidence_id": "G4-EV-S13",
            "evidence_class": "CALC",
            "label_en": "Validated S13 constraint result",
            "label_zh": "经验证的 S13 约束结果",
            "source_object": "gate4_constraint_engine_result",
            "source_fields": [
                "constraints",
                "binding_constraints",
                "maximum_constraint_based_incremental_position_weight",
                "maximum_constraint_based_total_position_weight",
            ],
            "value": {
                "s13_result_hash": s13_hash,
                "status": s13_result.get("status"),
                "binding_constraints": s13_result.get("binding_constraints", []),
                "maximum_incremental_weight": s13_result.get(
                    "maximum_constraint_based_incremental_position_weight"
                ),
                "maximum_total_issuer_weight": s13_result.get(
                    "maximum_constraint_based_total_position_weight"
                ),
            },
        },
    ]
    for row in s13_result.get("constraints", []):
        if not isinstance(row, dict):
            continue
        evidence.append(
            {
                "evidence_id": _constraint_evidence_id(row.get("constraint_id")),
                "evidence_class": "CALC",
                "label_en": str(row.get("label_en") or row.get("constraint_id")),
                "label_zh": str(row.get("label_zh") or row.get("constraint_id")),
                "source_object": "s13_result.constraints",
                "source_fields": list(row.get("source_fields", [])),
                "value": {
                    "status": row.get("status"),
                    "limit_value": row.get("limit_value"),
                    "current_value": row.get("current_value"),
                    "candidate_value": row.get("candidate_value"),
                    "maximum_incremental_position_weight": row.get(
                        "maximum_incremental_position_weight"
                    ),
                    "formula": row.get("formula"),
                    "binding": row.get("binding"),
                    "escalation_triggered": row.get("escalation_triggered"),
                },
            }
        )
    evidence.extend(
        [
            {
                "evidence_id": "G4-EV-SYSTEM-ASSESSMENT",
                "evidence_class": "JUDGMENT",
                "label_en": "System portfolio assessment",
                "label_zh": "系统组合评估",
                "source_object": "gate4_assessment_engine",
                "source_fields": ["system_portfolio_assessment"],
                "value": {
                    "assessment": system_assessment.get("assessment"),
                    "rationale_codes": system_assessment.get("rationale_codes", []),
                },
            },
            {
                "evidence_id": "G4-EV-PARTNER-DECISION",
                "evidence_class": "CONTROL",
                "label_en": "Separately owned Partner decision",
                "label_zh": "独立归属的 Partner 决策",
                "source_object": "approval_config.partner_decision",
                "source_fields": ["partner_decision"],
                "value": {
                    "submitted_decision": partner_decision.get(
                        "submitted_decision"
                    ),
                    "effective_decision": partner_decision.get("decision"),
                    "validation_status": partner_decision.get("validation_status"),
                    "decision_hash": partner_decision.get("decision_hash"),
                },
            },
        ]
    )
    return evidence


def build_gate4_assessment(
    s13_result: dict[str, Any],
    approval_config: dict[str, Any],
    *,
    assessment_input_fingerprint: str | None,
    private_bundle_unchanged: bool = True,
) -> dict[str, Any]:
    s13_hash = s13_result_hash(s13_result)
    system_assessment, checks = build_system_assessment(
        s13_result,
        private_bundle_unchanged=private_bundle_unchanged,
    )
    ready = system_assessment.get("assessment") != "NOT_EVALUATED"
    assessment_hash = (
        _canonical_hash(
            _assessment_hash_payload(
                s13_hash=s13_hash,
                assessment_input_fingerprint=assessment_input_fingerprint,
                gate3_identity=dict(s13_result.get("gate3_identity", {})),
                candidate_identity=dict(s13_result.get("candidate_identity", {})),
                system_assessment=system_assessment,
            )
        )
        if ready
        else None
    )
    partner_decision, partner_checks = build_partner_decision(
        approval_config,
        system_assessment=system_assessment,
        assessment_hash=assessment_hash,
    )
    checks.extend(partner_checks)
    hard_stop_count = sum(check["status"] == "FAIL" for check in checks)
    warning_count = sum(check["status"] == "WARNING" for check in checks)

    decision = partner_decision["decision"]
    if system_assessment["assessment"] == "NOT_EVALUATED":
        next_action_en = "Resolve the named S13 or input validation failures and rerun S14."
        next_action_zh = "解决列明的 S13 或输入验证问题后重新运行 S14。"
    elif decision == "PENDING":
        next_action_en = "The designated Partner should review the assessment and record a dated decision locally."
        next_action_zh = "应由指定 Partner 在本地复核评估并记录带日期的决定。"
    elif decision in {"APPROVED", "MODIFIED"}:
        next_action_en = "Apply the validated Partner-owned range through the fund's separate implementation controls; no trade is automatic."
        next_action_zh = "通过基金独立的执行控制落实经验证的 Partner 区间；系统不会自动交易。"
    elif decision == "REJECTED":
        next_action_en = "Do not add exposure under this decision record; reassess only after material inputs change."
        next_action_zh = "根据本次决定不得新增敞口；仅在重要输入变化后重新评估。"
    else:
        next_action_en = "Keep the candidate deferred until the stated decision conditions are resolved."
        next_action_zh = "在列明的决策条件解决前维持暂缓状态。"

    output = {
        "assessment_engine_version": ASSESSMENT_ENGINE_VERSION,
        "assessment_output_contract_version": ASSESSMENT_OUTPUT_CONTRACT_VERSION,
        "generated_at": utc_now(),
        "status": READY_STATUS if ready else NOT_EVALUATED_STATUS,
        "data_classification": str(
            s13_result.get("data_classification") or "PRIVATE_PORTFOLIO"
        ),
        "input_mode": str(s13_result.get("input_mode") or "NOT_EVALUATED"),
        "gate3_identity": dict(s13_result.get("gate3_identity", {})),
        "candidate_identity": dict(s13_result.get("candidate_identity", {})),
        "assessment_input_fingerprint": assessment_input_fingerprint,
        "s13_result_hash": s13_hash,
        "assessment_hash": assessment_hash,
        "constraint_snapshot": _constraint_snapshot(s13_result),
        "system_portfolio_assessment": system_assessment,
        "partner_decision": partner_decision,
        "evidence_ledger": _evidence_ledger(
            s13_result,
            system_assessment=system_assessment,
            partner_decision=partner_decision,
            assessment_input_fingerprint=assessment_input_fingerprint,
            s13_hash=s13_hash,
        ),
        "validation": {
            "status": "FAIL" if hard_stop_count else "PASS",
            "hard_stop_count": hard_stop_count,
            "warning_count": warning_count,
            "checks": checks,
        },
        "report_controls": {
            "bilingual": True,
            "renderer_may_recalculate": False,
            "synthetic_pdf_generation_allowed": (
                s13_result.get("data_classification")
                == "SYNTHETIC_PUBLIC_EXAMPLE"
            ),
            "private_pdf_requires_sanitizer": True,
            "maximum_ceiling_term_en": "Constraint ceiling",
            "maximum_ceiling_term_zh": "约束上限",
        },
        "automatic_trade_execution": False,
        "external_transmission": "DENIED",
        "local_private_output_only": (
            s13_result.get("data_classification") == "PRIVATE_PORTFOLIO"
        ),
        "raw_private_values_included": (
            s13_result.get("data_classification") == "PRIVATE_PORTFOLIO"
        ),
        "contract_validation": {
            "status": "PASS",
            "error_count": 0,
            "error_paths": [],
        },
        "next_action_en": next_action_en,
        "next_action_zh": next_action_zh,
    }
    errors = validate_assessment_output(output)
    output["contract_validation"] = {
        "status": "FAIL" if errors else "PASS",
        "error_count": len(errors),
        "error_paths": errors,
    }
    if errors:
        output["status"] = INVALID_STATUS
    return output
