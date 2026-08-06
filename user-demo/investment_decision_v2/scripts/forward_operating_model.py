#!/usr/bin/env python3
"""Company-agnostic forward operating and share-count bridges for S10.

Business-model modules own only their revenue-driver logic. Every supported
module produces the same audited FCF and forward-share output contract.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from math import isclose, isfinite
from typing import Any, Callable

from equity_valuation_contract import normalize_valuation_period


FORWARD_VALUATION_CONTRACT_VERSION = "1.0.0"
DRIVER_MODULE_REGISTRY_VERSION = "1.0.0"
FORWARD_CONTRACT_STATUSES = {
    "DRIVER_MODEL_NOT_AVAILABLE",
    "INVALID",
    "PARTIALLY_VALIDATED",
    "VALIDATED",
}
FORWARD_FCF_BASIS = "LEVERED_CFO_MINUS_CAPEX_BRIDGE"
FORWARD_FCF_FORMULA = (
    "operating_income - cash_interest - cash_taxes "
    "+ depreciation_and_amortization + stock_based_compensation "
    "+ other_non_cash_items - working_capital_investment - capex "
    "- restructuring_cash - acquisition_integration_cash "
    "+ other_cash_adjustments"
)
FORWARD_SHARE_FORMULA = (
    "latest_reported_shares - repurchases "
    "+ stock_based_compensation_issuance + employee_plan_issuance "
    "+ convertible_dilution + acquisition_share_issuance + other_net_change"
)
INPUT_EVIDENCE_CLASSES = {"FACT", "CALC", "JUDGMENT", "MISSING"}
SCENARIO_NAMES = {"Bear", "Base", "Bull"}
KNOWN_SHARE_EVENT_STATUSES = {
    "REVIEWED_NO_QUANTIFIED_CHANGE",
    "REVIEWED_CHANGE_REFLECTED",
}
SHARE_CHANGE_FIELDS = (
    "repurchases",
    "stock_based_compensation_issuance",
    "employee_plan_issuance",
    "convertible_dilution",
    "acquisition_share_issuance",
    "other_net_change",
)
COMMON_CASH_FLOW_FIELDS = (
    "operating_margin",
    "cash_interest",
    "cash_taxes",
    "depreciation_and_amortization",
    "stock_based_compensation",
    "other_non_cash_items",
    "working_capital_investment",
    "capex",
    "restructuring_cash",
    "acquisition_integration_cash",
    "other_cash_adjustments",
)
NONNEGATIVE_CASH_FLOW_FIELDS = {
    "cash_interest",
    "depreciation_and_amortization",
    "stock_based_compensation",
    "capex",
    "restructuring_cash",
    "acquisition_integration_cash",
}
CASH_FLOW_MEASUREMENT_BASES = {
    "operating_margin": (
        "EBIT_MARGIN_BEFORE_SEPARATELY_MODELED_RESTRUCTURING_AND_"
        "INTEGRATION_CASH_ITEMS_INCLUDING_DA_AND_SBC"
    ),
    "cash_interest": "TOTAL_CASH_INTEREST_FOR_FORECAST_PERIOD",
    "cash_taxes": "TOTAL_CASH_TAXES_FOR_FORECAST_PERIOD",
    "depreciation_and_amortization": (
        "NONCASH_DA_INCLUDED_IN_OPERATING_MARGIN"
    ),
    "stock_based_compensation": (
        "NONCASH_SBC_INCLUDED_IN_OPERATING_MARGIN"
    ),
    "other_non_cash_items": (
        "SIGNED_NONCASH_ITEMS_INCLUDED_IN_OPERATING_MARGIN"
    ),
    "working_capital_investment": "NET_CASH_WORKING_CAPITAL_INVESTMENT",
    "capex": "CASH_CAPITAL_EXPENDITURES",
    "restructuring_cash": (
        "CASH_RESTRUCTURING_EXCLUDED_FROM_OPERATING_MARGIN"
    ),
    "acquisition_integration_cash": (
        "CASH_ACQUISITION_INTEGRATION_COSTS_EXCLUDED_FROM_OPERATING_MARGIN"
    ),
    "other_cash_adjustments": (
        "SIGNED_CASH_ITEMS_EXCLUDED_FROM_OPERATING_MARGIN"
    ),
}


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


def _same_number(actual: Any, expected: Any) -> bool:
    actual_number = _number(actual)
    expected_number = _number(expected)
    return (
        actual_number is not None
        and expected_number is not None
        and isclose(actual_number, expected_number, rel_tol=1e-9, abs_tol=1e-9)
    )


def _forecast_period_matches_horizon(
    period: dict[str, Any],
    valuation_as_of_date: Any,
    target_date: Any,
) -> bool:
    if (
        not isinstance(period, dict)
        or period.get("status") != "VALIDATED"
        or period.get("period_type") != "FORECAST"
        or period.get("basis") != "HOLDING_PERIOD_FORECAST"
        or not _iso_date(valuation_as_of_date)
        or not _iso_date(target_date)
        or not _iso_date(period.get("start_date"))
        or not _iso_date(period.get("end_date"))
    ):
        return False
    as_of_day = date.fromisoformat(str(valuation_as_of_date))
    target_day = date.fromisoformat(str(target_date))
    start_day = date.fromisoformat(str(period.get("start_date")))
    end_day = date.fromisoformat(str(period.get("end_date")))
    return (
        start_day in {as_of_day, as_of_day + timedelta(days=1)}
        and end_day == target_day
    )


def _metric_period_matches_target(
    period: dict[str, Any],
    valuation_as_of_date: Any,
    target_date: Any,
) -> bool:
    if (
        not isinstance(period, dict)
        or period.get("status") != "VALIDATED"
        or not _iso_date(valuation_as_of_date)
        or not _iso_date(target_date)
        or not _iso_date(period.get("start_date"))
        or not _iso_date(period.get("end_date"))
    ):
        return False
    as_of_day = date.fromisoformat(str(valuation_as_of_date))
    target_day = date.fromisoformat(str(target_date))
    start_day = date.fromisoformat(str(period.get("start_date")))
    end_day = date.fromisoformat(str(period.get("end_date")))
    if (
        period.get("period_type") == "FORWARD_METRIC"
        and period.get("basis") == "FORWARD_PERIOD_ENDING_AT_TARGET"
    ):
        return as_of_day < start_day <= end_day == target_day
    if (
        period.get("period_type") == "FORWARD_METRIC"
        and period.get("basis") == "FORWARD_PERIOD_STARTING_AT_TARGET"
    ):
        return start_day == target_day < end_day
    return False


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


def _issue(
    code: str,
    message: str,
    path: str,
    *,
    status: str = "FAIL",
    issue_class: str = "WARNING",
) -> dict[str, str]:
    return {
        "code": code,
        "status": status,
        "issue_class": issue_class,
        "message": message,
        "path": path,
        "decision_impact": (
            "The affected forward forecast, per-share output, and formal return remain unavailable."
        ),
        "remediation": "Correct the identified input and rerun the shared S10 engine.",
        "scope": "shared_forward_valuation_engine",
    }


def _known_evidence_ids(parent: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("evidence_id")): row
        for row in parent.get("evidence_records", [])
        if row.get("evidence_id")
    }


def _evidence_binding_matches(
    record: dict[str, Any],
    *,
    value: float,
    evidence_class: str,
    expected_kind: str,
    currency: str,
    unit: str,
) -> bool:
    if (
        str(record.get("evidence_class") or record.get("evidence_type") or "").upper()
        != evidence_class
        or str(record.get("validation_status") or "").upper() != "PASS"
    ):
        return False
    record_value = _number(record.get("value"))
    scale = _number(record.get("scale"))
    canonical_value = (
        record_value * (scale if scale is not None else 1.0)
        if record_value is not None
        else None
    )
    if canonical_value is None or not _same_number(canonical_value, value):
        return False
    if expected_kind == "amount":
        record_unit = str(record.get("unit") or "").upper()
        record_currency = str(record.get("currency") or "").upper()
        if record_unit != unit.upper():
            return False
        if currency.upper() != "SHARES" and record_currency != currency.upper():
            return False
    elif str(record.get("unit") or "").upper() not in {"RATIO", "PURE"}:
        return False
    return any(
        _iso_date(record.get(field))
        for field in (
            "period_start",
            "period_end",
            "as_of_date",
            "publication_date",
        )
    )


def _normalize_assumption(
    value: Any,
    *,
    field_name: str,
    path: str,
    known_ids: dict[str, dict[str, Any]],
    expected_kind: str,
    currency: str,
    unit: str,
    nonnegative: bool = False,
    rate_floor: float | None = None,
    rate_ceiling: float | None = None,
    required_measurement_basis: str | None = None,
    allowed_evidence_classes: set[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    supplied = value if isinstance(value, dict) else {}
    number = _number(supplied.get("value"))
    evidence_class = str(supplied.get("evidence_class") or "MISSING").upper()
    evidence_ids = _unique(supplied.get("evidence_ids"))
    reviewer = str(supplied.get("reviewed_by") or "").strip()
    rationale = str(supplied.get("rationale") or "").strip()
    formula = str(supplied.get("formula") or "").strip()
    measurement_basis = str(
        supplied.get("measurement_basis") or ""
    ).strip().upper()
    supplied_currency = str(supplied.get("currency") or "").upper()
    supplied_unit = str(supplied.get("unit") or "").upper()
    issues: list[dict[str, str]] = []
    if evidence_class not in INPUT_EVIDENCE_CLASSES:
        issues.append(
            _issue(
                "INVALID_EVIDENCE_CLASS",
                f"{field_name} must be FACT, CALC, JUDGMENT, or MISSING.",
                path,
            )
        )
    if (
        allowed_evidence_classes is not None
        and evidence_class not in allowed_evidence_classes
    ):
        issues.append(
            _issue(
                "FORWARD_DRIVER_EVIDENCE_CLASS_NOT_ALLOWED",
                (
                    f"{field_name} must use one of "
                    f"{sorted(allowed_evidence_classes)}."
                ),
                path,
            )
        )
    if number is None:
        issues.append(
            _issue(
                "FORWARD_DRIVER_MISSING",
                f"{field_name} requires a finite numeric value; an unsupported zero must not be inferred.",
                path,
                status="MISSING",
            )
        )
    if evidence_class == "MISSING":
        issues.append(
            _issue(
                "FORWARD_DRIVER_CLASSIFIED_MISSING",
                f"{field_name} is explicitly MISSING.",
                path,
                status="MISSING",
            )
        )
    if evidence_class in {"FACT", "CALC", "JUDGMENT"}:
        if not evidence_ids:
            issues.append(
                _issue(
                    "FORWARD_DRIVER_EVIDENCE_MISSING",
                    f"{field_name} requires at least one linked evidence ID.",
                    path,
                    status="MISSING",
                )
            )
        unknown = sorted(set(evidence_ids) - set(known_ids))
        if unknown:
            issues.append(
                _issue(
                    "FORWARD_DRIVER_EVIDENCE_UNKNOWN",
                    f"{field_name} contains unknown evidence IDs: {unknown}.",
                    path,
                )
            )
        if not reviewer:
            issues.append(
                _issue(
                    "FORWARD_DRIVER_REVIEWER_MISSING",
                    f"{field_name} requires a named reviewer.",
                    path,
                    status="MISSING",
                )
            )
    matching_binding_ids: list[str] = []
    if number is not None and evidence_class in {"FACT", "CALC"}:
        matching_binding_ids = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_id in known_ids
            and _evidence_binding_matches(
                known_ids[evidence_id],
                value=number,
                evidence_class=evidence_class,
                expected_kind=expected_kind,
                currency=currency,
                unit=unit,
            )
        ]
        if not matching_binding_ids:
            issues.append(
                _issue(
                    "FORWARD_DRIVER_EVIDENCE_BINDING_FAILED",
                    (
                        f"{field_name} FACT/CALC value must match a PASS evidence record "
                        "with the same class, dated period, currency, unit, and canonical value."
                    ),
                    path,
                )
            )
    if evidence_class == "JUDGMENT" and not rationale:
        issues.append(
            _issue(
                "FORWARD_DRIVER_RATIONALE_MISSING",
                f"Judgment line {field_name} requires a rationale.",
                path,
                status="MISSING",
            )
        )
    if evidence_class == "CALC" and not formula:
        issues.append(
            _issue(
                "FORWARD_DRIVER_FORMULA_MISSING",
                f"Calculated input {field_name} requires its upstream formula.",
                path,
                status="MISSING",
            )
        )
    if (
        required_measurement_basis
        and measurement_basis != required_measurement_basis
    ):
        issues.append(
            _issue(
                "FORWARD_DRIVER_MEASUREMENT_BASIS_INVALID",
                (
                    f"{field_name} must use controlled measurement basis "
                    f"{required_measurement_basis}."
                ),
                path,
            )
        )
    if expected_kind == "amount":
        if supplied_currency != currency.upper() or supplied_unit != unit.upper():
            issues.append(
                _issue(
                    "FORWARD_DRIVER_UNIT_OR_CURRENCY_MISMATCH",
                    (
                        f"{field_name} must use {currency.upper()} and {unit.upper()}, "
                        f"not {supplied_currency or 'missing'} and {supplied_unit or 'missing'}."
                    ),
                    path,
                )
            )
    elif supplied_unit != "RATIO":
        issues.append(
            _issue(
                "FORWARD_DRIVER_RATE_UNIT_INVALID",
                f"{field_name} must use unit RATIO.",
                path,
            )
        )
    if number is not None and nonnegative and number < 0:
        issues.append(
            _issue(
                "FORWARD_DRIVER_NEGATIVE_NOT_ALLOWED",
                f"{field_name} uses a positive cash-use or issuance convention and cannot be negative.",
                path,
            )
        )
    if number is not None and rate_floor is not None and number <= rate_floor:
        issues.append(
            _issue(
                "FORWARD_DRIVER_RATE_OUT_OF_RANGE",
                f"{field_name} must be greater than {rate_floor:g}.",
                path,
            )
        )
    if number is not None and rate_ceiling is not None and number > rate_ceiling:
        issues.append(
            _issue(
                "FORWARD_DRIVER_RATE_OUT_OF_RANGE",
                f"{field_name} cannot exceed {rate_ceiling:g}.",
                path,
            )
        )
    return (
        {
            "field": field_name,
            "value": number,
            "evidence_class": (
                evidence_class if evidence_class in INPUT_EVIDENCE_CLASSES else "MISSING"
            ),
            "evidence_ids": evidence_ids,
            "matching_evidence_ids": matching_binding_ids,
            "evidence_binding_status": (
                "PASS"
                if evidence_class in {"FACT", "CALC"} and matching_binding_ids
                else "CONTEXTUAL"
                if evidence_class == "JUDGMENT"
                else "FAIL"
            ),
            "reviewed_by": reviewer or None,
            "rationale": rationale or None,
            "formula": formula or None,
            "measurement_basis": measurement_basis or None,
            "currency": currency.upper() if expected_kind == "amount" else None,
            "unit": unit.upper() if expected_kind == "amount" else "RATIO",
            "validation_status": "PASS" if not issues else "FAIL",
        },
        issues,
    )


def _calc_line(
    line_id: str,
    label: str,
    value: float | None,
    *,
    formula: str,
    input_lines: list[dict[str, Any]],
    currency: str,
    unit: str,
    expected_kind: str = "amount",
) -> dict[str, Any]:
    return {
        "line_id": line_id,
        "label": label,
        "value": value,
        "evidence_class": "CALC" if value is not None else "MISSING",
        "evidence_ids": _unique(
            [
                evidence_id
                for line in input_lines
                for evidence_id in _as_list(line.get("evidence_ids"))
            ]
        ),
        "formula": formula,
        "currency": currency if expected_kind == "amount" else None,
        "unit": unit if expected_kind == "amount" else "RATIO",
        "validation_status": "PASS" if value is not None else "FAIL",
    }


def _normalize_revenue_line(
    supplied: Any,
    *,
    field_name: str,
    path: str,
    known_ids: dict[str, dict[str, Any]],
    kind: str,
    currency: str,
    unit: str,
    nonnegative: bool = False,
    allowed_evidence_classes: set[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    return _normalize_assumption(
        supplied,
        field_name=field_name,
        path=path,
        known_ids=known_ids,
        expected_kind=kind,
        currency=currency,
        unit=unit,
        nonnegative=nonnegative,
        rate_floor=-1.0 if kind == "rate" else None,
        allowed_evidence_classes=allowed_evidence_classes,
    )


def _multiplicative_revenue(
    supplied: dict[str, Any],
    *,
    module: str,
    growth_fields: tuple[str, ...],
    known_ids: dict[str, dict[str, Any]],
    currency: str,
    unit: str,
    path: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    allowed = {"base_revenue", *growth_fields}
    issues = [
        _issue(
            "UNSUPPORTED_DRIVER_FIELD",
            f"{module} does not support revenue driver {field}.",
            f"{path}.{field}",
        )
        for field in sorted(set(supplied) - allowed)
    ]
    base, base_issues = _normalize_revenue_line(
        supplied.get("base_revenue"),
        field_name="base_revenue",
        path=f"{path}.base_revenue",
        known_ids=known_ids,
        kind="amount",
        currency=currency,
        unit=unit,
        nonnegative=True,
        allowed_evidence_classes={"FACT", "CALC"},
    )
    issues.extend(base_issues)
    inputs = [base]
    for field in growth_fields:
        line, line_issues = _normalize_revenue_line(
            supplied.get(field),
            field_name=field,
            path=f"{path}.{field}",
            known_ids=known_ids,
            kind="rate",
            currency=currency,
            unit=unit,
        )
        inputs.append(line)
        issues.extend(line_issues)
    value = None
    if not issues and base["value"] is not None:
        value = float(base["value"])
        for line in inputs[1:]:
            value *= 1.0 + float(line["value"])
    if value is not None and value <= 0:
        issues.append(
            _issue(
                "FORWARD_REVENUE_NONPOSITIVE",
                "The module revenue bridge produced non-positive forward revenue.",
                path,
            )
        )
        value = None
    formula = "base_revenue * " + " * ".join(
        f"(1 + {field})" for field in growth_fields
    )
    return (
        {
            "module": module,
            "method": "MULTIPLICATIVE_REVENUE_BRIDGE",
            "input_lines": inputs,
            "forward_revenue": _calc_line(
                "forward_revenue",
                "Forward revenue",
                value,
                formula=formula,
                input_lines=inputs,
                currency=currency,
                unit=unit,
            ),
        },
        issues,
    )


def _industrial_revenue(
    supplied: dict[str, Any],
    *,
    module: str,
    known_ids: dict[str, dict[str, Any]],
    currency: str,
    unit: str,
    path: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    allowed = {
        "base_revenue",
        "volume_growth",
        "price_mix_growth",
        "acquisition_revenue",
        "divestiture_revenue",
    }
    issues = [
        _issue(
            "UNSUPPORTED_DRIVER_FIELD",
            f"{module} does not support revenue driver {field}.",
            f"{path}.{field}",
        )
        for field in sorted(set(supplied) - allowed)
    ]
    inputs: list[dict[str, Any]] = []
    specs = (
        ("base_revenue", "amount", True),
        ("volume_growth", "rate", False),
        ("price_mix_growth", "rate", False),
        ("acquisition_revenue", "amount", True),
        ("divestiture_revenue", "amount", True),
    )
    for field, kind, nonnegative in specs:
        line, line_issues = _normalize_revenue_line(
            supplied.get(field),
            field_name=field,
            path=f"{path}.{field}",
            known_ids=known_ids,
            kind=kind,
            currency=currency,
            unit=unit,
            nonnegative=nonnegative,
            allowed_evidence_classes=(
                {"FACT", "CALC"} if field == "base_revenue" else None
            ),
        )
        inputs.append(line)
        issues.extend(line_issues)
    value = None
    if not issues:
        values = {line["field"]: float(line["value"]) for line in inputs}
        value = (
            values["base_revenue"]
            * (1.0 + values["volume_growth"] + values["price_mix_growth"])
            + values["acquisition_revenue"]
            - values["divestiture_revenue"]
        )
    if value is not None and value <= 0:
        issues.append(
            _issue(
                "FORWARD_REVENUE_NONPOSITIVE",
                "The industrial revenue bridge produced non-positive forward revenue.",
                path,
            )
        )
        value = None
    return (
        {
            "module": module,
            "method": "VOLUME_PRICE_AND_PORTFOLIO_REVENUE_BRIDGE",
            "input_lines": inputs,
            "forward_revenue": _calc_line(
                "forward_revenue",
                "Forward revenue",
                value,
                formula=(
                    "base_revenue * (1 + volume_growth + price_mix_growth) "
                    "+ acquisition_revenue - divestiture_revenue"
                ),
                input_lines=inputs,
                currency=currency,
                unit=unit,
            ),
        },
        issues,
    )


def _acquisition_revenue(
    supplied: dict[str, Any],
    *,
    module: str,
    known_ids: dict[str, dict[str, Any]],
    currency: str,
    unit: str,
    path: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    allowed = {
        "base_revenue",
        "organic_growth",
        "acquired_revenue",
        "divested_revenue",
    }
    issues = [
        _issue(
            "UNSUPPORTED_DRIVER_FIELD",
            f"{module} does not support revenue driver {field}.",
            f"{path}.{field}",
        )
        for field in sorted(set(supplied) - allowed)
    ]
    inputs: list[dict[str, Any]] = []
    specs = (
        ("base_revenue", "amount", True),
        ("organic_growth", "rate", False),
        ("acquired_revenue", "amount", True),
        ("divested_revenue", "amount", True),
    )
    for field, kind, nonnegative in specs:
        line, line_issues = _normalize_revenue_line(
            supplied.get(field),
            field_name=field,
            path=f"{path}.{field}",
            known_ids=known_ids,
            kind=kind,
            currency=currency,
            unit=unit,
            nonnegative=nonnegative,
            allowed_evidence_classes=(
                {"FACT", "CALC"} if field == "base_revenue" else None
            ),
        )
        inputs.append(line)
        issues.extend(line_issues)
    value = None
    if not issues:
        values = {line["field"]: float(line["value"]) for line in inputs}
        value = (
            values["base_revenue"] * (1.0 + values["organic_growth"])
            + values["acquired_revenue"]
            - values["divested_revenue"]
        )
    if value is not None and value <= 0:
        issues.append(
            _issue(
                "FORWARD_REVENUE_NONPOSITIVE",
                "The acquisition-heavy revenue bridge produced non-positive forward revenue.",
                path,
            )
        )
        value = None
    return (
        {
            "module": module,
            "method": "ORGANIC_AND_ACQUIRED_REVENUE_BRIDGE",
            "input_lines": inputs,
            "forward_revenue": _calc_line(
                "forward_revenue",
                "Forward revenue",
                value,
                formula=(
                    "base_revenue * (1 + organic_growth) "
                    "+ acquired_revenue - divested_revenue"
                ),
                input_lines=inputs,
                currency=currency,
                unit=unit,
            ),
        },
        issues,
    )


def _segment_revenue(
    supplied: dict[str, Any],
    *,
    module: str,
    segment_field: str,
    minimum_segments: int,
    known_ids: dict[str, dict[str, Any]],
    currency: str,
    unit: str,
    path: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    if set(supplied) - {segment_field}:
        for field in sorted(set(supplied) - {segment_field}):
            issues.append(
                _issue(
                    "UNSUPPORTED_DRIVER_FIELD",
                    f"{module} does not support revenue driver {field}.",
                    f"{path}.{field}",
                )
            )
    rows = supplied.get(segment_field, [])
    if not isinstance(rows, list) or len(rows) < minimum_segments:
        issues.append(
            _issue(
                "REVENUE_COMPONENTS_INCOMPLETE",
                f"{module} requires at least {minimum_segments} named revenue component(s).",
                f"{path}.{segment_field}",
                status="MISSING",
            )
        )
        rows = []
    components: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, row_value in enumerate(rows):
        row = row_value if isinstance(row_value, dict) else {}
        row_path = f"{path}.{segment_field}[{index}]"
        name = str(row.get("name") or "").strip()
        if not name or name in names:
            issues.append(
                _issue(
                    "REVENUE_COMPONENT_NAME_INVALID",
                    "Revenue component names must be non-empty and unique.",
                    f"{row_path}.name",
                )
            )
        names.add(name)
        base, base_issues = _normalize_revenue_line(
            row.get("base_revenue"),
            field_name=f"{name or index}_base_revenue",
            path=f"{row_path}.base_revenue",
            known_ids=known_ids,
            kind="amount",
            currency=currency,
            unit=unit,
            nonnegative=True,
            allowed_evidence_classes={"FACT", "CALC"},
        )
        growth, growth_issues = _normalize_revenue_line(
            row.get("revenue_growth"),
            field_name=f"{name or index}_revenue_growth",
            path=f"{row_path}.revenue_growth",
            known_ids=known_ids,
            kind="rate",
            currency=currency,
            unit=unit,
        )
        issues.extend(base_issues + growth_issues)
        component_value = (
            float(base["value"]) * (1.0 + float(growth["value"]))
            if not base_issues and not growth_issues
            else None
        )
        components.append(
            {
                "name": name or None,
                "base_revenue": base,
                "revenue_growth": growth,
                "forward_revenue": _calc_line(
                    f"{name or index}_forward_revenue",
                    f"{name or index} forward revenue",
                    component_value,
                    formula="base_revenue * (1 + revenue_growth)",
                    input_lines=[base, growth],
                    currency=currency,
                    unit=unit,
                ),
            }
        )
    value = (
        sum(float(row["forward_revenue"]["value"]) for row in components)
        if components
        and not issues
        and all(row["forward_revenue"]["value"] is not None for row in components)
        else None
    )
    component_inputs = [
        line
        for component in components
        for line in (component["base_revenue"], component["revenue_growth"])
    ]
    return (
        {
            "module": module,
            "method": "COMPONENT_REVENUE_BRIDGE",
            "component_field": segment_field,
            "components": components,
            "input_lines": component_inputs,
            "forward_revenue": _calc_line(
                "forward_revenue",
                "Forward revenue",
                value,
                formula="sum(component base_revenue * (1 + component revenue_growth))",
                input_lines=component_inputs,
                currency=currency,
                unit=unit,
            ),
        },
        issues,
    )


RevenueBuilder = Callable[..., tuple[dict[str, Any], list[dict[str, str]]]]


def _retail_builder(supplied: dict[str, Any], **kwargs: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    return _multiplicative_revenue(
        supplied,
        growth_fields=(
            "comparable_sales_growth",
            "net_store_growth",
            "other_revenue_growth",
        ),
        **kwargs,
    )


def _distribution_builder(supplied: dict[str, Any], **kwargs: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    return _multiplicative_revenue(
        supplied,
        growth_fields=("volume_growth", "price_mix_growth"),
        **kwargs,
    )


def _consumer_brand_builder(supplied: dict[str, Any], **kwargs: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    return _segment_revenue(
        supplied,
        segment_field="brand_segments",
        minimum_segments=1,
        **kwargs,
    )


def _subscription_software_builder(
    supplied: dict[str, Any],
    **kwargs: Any,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    return _segment_revenue(
        supplied,
        segment_field="revenue_streams",
        minimum_segments=2,
        **kwargs,
    )


DRIVER_MODULE_REGISTRY: dict[str, dict[str, Any]] = {
    "RETAIL": {
        "description": "Comparable sales, unit footprint, and other revenue growth.",
        "revenue_builder": _retail_builder,
        "required_revenue_fields": [
            "base_revenue",
            "comparable_sales_growth",
            "net_store_growth",
            "other_revenue_growth",
        ],
    },
    "CONSUMER_BRAND": {
        "description": "Brand or segment revenue bases and scenario growth.",
        "revenue_builder": _consumer_brand_builder,
        "required_revenue_fields": ["brand_segments"],
    },
    "SUBSCRIPTION_SOFTWARE": {
        "description": "Subscription and non-subscription revenue-stream bridge.",
        "revenue_builder": _subscription_software_builder,
        "required_revenue_fields": ["revenue_streams"],
    },
    "INDUSTRIAL": {
        "description": "Volume, price/mix, acquisition, and divestiture revenue bridge.",
        "revenue_builder": _industrial_revenue,
        "required_revenue_fields": [
            "base_revenue",
            "volume_growth",
            "price_mix_growth",
            "acquisition_revenue",
            "divestiture_revenue",
        ],
    },
    "ACQUISITION_HEAVY": {
        "description": "Organic, acquired, and divested revenue bridge.",
        "revenue_builder": _acquisition_revenue,
        "required_revenue_fields": [
            "base_revenue",
            "organic_growth",
            "acquired_revenue",
            "divested_revenue",
        ],
    },
    "DISTRIBUTION": {
        "description": "Volume and price/mix bridge for low-margin distribution.",
        "revenue_builder": _distribution_builder,
        "required_revenue_fields": [
            "base_revenue",
            "volume_growth",
            "price_mix_growth",
        ],
    },
}


def driver_module_catalog() -> dict[str, Any]:
    return {
        "registry_version": DRIVER_MODULE_REGISTRY_VERSION,
        "modules": {
            name: {
                key: deepcopy(value)
                for key, value in specification.items()
                if key != "revenue_builder"
            }
            for name, specification in DRIVER_MODULE_REGISTRY.items()
        },
    }


def _build_cash_flow_bridge(
    supplied: Any,
    *,
    forward_revenue: dict[str, Any],
    known_ids: dict[str, dict[str, Any]],
    currency: str,
    unit: str,
    path: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    inputs = supplied if isinstance(supplied, dict) else {}
    issues = [
        _issue(
            "UNSUPPORTED_CASH_FLOW_FIELD",
            (
                f"Unsupported cash-flow driver {field}; CFO or another embedded subtotal "
                "must not be mixed into the operating bridge."
            ),
            f"{path}.{field}",
        )
        for field in sorted(set(inputs) - set(COMMON_CASH_FLOW_FIELDS))
    ]
    lines: dict[str, dict[str, Any]] = {}
    for field in COMMON_CASH_FLOW_FIELDS:
        expected_kind = "rate" if field == "operating_margin" else "amount"
        line, line_issues = _normalize_assumption(
            inputs.get(field),
            field_name=field,
            path=f"{path}.{field}",
            known_ids=known_ids,
            expected_kind=expected_kind,
            currency=currency,
            unit=unit,
            nonnegative=field in NONNEGATIVE_CASH_FLOW_FIELDS,
            rate_ceiling=1.0 if field == "operating_margin" else None,
            required_measurement_basis=CASH_FLOW_MEASUREMENT_BASES[field],
        )
        lines[field] = line
        issues.extend(line_issues)
    revenue_value = _number(forward_revenue.get("value"))
    calculated: list[dict[str, Any]] = []
    operating_income_value = (
        revenue_value * float(lines["operating_margin"]["value"])
        if revenue_value is not None
        and lines["operating_margin"]["value"] is not None
        and not issues
        else None
    )
    operating_income = _calc_line(
        "operating_income",
        "Operating income",
        operating_income_value,
        formula="forward_revenue * operating_margin",
        input_lines=[forward_revenue, lines["operating_margin"]],
        currency=currency,
        unit=unit,
    )
    calculated.append(operating_income)
    post_interest_tax_value = (
        operating_income_value
        - float(lines["cash_interest"]["value"])
        - float(lines["cash_taxes"]["value"])
        if operating_income_value is not None and not issues
        else None
    )
    post_interest_tax = _calc_line(
        "cash_earnings_after_interest_and_tax",
        "Cash earnings after interest and tax",
        post_interest_tax_value,
        formula="operating_income - cash_interest - cash_taxes",
        input_lines=[
            operating_income,
            lines["cash_interest"],
            lines["cash_taxes"],
        ],
        currency=currency,
        unit=unit,
    )
    calculated.append(post_interest_tax)
    forward_fcf_value = None
    if post_interest_tax_value is not None and not issues:
        forward_fcf_value = (
            post_interest_tax_value
            + float(lines["depreciation_and_amortization"]["value"])
            + float(lines["stock_based_compensation"]["value"])
            + float(lines["other_non_cash_items"]["value"])
            - float(lines["working_capital_investment"]["value"])
            - float(lines["capex"]["value"])
            - float(lines["restructuring_cash"]["value"])
            - float(lines["acquisition_integration_cash"]["value"])
            + float(lines["other_cash_adjustments"]["value"])
        )
    forward_fcf = _calc_line(
        "forward_fcf",
        "Forward FCF",
        forward_fcf_value,
        formula=FORWARD_FCF_FORMULA,
        input_lines=[forward_revenue, *lines.values()],
        currency=currency,
        unit=unit,
    )
    calculated.append(forward_fcf)
    return (
        {
            "basis": FORWARD_FCF_BASIS,
            "sign_convention": {
                "cash_interest": "positive use",
                "cash_taxes": "positive use; negative amount represents a refund",
                "working_capital_investment": "positive use; negative amount represents a release",
                "capex": "positive use",
                "restructuring_cash": "positive use",
                "acquisition_integration_cash": "positive use",
                "other_cash_adjustments": "positive source; negative use",
            },
            "input_lines": list(lines.values()),
            "calculated_lines": calculated,
            "forward_fcf": forward_fcf,
            "embedded_cfo_used": False,
            "double_counting_status": "PASS" if not issues else "NOT_EVALUATED",
        },
        issues,
    )


def _share_change_line(
    supplied: Any,
    *,
    field_name: str,
    path: str,
    known_ids: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    return _normalize_assumption(
        supplied,
        field_name=field_name,
        path=path,
        known_ids=known_ids,
        expected_kind="amount",
        currency="SHARES",
        unit="SHARES",
        nonnegative=field_name != "other_net_change",
    )


def _matching_share_evidence_ids(
    parent: dict[str, Any],
    value: float | None,
    as_of_date: str,
) -> list[str]:
    return _unique(
        [
            row.get("evidence_id")
            for row in parent.get("evidence_records", [])
            if row.get("metric_name") == "shares_outstanding_point_in_time"
            and _same_number(row.get("value"), value)
            and str(row.get("as_of_date") or row.get("period_end") or "") == as_of_date
        ]
    )


def _build_forward_share_bridge(
    parent: dict[str, Any],
    supplied: Any,
    *,
    target_date: Any,
    known_ids: dict[str, dict[str, Any]],
    path: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    value = supplied if isinstance(supplied, dict) else {}
    issues: list[dict[str, str]] = []
    requested_status = str(value.get("status") or "NOT_DEFINED").upper()
    reviewer = str(value.get("reviewed_by") or "").strip()
    bridge_target = str(value.get("target_date") or target_date or "")
    event_status = str(value.get("known_subsequent_event_status") or "NOT_REVIEWED").upper()
    event_note = str(value.get("known_subsequent_event_note") or "").strip()
    valuation = parent.get("valuation", {})
    base_value = _number(valuation.get("shares"))
    base_date = str(valuation.get("shares_as_of_date") or "")
    base_ids = _matching_share_evidence_ids(parent, base_value, base_date)
    if requested_status != "ANALYST_VALIDATED":
        issues.append(
            _issue(
                "FORWARD_SHARE_BRIDGE_NOT_REVIEWED",
                "Forward share-count bridge must be submitted as ANALYST_VALIDATED.",
                path,
                status="MISSING",
            )
        )
    if not reviewer:
        issues.append(
            _issue(
                "FORWARD_SHARE_BRIDGE_REVIEWER_MISSING",
                "Forward share-count bridge requires a named reviewer.",
                path,
                status="MISSING",
            )
        )
    if base_value is None or base_value <= 0 or not _iso_date(base_date):
        issues.append(
            _issue(
                "FORWARD_SHARE_BASE_INVALID",
                "Authoritative point-in-time shares and date are required.",
                path,
            )
        )
    if not base_ids:
        issues.append(
            _issue(
                "FORWARD_SHARE_BASE_EVIDENCE_MISSING",
                "The authoritative point-in-time share value must resolve to a stable evidence ID.",
                path,
                status="MISSING",
            )
        )
    if not _iso_date(bridge_target) or bridge_target != target_date:
        issues.append(
            _issue(
                "FORWARD_SHARE_TARGET_DATE_MISMATCH",
                "Forward share-count target date must equal the shared valuation target date.",
                f"{path}.target_date",
            )
        )
    if event_status not in KNOWN_SHARE_EVENT_STATUSES or not event_note:
        issues.append(
            _issue(
                "FORWARD_SHARE_SUBSEQUENT_EVENTS_NOT_REVIEWED",
                "Known share-count subsequent events must be reviewed and documented.",
                path,
                status="MISSING",
            )
        )
    changes = value.get("changes", {})
    changes = changes if isinstance(changes, dict) else {}
    for field in sorted(set(changes) - set(SHARE_CHANGE_FIELDS)):
        issues.append(
            _issue(
                "UNSUPPORTED_SHARE_CHANGE_FIELD",
                f"Unsupported forward share-count line {field}.",
                f"{path}.changes.{field}",
            )
        )
    lines: dict[str, dict[str, Any]] = {}
    for field in SHARE_CHANGE_FIELDS:
        line, line_issues = _share_change_line(
            changes.get(field),
            field_name=field,
            path=f"{path}.changes.{field}",
            known_ids=known_ids,
        )
        lines[field] = line
        issues.extend(line_issues)
    forward_value = None
    if base_value is not None and not issues:
        forward_value = (
            base_value
            - float(lines["repurchases"]["value"])
            + float(lines["stock_based_compensation_issuance"]["value"])
            + float(lines["employee_plan_issuance"]["value"])
            + float(lines["convertible_dilution"]["value"])
            + float(lines["acquisition_share_issuance"]["value"])
            + float(lines["other_net_change"]["value"])
        )
        if forward_value <= 0:
            issues.append(
                _issue(
                    "FORWARD_SHARE_COUNT_NONPOSITIVE",
                    "The forward share-count bridge produced a non-positive denominator.",
                    path,
                )
            )
            forward_value = None
    all_inputs = [
        {
            "field": "latest_reported_shares",
            "value": base_value,
            "evidence_class": "FACT",
            "evidence_ids": base_ids,
            "currency": None,
            "unit": "SHARES",
            "validation_status": "PASS" if base_ids else "FAIL",
        },
        *lines.values(),
    ]
    return (
        {
            "status": "VALIDATED" if not issues else "NOT_COMPLETED",
            "base_share_count": base_value,
            "base_share_count_date": base_date or None,
            "target_date": bridge_target or None,
            "forward_diluted_shares": forward_value,
            "formula": FORWARD_SHARE_FORMULA,
            "input_lines": all_inputs,
            "change_lines": list(lines.values()),
            "evidence_ids": _unique(
                [
                    evidence_id
                    for line in all_inputs
                    for evidence_id in _as_list(line.get("evidence_ids"))
                ]
            ),
            "known_subsequent_event_status": event_status,
            "known_subsequent_event_note": event_note or None,
            "reviewed_by": reviewer or None,
            "source": (
                f"S10 shared forward share-count bridge v{FORWARD_VALUATION_CONTRACT_VERSION}"
                if not issues
                else None
            ),
            "validation_issues": issues,
        },
        issues,
    )


def _module_not_available(
    module: str | None,
    message: str,
    *,
    forecast_period: dict[str, Any],
    metric_period: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": FORWARD_VALUATION_CONTRACT_VERSION,
        "registry_version": DRIVER_MODULE_REGISTRY_VERSION,
        "status": "DRIVER_MODEL_NOT_AVAILABLE",
        "driver_model_status": "DRIVER_MODEL_NOT_AVAILABLE",
        "driver_module": module,
        "module_selection": {
            "status": "NOT_VALIDATED",
            "rationale": None,
            "evidence_ids": [],
            "reviewed_by": None,
        },
        "forecast_period": forecast_period,
        "metric_period": metric_period,
        "currency": None,
        "unit": None,
        "amount_scale": 1.0,
        "fcf_basis": FORWARD_FCF_BASIS,
        "scenarios": [],
        "forward_share_count_bridge": {
            "status": "NOT_COMPLETED",
            "forward_diluted_shares": None,
        },
        "scenario_metric_eligibility": {
            "status": "NOT_EVALUATED",
            "positive_fcf_multiple_allowed": False,
        },
        "validation_issues": [
            _issue(
                "DRIVER_MODEL_NOT_AVAILABLE",
                message,
                "forward_valuation.driver_module",
                status="MISSING",
                issue_class="INFO",
            )
        ],
        "warnings": [],
        "reviewed_by": None,
    }


def build_forward_valuation_contract(
    parent: dict[str, Any],
    research_input: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the shared S10 forward FCF and forward-share contract."""

    research_input = research_input if isinstance(research_input, dict) else {}
    supplied = research_input.get("forward_valuation", {})
    supplied = supplied if isinstance(supplied, dict) else {}
    valuation_input = research_input.get("valuation_contract", {})
    valuation_input = valuation_input if isinstance(valuation_input, dict) else {}
    forecast_period = normalize_valuation_period(valuation_input.get("forecast_period"))
    metric_period = normalize_valuation_period(valuation_input.get("metric_period"))
    module = str(supplied.get("driver_module") or "").strip().upper() or None
    if module not in DRIVER_MODULE_REGISTRY:
        message = (
            "No business-model driver module was selected."
            if not module
            else f"No controlled S10 driver module exists for {module}."
        )
        return _module_not_available(
            module,
            message,
            forecast_period=forecast_period,
            metric_period=metric_period,
        )

    known_ids = _known_evidence_ids(parent)
    issues: list[dict[str, str]] = []
    reviewer = str(supplied.get("reviewed_by") or "").strip()
    currency = str(supplied.get("currency") or "").upper()
    unit = str(supplied.get("unit") or "").upper()
    amount_scale = _number(supplied.get("amount_scale"))
    parent_price_currency = str(
        parent.get("valuation", {}).get("price_currency") or ""
    ).upper()
    fcf_basis = str(supplied.get("fcf_basis") or "").upper()
    requested_status = str(supplied.get("status") or "NOT_DEFINED").upper()
    selection = supplied.get("module_selection", {})
    selection = selection if isinstance(selection, dict) else {}
    selection_ids = _unique(selection.get("evidence_ids"))
    selection_reviewer = str(selection.get("reviewed_by") or "").strip()
    selection_rationale = str(selection.get("rationale") or "").strip()
    if requested_status != "ANALYST_VALIDATED":
        issues.append(
            _issue(
                "FORWARD_MODEL_NOT_REVIEWED",
                "Forward model must be submitted as ANALYST_VALIDATED.",
                "forward_valuation.status",
                status="MISSING",
            )
        )
    if not reviewer:
        issues.append(
            _issue(
                "FORWARD_MODEL_REVIEWER_MISSING",
                "Forward model requires a named reviewer.",
                "forward_valuation.reviewed_by",
                status="MISSING",
            )
        )
    if not currency or not unit:
        issues.append(
            _issue(
                "FORWARD_MODEL_UNIT_OR_CURRENCY_MISSING",
                "Forward model requires explicit currency and unit.",
                "forward_valuation",
                status="MISSING",
            )
        )
    elif unit != currency:
        issues.append(
            _issue(
                "FORWARD_MODEL_UNIT_SCALE_UNSUPPORTED",
                (
                    "S10 monetary inputs must use unscaled atomic currency units "
                    "(for example USD, not USD_MILLIONS)."
                ),
                "forward_valuation.unit",
            )
        )
    if amount_scale not in (None, 1.0):
        issues.append(
            _issue(
                "FORWARD_MODEL_AMOUNT_SCALE_UNSUPPORTED",
                "S10 amount_scale must be 1.0; scaled analyst inputs are not accepted.",
                "forward_valuation.amount_scale",
            )
        )
    if not parent_price_currency or currency != parent_price_currency:
        issues.append(
            _issue(
                "FORWARD_MODEL_PRICE_CURRENCY_MISMATCH",
                "S10 currency must equal the authoritative market-price currency.",
                "forward_valuation.currency",
            )
        )
    if fcf_basis != FORWARD_FCF_BASIS:
        issues.append(
            _issue(
                "FORWARD_FCF_BASIS_UNSUPPORTED",
                f"S10 supports only {FORWARD_FCF_BASIS}.",
                "forward_valuation.fcf_basis",
            )
        )
    if (
        selection.get("status") != "ANALYST_VALIDATED"
        or not selection_reviewer
        or not selection_rationale
        or not selection_ids
    ):
        issues.append(
            _issue(
                "DRIVER_MODULE_SELECTION_NOT_VALIDATED",
                "Module selection requires rationale, linked evidence, and a named reviewer.",
                "forward_valuation.module_selection",
                status="MISSING",
            )
        )
    unknown_selection_ids = sorted(set(selection_ids) - set(known_ids))
    if unknown_selection_ids:
        issues.append(
            _issue(
                "DRIVER_MODULE_SELECTION_EVIDENCE_UNKNOWN",
                f"Module selection contains unknown evidence IDs: {unknown_selection_ids}.",
                "forward_valuation.module_selection.evidence_ids",
            )
        )
    if forecast_period.get("status") != "VALIDATED":
        issues.append(
            _issue(
                "FORWARD_FORECAST_PERIOD_NOT_VALIDATED",
                "S10 requires the validated S09 forecast period.",
                "valuation_contract.forecast_period",
                status="MISSING",
            )
        )
    elif not _forecast_period_matches_horizon(
        forecast_period,
        valuation_input.get("valuation_as_of_date"),
        valuation_input.get("target_date"),
    ):
        issues.append(
            _issue(
                "FORWARD_FORECAST_PERIOD_HORIZON_MISMATCH",
                "S10 forecast period must reproduce the dated S09 valuation horizon.",
                "valuation_contract.forecast_period",
            )
        )
    if metric_period.get("status") != "VALIDATED":
        issues.append(
            _issue(
                "FORWARD_METRIC_PERIOD_NOT_VALIDATED",
                "S10 requires the validated S09 forward metric period.",
                "valuation_contract.metric_period",
                status="MISSING",
            )
        )
    elif not _metric_period_matches_target(
        metric_period,
        valuation_input.get("valuation_as_of_date"),
        valuation_input.get("target_date"),
    ):
        issues.append(
            _issue(
                "FORWARD_METRIC_PERIOD_TARGET_MISMATCH",
                "S10 metric period must have an allowed relationship to the S09 target date.",
                "valuation_contract.metric_period",
            )
        )
    parent_price_date = (
        parent.get("valuation", {}).get("price_date")
        or parent.get("report_dates", {}).get("market_price_date")
    )
    if (
        not _iso_date(valuation_input.get("valuation_as_of_date"))
        or valuation_input.get("valuation_as_of_date") != parent_price_date
    ):
        issues.append(
            _issue(
                "FORWARD_VALUATION_AS_OF_DATE_MISMATCH",
                "S10 valuation as-of date must equal the authoritative market-price date.",
                "valuation_contract.valuation_as_of_date",
            )
        )
    assumptions = supplied.get("scenarios", [])
    if (
        not isinstance(assumptions, list)
        or len(assumptions) != 3
        or {str(row.get("name") or "") for row in assumptions if isinstance(row, dict)}
        != SCENARIO_NAMES
    ):
        issues.append(
            _issue(
                "FORWARD_SCENARIOS_INCOMPLETE",
                "S10 requires exactly Bear, Base, and Bull operating scenarios.",
                "forward_valuation.scenarios",
                status="MISSING",
            )
        )
        assumptions = []
    scenario_outputs: list[dict[str, Any]] = []
    builder: RevenueBuilder = DRIVER_MODULE_REGISTRY[module]["revenue_builder"]
    for row_value in assumptions:
        row = row_value if isinstance(row_value, dict) else {}
        name = str(row.get("name") or "")
        scenario_path = f"forward_valuation.scenarios.{name}"
        scenario_reviewer = str(row.get("reviewed_by") or "").strip()
        rationale = str(row.get("scenario_rationale") or "").strip()
        scenario_issues: list[dict[str, str]] = []
        if not scenario_reviewer or not rationale:
            scenario_issues.append(
                _issue(
                    "FORWARD_SCENARIO_GOVERNANCE_INCOMPLETE",
                    f"{name} requires a scenario rationale and named reviewer.",
                    scenario_path,
                    status="MISSING",
                )
            )
        revenue_bridge, revenue_issues = builder(
            row.get("revenue_driver", {})
            if isinstance(row.get("revenue_driver"), dict)
            else {},
            module=module,
            known_ids=known_ids,
            currency=currency,
            unit=unit,
            path=f"{scenario_path}.revenue_driver",
        )
        cash_flow_bridge, cash_flow_issues = _build_cash_flow_bridge(
            row.get("cash_flow_driver"),
            forward_revenue=revenue_bridge["forward_revenue"],
            known_ids=known_ids,
            currency=currency,
            unit=unit,
            path=f"{scenario_path}.cash_flow_driver",
        )
        scenario_issues.extend(revenue_issues + cash_flow_issues)
        fcf_value = cash_flow_bridge["forward_fcf"].get("value")
        scenario_outputs.append(
            {
                "name": name,
                "status": "VALIDATED" if not scenario_issues else "INVALID",
                "scenario_rationale": rationale or None,
                "driver_module": module,
                "revenue_bridge": revenue_bridge,
                "cash_flow_bridge": cash_flow_bridge,
                "forward_fcf": fcf_value,
                "metric": "Forward FCF",
                "metric_period": deepcopy(metric_period),
                "forecast_period": deepcopy(forecast_period),
                "currency": currency or None,
                "unit": unit or None,
                "evidence_ids": _unique(
                    _as_list(
                        revenue_bridge["forward_revenue"].get("evidence_ids")
                    )
                    + _as_list(
                        cash_flow_bridge["forward_fcf"].get("evidence_ids")
                    )
                ),
                "reviewed_by": scenario_reviewer or None,
                "validation_issues": scenario_issues,
            }
        )
        issues.extend(scenario_issues)

    target_date = valuation_input.get("target_date")
    share_bridge, share_issues = _build_forward_share_bridge(
        parent,
        supplied.get("share_count_bridge"),
        target_date=target_date,
        known_ids=known_ids,
        path="forward_valuation.share_count_bridge",
    )
    issues.extend(share_issues)

    manual_share = research_input.get("share_count_basis", {})
    manual_share = manual_share if isinstance(manual_share, dict) else {}
    if (
        share_bridge.get("status") == "VALIDATED"
        and manual_share.get("forward_share_count_bridge_status") == "COMPLETED"
    ):
        if (
            not _same_number(
                manual_share.get("forward_share_count_value"),
                share_bridge.get("forward_diluted_shares"),
            )
            or manual_share.get("forward_share_count_date")
            != share_bridge.get("target_date")
        ):
            conflict = _issue(
                "FORWARD_SHARE_INPUT_CONFLICT",
                "Manual and S10-generated forward share-count values conflict.",
                "share_count_basis",
            )
            issues.append(conflict)
            share_bridge["status"] = "NOT_COMPLETED"
            share_bridge.setdefault("validation_issues", []).append(conflict)

    operating_issues = [
        row
        for row in issues
        if not str(row.get("path") or "").startswith(
            "forward_valuation.share_count_bridge"
        )
        and row.get("code") != "FORWARD_SHARE_INPUT_CONFLICT"
    ]
    operating_valid = (
        bool(scenario_outputs)
        and all(row.get("status") == "VALIDATED" for row in scenario_outputs)
        and not operating_issues
    )
    share_valid = share_bridge.get("status") == "VALIDATED"
    if operating_valid and share_valid:
        status = "VALIDATED"
    elif operating_valid:
        status = "PARTIALLY_VALIDATED"
    else:
        status = "INVALID"
    fcf_values = [_number(row.get("forward_fcf")) for row in scenario_outputs]
    positive_multiple_allowed = (
        status == "VALIDATED"
        and len(fcf_values) == 3
        and all(value is not None and value > 0 for value in fcf_values)
    )
    return {
        "contract_version": FORWARD_VALUATION_CONTRACT_VERSION,
        "registry_version": DRIVER_MODULE_REGISTRY_VERSION,
        "status": status,
        "driver_model_status": (
            "VALIDATED" if operating_valid else "INVALID"
        ),
        "driver_module": module,
        "module_selection": {
            "status": (
                "VALIDATED"
                if selection.get("status") == "ANALYST_VALIDATED"
                and selection_reviewer
                and selection_rationale
                and selection_ids
                and not unknown_selection_ids
                else "NOT_VALIDATED"
            ),
            "rationale": selection_rationale or None,
            "evidence_ids": selection_ids,
            "reviewed_by": selection_reviewer or None,
        },
        "forecast_period": forecast_period,
        "metric_period": metric_period,
        "currency": currency or None,
        "unit": unit or None,
        "amount_scale": 1.0,
        "fcf_basis": fcf_basis or None,
        "scenarios": scenario_outputs,
        "forward_share_count_bridge": share_bridge,
        "scenario_metric_eligibility": {
            "status": (
                "ELIGIBLE_FOR_POSITIVE_FCF_MULTIPLE"
                if positive_multiple_allowed
                else "NOT_ELIGIBLE_FOR_POSITIVE_FCF_MULTIPLE"
            ),
            "positive_fcf_multiple_allowed": positive_multiple_allowed,
            "reason": (
                None
                if positive_multiple_allowed
                else (
                    "Every scenario must have positive calculated forward FCF and a validated "
                    "target-date share bridge before an FCF multiple can be applied."
                )
            ),
        },
        "validation_issues": issues,
        "warnings": [
            row for row in issues if row.get("issue_class") == "WARNING"
        ],
        "reviewed_by": reviewer or None,
    }


