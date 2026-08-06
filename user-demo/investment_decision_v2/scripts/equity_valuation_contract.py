#!/usr/bin/env python3
"""Shared, company-agnostic equity valuation and return contract.

S09 separates dated price sensitivity from horizon-dependent returns. This
module owns the calculations and validation so renderers cannot recreate them.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from math import isclose
from typing import Any


VALUATION_CONTRACT_VERSION = "1.0.0"
VALUATION_HORIZON_STATUSES = {"NOT_DEFINED", "INVALID", "VALIDATED"}
VALUATION_OUTPUT_STATUSES = {
    "NOT_EVALUATED",
    "SUPPRESSED_BELOW_GATE_3",
    "VALIDATED",
    "DISABLED_PRIVATE_GATE_4_ONLY",
}
PERIOD_VALIDATION_STATUSES = {"NOT_DEFINED", "INVALID", "VALIDATED"}
FORECAST_PERIOD_TYPES = {"FORECAST"}
FORECAST_PERIOD_BASES = {"HOLDING_PERIOD_FORECAST"}
METRIC_PERIOD_TYPES = {"FORWARD_METRIC", "POINT_IN_TIME_METRIC"}
METRIC_PERIOD_BASES = {
    "FORWARD_PERIOD_ENDING_AT_TARGET",
    "FORWARD_PERIOD_STARTING_AT_TARGET",
    "POINT_IN_TIME_AT_TARGET",
}
DIVIDEND_BASES = {"CUMULATIVE_CASH_DIVIDENDS_THROUGH_TARGET_DATE"}
DIVIDEND_PAYMENT_TIMINGS = {"DURING_HOLDING_PERIOD", "AT_TARGET_DATE"}
EXIT_METHODS = {"SCENARIO_EXIT_MULTIPLE"}
EXIT_TIMINGS = {"EXIT"}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _iso_date(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def normalize_valuation_period(value: Any) -> dict[str, Any]:
    supplied = value if isinstance(value, dict) else {}
    start_date = supplied.get("start_date")
    end_date = supplied.get("end_date")
    label = str(supplied.get("label") or "").strip()
    requested = str(supplied.get("status") or "NOT_DEFINED").upper()
    valid_dates = (
        _iso_date(start_date)
        and _iso_date(end_date)
        and str(start_date) <= str(end_date)
    )
    if requested == "VALIDATED" and valid_dates and label:
        status = "VALIDATED"
    elif requested == "NOT_DEFINED" and not any((start_date, end_date, label)):
        status = "NOT_DEFINED"
    else:
        status = "INVALID"
    return {
        "status": status,
        "start_date": start_date or None,
        "end_date": end_date or None,
        "label": label or None,
        "period_type": str(supplied.get("period_type") or "").strip().upper() or None,
        "basis": str(supplied.get("basis") or "").strip().upper() or None,
        "evidence_ids": sorted(
            {str(value) for value in supplied.get("evidence_ids", []) if value}
        ),
    }


def _forecast_period_matches_horizon(
    period: dict[str, Any],
    valuation_as_of_date: Any,
    target_date: Any,
) -> bool:
    if (
        period.get("status") != "VALIDATED"
        or period.get("period_type") not in FORECAST_PERIOD_TYPES
        or period.get("basis") not in FORECAST_PERIOD_BASES
        or not _iso_date(valuation_as_of_date)
        or not _iso_date(target_date)
    ):
        return False
    as_of_day = date.fromisoformat(str(valuation_as_of_date))
    target_day = date.fromisoformat(str(target_date))
    start_day = date.fromisoformat(str(period.get("start_date")))
    end_day = date.fromisoformat(str(period.get("end_date")))
    return start_day in {as_of_day, as_of_day + timedelta(days=1)} and end_day == target_day


def _metric_period_matches_target(
    period: dict[str, Any],
    valuation_as_of_date: Any,
    target_date: Any,
) -> bool:
    if (
        period.get("status") != "VALIDATED"
        or period.get("period_type") not in METRIC_PERIOD_TYPES
        or period.get("basis") not in METRIC_PERIOD_BASES
        or not _iso_date(valuation_as_of_date)
        or not _iso_date(target_date)
    ):
        return False
    as_of_day = date.fromisoformat(str(valuation_as_of_date))
    target_day = date.fromisoformat(str(target_date))
    start_day = date.fromisoformat(str(period.get("start_date")))
    end_day = date.fromisoformat(str(period.get("end_date")))
    basis = period.get("basis")
    if basis == "FORWARD_PERIOD_ENDING_AT_TARGET":
        return period.get("period_type") == "FORWARD_METRIC" and as_of_day < start_day <= end_day == target_day
    if basis == "FORWARD_PERIOD_STARTING_AT_TARGET":
        return period.get("period_type") == "FORWARD_METRIC" and start_day == target_day < end_day
    return (
        basis == "POINT_IN_TIME_AT_TARGET"
        and period.get("period_type") == "POINT_IN_TIME_METRIC"
        and start_day == end_day == target_day
    )


def _holding_period(
    valuation_as_of_date: Any,
    target_date: Any,
    supplied_days: Any,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    if not _iso_date(valuation_as_of_date) or not _iso_date(target_date):
        return (
            {
                "status": "NOT_DEFINED",
                "calendar_days": None,
                "years_act_365_25": None,
                "day_count_basis": "ACT/365.25",
                "source": "DERIVED_FROM_VALUATION_AND_TARGET_DATES",
            },
            issues,
        )
    days = (date.fromisoformat(str(target_date)) - date.fromisoformat(str(valuation_as_of_date))).days
    if days <= 0:
        issues.append(
            {
                "code": "TARGET_DATE_NOT_AFTER_AS_OF_DATE",
                "message": "Target date must be later than the valuation as-of date.",
            }
        )
        status = "INVALID"
    else:
        status = "VALIDATED"
    explicit_days = _number(supplied_days)
    if explicit_days is not None and not isclose(explicit_days, float(days), abs_tol=0.0):
        issues.append(
            {
                "code": "HOLDING_PERIOD_DATE_MISMATCH",
                "message": "Supplied holding-period days do not reconcile to the two dated endpoints.",
            }
        )
        status = "INVALID"
    return (
        {
            "status": status,
            "calendar_days": days if days > 0 else None,
            "years_act_365_25": days / 365.25 if days > 0 else None,
            "day_count_basis": "ACT/365.25",
            "source": "DERIVED_FROM_VALUATION_AND_TARGET_DATES",
        },
        issues,
    )


def _dividend_assumption(value: Any, price_currency: str) -> dict[str, Any]:
    supplied = value if isinstance(value, dict) else {}
    amount = _number(supplied.get("amount_per_share"))
    currency = str(supplied.get("currency") or "").upper()
    basis = str(supplied.get("basis") or "").strip().upper()
    payment_timing = str(supplied.get("payment_timing") or "").strip().upper()
    reinvestment = supplied.get("reinvestment")
    reviewer = str(supplied.get("reviewed_by") or "").strip()
    requested = str(supplied.get("status") or "NOT_DEFINED").upper()
    valid = (
        requested == "VALIDATED"
        and amount is not None
        and amount >= 0
        and bool(currency)
        and currency == price_currency.upper()
        and basis in DIVIDEND_BASES
        and payment_timing in DIVIDEND_PAYMENT_TIMINGS
        and reinvestment is False
        and bool(reviewer)
    )
    if valid:
        status = "VALIDATED"
    elif (
        requested == "NOT_DEFINED"
        and amount is None
        and reinvestment is None
        and not any((currency, basis, payment_timing, reviewer))
    ):
        status = "NOT_DEFINED"
    else:
        status = "INVALID"
    return {
        "status": status,
        "amount_per_share": amount,
        "currency": currency or None,
        "basis": basis or None,
        "payment_timing": payment_timing or None,
        "reinvestment": reinvestment if isinstance(reinvestment, bool) else None,
        "evidence_ids": sorted(
            {str(value) for value in supplied.get("evidence_ids", []) if value}
        ),
        "reviewed_by": reviewer or None,
        "note": (
            "A zero dividend is accepted only when it is explicitly entered and validated."
            if amount == 0
            else None
        ),
    }


def _scenario_rows(contract: dict[str, Any], *, include_values: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    valuation = contract.get("valuation", {})
    for scenario in contract.get("scenarios", []):
        name = str(scenario.get("name") or "")
        rows.append(
            {
                "name": name,
                "metric": scenario.get("metric"),
                "metric_per_share": _number(scenario.get("metric_per_share")),
                "exit_multiple": _number(scenario.get("exit_multiple")),
                "implied_price": _number(scenario.get("implied_price")) if include_values else None,
                "price_change_vs_current": (
                    _number(scenario.get("price_change_vs_current")) if include_values else None
                ),
                "probability": _number(scenario.get("probability")),
                "share_count_basis_value": _number(
                    scenario.get("share_count_basis_value")
                    if scenario.get("share_count_basis_value") is not None
                    else valuation.get("shares")
                ),
                "share_count_basis_date": (
                    scenario.get("share_count_basis_date")
                    or valuation.get("shares_as_of_date")
                ),
                "forecast_period": deepcopy(scenario.get("forecast_period")),
                "metric_period": deepcopy(scenario.get("metric_period")),
                "evidence_ids": sorted(
                    {str(value) for value in scenario.get("evidence_ids", []) if value}
                ),
            }
        )
    return rows


def _exit_basis(
    contract: dict[str, Any],
    value: Any,
    share_basis: dict[str, Any],
    forecast_period: dict[str, Any],
    metric_period: dict[str, Any],
) -> dict[str, Any]:
    supplied = value if isinstance(value, dict) else {}
    method = str(supplied.get("method") or "").strip()
    metric = str(supplied.get("metric") or "").strip()
    reviewer = str(supplied.get("reviewed_by") or "").strip()
    requested = str(supplied.get("status") or "NOT_DEFINED").upper()
    terminal_or_exit = str(supplied.get("terminal_or_exit") or "").strip().upper()
    scenario_rows = _scenario_rows(contract, include_values=True)
    scenarios_complete = (
        len(scenario_rows) == 3
        and {row["name"] for row in scenario_rows} == {"Bear", "Base", "Bull"}
        and all(
            row["metric_per_share"] is not None
            and row["exit_multiple"] is not None
            and row["exit_multiple"] > 0
            and row["implied_price"] is not None
            for row in scenario_rows
        )
    )
    scenario_metrics = {
        str(row.get("metric") or "").strip()
        for row in scenario_rows
        if row.get("metric")
    }
    share_basis_matches = all(
        _same_number(
            row.get("share_count_basis_value"),
            share_basis.get("share_count_value"),
        )
        and row.get("share_count_basis_date") == share_basis.get("share_count_date")
        for row in scenario_rows
    )
    forecast_period_matches = all(
        row.get("forecast_period") == forecast_period for row in scenario_rows
    )
    metric_period_matches = all(
        row.get("metric_period") == metric_period for row in scenario_rows
    )
    valid = (
        requested == "VALIDATED"
        and method in EXIT_METHODS
        and bool(metric)
        and terminal_or_exit in EXIT_TIMINGS
        and scenario_metrics == {metric}
        and bool(reviewer)
        and scenarios_complete
        and share_basis_matches
        and forecast_period_matches
        and metric_period_matches
    )
    if valid:
        status = "VALIDATED"
    elif requested == "NOT_DEFINED" and not any((method, metric, reviewer)):
        status = "NOT_DEFINED"
    else:
        status = "INVALID"
    return {
        "status": status,
        "method": method or None,
        "metric": metric or None,
        "terminal_or_exit": terminal_or_exit or None,
        "scenario_assumptions": scenario_rows,
        "share_basis_reconciliation_status": "PASS" if share_basis_matches else "FAIL",
        "forecast_period_reconciliation_status": (
            "PASS" if forecast_period_matches else "FAIL"
        ),
        "metric_period_reconciliation_status": (
            "PASS" if metric_period_matches else "FAIL"
        ),
        "evidence_ids": sorted(
            {str(value) for value in supplied.get("evidence_ids", []) if value}
        ),
        "reviewed_by": reviewer or None,
        "disclosure": (
            "Exit assumptions are analyst-owned unless independently validated by later cross-check modules."
        ),
    }


def _share_basis_valid(share_basis: dict[str, Any]) -> bool:
    value = _number(share_basis.get("share_count_value"))
    forward = (
        share_basis.get("forward_share_count_bridge", {})
        if isinstance(share_basis.get("forward_share_count_bridge"), dict)
        else {}
    )
    return (
        value is not None
        and value > 0
        and _iso_date(share_basis.get("share_count_date"))
        and bool(share_basis.get("share_count_source"))
        and share_basis.get("point_in_time_or_forward") == "FORWARD"
        and share_basis.get("forward_share_count_bridge_status") == "COMPLETED"
        and share_basis.get("known_subsequent_event_status")
        in {"REVIEWED_NO_QUANTIFIED_CHANGE", "REVIEWED_CHANGE_REFLECTED"}
        and forward.get("status") == "COMPLETED"
        and _same_number(forward.get("value"), value)
        and forward.get("date") == share_basis.get("share_count_date")
        and forward.get("source") == share_basis.get("share_count_source")
        and bool(forward.get("evidence_ids"))
        and bool(forward.get("reviewed_by"))
    )


def _return_values(
    *,
    current_price: float,
    exit_price: float,
    dividend_per_share: float,
    calendar_days: int,
) -> dict[str, float]:
    price_return = exit_price / current_price - 1.0
    dividend_return = dividend_per_share / current_price
    total_return = (exit_price + dividend_per_share) / current_price - 1.0
    annualized_return = (1.0 + total_return) ** (365.25 / calendar_days) - 1.0
    return {
        "price_return": price_return,
        "dividend_return": dividend_return,
        "total_return": total_return,
        "annualized_return": annualized_return,
    }


def _probability_governance_valid(contract: dict[str, Any]) -> bool:
    probability = contract.get("probability_validation", {})
    approval = probability.get("approval", {})
    return (
        probability.get("status") == "VALIDATED"
        and probability.get("freshness_status") in {"CURRENT", "EXPIRING_SOON"}
        and approval.get("status") == "APPROVED"
        and bool(approval.get("approved_by"))
    )


def build_shared_valuation_contract(
    contract: dict[str, Any],
    supplied: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical S09 valuation object from validated shared inputs."""

    supplied = supplied if isinstance(supplied, dict) else {}
    valuation = contract.get("valuation", {})
    gate_level = float(contract.get("data_gate", {}).get("level", 0))
    current_price = _number(valuation.get("price"))
    price_currency = str(valuation.get("price_currency") or "").upper()
    market_price_date = valuation.get("price_date") or contract.get("report_dates", {}).get(
        "market_price_date"
    )
    input_as_of_date = supplied.get("valuation_as_of_date")
    valuation_as_of_date = input_as_of_date or market_price_date
    target_date = supplied.get("target_date")
    holding_period, holding_issues = _holding_period(
        valuation_as_of_date,
        target_date,
        supplied.get("holding_period_days"),
    )
    forecast_period = normalize_valuation_period(supplied.get("forecast_period"))
    metric_period = normalize_valuation_period(supplied.get("metric_period"))
    dividend = _dividend_assumption(supplied.get("dividend_assumption"), price_currency)
    share_basis = deepcopy(contract.get("share_count_basis", {}))
    exit_basis = _exit_basis(
        contract,
        supplied.get("exit_basis"),
        share_basis,
        forecast_period,
        metric_period,
    )
    requested_status = str(supplied.get("status") or "NOT_DEFINED").upper()
    reviewed_by = str(supplied.get("reviewed_by") or "").strip()
    known_evidence_ids = {
        str(row.get("evidence_id"))
        for row in contract.get("evidence_records", [])
        if row.get("evidence_id")
    }
    forward_share_evidence_ids = set(
        share_basis.get("forward_share_count_bridge", {}).get("evidence_ids", [])
    )
    share_basis_valid = (
        _share_basis_valid(share_basis)
        and forward_share_evidence_ids.issubset(known_evidence_ids)
    )

    issues = list(holding_issues)
    if requested_status != "VALIDATED":
        issues.append(
            {
                "code": "VALUATION_CONTRACT_NOT_REVIEWED",
                "message": "The shared valuation contract has not been submitted as VALIDATED.",
            }
        )
    if not reviewed_by:
        issues.append(
            {
                "code": "VALUATION_CONTRACT_REVIEWER_MISSING",
                "message": "A named reviewer is required.",
            }
        )
    if not _iso_date(input_as_of_date) or input_as_of_date != market_price_date:
        issues.append(
            {
                "code": "VALUATION_AS_OF_DATE_MISMATCH",
                "message": "Valuation as-of date must be explicit and equal the dated market-price input.",
            }
        )
    if not _iso_date(target_date):
        issues.append(
            {
                "code": "TARGET_DATE_MISSING_OR_INVALID",
                "message": "A valid target date is required.",
            }
        )
    if holding_period.get("status") != "VALIDATED":
        issues.append(
            {
                "code": "HOLDING_PERIOD_INVALID",
                "message": "Holding period must reconcile to valid as-of and target dates.",
            }
        )
    if forecast_period.get("status") != "VALIDATED":
        issues.append(
            {
                "code": "FORECAST_PERIOD_NOT_VALIDATED",
                "message": (
                    "Forecast period requires validated dates, a label, period type, and "
                    "an explicit horizon basis."
                ),
            }
        )
    elif not _forecast_period_matches_horizon(
        forecast_period,
        valuation_as_of_date,
        target_date,
    ):
        issues.append(
            {
                "code": "FORECAST_PERIOD_HORIZON_MISMATCH",
                "message": (
                    "S09 formal returns require a HOLDING_PERIOD_FORECAST beginning on "
                    "the valuation date or the next day and ending on the target date."
                ),
            }
        )
    if metric_period.get("status") != "VALIDATED":
        issues.append(
            {
                "code": "VALUATION_METRIC_PERIOD_NOT_VALIDATED",
                "message": (
                    "Valuation metric period requires validated dates, a label, period type, "
                    "and an explicit relationship to the target date."
                ),
            }
        )
    elif not _metric_period_matches_target(
        metric_period,
        valuation_as_of_date,
        target_date,
    ):
        issues.append(
            {
                "code": "VALUATION_METRIC_PERIOD_TARGET_MISMATCH",
                "message": (
                    "The metric period must explicitly end at, start at, or represent a "
                    "point-in-time value at the target date."
                ),
            }
        )
    if dividend.get("status") != "VALIDATED":
        issues.append(
            {
                "code": "DIVIDEND_ASSUMPTION_NOT_VALIDATED",
                "message": "Dividend must be explicitly entered, currency-matched, and reviewed; missing is not zero.",
            }
        )
    if not share_basis_valid:
        issues.append(
            {
                "code": "FORWARD_SHARE_BASIS_NOT_VALIDATED",
                "message": (
                    "Formal return requires a completed forward share-count bridge "
                    "and reviewed subsequent events."
                ),
            }
        )
    elif share_basis.get("share_count_date") != target_date:
        issues.append(
            {
                "code": "FORWARD_SHARE_DATE_TARGET_MISMATCH",
                "message": "The forward per-share denominator must be dated to the valuation target date.",
            }
        )
    if exit_basis.get("status") != "VALIDATED":
        issues.append(
            {
                "code": "EXIT_BASIS_NOT_VALIDATED",
                "message": "Exit or terminal basis must be explicit, reproducible, and reviewer-owned.",
            }
        )
    issue_codes = {row["code"] for row in issues}
    horizon_status = "VALIDATED" if not issues else (
        "NOT_DEFINED" if requested_status == "NOT_DEFINED" else "INVALID"
    )

    price_rows = _scenario_rows(contract, include_values=gate_level >= 3)
    price_rows_valid = (
        gate_level >= 3
        and current_price is not None
        and current_price > 0
        and _iso_date(market_price_date)
        and len(price_rows) == 3
        and {row["name"] for row in price_rows} == {"Bear", "Base", "Bull"}
        and all(
            row["metric_per_share"] is not None
            and row["exit_multiple"] is not None
            and row["implied_price"] is not None
            and row["implied_price"] > 0
            and row["price_change_vs_current"] is not None
            and isclose(
                row["implied_price"],
                row["metric_per_share"] * row["exit_multiple"],
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            and isclose(
                row["price_change_vs_current"],
                row["implied_price"] / current_price - 1.0,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            for row in price_rows
        )
    )
    if gate_level < 3:
        price_status = "SUPPRESSED_BELOW_GATE_3"
        price_rows = []
    elif price_rows_valid:
        price_status = "VALIDATED"
    else:
        price_status = "NOT_EVALUATED"

    price_sensitivity = {
        "status": price_status,
        "valuation_as_of_date": market_price_date,
        "current_price": current_price,
        "currency": price_currency or None,
        "scenarios": price_rows,
        "formula": "price_change_vs_current = implied_price / dated_market_price - 1",
        "input_evidence_ids": sorted(
            {
                str(value)
                for row in price_rows
                for value in row.get("evidence_ids", [])
                if value
            }
        ),
        "formal_return": False,
        "limitations": (
            []
            if price_status == "VALIDATED"
            else ["Gate 3 and three reproducible scenario prices are required."]
        ),
    }

    base_case_return: dict[str, Any] = {
        "status": "NOT_EVALUATED",
        "valuation_as_of_date": valuation_as_of_date,
        "target_date": target_date,
        "holding_period": holding_period,
        "current_price": current_price,
        "exit_price": None,
        "dividend_per_share": dividend.get("amount_per_share"),
        "currency": price_currency or None,
        "price_return": None,
        "dividend_return": None,
        "total_return": None,
        "annualized_return": None,
        "formula": "(base_exit_price + dividends_per_share) / current_price - 1",
        "dividend_reinvestment": False,
        "return_convention": "Cumulative dividends treated as target-date proceeds; no reinvestment.",
        "input_evidence_ids": [],
        "blocking_reasons": sorted(issue_codes),
    }
    base_row = next((row for row in price_rows if row.get("name") == "Base"), None)
    formal_ready = horizon_status == "VALIDATED" and price_status == "VALIDATED"
    if formal_ready and base_row and base_row.get("implied_price") is not None:
        base_values = _return_values(
            current_price=float(current_price),
            exit_price=float(base_row["implied_price"]),
            dividend_per_share=float(dividend["amount_per_share"]),
            calendar_days=int(holding_period["calendar_days"]),
        )
        base_case_return.update(
            {
                "status": "VALIDATED",
                "exit_price": base_row["implied_price"],
                **base_values,
                "input_evidence_ids": sorted(
                    {
                        str(value)
                        for value in (
                            list(base_row.get("evidence_ids", []))
                            + list(dividend.get("evidence_ids", []))
                            + list(share_basis.get("evidence_ids", []))
                            + list(exit_basis.get("evidence_ids", []))
                        )
                        if value
                    }
                ),
                "blocking_reasons": [],
            }
        )

    weighted_return: dict[str, Any] = {
        "status": "NOT_EVALUATED",
        "valuation_as_of_date": valuation_as_of_date,
        "target_date": target_date,
        "holding_period": holding_period,
        "current_price": current_price,
        "expected_exit_price": None,
        "dividend_per_share": dividend.get("amount_per_share"),
        "currency": price_currency or None,
        "price_return": None,
        "dividend_return": None,
        "total_return": None,
        "annualized_return": None,
        "probabilities": {},
        "formula": "sum(probability * scenario total return)",
        "dividend_reinvestment": False,
        "return_convention": "Cumulative dividends treated as target-date proceeds; no reinvestment.",
        "input_evidence_ids": [],
        "blocking_reasons": sorted(
            issue_codes
            | (
                set()
                if _probability_governance_valid(contract)
                else {"PROBABILITY_GOVERNANCE_NOT_VALIDATED"}
            )
        ),
    }
    probability_ready = _probability_governance_valid(contract)
    probabilities = {
        str(row["name"]): row.get("probability")
        for row in price_rows
        if row.get("name")
    }
    probability_math_valid = (
        len(probabilities) == 3
        and all(value is not None and 0 <= value <= 1 for value in probabilities.values())
        and isclose(sum(float(value) for value in probabilities.values()), 1.0, abs_tol=1e-9)
    )
    if formal_ready and probability_ready and probability_math_valid:
        expected_exit_price = sum(
            float(row["probability"]) * float(row["implied_price"]) for row in price_rows
        )
        weighted_values = _return_values(
            current_price=float(current_price),
            exit_price=expected_exit_price,
            dividend_per_share=float(dividend["amount_per_share"]),
            calendar_days=int(holding_period["calendar_days"]),
        )
        weighted_return.update(
            {
                "status": "VALIDATED",
                "expected_exit_price": expected_exit_price,
                **weighted_values,
                "probabilities": probabilities,
                "input_evidence_ids": sorted(
                    {
                        str(value)
                        for value in (
                            [
                                evidence_id
                                for row in price_rows
                                for evidence_id in row.get("evidence_ids", [])
                            ]
                            + list(dividend.get("evidence_ids", []))
                            + list(share_basis.get("evidence_ids", []))
                            + list(exit_basis.get("evidence_ids", []))
                            + list(
                                contract.get("probability_validation", {}).get(
                                    "method_evidence_ids", []
                                )
                            )
                        )
                        if value
                    }
                ),
                "blocking_reasons": [],
            }
        )
    elif probability_ready and not probability_math_valid:
        weighted_return["blocking_reasons"] = sorted(
            set(weighted_return["blocking_reasons"]) | {"SCENARIO_PROBABILITIES_INVALID"}
        )

    partner_internal_input_detected = supplied.get("partner_internal_return") not in (None, "", {}, [])
    partner_internal_return = {
        "status": "DISABLED_PRIVATE_GATE_4_ONLY",
        "expected_return": None,
        "target_return": None,
        "portfolio_hurdle": None,
        "position_sizing": None,
        "private_input_detected_and_discarded": partner_internal_input_detected,
        "reason": (
            "User internal return belongs to the repo-external private Gate 4 overlay and is never "
            "stored in the public issuer contract."
        ),
    }

    return {
        "contract_version": VALUATION_CONTRACT_VERSION,
        "scope": "PUBLIC_COMPANY_EQUITY_VALUATION",
        "status": horizon_status,
        "valuation_as_of_date": valuation_as_of_date,
        "target_date": target_date,
        "holding_period": holding_period,
        "forecast_period": forecast_period,
        "metric_period": metric_period,
        "dividend_assumption": dividend,
        "share_basis": share_basis,
        "exit_basis": exit_basis,
        "formal_return_language_allowed": formal_ready,
        "reviewed_by": reviewed_by or None,
        "validation_issues": issues,
        "outputs": {
            "price_sensitivity": price_sensitivity,
            "base_case_return": base_case_return,
            "probability_weighted_return": weighted_return,
            "partner_internal_return": partner_internal_return,
        },
    }


def legacy_return_context(valuation_contract: dict[str, Any]) -> dict[str, Any]:
    """Project S09 into the legacy field without creating a second calculation."""

    formal_allowed = bool(valuation_contract.get("formal_return_language_allowed"))
    holding = valuation_contract.get("holding_period", {})
    disclosure = (
        "The dated valuation horizon, forecast and metric periods, dividend assumption, forward share "
        "basis, and exit basis are validated. Formal base-case return language is allowed."
        if formal_allowed
        else "The complete dated valuation horizon is not validated. Scenario percentages remain price "
        "sensitivities, not expected, total, or annualized returns and not formal price targets. / "
        "完整的估值时间口径尚未验证；情景百分比仅为价格敏感性，不是预期、总计或年化回报，"
        "也不是正式目标价。"
    )
    return {
        "status": valuation_contract.get("status"),
        "valuation_as_of_date": valuation_contract.get("valuation_as_of_date"),
        "target_date": valuation_contract.get("target_date"),
        "holding_period": holding,
        "forecast_period": valuation_contract.get("forecast_period"),
        "metric_period": valuation_contract.get("metric_period"),
        "dividend_assumption": valuation_contract.get("dividend_assumption"),
        "share_count_basis": valuation_contract.get("share_basis"),
        "exit_basis": valuation_contract.get("exit_basis"),
        "formal_return_language_allowed": formal_allowed,
        "reviewed_by": valuation_contract.get("reviewed_by"),
        "missing_or_invalid_fields": [
            row.get("code") for row in valuation_contract.get("validation_issues", [])
        ],
        "disclosure": disclosure,
    }


def suppress_shared_valuation_outputs(contract: dict[str, Any]) -> None:
    """Apply Data Gate and probability suppression to an existing S09 object."""

    valuation_contract = contract.get("valuation_contract")
    if not isinstance(valuation_contract, dict):
        return
    outputs = valuation_contract.get("outputs", {})
    gate_level = float(contract.get("data_gate", {}).get("level", 0))
    if gate_level < 3:
        valuation_contract["formal_return_language_allowed"] = False
        price = outputs.get("price_sensitivity", {})
        price.update(
            {
                "status": "SUPPRESSED_BELOW_GATE_3",
                "scenarios": [],
                "formal_return": False,
            }
        )
        for name in ("base_case_return", "probability_weighted_return"):
            output = outputs.get(name, {})
            output["status"] = "NOT_EVALUATED"
            for field in (
                "exit_price",
                "expected_exit_price",
                "price_return",
                "dividend_return",
                "total_return",
                "annualized_return",
            ):
                if field in output:
                    output[field] = None
        for row in valuation_contract.get("exit_basis", {}).get(
            "scenario_assumptions", []
        ):
            row["implied_price"] = None
            row["price_change_vs_current"] = None
        exit_basis = valuation_contract.get("exit_basis", {})
        if exit_basis.get("status") == "VALIDATED":
            exit_basis["status"] = "SUPPRESSED_BELOW_GATE_3"
            for field in (
                "share_basis_reconciliation_status",
                "forecast_period_reconciliation_status",
                "metric_period_reconciliation_status",
            ):
                exit_basis[field] = "SUPPRESSED"
    if contract.get("probability_validation", {}).get("status") != "VALIDATED":
        output = outputs.get("probability_weighted_return", {})
        output["status"] = "NOT_EVALUATED"
        for field in (
            "expected_exit_price",
            "price_return",
            "dividend_return",
            "total_return",
            "annualized_return",
        ):
            output[field] = None


def validate_shared_valuation_contract(contract: dict[str, Any]) -> list[str]:
    """Recalculate material S09 outputs and return contract-integrity errors."""

    errors: list[str] = []
    valuation_contract = contract.get("valuation_contract")
    if not isinstance(valuation_contract, dict):
        return ["Missing shared valuation_contract object."]
    if valuation_contract.get("contract_version") != VALUATION_CONTRACT_VERSION:
        errors.append("Unsupported shared valuation-contract version.")
    required = {
        "valuation_as_of_date",
        "target_date",
        "holding_period",
        "forecast_period",
        "metric_period",
        "dividend_assumption",
        "share_basis",
        "exit_basis",
        "outputs",
    }
    missing = sorted(required - set(valuation_contract))
    if missing:
        errors.append("Missing shared valuation fields: " + ", ".join(missing))
        return errors
    if valuation_contract.get("status") not in VALUATION_HORIZON_STATUSES:
        errors.append("Invalid shared valuation-horizon status.")
    for name in ("forecast_period", "metric_period"):
        if valuation_contract.get(name, {}).get("status") not in PERIOD_VALIDATION_STATUSES:
            errors.append(f"Invalid {name} status.")
    outputs = valuation_contract.get("outputs", {})
    if set(outputs) != {
        "price_sensitivity",
        "base_case_return",
        "probability_weighted_return",
        "partner_internal_return",
    }:
        errors.append("Shared valuation outputs must contain exactly the four S09 output classes.")
        return errors
    for name, output in outputs.items():
        if output.get("status") not in VALUATION_OUTPUT_STATUSES:
            errors.append(f"Invalid S09 output status for {name}.")

    price_output = outputs["price_sensitivity"]
    current_price = _number(price_output.get("current_price"))
    parent_valuation = contract.get("valuation", {})
    parent_price = _number(parent_valuation.get("price"))
    if (
        current_price is not None
        and parent_price is not None
        and not isclose(current_price, parent_price, rel_tol=1e-12, abs_tol=1e-12)
    ):
        errors.append("Shared valuation current price disagrees with the authoritative valuation object.")
    parent_price_date = parent_valuation.get("price_date") or contract.get("report_dates", {}).get(
        "market_price_date"
    )
    parent_currency = str(parent_valuation.get("price_currency") or "").upper()
    if valuation_contract.get("valuation_as_of_date") != parent_price_date:
        errors.append("Valuation horizon as-of date disagrees with the authoritative market-price date.")
    if price_output.get("valuation_as_of_date") != parent_price_date:
        errors.append("Price-sensitivity as-of date disagrees with the authoritative market-price date.")
    if valuation_contract.get("share_basis") != contract.get("share_count_basis", {}):
        errors.append("Shared valuation share basis disagrees with the authoritative share-count object.")
    known_evidence_ids = {
        str(row.get("evidence_id"))
        for row in contract.get("evidence_records", [])
        if row.get("evidence_id")
    }
    forward_share_evidence_ids = set(
        valuation_contract.get("share_basis", {})
        .get("forward_share_count_bridge", {})
        .get("evidence_ids", [])
    )
    unresolved_forward_ids = sorted(forward_share_evidence_ids - known_evidence_ids)
    if unresolved_forward_ids:
        errors.append(
            f"Forward share-count bridge contains unknown evidence IDs: {unresolved_forward_ids}."
        )
    expected_formal_flag = (
        valuation_contract.get("status") == "VALIDATED"
        and price_output.get("status") == "VALIDATED"
    )
    if bool(valuation_contract.get("formal_return_language_allowed")) != expected_formal_flag:
        errors.append("Formal-return language flag disagrees with horizon and price validation.")
    if valuation_contract.get("status") == "VALIDATED":
        if not _forecast_period_matches_horizon(
            valuation_contract.get("forecast_period", {}),
            valuation_contract.get("valuation_as_of_date"),
            valuation_contract.get("target_date"),
        ):
            errors.append("Validated forecast period does not match the valuation horizon.")
        if not _metric_period_matches_target(
            valuation_contract.get("metric_period", {}),
            valuation_contract.get("valuation_as_of_date"),
            valuation_contract.get("target_date"),
        ):
            errors.append("Validated metric period does not have an allowed target-date relationship.")
        rebuilt_holding, holding_issues = _holding_period(
            valuation_contract.get("valuation_as_of_date"),
            valuation_contract.get("target_date"),
            valuation_contract.get("holding_period", {}).get("calendar_days"),
        )
        if holding_issues or rebuilt_holding != valuation_contract.get("holding_period"):
            errors.append("Validated holding period does not reconcile to authoritative dated endpoints.")
        rebuilt_dividend = _dividend_assumption(
            valuation_contract.get("dividend_assumption"),
            parent_currency,
        )
        if rebuilt_dividend != valuation_contract.get("dividend_assumption"):
            errors.append("Validated dividend assumption fails canonical semantic validation.")
        exit_basis = valuation_contract.get("exit_basis", {})
        exit_status_allowed = (
            exit_basis.get("status") == "VALIDATED"
            if price_output.get("status") == "VALIDATED"
            else exit_basis.get("status") == "SUPPRESSED_BELOW_GATE_3"
        )
        if (
            not exit_status_allowed
            or exit_basis.get("method") not in EXIT_METHODS
            or exit_basis.get("terminal_or_exit") not in EXIT_TIMINGS
        ):
            errors.append("Validated valuation horizon requires an allowed exit-basis method and timing.")
    if price_output.get("status") == "VALIDATED":
        if current_price is None or current_price <= 0:
            errors.append("Validated price sensitivity requires a positive current price.")
        parent_rows = {
            str(row.get("name")): row for row in contract.get("scenarios", [])
        }
        for row in price_output.get("scenarios", []):
            name = str(row.get("name"))
            implied = _number(row.get("implied_price"))
            change = _number(row.get("price_change_vs_current"))
            parent = parent_rows.get(name, {})
            if implied is None or change is None or current_price is None:
                errors.append(f"Validated price sensitivity has incomplete {name} values.")
                continue
            metric_per_share = _number(row.get("metric_per_share"))
            exit_multiple = _number(row.get("exit_multiple"))
            if (
                metric_per_share is None
                or exit_multiple is None
                or not isclose(
                    implied,
                    metric_per_share * exit_multiple,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
            ):
                errors.append(f"Price-sensitivity implied price does not reproduce for {name}.")
            if not isclose(change, implied / current_price - 1.0, rel_tol=1e-9, abs_tol=1e-9):
                errors.append(f"Price-sensitivity calculation does not reproduce for {name}.")
            if not _same_number(implied, parent.get("implied_price")):
                errors.append(f"Price-sensitivity output disagrees with shared scenario {name}.")
            if not _same_number(
                change,
                parent.get("price_change_vs_current"),
            ):
                errors.append(f"Price-sensitivity change disagrees with shared scenario {name}.")

    if valuation_contract.get("exit_basis", {}).get("status") == "VALIDATED":
        parent_rows = {
            str(row.get("name") or ""): row for row in contract.get("scenarios", [])
        }
        for row in valuation_contract.get("exit_basis", {}).get("scenario_assumptions", []):
            parent = parent_rows.get(str(row.get("name") or ""), {})
            for field in (
                "metric_per_share",
                "exit_multiple",
                "implied_price",
                "share_count_basis_value",
            ):
                actual = _number(row.get(field))
                expected = _number(
                    parent.get(field)
                    if parent.get(field) is not None
                    else (
                        contract.get("valuation", {}).get("shares")
                        if field == "share_count_basis_value"
                        else None
                    )
                )
                if not _same_number(actual, expected):
                    errors.append(
                        f"Exit-basis scenario {row.get('name')} disagrees with "
                        f"shared scenario field {field}."
                    )
            expected_share_date = (
                parent.get("share_count_basis_date")
                or contract.get("valuation", {}).get("shares_as_of_date")
            )
            if row.get("share_count_basis_date") != expected_share_date:
                errors.append(
                    f"Exit-basis scenario {row.get('name')} disagrees with "
                    "the shared scenario share date."
                )
            for field in ("forecast_period", "metric_period"):
                if row.get(field) != parent.get(field):
                    errors.append(
                        f"Exit-basis scenario {row.get('name')} disagrees with "
                        f"the shared scenario {field}."
                    )

    holding = valuation_contract.get("holding_period", {})
    dividend_object = valuation_contract.get("dividend_assumption", {})
    dividend = _number(dividend_object.get("amount_per_share"))
    authoritative_rows = {
        str(row.get("name") or ""): row for row in contract.get("scenarios", [])
    }
    base = outputs["base_case_return"]
    if base.get("status") == "VALIDATED":
        if not valuation_contract.get("formal_return_language_allowed"):
            errors.append("Validated base-case return requires formal-return language permission.")
        if valuation_contract.get("status") != "VALIDATED":
            errors.append("Validated base-case return requires a validated valuation horizon.")
        authoritative_base_price = _number(
            authoritative_rows.get("Base", {}).get("implied_price")
        )
        if not _same_number(base.get("current_price"), parent_price):
            errors.append("Base-case current price disagrees with the authoritative valuation object.")
        if not _same_number(base.get("exit_price"), authoritative_base_price):
            errors.append("Base-case exit price disagrees with the authoritative Base scenario.")
        if not _same_number(base.get("dividend_per_share"), dividend):
            errors.append("Base-case dividend disagrees with the validated dividend assumption.")
        if base.get("currency") != parent_currency:
            errors.append("Base-case currency disagrees with the authoritative market-price currency.")
        if (
            base.get("valuation_as_of_date") != valuation_contract.get("valuation_as_of_date")
            or base.get("target_date") != valuation_contract.get("target_date")
            or base.get("holding_period") != holding
        ):
            errors.append("Base-case return horizon disagrees with the shared valuation horizon.")
        if (
            parent_price is None
            or authoritative_base_price is None
            or dividend is None
            or holding.get("calendar_days") is None
        ):
            errors.append("Validated base-case return lacks authoritative calculation inputs.")
        else:
            expected = _return_values(
                current_price=parent_price,
                exit_price=authoritative_base_price,
                dividend_per_share=dividend,
                calendar_days=int(holding["calendar_days"]),
            )
            for field, value in expected.items():
                if not _same_number(base.get(field), value):
                    errors.append(f"Base-case {field} does not reproduce from authoritative inputs.")

    weighted = outputs["probability_weighted_return"]
    if weighted.get("status") == "VALIDATED":
        if not _probability_governance_valid(contract):
            errors.append("Validated weighted return lacks validated probability governance.")
        rows = price_output.get("scenarios", [])
        probabilities = {
            str(row.get("name") or ""): _number(row.get("probability")) for row in rows
        }
        expected_exit = (
            sum(
                float(row["probability"]) * float(row["implied_price"])
                for row in rows
            )
            if len(rows) == 3
            and all(
                _number(row.get("probability")) is not None
                and _number(row.get("implied_price")) is not None
                for row in rows
            )
            else None
        )
        if weighted.get("probabilities") != probabilities:
            errors.append("Probability-weighted output probabilities disagree with shared scenarios.")
        if not _same_number(weighted.get("current_price"), parent_price):
            errors.append(
                "Probability-weighted current price disagrees with the authoritative valuation object."
            )
        if not _same_number(weighted.get("dividend_per_share"), dividend):
            errors.append(
                "Probability-weighted dividend disagrees with the validated dividend assumption."
            )
        if weighted.get("currency") != parent_currency:
            errors.append(
                "Probability-weighted currency disagrees with the authoritative market-price currency."
            )
        if (
            weighted.get("valuation_as_of_date") != valuation_contract.get("valuation_as_of_date")
            or weighted.get("target_date") != valuation_contract.get("target_date")
            or weighted.get("holding_period") != holding
        ):
            errors.append(
                "Probability-weighted return horizon disagrees with the shared valuation horizon."
            )
        if not _same_number(weighted.get("expected_exit_price"), expected_exit):
            errors.append("Probability-weighted exit price does not reproduce.")
        if (
            parent_price is None
            or expected_exit is None
            or dividend is None
            or holding.get("calendar_days") is None
        ):
            errors.append("Validated weighted return lacks authoritative calculation inputs.")
        else:
            expected = _return_values(
                current_price=parent_price,
                exit_price=expected_exit,
                dividend_per_share=dividend,
                calendar_days=int(holding["calendar_days"]),
            )
            for field, value in expected.items():
                if not _same_number(weighted.get(field), value):
                    errors.append(
                        f"Probability-weighted {field} does not reproduce from authoritative inputs."
                    )

    user = outputs["partner_internal_return"]
    if user.get("status") != "DISABLED_PRIVATE_GATE_4_ONLY":
        errors.append("User internal return must remain disabled in the public issuer contract.")
    for field in ("expected_return", "target_return", "portfolio_hurdle", "position_sizing"):
        if user.get(field) is not None:
            errors.append(f"Public issuer contract must not retain private field {field}.")
    return errors