def forward_share_basis_input(
    forward_contract: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Project a validated S10 share bridge into the existing S09 input surface."""

    contract = forward_contract if isinstance(forward_contract, dict) else {}
    bridge = contract.get("forward_share_count_bridge", {})
    if contract.get("status") != "VALIDATED" or bridge.get("status") != "VALIDATED":
        return None
    return {
        "share_count_type": "FORWARD_DILUTED_SHARES",
        "share_count_source": bridge.get("source"),
        "forward_share_count_bridge_status": "COMPLETED",
        "forward_share_count_value": bridge.get("forward_diluted_shares"),
        "forward_share_count_date": bridge.get("target_date"),
        "forward_share_count_source": bridge.get("source"),
        "forward_share_count_source_detail": {
            "contract_version": contract.get("contract_version"),
            "driver_module": contract.get("driver_module"),
        },
        "forward_share_count_evidence_ids": _unique(bridge.get("evidence_ids")),
        "known_subsequent_event_status": bridge.get(
            "known_subsequent_event_status"
        ),
        "known_subsequent_event_note": bridge.get(
            "known_subsequent_event_note"
        ),
        "reviewed_by": bridge.get("reviewed_by"),
        "limitations": [],
    }


def _persisted_input_line_errors(
    line: Any,
    *,
    label: str,
    evidence_index: dict[str, dict[str, Any]],
    expected_kind: str,
    currency: str,
    unit: str,
    require_pass: bool,
    required_measurement_basis: str | None = None,
    allowed_evidence_classes: set[str] | None = None,
) -> list[str]:
    if not isinstance(line, dict):
        return [f"{label} must be an object."]
    errors: list[str] = []
    validation_status = str(line.get("validation_status") or "").upper()
    if require_pass and validation_status != "PASS":
        errors.append(f"{label} must have PASS validation status.")
    if validation_status != "PASS":
        return errors
    value = _number(line.get("value"))
    evidence_class = str(line.get("evidence_class") or "").upper()
    evidence_ids = _unique(line.get("evidence_ids"))
    if value is None:
        errors.append(f"{label} PASS line lacks a finite value.")
    if evidence_class not in {"FACT", "CALC", "JUDGMENT"}:
        errors.append(f"{label} has an invalid evidence class.")
    if (
        allowed_evidence_classes is not None
        and evidence_class not in allowed_evidence_classes
    ):
        errors.append(f"{label} uses a prohibited evidence class.")
    if not evidence_ids:
        errors.append(f"{label} lacks evidence IDs.")
    unknown = sorted(set(evidence_ids) - set(evidence_index))
    if unknown:
        errors.append(f"{label} contains unknown evidence IDs: {unknown}.")
    if not str(line.get("reviewed_by") or "").strip():
        errors.append(f"{label} lacks a named reviewer.")
    if evidence_class == "JUDGMENT" and not str(line.get("rationale") or "").strip():
        errors.append(f"{label} judgment lacks a rationale.")
    if evidence_class == "CALC" and not str(line.get("formula") or "").strip():
        errors.append(f"{label} calculation lacks a formula.")
    if (
        required_measurement_basis
        and str(line.get("measurement_basis") or "").upper()
        != required_measurement_basis
    ):
        errors.append(f"{label} has an invalid measurement basis.")
    if expected_kind == "amount":
        if (
            str(line.get("currency") or "").upper() != currency.upper()
            or str(line.get("unit") or "").upper() != unit.upper()
        ):
            errors.append(f"{label} has an invalid currency or unit.")
    elif str(line.get("unit") or "").upper() != "RATIO":
        errors.append(f"{label} must use unit RATIO.")
    if value is not None and evidence_class in {"FACT", "CALC"}:
        matching_ids = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_id in evidence_index
            and _evidence_binding_matches(
                evidence_index[evidence_id],
                value=value,
                evidence_class=evidence_class,
                expected_kind=expected_kind,
                currency=currency,
                unit=unit,
            )
        ]
        if not matching_ids:
            errors.append(f"{label} FACT/CALC evidence binding does not reproduce.")
        if line.get("matching_evidence_ids") != matching_ids:
            errors.append(f"{label} stored evidence-binding IDs do not reproduce.")
        if line.get("evidence_binding_status") != "PASS":
            errors.append(f"{label} stored evidence-binding status is not PASS.")
    elif evidence_class == "JUDGMENT" and line.get(
        "evidence_binding_status"
    ) != "CONTEXTUAL":
        errors.append(f"{label} judgment binding status must be CONTEXTUAL.")
    return errors


def _revenue_input_kind(field: Any) -> str:
    name = str(field or "")
    if name == "base_revenue" or name.endswith("_base_revenue"):
        return "amount"
    if name in {
        "acquisition_revenue",
        "divestiture_revenue",
        "acquired_revenue",
        "divested_revenue",
    }:
        return "amount"
    return "rate"


def _revenue_structure_errors(
    module: str,
    bridge: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    expected_methods = {
        "RETAIL": "MULTIPLICATIVE_REVENUE_BRIDGE",
        "CONSUMER_BRAND": "COMPONENT_REVENUE_BRIDGE",
        "SUBSCRIPTION_SOFTWARE": "COMPONENT_REVENUE_BRIDGE",
        "INDUSTRIAL": "VOLUME_PRICE_AND_PORTFOLIO_REVENUE_BRIDGE",
        "ACQUISITION_HEAVY": "ORGANIC_AND_ACQUIRED_REVENUE_BRIDGE",
        "DISTRIBUTION": "MULTIPLICATIVE_REVENUE_BRIDGE",
    }
    if bridge.get("module") != module:
        errors.append("Revenue bridge module disagrees with the S10 contract.")
    if bridge.get("method") != expected_methods[module]:
        errors.append("Revenue bridge method disagrees with the module registry.")
        return errors
    lines = bridge.get("input_lines", [])
    if not isinstance(lines, list):
        return [*errors, "Revenue bridge input_lines must be a list."]
    if bridge.get("method") != "COMPONENT_REVENUE_BRIDGE":
        expected_fields = set(
            DRIVER_MODULE_REGISTRY[module]["required_revenue_fields"]
        )
        actual_fields = {str(line.get("field") or "") for line in lines}
        if actual_fields != expected_fields or len(lines) != len(expected_fields):
            errors.append("Revenue bridge input fields disagree with the module registry.")
        if bridge.get("method") == "MULTIPLICATIVE_REVENUE_BRIDGE":
            growth_fields = [
                str(line.get("field") or "")
                for line in lines
                if line.get("field") != "base_revenue"
            ]
            expected_formula = "base_revenue * " + " * ".join(
                f"(1 + {field})" for field in growth_fields
            )
        elif bridge.get("method") == "VOLUME_PRICE_AND_PORTFOLIO_REVENUE_BRIDGE":
            expected_formula = (
                "base_revenue * (1 + volume_growth + price_mix_growth) "
                "+ acquisition_revenue - divestiture_revenue"
            )
        else:
            expected_formula = (
                "base_revenue * (1 + organic_growth) "
                "+ acquired_revenue - divested_revenue"
            )
    else:
        expected_component_field = (
            "brand_segments"
            if module == "CONSUMER_BRAND"
            else "revenue_streams"
        )
        minimum_components = 1 if module == "CONSUMER_BRAND" else 2
        components = bridge.get("components", [])
        if (
            bridge.get("component_field") != expected_component_field
            or not isinstance(components, list)
            or len(components) < minimum_components
        ):
            errors.append("Revenue component structure disagrees with the module registry.")
            components = []
        names = [str(row.get("name") or "") for row in components]
        if not all(names) or len(names) != len(set(names)):
            errors.append("Revenue component names must be non-empty and unique.")
        flattened = [
            line
            for component in components
            for line in (
                component.get("base_revenue"),
                component.get("revenue_growth"),
            )
        ]
        if lines != flattened:
            errors.append("Revenue component inputs do not reconcile to input_lines.")
        for component in components:
            base = _number(component.get("base_revenue", {}).get("value"))
            growth = _number(component.get("revenue_growth", {}).get("value"))
            output = component.get("forward_revenue", {})
            expected_value = (
                base * (1.0 + growth)
                if base is not None and growth is not None
                else None
            )
            if expected_value is not None and not _same_number(
                output.get("value"),
                expected_value,
            ):
                errors.append(
                    f"Revenue component {component.get('name')} does not reproduce."
                )
            if output.get("formula") != "base_revenue * (1 + revenue_growth)":
                errors.append(
                    f"Revenue component {component.get('name')} formula is invalid."
                )
        expected_formula = (
            "sum(component base_revenue * (1 + component revenue_growth))"
        )
    if bridge.get("forward_revenue", {}).get("formula") != expected_formula:
        errors.append("Forward revenue formula disagrees with the controlled method.")
    return errors


def _s09_forward_fcf_rows(parent: dict[str, Any]) -> list[dict[str, Any]]:
    valuation_contract = parent.get("valuation_contract")
    valuation_contract = (
        valuation_contract if isinstance(valuation_contract, dict) else {}
    )
    exit_basis = valuation_contract.get("exit_basis")
    exit_basis = exit_basis if isinstance(exit_basis, dict) else {}
    outputs = valuation_contract.get("outputs")
    outputs = outputs if isinstance(outputs, dict) else {}
    price_output = outputs.get("price_sensitivity")
    price_output = price_output if isinstance(price_output, dict) else {}
    candidates = [
        *_as_list(parent.get("scenarios")),
        *_as_list(exit_basis.get("scenario_assumptions")),
        *_as_list(price_output.get("scenarios")),
    ]
    return [
        row
        for row in candidates
        if isinstance(row, dict)
        and str(row.get("metric") or "").strip().upper() == "FORWARD FCF"
    ]


def _s09_forward_fcf_alignment_errors(
    parent: dict[str, Any],
    contract: dict[str, Any],
) -> list[str]:
    rows = [
        row
        for row in _as_list(parent.get("scenarios"))
        if isinstance(row, dict)
    ]
    if not rows:
        return []
    if len(rows) != 3 or {row.get("name") for row in rows} != SCENARIO_NAMES:
        return ["S09 Forward FCF scenarios do not contain Bear, Base, and Bull."]
    bridge = contract.get("forward_share_count_bridge")
    bridge = bridge if isinstance(bridge, dict) else {}
    shares = _number(bridge.get("forward_diluted_shares"))
    target_date = bridge.get("target_date")
    forward_rows = {
        row.get("name"): row
        for row in _as_list(contract.get("scenarios"))
        if isinstance(row, dict)
    }
    errors: list[str] = []
    for row in rows:
        name = str(row.get("name") or "")
        forward_row = forward_rows.get(name, {})
        fcf = _number(forward_row.get("forward_fcf"))
        metric_per_share = _number(row.get("metric_per_share"))
        if str(row.get("metric") or "").strip().upper() != "FORWARD FCF":
            errors.append(f"S09 {name} metric does not identify Forward FCF.")
        if (
            shares is None
            or shares <= 0
            or fcf is None
            or metric_per_share is None
            or not _same_number(metric_per_share, fcf / shares)
        ):
            errors.append(f"S09 {name} per-share Forward FCF does not reconcile to S10.")
        if (
            not _same_number(row.get("share_count_basis_value"), shares)
            or row.get("share_count_basis_date") != target_date
        ):
            errors.append(f"S09 {name} share basis does not reconcile to S10.")
        calculation_ids = _unique(forward_row.get("calculation_evidence_ids"))
        scenario_ids = set(_unique(row.get("evidence_ids")))
        evidence_index = _known_evidence_ids(parent)
        fcf_calculation_ids = {
            evidence_id
            for evidence_id in calculation_ids
            if evidence_index.get(evidence_id, {}).get("metric_name")
            == f"forward_{name.lower()}_fcf"
        }
        if fcf_calculation_ids and not fcf_calculation_ids.issubset(scenario_ids):
            errors.append(f"S09 {name} evidence does not include S10 calculations.")
    return errors


def _validate_forward_valuation_contract(
    parent: dict[str, Any],
) -> list[str]:
    """Recalculate material S10 outputs and detect renderer-side tampering."""

    contract = parent.get("forward_valuation_contract")
    if contract is None:
        return []
    if not isinstance(contract, dict):
        return ["forward_valuation_contract must be an object."]
    errors: list[str] = []
    if contract.get("contract_version") != FORWARD_VALUATION_CONTRACT_VERSION:
        errors.append("Unsupported S10 forward-valuation contract version.")
    if contract.get("registry_version") != DRIVER_MODULE_REGISTRY_VERSION:
        errors.append("Unsupported S10 driver-module registry version.")
    if contract.get("status") not in FORWARD_CONTRACT_STATUSES:
        errors.append("Invalid S10 forward-valuation status.")
    driver_model_available = (
        contract.get("status") != "DRIVER_MODEL_NOT_AVAILABLE"
    )
    currency = str(contract.get("currency") or "").upper()
    unit = str(contract.get("unit") or "").upper()
    parent_price_currency = str(
        parent.get("valuation", {}).get("price_currency") or ""
    ).upper()
    if contract.get("status") != "DRIVER_MODEL_NOT_AVAILABLE":
        if not currency or unit != currency or contract.get("amount_scale") != 1.0:
            errors.append(
                "S10 monetary values must use unscaled atomic currency units."
            )
        if not parent_price_currency or currency != parent_price_currency:
            errors.append("S10 currency disagrees with market-price currency.")
        if contract.get("fcf_basis") != FORWARD_FCF_BASIS:
            errors.append("S10 FCF basis is unsupported.")
    valuation_contract = parent.get("valuation_contract")
    if not isinstance(valuation_contract, dict):
        errors.append("S10 contract requires the parent S09 valuation contract.")
    else:
        valuation_as_of_date = valuation_contract.get("valuation_as_of_date")
        target_date = valuation_contract.get("target_date")
        parent_price_date = (
            parent.get("valuation", {}).get("price_date")
            or parent.get("report_dates", {}).get("market_price_date")
        )
        if valuation_as_of_date != parent_price_date:
            errors.append(
                "S10 parent valuation as-of date disagrees with the authoritative market-price date."
            )
        if contract.get("forecast_period") != valuation_contract.get(
            "forecast_period"
        ):
            errors.append("S10 forecast period disagrees with the S09 valuation contract.")
        if contract.get("metric_period") != valuation_contract.get("metric_period"):
            errors.append("S10 metric period disagrees with the S09 valuation contract.")
        if driver_model_available:
            if not _forecast_period_matches_horizon(
                contract.get("forecast_period", {}),
                valuation_as_of_date,
                target_date,
            ):
                errors.append("S10 forecast period does not reproduce the valuation horizon.")
            if not _metric_period_matches_target(
                contract.get("metric_period", {}),
                valuation_as_of_date,
                target_date,
            ):
                errors.append("S10 metric period is not aligned with the valuation target.")
    s09_forward_fcf_rows = _s09_forward_fcf_rows(parent)
    if contract.get("status") != "VALIDATED" and s09_forward_fcf_rows:
        errors.append(
            "S09 Forward FCF scenarios require a VALIDATED S10 contract."
        )
    elif contract.get("status") == "VALIDATED" and s09_forward_fcf_rows:
        errors.extend(_s09_forward_fcf_alignment_errors(parent, contract))
    module = contract.get("driver_module")
    if contract.get("status") == "DRIVER_MODEL_NOT_AVAILABLE":
        if contract.get("scenarios"):
            errors.append("DRIVER_MODEL_NOT_AVAILABLE must not contain forward scenarios.")
        if contract.get("scenario_metric_eligibility", {}).get(
            "positive_fcf_multiple_allowed"
        ):
            errors.append(
                "DRIVER_MODEL_NOT_AVAILABLE cannot allow a forward FCF multiple."
            )
        return errors
    if module not in DRIVER_MODULE_REGISTRY:
        errors.append("S10 contract contains an unsupported driver module.")
        return errors
    known_ids = _known_evidence_ids(parent)
    selection = contract.get("module_selection", {})
    selection_ids = _unique(selection.get("evidence_ids"))
    selection_valid = (
        selection.get("status") == "VALIDATED"
        and bool(str(selection.get("rationale") or "").strip())
        and bool(str(selection.get("reviewed_by") or "").strip())
        and bool(selection_ids)
        and not (set(selection_ids) - set(known_ids))
    )
    if selection.get("status") == "VALIDATED" and not selection_valid:
        errors.append("S10 validated module selection does not reproduce.")
    top_reviewer_present = bool(str(contract.get("reviewed_by") or "").strip())
    if contract.get("status") in {"PARTIALLY_VALIDATED", "VALIDATED"}:
        if not selection_valid:
            errors.append("Validated S10 operating model requires validated module selection.")
        if not top_reviewer_present:
            errors.append("Validated S10 contract lacks a named reviewer.")
    scenarios = contract.get("scenarios", [])
    if len(scenarios) != 3 or {row.get("name") for row in scenarios} != SCENARIO_NAMES:
        errors.append("S10 contract must contain exactly Bear, Base, and Bull scenarios.")
    scenario_semantics: list[bool] = []
    fcf_values: list[float | None] = []
    for scenario in scenarios:
        name = str(scenario.get("name") or "")
        require_valid = scenario.get("status") == "VALIDATED"
        scenario_local_errors: list[str] = []
        if scenario.get("driver_module") != module:
            scenario_local_errors.append(f"S10 {name} driver module disagrees with contract.")
        if scenario.get("forecast_period") != contract.get("forecast_period"):
            scenario_local_errors.append(f"S10 {name} forecast period disagrees with contract.")
        if scenario.get("metric_period") != contract.get("metric_period"):
            scenario_local_errors.append(f"S10 {name} metric period disagrees with contract.")
        if (
            str(scenario.get("currency") or "").upper() != currency
            or str(scenario.get("unit") or "").upper() != unit
        ):
            scenario_local_errors.append(f"S10 {name} currency or unit disagrees with contract.")
        if require_valid and (
            not str(scenario.get("reviewed_by") or "").strip()
            or not str(scenario.get("scenario_rationale") or "").strip()
        ):
            scenario_local_errors.append(f"S10 {name} governance fields are incomplete.")
        revenue_bridge = scenario.get("revenue_bridge", {})
        scenario_local_errors.extend(
            f"S10 {name} {message}"
            for message in _revenue_structure_errors(module, revenue_bridge)
        )
        revenue = revenue_bridge.get("forward_revenue", {})
        revenue_lines = revenue_bridge.get("input_lines", [])
        if not isinstance(revenue_lines, list):
            revenue_lines = []
            scenario_local_errors.append(f"S10 {name} revenue inputs must be a list.")
        for line in revenue_lines:
            kind = _revenue_input_kind(line.get("field"))
            scenario_local_errors.extend(
                _persisted_input_line_errors(
                    line,
                    label=f"S10 {name} revenue input {line.get('field')}",
                    evidence_index=known_ids,
                    expected_kind=kind,
                    currency=currency,
                    unit=unit,
                    require_pass=require_valid,
                    allowed_evidence_classes=(
                        {"FACT", "CALC"}
                        if str(line.get("field") or "") == "base_revenue"
                        or str(line.get("field") or "").endswith("_base_revenue")
                        else None
                    ),
                )
            )
        cash = scenario.get("cash_flow_bridge", {})
        if (
            cash.get("basis") != FORWARD_FCF_BASIS
            or cash.get("embedded_cfo_used") is not False
        ):
            scenario_local_errors.append(
                f"S10 {name} cash-flow basis or embedded-CFO control is invalid."
            )
        if cash.get("forward_fcf", {}).get("formula") != FORWARD_FCF_FORMULA:
            scenario_local_errors.append(
                f"S10 {name} forward FCF formula is invalid."
            )
        inputs = {
            row.get("field"): row
            for row in cash.get("input_lines", [])
            if row.get("field")
        }
        required = set(COMMON_CASH_FLOW_FIELDS)
        if set(inputs) != required:
            scenario_local_errors.append(
                f"S10 {name} cash-flow inputs do not match the shared contract."
            )
        for field, line in inputs.items():
            scenario_local_errors.extend(
                _persisted_input_line_errors(
                    line,
                    label=f"S10 {name} cash-flow input {field}",
                    evidence_index=known_ids,
                    expected_kind="rate" if field == "operating_margin" else "amount",
                    currency=currency,
                    unit=unit,
                    require_pass=require_valid,
                    required_measurement_basis=CASH_FLOW_MEASUREMENT_BASES.get(field),
                )
            )
        input_values = {
            field: _number(line.get("value")) for field, line in inputs.items()
        }
        expected_revenue = _recalculate_revenue_bridge(revenue_bridge)
        revenue_value = _number(revenue.get("value"))
        if expected_revenue is None:
            if revenue_value is not None:
                scenario_local_errors.append(
                    f"S10 {name} displays revenue that cannot be reproduced."
                )
            if require_valid:
                scenario_local_errors.append(f"S10 {name} forward revenue is missing.")
        elif revenue_value is None:
            if require_valid:
                scenario_local_errors.append(f"S10 {name} forward revenue is missing.")
        elif not _same_number(revenue_value, expected_revenue):
            scenario_local_errors.append(
                f"S10 {name} forward revenue does not reproduce."
            )
        expected_fcf = None
        if (
            expected_revenue is not None
            and set(input_values) == required
            and all(value is not None for value in input_values.values())
        ):
            operating_income = expected_revenue * float(
                input_values["operating_margin"]
            )
            expected_fcf = (
                operating_income
                - float(input_values["cash_interest"])
                - float(input_values["cash_taxes"])
                + float(input_values["depreciation_and_amortization"])
                + float(input_values["stock_based_compensation"])
                + float(input_values["other_non_cash_items"])
                - float(input_values["working_capital_investment"])
                - float(input_values["capex"])
                - float(input_values["restructuring_cash"])
                - float(input_values["acquisition_integration_cash"])
                + float(input_values["other_cash_adjustments"])
            )
        displayed_fcf = _number(scenario.get("forward_fcf"))
        bridge_fcf = _number(cash.get("forward_fcf", {}).get("value"))
        if expected_fcf is None:
            if displayed_fcf is not None or bridge_fcf is not None:
                scenario_local_errors.append(
                    f"S10 {name} displays FCF that cannot be reproduced."
                )
            if require_valid:
                scenario_local_errors.append(f"S10 {name} forward FCF is missing.")
        else:
            if displayed_fcf is None or not _same_number(displayed_fcf, expected_fcf):
                scenario_local_errors.append(
                    f"S10 {name} forward FCF does not reproduce."
                )
            if bridge_fcf is None or not _same_number(bridge_fcf, expected_fcf):
                scenario_local_errors.append(
                    f"S10 {name} FCF bridge output does not reproduce."
                )
        upstream_ids = _unique(
            [
                evidence_id
                for line in [*revenue_lines, *inputs.values()]
                for evidence_id in _as_list(line.get("evidence_ids"))
            ]
        )
        calculation_ids = _unique(scenario.get("calculation_evidence_ids"))
        stored_scenario_ids = _unique(scenario.get("evidence_ids"))
        unknown_scenario_ids = sorted(
            set([*calculation_ids, *stored_scenario_ids]) - set(known_ids)
        )
        if unknown_scenario_ids:
            scenario_local_errors.append(
                f"S10 {name} contains unknown scenario evidence IDs: {unknown_scenario_ids}."
            )
        if calculation_ids:
            if len(calculation_ids) != 2:
                scenario_local_errors.append(
                    f"S10 {name} calculation evidence IDs are incomplete."
                )
            else:
                revenue_upstream_ids = _unique(
                    [
                        evidence_id
                        for line in revenue_lines
                        for evidence_id in _as_list(line.get("evidence_ids"))
                    ]
                )
                expected_calculations = (
                    (
                        f"forward_{name.lower()}_revenue",
                        revenue_value,
                        revenue.get("formula"),
                        contract.get("forecast_period", {}),
                        revenue_upstream_ids,
                    ),
                    (
                        f"forward_{name.lower()}_fcf",
                        displayed_fcf,
                        FORWARD_FCF_FORMULA,
                        contract.get("metric_period", {}),
                        _unique(
                            [
                                calculation_ids[0],
                                *[
                                    evidence_id
                                    for line in inputs.values()
                                    for evidence_id in _as_list(
                                        line.get("evidence_ids")
                                    )
                                ],
                            ]
                        ),
                    ),
                )
                for evidence_id, (
                    metric_name,
                    expected_value,
                    expected_formula,
                    expected_period,
                    expected_input_ids,
                ) in zip(
                    calculation_ids,
                    expected_calculations,
                ):
                    record = known_ids.get(evidence_id, {})
                    if (
                        record.get("metric_name") != metric_name
                        or str(record.get("evidence_class") or "").upper()
                        != "CALC"
                        or str(record.get("validation_status") or "").upper()
                        != "PASS"
                        or not _same_number(record.get("value"), expected_value)
                        or str(record.get("unit") or "").upper() != unit
                        or str(record.get("currency") or "").upper() != currency
                        or record.get("scale") != 1.0
                        or record.get("period_start")
                        != expected_period.get("start_date")
                        or record.get("period_end")
                        != expected_period.get("end_date")
                        or record.get("formula") != expected_formula
                        or _unique(record.get("input_evidence_ids"))
                        != expected_input_ids
                    ):
                        scenario_local_errors.append(
                            f"S10 {name} calculation evidence {evidence_id} does not reproduce."
                        )
        expected_scenario_ids = _unique([*upstream_ids, *calculation_ids])
        if stored_scenario_ids != expected_scenario_ids:
            scenario_local_errors.append(
                f"S10 {name} stored scenario evidence IDs do not reproduce."
            )
        fcf_values.append(displayed_fcf)
        scenario_semantics.append(
            require_valid
            and not scenario.get("validation_issues")
            and not scenario_local_errors
        )
        errors.extend(scenario_local_errors)
    bridge = contract.get("forward_share_count_bridge", {})
    share_declared_valid = bridge.get("status") == "VALIDATED"
    share_error_start = len(errors)
    if share_declared_valid:
        if (
            not str(bridge.get("reviewed_by") or "").strip()
            or bridge.get("known_subsequent_event_status")
            not in KNOWN_SHARE_EVENT_STATUSES
            or not str(bridge.get("known_subsequent_event_note") or "").strip()
        ):
            errors.append("S10 validated share-count governance is incomplete.")
        change_lines = _as_list(bridge.get("change_lines"))
        input_lines = _as_list(bridge.get("input_lines"))
        for line in change_lines:
            errors.extend(
                _persisted_input_line_errors(
                    line,
                    label=f"S10 share-count input {line.get('field')}",
                    evidence_index=known_ids,
                    expected_kind="amount",
                    currency="SHARES",
                    unit="SHARES",
                    require_pass=True,
                )
            )
        if bridge.get("formula") != FORWARD_SHARE_FORMULA:
            errors.append("S10 forward share-count formula is invalid.")
    if share_declared_valid:
        valuation = parent.get("valuation", {})
        base = _number(valuation.get("shares"))
        base_date = str(valuation.get("shares_as_of_date") or "")
        base_ids = _matching_share_evidence_ids(parent, base, base_date)
        base_line = input_lines[0] if input_lines else {}
        base_line_ids = _unique(base_line.get("evidence_ids"))
        if (
            base_line.get("field") != "latest_reported_shares"
            or not _same_number(base_line.get("value"), base)
            or base_line.get("evidence_class") != "FACT"
            or not base_line_ids
            or bool(set(base_line_ids) - set(base_ids))
            or str(base_line.get("unit") or "").upper() != "SHARES"
            or base_line.get("validation_status") != "PASS"
        ):
            errors.append(
                "S10 reported-share input line does not reproduce authoritative evidence."
            )
        if input_lines[1:] != change_lines:
            errors.append(
                "S10 share-count input lines do not reconcile to change lines."
            )
        changes = {
            row.get("field"): _number(row.get("value"))
            for row in change_lines
        }
        if set(changes) != set(SHARE_CHANGE_FIELDS) or any(
            value is None for value in changes.values()
        ):
            errors.append("S10 forward share-count change lines are incomplete.")
        elif base is None:
            errors.append("S10 forward share-count bridge lacks authoritative base shares.")
        else:
            expected_shares = (
                base
                - float(changes["repurchases"])
                + float(changes["stock_based_compensation_issuance"])
                + float(changes["employee_plan_issuance"])
                + float(changes["convertible_dilution"])
                + float(changes["acquisition_share_issuance"])
                + float(changes["other_net_change"])
            )
            if not _same_number(bridge.get("base_share_count"), base):
                errors.append("S10 forward share-count base disagrees with authoritative shares.")
            if not _same_number(bridge.get("forward_diluted_shares"), expected_shares):
                errors.append("S10 forward share-count bridge does not reproduce.")
        target_date = parent.get("valuation_contract", {}).get("target_date")
        if target_date and bridge.get("target_date") != target_date:
            errors.append("S10 forward share-count date disagrees with the S09 target date.")
        share_calculation_id = str(
            bridge.get("calculation_evidence_id") or ""
        )
        expected_bridge_ids = _unique(
            [
                *base_line_ids,
                *[
                    evidence_id
                    for line in change_lines
                    for evidence_id in _as_list(line.get("evidence_ids"))
                ],
                *([share_calculation_id] if share_calculation_id else []),
            ]
        )
        stored_bridge_ids = _unique(bridge.get("evidence_ids"))
        if stored_bridge_ids != expected_bridge_ids:
            errors.append("S10 stored share-count evidence IDs do not reproduce.")
        if share_calculation_id:
            record = known_ids.get(share_calculation_id, {})
            record_input_ids = _unique(record.get("input_evidence_ids"))
            input_share_ids = [
                evidence_id
                for evidence_id in record_input_ids
                if known_ids.get(evidence_id, {}).get("metric_name")
                == "shares_outstanding_point_in_time"
                and _same_number(
                    known_ids[evidence_id].get("value"),
                    base,
                )
                and str(
                    known_ids[evidence_id].get("as_of_date")
                    or known_ids[evidence_id].get("period_end")
                    or ""
                )
                == base_date
            ]
            change_evidence_ids = {
                evidence_id
                for line in change_lines
                for evidence_id in _as_list(line.get("evidence_ids"))
            }
            if (
                record.get("metric_name") != "forward_share_count_basis"
                or str(record.get("evidence_class") or "").upper() != "CALC"
                or str(record.get("validation_status") or "").upper() != "PASS"
                or not _same_number(
                    record.get("value"),
                    bridge.get("forward_diluted_shares"),
                )
                or record.get("formula") != FORWARD_SHARE_FORMULA
                or str(record.get("unit") or "").upper() != "SHARES"
                or record.get("scale") != 1.0
                or str(record.get("as_of_date") or "") != bridge.get("target_date")
                or not input_share_ids
                or not change_evidence_ids.issubset(set(record_input_ids))
            ):
                errors.append(
                    "S10 forward share-count calculation evidence does not reproduce."
                )
    share_valid = share_declared_valid and len(errors) == share_error_start
    operating_validation_issues = [
        row
        for row in contract.get("validation_issues", [])
        if not str(row.get("path") or "").startswith(
            "forward_valuation.share_count_bridge"
        )
        and row.get("code") != "FORWARD_SHARE_INPUT_CONFLICT"
    ]
    operating_valid = (
        len(scenario_semantics) == 3
        and all(scenario_semantics)
        and selection_valid
        and top_reviewer_present
        and not operating_validation_issues
    )
    expected_status = (
        "VALIDATED"
        if operating_valid and share_valid
        else "PARTIALLY_VALIDATED"
        if operating_valid
        else "INVALID"
    )
    if contract.get("status") != expected_status:
        errors.append(
            f"S10 contract status does not reproduce; expected {expected_status}."
        )
    expected_driver_status = "VALIDATED" if operating_valid else "INVALID"
    if contract.get("driver_model_status") != expected_driver_status:
        errors.append("S10 driver-model status does not reproduce.")
    expected_multiple_allowed = (
        expected_status == "VALIDATED"
        and len(fcf_values) == 3
        and all(value is not None and value > 0 for value in fcf_values)
    )
    if contract.get("scenario_metric_eligibility", {}).get(
        "positive_fcf_multiple_allowed"
    ) != expected_multiple_allowed:
        errors.append("S10 positive-FCF multiple eligibility does not reproduce.")
    return errors


def validate_forward_valuation_contract(
    parent: dict[str, Any],
) -> list[str]:
    """Fail closed on malformed persisted S10 contracts without raising."""

    try:
        return _validate_forward_valuation_contract(parent)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return [
            "Malformed S10 forward-valuation contract: "
            f"{type(exc).__name__}: {exc}"
        ]


def _recalculate_revenue_bridge(bridge: dict[str, Any]) -> float | None:
    method = bridge.get("method")
    if method == "MULTIPLICATIVE_REVENUE_BRIDGE":
        values = {
            row.get("field"): _number(row.get("value"))
            for row in bridge.get("input_lines", [])
        }
        base = values.pop("base_revenue", None)
        if base is None or any(value is None for value in values.values()):
            return None
        result = float(base)
        for value in values.values():
            result *= 1.0 + float(value)
        return result
    if method == "VOLUME_PRICE_AND_PORTFOLIO_REVENUE_BRIDGE":
        values = {
            row.get("field"): _number(row.get("value"))
            for row in bridge.get("input_lines", [])
        }
        required = {
            "base_revenue",
            "volume_growth",
            "price_mix_growth",
            "acquisition_revenue",
            "divestiture_revenue",
        }
        if set(values) != required or any(value is None for value in values.values()):
            return None
        return (
            float(values["base_revenue"])
            * (
                1.0
                + float(values["volume_growth"])
                + float(values["price_mix_growth"])
            )
            + float(values["acquisition_revenue"])
            - float(values["divestiture_revenue"])
        )
    if method == "ORGANIC_AND_ACQUIRED_REVENUE_BRIDGE":
        values = {
            row.get("field"): _number(row.get("value"))
            for row in bridge.get("input_lines", [])
        }
        required = {
            "base_revenue",
            "organic_growth",
            "acquired_revenue",
            "divested_revenue",
        }
        if set(values) != required or any(value is None for value in values.values()):
            return None
        return (
            float(values["base_revenue"])
            * (1.0 + float(values["organic_growth"]))
            + float(values["acquired_revenue"])
            - float(values["divested_revenue"])
        )
    if method == "COMPONENT_REVENUE_BRIDGE":
        components = bridge.get("components", [])
        values: list[float] = []
        for component in components:
            base = _number(component.get("base_revenue", {}).get("value"))
            growth = _number(component.get("revenue_growth", {}).get("value"))
            if base is None or growth is None:
                return None
            values.append(base * (1.0 + growth))
        return sum(values) if values else None
    return None
