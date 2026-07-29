#!/usr/bin/env python3
"""Build a generic SEC public-company decision-support data pack.

The goal is to make the public-company skill usable when a user provides an
arbitrary SEC-reporting company name or ticker. It creates a period-aware data
table, a validation report, and a human-readable investment-support data pack.

This is not a buy/sell model. It is the data-integrity and credit/liquidity
foundation required before a full investment memo.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import re
import sys
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from underwriting_contract import (
    CashFlowLedgerLine,
    SCHEMA_VERSION,
    assess_supported_universe,
    detect_material_conflicts,
    make_evidence_id,
    stable_id,
    utc_now,
    validate_cash_flow_ledger,
)


SEC_UA = os.environ.get(
    "SEC_USER_AGENT",
    "public-company-investment-underwriting contact@example.com",
)
SEC_BASE = "https://data.sec.gov"
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_ROOT = ROOT / "partner-demo" / "investment_decision_v2" / "generic_outputs"


INSTANT_TAGS: dict[str, tuple[str, ...]] = {
    "unrestricted_cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "Cash",
        "CashAndDueFromBanks",
    ),
    "restricted_cash": (
        "RestrictedCash",
        "RestrictedCashAndCashEquivalentsAtCarryingValue",
        "RestrictedCashAndCashEquivalentsNoncurrent",
    ),
    "cash_and_restricted_cash": (
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
    ),
    "short_term_investments": (
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    ),
    "accounts_receivable_net": (
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
        "ContractWithCustomerReceivableBeforeAllowanceForCreditLossCurrent",
        "AccountsNotesAndLoansReceivableNetCurrent",
    ),
    "allowance_for_credit_losses_ar": (
        "AllowanceForDoubtfulAccountsReceivableCurrent",
        "AllowanceForDoubtfulAccountsReceivable",
        "AllowanceForCreditLossesOnAccountsReceivable",
    ),
    "inventory_net": (
        "InventoryNet",
        "InventoryFinishedGoodsNetOfReserves",
        "InventoryGross",
    ),
    "accounts_payable": (
        "AccountsPayableCurrent",
        "AccountsPayableTradeCurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
        "AccountsPayableAndOtherAccruedLiabilitiesCurrent",
    ),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "shareholders_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "current_debt": (
        "DebtCurrent",
        "ShortTermBorrowings",
        "ShortTermDebtCurrent",
        "LongTermDebtCurrent",
        "ConvertibleDebtCurrent",
    ),
    "long_term_debt": (
        "LongTermDebtNoncurrent",
        "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
        "ConvertibleDebtNoncurrent",
    ),
    "finance_lease_current": ("FinanceLeaseLiabilityCurrent",),
    "finance_lease_noncurrent": ("FinanceLeaseLiabilityNoncurrent",),
    "operating_lease_current": ("OperatingLeaseLiabilityCurrent",),
    "operating_lease_noncurrent": ("OperatingLeaseLiabilityNoncurrent",),
}


FLOW_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ),
    "cogs": (
        "CostOfGoodsAndServicesSold",
        "CostOfRevenue",
        "CostOfGoodsSold",
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "cfo": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "CapitalExpendituresIncurredButNotYetPaid",
    ),
    "interest_paid": ("InterestPaidNet", "InterestPaid", "InterestPaidOperatingActivities"),
    "interest_expense": ("InterestExpenseNonOperating", "InterestExpense", "InterestExpenseDebt"),
    "share_repurchases": (
        "PaymentsForRepurchaseOfCommonStock",
        "PaymentsForRepurchaseOfEquity",
    ),
    "dividends_paid": (
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfOrdinaryDividends",
    ),
    "debt_issuance": (
        "ProceedsFromIssuanceOfLongTermDebt",
        "ProceedsFromIssuanceOfDebt",
    ),
    "debt_repayment": (
        "RepaymentsOfLongTermDebt",
        "RepaymentsOfDebt",
    ),
    "business_acquisitions": (
        "PaymentsToAcquireBusinessesNetOfCashAcquired",
        "PaymentsToAcquireBusinessesGrossOfCashAcquired",
    ),
}


AP_LABELS = (
    "Accounts payable, accrued expenses and other liabilities",
    "Trade accounts payable and outstanding checks in excess of deposits",
    "Trade accounts payable",
    "Accounts payable and accrued expenses",
    "Accounts payable",
)

TRADE_AP_COMPATIBLE_TAGS = {
    "us-gaap:AccountsPayableCurrent",
    "us-gaap:AccountsPayableTradeCurrent",
}


def ap_balance_is_trade_compatible(source_tag: Any) -> bool:
    return str(source_tag) in TRADE_AP_COMPATIBLE_TAGS


def derive_total_liabilities(total_assets: Any, shareholders_equity: Any) -> float | None:
    assets = safe_float(total_assets)
    equity = safe_float(shareholders_equity)
    if assets is None or equity is None:
        return None
    derived = assets - equity
    return derived if derived >= 0 else None


@dataclass
class Filing:
    form: str
    filed: str
    period: str
    accession: str
    primary_doc: str
    url: str


@dataclass
class DataPoint:
    metric_name: str
    value: Any
    unit: str
    currency: str
    period_start: str
    period_end: str
    period_type: str
    duration_days: Any
    fiscal_period: str
    filing_type: str
    filing_date: str
    source_location: str
    source_tag: str
    source_url: str
    evidence_type: str
    reported_or_calculated: str
    confidence: str
    validation_status: str
    notes: str = ""
    evidence_id: str = ""
    scale: float = 1.0
    as_of_date: str = ""
    measurement_basis: str = "reported"
    publication_date: str = ""
    retrieval_date: str = ""
    source_level: int = 1
    source_type: str = "regulatory_filing"
    source_name: str = "SEC filing"
    source_id: str = ""
    source_locator: str = ""
    evidence_class: str = "FACT"
    formula: str = ""
    input_evidence_ids: list[str] | None = None
    subsequent_event_status: str = "NOT_REVIEWED"


S06_DATA_CONTROL_VERSION = "1.0.0"
SEC_FINANCIAL_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}
QUARTER_MIN_DAYS = 70
QUARTER_MAX_DAYS = 105
ANNUAL_MIN_DAYS = 350
ANNUAL_MAX_DAYS = 380
COMPARABLE_YTD_DURATION_TOLERANCE_DAYS = 7
COMPARABLE_FISCAL_SHIFT_MIN_DAYS = 350
COMPARABLE_FISCAL_SHIFT_MAX_DAYS = 380


def unit_profile(unit: Any) -> dict[str, str]:
    """Classify an SEC unit without assuming that every monetary fact is USD."""

    raw = str(unit or "").strip()
    normalized = raw.replace("iso4217:", "")
    if normalized == "shares":
        return {"unit": raw, "category": "SHARES", "currency": ""}
    if normalized == "pure":
        return {"unit": raw, "category": "PURE", "currency": ""}

    match = re.fullmatch(r"([A-Z]{3})(?:/(?:shares?|common shares?))?", normalized)
    if match:
        category = "MONETARY_PER_SHARE" if "/" in normalized else "MONETARY"
        return {"unit": raw, "category": category, "currency": match.group(1)}
    return {"unit": raw, "category": "UNKNOWN", "currency": ""}


def fact_context_kind(point: dict[str, Any]) -> str:
    start = str(point.get("start") or "")
    end = str(point.get("end") or point.get("instant") or "")
    if end and not start:
        return "INSTANT"
    if start and end:
        return "FLOW"
    return "INVALID"


def is_quarter_flow(point: dict[str, Any]) -> bool:
    duration = days_between(point.get("start"), point.get("end")) or 0
    return (
        fact_context_kind(point) == "FLOW"
        and str(point.get("form", "")).upper() in {"10-Q", "10-Q/A"}
        and QUARTER_MIN_DAYS <= duration <= QUARTER_MAX_DAYS
    )


def is_ytd_flow(point: dict[str, Any]) -> bool:
    duration = days_between(point.get("start"), point.get("end")) or 0
    if (
        fact_context_kind(point) != "FLOW"
        or str(point.get("form", "")).upper() not in {"10-Q", "10-Q/A"}
    ):
        return False
    fiscal_period = str(point.get("fp") or "").upper()
    if fiscal_period == "Q1":
        return QUARTER_MIN_DAYS <= duration <= QUARTER_MAX_DAYS
    if fiscal_period == "Q2":
        return 140 <= duration <= 210
    if fiscal_period == "Q3":
        return 220 <= duration < ANNUAL_MIN_DAYS
    return QUARTER_MAX_DAYS < duration < ANNUAL_MIN_DAYS


def is_annual_flow(point: dict[str, Any]) -> bool:
    duration = days_between(point.get("start"), point.get("end")) or 0
    return (
        fact_context_kind(point) == "FLOW"
        and str(point.get("form", "")).upper() in {"10-K", "10-K/A"}
        and ANNUAL_MIN_DAYS <= duration <= ANNUAL_MAX_DAYS
    )


def fiscal_calendar_profile(annual_point: dict[str, Any] | None) -> dict[str, Any]:
    """Describe a fiscal year from its reported dates, including 53-week years."""

    if not annual_point or not is_annual_flow(annual_point):
        return {
            "status": "MISSING",
            "control_version": S06_DATA_CONTROL_VERSION,
            "reason": "No validated annual flow context is available.",
        }

    start = str(annual_point.get("start") or "")
    end = str(annual_point.get("end") or "")
    start_date = parse_date(start)
    end_date = parse_date(end)
    duration = days_between(start, end)
    if not start_date or not end_date or duration is None:
        return {
            "status": "INVALID",
            "control_version": S06_DATA_CONTROL_VERSION,
            "reason": "Annual context dates are invalid.",
        }

    calendar_basis = (
        "CALENDAR_YEAR"
        if (start_date.month, start_date.day, end_date.month, end_date.day)
        == (1, 1, 12, 31)
        else "NON_CALENDAR_FISCAL_YEAR"
    )
    if 368 <= duration <= 374:
        week_structure = "53_WEEK"
    elif (
        360 <= duration <= 367
        and start_date.weekday() == (end_date.weekday() + 1) % 7
    ):
        week_structure = "52_WEEK"
    else:
        week_structure = "DATE_BASED"

    return {
        "status": "PASS",
        "control_version": S06_DATA_CONTROL_VERSION,
        "fiscal_year_start": start,
        "fiscal_year_end": end,
        "duration_days": duration,
        "calendar_basis": calendar_basis,
        "week_structure": week_structure,
        "is_non_calendar_fiscal_year": calendar_basis == "NON_CALENDAR_FISCAL_YEAR",
        "is_53_week_fiscal_year": week_structure == "53_WEEK",
        "source_tag": annual_point.get("tag", ""),
        "unit": annual_point.get("unit", ""),
        "currency": unit_profile(annual_point.get("unit"))["currency"],
    }


def comparable_ytd_periods(current: dict[str, Any], prior: dict[str, Any]) -> tuple[bool, str]:
    """Require comparable fiscal periods while allowing a one-week 53-week shift."""

    if not is_ytd_flow(current) or not is_ytd_flow(prior):
        return False, "Both inputs must be validated 10-Q YTD flow contexts."
    if current.get("tag") != prior.get("tag"):
        return False, "Current and prior YTD concepts differ."
    if current.get("unit") != prior.get("unit"):
        return False, "Current and prior YTD units differ."
    if unit_profile(current.get("unit"))["currency"] != unit_profile(prior.get("unit"))["currency"]:
        return False, "Current and prior YTD currencies differ."
    current_fp = str(current.get("fp") or "")
    prior_fp = str(prior.get("fp") or "")
    if current_fp and prior_fp and current_fp != prior_fp:
        return False, "Current and prior YTD fiscal-period labels differ."

    current_duration = days_between(current.get("start"), current.get("end")) or 0
    prior_duration = days_between(prior.get("start"), prior.get("end")) or 0
    if abs(current_duration - prior_duration) > COMPARABLE_YTD_DURATION_TOLERANCE_DAYS:
        return False, "Current and prior YTD durations differ by more than seven days."

    current_start = parse_date(current.get("start"))
    current_end = parse_date(current.get("end"))
    prior_start = parse_date(prior.get("start"))
    prior_end = parse_date(prior.get("end"))
    if not all((current_start, current_end, prior_start, prior_end)):
        return False, "A YTD comparison date is invalid."
    start_shift = (current_start - prior_start).days
    end_shift = (current_end - prior_end).days
    if not (
        COMPARABLE_FISCAL_SHIFT_MIN_DAYS <= start_shift <= COMPARABLE_FISCAL_SHIFT_MAX_DAYS
        and COMPARABLE_FISCAL_SHIFT_MIN_DAYS <= end_shift <= COMPARABLE_FISCAL_SHIFT_MAX_DAYS
    ):
        return False, "Current and prior YTD contexts are not one comparable fiscal year apart."
    return True, "Comparable concept, unit, currency, fiscal label, duration, and fiscal-year shift."


def controlled_ratio(
    numerator: Any,
    denominator: Any,
    *,
    multiplier: float = 1.0,
    require_positive_denominator: bool = True,
) -> dict[str, Any]:
    """Return a ratio or a structured safe suppression; never divide implicitly."""

    numerator_value = safe_float(numerator)
    denominator_value = safe_float(denominator)
    if numerator_value is None or denominator_value is None:
        return {"status": "MISSING", "value": None, "reason": "Numerator or denominator is missing."}
    if not math.isfinite(numerator_value) or not math.isfinite(denominator_value):
        return {"status": "SUPPRESSED", "value": None, "reason": "Numerator or denominator is non-finite."}
    if denominator_value == 0:
        return {"status": "SUPPRESSED", "value": None, "reason": "Denominator is zero."}
    if require_positive_denominator and denominator_value < 0:
        return {"status": "SUPPRESSED", "value": None, "reason": "Denominator is negative."}
    return {
        "status": "PASS",
        "value": numerator_value / denominator_value * multiplier,
        "reason": "Validated denominator.",
    }


def compatible_monetary_inputs(*rows: DataPoint | None) -> dict[str, Any]:
    present = [row for row in rows if row is not None]
    if not present:
        return {"status": "MISSING", "currency": "", "unit": "", "reason": "No monetary inputs are available."}
    profiles = [unit_profile(row.unit) for row in present]
    if any(profile["category"] != "MONETARY" for profile in profiles):
        return {
            "status": "INCOMPATIBLE",
            "currency": "",
            "unit": "",
            "reason": "At least one input is not a monetary unit.",
        }
    currencies = {profile["currency"] for profile in profiles}
    if len(currencies) != 1 or "" in currencies:
        return {
            "status": "INCOMPATIBLE",
            "currency": "",
            "unit": "",
            "reason": "Monetary input currencies differ or are unknown.",
        }
    return {
        "status": "PASS",
        "currency": profiles[0]["currency"],
        "unit": present[0].unit,
        "reason": "Monetary input currencies are compatible.",
    }


def fact_points_any_taxonomy(companyfacts: dict[str, Any], tag: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for taxonomy, facts in companyfacts.get("facts", {}).items():
        item = facts.get(tag)
        if not item:
            continue
        for unit, values in item.get("units", {}).items():
            for value in values:
                point = dict(value)
                point["unit"] = unit
                point["tag"] = tag
                point["taxonomy"] = taxonomy
                out.append(point)
    return out


def latest_share_count_fact(
    companyfacts: dict[str, Any],
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Select a point-in-time share count without future-publication leakage."""

    candidates: list[dict[str, Any]] = []
    for tag in ("EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"):
        candidates.extend(fact_points_any_taxonomy(companyfacts, tag))

    eligible = [
        point
        for point in candidates
        if point.get("val") is not None
        and unit_profile(point.get("unit"))["category"] == "SHARES"
        and fact_context_kind(point) == "INSTANT"
        and str(point.get("form", "")).upper() in SEC_FINANCIAL_FORMS
    ]
    if as_of_date:
        eligible = [
            point
            for point in eligible
            if str(point.get("end") or point.get("instant") or "") <= as_of_date
            and str(point.get("filed") or "") <= as_of_date
        ]
    if not eligible:
        return {
            "status": "MISSING",
            "value": None,
            "point": None,
            "reason": "No published point-in-time share-count fact is available on or before the requested date.",
        }

    eligible.sort(
        key=lambda point: (
            point.get("end") or point.get("instant") or "",
            point.get("filed", ""),
            point.get("accn", ""),
        )
    )
    latest_date = str(eligible[-1].get("end") or eligible[-1].get("instant") or "")
    latest_filed = str(eligible[-1].get("filed") or "")
    latest = [
        point
        for point in eligible
        if str(point.get("end") or point.get("instant") or "") == latest_date
        and str(point.get("filed") or "") == latest_filed
    ]
    distinct_values = sorted(
        {
            value
            for point in latest
            if (value := safe_float(point.get("val"))) is not None
        }
    )
    if len(distinct_values) > 1:
        return {
            "status": "CONFLICT",
            "value": None,
            "point": None,
            "reason": "Multiple different share counts exist for the latest date and filing date; class or dimensional reconciliation is required.",
            "candidate_values": distinct_values,
            "share_count_date": latest_date,
            "publication_date": latest_filed,
        }

    chosen = latest[-1]
    return {
        "status": "PASS",
        "value": safe_float(chosen.get("val")),
        "point": chosen,
        "reason": "Latest published point-in-time share count on or before the requested date.",
        "share_count_date": latest_date,
        "publication_date": latest_filed,
    }


def source_summary_from_fact(point: dict[str, Any] | None) -> dict[str, Any] | None:
    if not point:
        return None
    return {
        "tag": point.get("tag"),
        "taxonomy": point.get("taxonomy", "us-gaap"),
        "unit": point.get("unit"),
        "currency": unit_profile(point.get("unit"))["currency"],
        "value": point.get("val"),
        "form": point.get("form"),
        "fy": point.get("fy"),
        "fp": point.get("fp"),
        "start": point.get("start"),
        "end": point.get("end"),
        "filed": point.get("filed"),
        "accn": point.get("accn"),
    }


def flow_points_for_tags(
    companyfacts: dict[str, Any],
    tags: tuple[str, ...],
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for tag in tags:
        points.extend(
            point
            for point in fact_points_any_taxonomy(companyfacts, tag)
            if point.get("val") is not None
            and fact_context_kind(point) == "FLOW"
            and str(point.get("form", "")).upper() in SEC_FINANCIAL_FORMS
            and unit_profile(point.get("unit"))["category"] == "MONETARY"
        )
    return points


def select_latest_annual_from_points(
    points: list[dict[str, Any]],
    annual_period: str | None,
) -> dict[str, Any] | None:
    annuals = [point for point in points if is_annual_flow(point)]
    if annual_period:
        exact = [point for point in annuals if point.get("end") == annual_period]
        if exact:
            annuals = exact
    if not annuals:
        return None
    annuals.sort(
        key=lambda point: (
            point.get("end", ""),
            point.get("filed", ""),
            days_between(point.get("start"), point.get("end")) or 0,
            point.get("accn", ""),
        )
    )
    return annuals[-1]


def select_latest_ytd_from_points(
    points: list[dict[str, Any]],
    latest_q_period: str | None,
) -> dict[str, Any] | None:
    if not latest_q_period:
        return None
    candidates = [
        point
        for point in points
        if point.get("end") == latest_q_period and is_ytd_flow(point)
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda point: (
            days_between(point.get("start"), point.get("end")) or 0,
            point.get("filed", ""),
            point.get("accn", ""),
        )
    )
    return candidates[-1]


def select_prior_comparable_ytd_from_points(
    points: list[dict[str, Any]],
    current_ytd: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not current_ytd:
        return None
    candidates = [
        point
        for point in points
        if point.get("end", "") < current_ytd.get("end", "")
        and comparable_ytd_periods(current_ytd, point)[0]
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda point: (
            point.get("end", ""),
            point.get("filed", ""),
            point.get("accn", ""),
        )
    )
    return candidates[-1]


def build_ltm_metric(
    companyfacts: dict[str, Any],
    metric: str,
    latest_q_period: str | None,
    annual_period: str | None,
) -> dict[str, Any]:
    """Build LTM from one concept and comparable fiscal contexts, or fall back safely."""

    if metric not in FLOW_TAGS:
        return {
            "metric": metric,
            "value": None,
            "method": "missing",
            "period_type": "missing",
            "confidence": "Low",
            "evidence_type": "MISSING",
            "validation_status": "MISSING_XBRL_TAG",
            "components": {},
        }

    first_annual_fallback: dict[str, Any] | None = None
    rejected_reasons: list[str] = []
    for tag in FLOW_TAGS[metric]:
        points = flow_points_for_tags(companyfacts, (tag,))
        if not points:
            continue
        annual = select_latest_annual_from_points(points, annual_period)
        if annual and first_annual_fallback is None:
            first_annual_fallback = annual

        current = select_latest_ytd_from_points(points, latest_q_period)
        if not annual or not current:
            rejected_reasons.append(f"{tag}: annual or current YTD context missing.")
            continue

        prior_candidates = [
            point
            for point in points
            if point.get("end", "") < current.get("end", "")
            and is_ytd_flow(point)
        ]
        comparable_prior: list[dict[str, Any]] = []
        for point in prior_candidates:
            comparable, reason = comparable_ytd_periods(current, point)
            if comparable:
                comparable_prior.append(point)
            else:
                rejected_reasons.append(f"{tag}: {reason}")
        prior = select_prior_comparable_ytd_from_points(comparable_prior, current)
        if not prior:
            continue

        annual_end = parse_date(annual.get("end"))
        current_start = parse_date(current.get("start"))
        if not annual_end or not current_start:
            rejected_reasons.append(f"{tag}: annual-to-current period chain has invalid dates.")
            continue
        chain_gap = (current_start - annual_end).days
        if not 1 <= chain_gap <= 14:
            rejected_reasons.append(f"{tag}: annual-to-current period chain gap is {chain_gap} days.")
            continue
        if len({annual.get("unit"), current.get("unit"), prior.get("unit")}) != 1:
            rejected_reasons.append(f"{tag}: annual and YTD units differ.")
            continue
        if len(
            {
                unit_profile(annual.get("unit"))["currency"],
                unit_profile(current.get("unit"))["currency"],
                unit_profile(prior.get("unit"))["currency"],
            }
        ) != 1:
            rejected_reasons.append(f"{tag}: annual and YTD currencies differ.")
            continue

        annual_value = safe_float(annual.get("val"))
        current_value = safe_float(current.get("val"))
        prior_value = safe_float(prior.get("val"))
        if None in (annual_value, current_value, prior_value):
            rejected_reasons.append(f"{tag}: an LTM component is nonnumeric.")
            continue
        return {
            "metric": metric,
            "value": annual_value + current_value - prior_value,
            "method": "annual + latest YTD - prior-year comparable YTD using one XBRL concept",
            "period_type": "LTM",
            "confidence": "High",
            "evidence_type": "CALC",
            "validation_status": "PASS",
            "unit": annual.get("unit"),
            "currency": unit_profile(annual.get("unit"))["currency"],
            "components": {
                "annual": source_summary_from_fact(annual),
                "current_ytd": source_summary_from_fact(current),
                "prior_year_ytd": source_summary_from_fact(prior),
            },
            "rejected_reasons": sorted(set(rejected_reasons)),
        }

    if first_annual_fallback:
        return {
            "metric": metric,
            "value": safe_float(first_annual_fallback.get("val")),
            "method": "latest annual fallback; LTM components did not pass shared comparability controls",
            "period_type": "annual",
            "confidence": "Medium",
            "evidence_type": "FACT",
            "validation_status": "LTM_NOT_AVAILABLE",
            "unit": first_annual_fallback.get("unit"),
            "currency": unit_profile(first_annual_fallback.get("unit"))["currency"],
            "components": {"annual": source_summary_from_fact(first_annual_fallback)},
            "rejected_reasons": sorted(set(rejected_reasons)),
        }

    return {
        "metric": metric,
        "value": None,
        "method": "missing",
        "period_type": "missing",
        "confidence": "Low",
        "evidence_type": "MISSING",
        "validation_status": "MISSING_XBRL_TAG",
        "components": {},
        "rejected_reasons": sorted(set(rejected_reasons)),
    }


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read().decode("utf-8", errors="replace")


def cik10(cik: int | str) -> str:
    return str(cik).zfill(10)


def cik_short(cik: int | str) -> str:
    return str(int(cik))


def slugify(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", text.strip().lower())
    return re.sub(r"_+", "_", text).strip("_")[:80] or "company"


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def days_between(start: str | None, end: str | None) -> int | None:
    s = parse_date(start)
    e = parse_date(end)
    if not s or not e:
        return None
    return (e - s).days + 1


def fmt_usd(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value / 1_000_000:,.1f}m"


def fmt_num(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:,.1f}{suffix}"


def safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def near(a: float | None, b: float | None, tolerance: float = 1.0) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tolerance


def resolve_company(query: str) -> dict[str, Any]:
    data = fetch_json(TICKERS_URL)
    rows = data.get("data", [])
    q = query.strip()
    q_upper = q.upper()
    exact_ticker = [r for r in rows if str(r[2]).upper() == q_upper]
    if exact_ticker:
        r = exact_ticker[0]
        return {"cik": cik10(r[0]), "name": r[1], "ticker": str(r[2]).upper(), "exchange": r[3]}

    q_norm = re.sub(r"\s+", " ", q.lower())
    exact_name = [r for r in rows if re.sub(r"\s+", " ", str(r[1]).lower()) == q_norm]
    if exact_name:
        r = exact_name[0]
        return {"cik": cik10(r[0]), "name": r[1], "ticker": str(r[2]).upper(), "exchange": r[3]}

    contains = [r for r in rows if q_norm in str(r[1]).lower()]
    if contains:
        contains.sort(key=lambda r: (0 if str(r[3]) in {"Nasdaq", "NYSE"} else 1, len(str(r[1]))))
        r = contains[0]
        return {"cik": cik10(r[0]), "name": r[1], "ticker": str(r[2]).upper(), "exchange": r[3]}

    raise SystemExit(f"Could not resolve company or ticker from SEC ticker list: {query}")


def latest_filings(submissions: dict[str, Any]) -> tuple[Filing | None, Filing | None, Filing | None]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filings: list[Filing] = []
    for i, form in enumerate(forms):
        if form not in {"10-Q", "10-K"}:
            continue
        accession = recent["accessionNumber"][i]
        primary_doc = recent["primaryDocument"][i]
        accession_path = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_short(submissions['cik'])}/{accession_path}/{primary_doc}"
        filings.append(
            Filing(
                form=form,
                filed=recent["filingDate"][i],
                period=recent["reportDate"][i],
                accession=accession,
                primary_doc=primary_doc,
                url=url,
            )
        )
    latest_q = next((f for f in filings if f.form == "10-Q"), None)
    latest_k = next((f for f in filings if f.form == "10-K"), None)
    prior_q = None
    if latest_q:
        for filing in filings:
            if filing.form == "10-Q" and filing.period < latest_q.period:
                prior_q = filing
                break
    return latest_q, prior_q, latest_k


def fact_points(companyfacts: dict[str, Any], tag: str) -> list[dict[str, Any]]:
    item = companyfacts.get("facts", {}).get("us-gaap", {}).get(tag)
    if not item:
        return []
    out: list[dict[str, Any]] = []
    for unit, values in item.get("units", {}).items():
        for value in values:
            point = dict(value)
            point["unit"] = unit
            point["tag"] = tag
            point["taxonomy"] = "us-gaap"
            out.append(point)
    return out


def _record_selection(
    audit_log: list[dict[str, Any]] | None,
    *,
    metric_name: str,
    requested_period: str,
    expected_context: str,
    expected_period_type: str,
    tags: tuple[str, ...],
    status: str,
    chosen: dict[str, Any] | None,
    rejected_reasons: list[str],
) -> None:
    if audit_log is None:
        return
    audit_log.append(
        {
            "metric_name": metric_name,
            "requested_period": requested_period,
            "expected_context": expected_context,
            "expected_period_type": expected_period_type,
            "expected_unit_category": "MONETARY",
            "attempted_tags": list(tags),
            "status": status,
            "chosen_tag": chosen.get("tag") if chosen else None,
            "chosen_unit": chosen.get("unit") if chosen else None,
            "chosen_currency": unit_profile(chosen.get("unit"))["currency"] if chosen else None,
            "chosen_start": chosen.get("start") if chosen else None,
            "chosen_end": chosen.get("end") if chosen else None,
            "chosen_accession": chosen.get("accn") if chosen else None,
            "rejected_reasons": sorted(set(rejected_reasons)),
            "missing_value_assumed_zero": False,
            "control_version": S06_DATA_CONTROL_VERSION,
        }
    )


def choose_instant(
    companyfacts: dict[str, Any],
    tags: tuple[str, ...],
    end: str,
    accn: str | None = None,
    *,
    metric_name: str = "",
    audit_log: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    rejected_reasons: list[str] = []
    for tag in tags:
        points = fact_points(companyfacts, tag)
        values = [
            p
            for p in points
            if p.get("end") == end
            and str(p.get("form", "")).upper() in SEC_FINANCIAL_FORMS
            and fact_context_kind(p) == "INSTANT"
            and unit_profile(p.get("unit"))["category"] == "MONETARY"
            and (accn is None or p.get("accn") == accn)
        ]
        if values:
            values.sort(key=lambda p: (p.get("filed", ""), p.get("accn", "")))
            chosen = values[-1]
            _record_selection(
                audit_log,
                metric_name=metric_name,
                requested_period=end,
                expected_context="INSTANT",
                expected_period_type="instant",
                tags=tags,
                status="SELECTED",
                chosen=chosen,
                rejected_reasons=rejected_reasons,
            )
            return chosen
        if points:
            rejected_reasons.append(
                f"{tag}: no candidate matched date, accession, instant context, filing form, and monetary unit."
            )
    _record_selection(
        audit_log,
        metric_name=metric_name,
        requested_period=end,
        expected_context="INSTANT",
        expected_period_type="instant",
        tags=tags,
        status="MISSING_XBRL_TAG" if not rejected_reasons else "INCOMPATIBLE_XBRL_CONTEXT",
        chosen=None,
        rejected_reasons=rejected_reasons,
    )
    return None


def choose_duration(
    companyfacts: dict[str, Any],
    tags: tuple[str, ...],
    end: str,
    *,
    form: str | None = None,
    accn: str | None = None,
    prefer: str = "quarter",
    metric_name: str = "",
    audit_log: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    rejected_reasons: list[str] = []
    for tag in tags:
        points = fact_points(companyfacts, tag)
        values = [
            p
            for p in points
            if p.get("end") == end
            and fact_context_kind(p) == "FLOW"
            and str(p.get("form", "")).upper() in SEC_FINANCIAL_FORMS
            and unit_profile(p.get("unit"))["category"] == "MONETARY"
            and (form is None or p.get("form") == form)
            and (accn is None or p.get("accn") == accn)
        ]
        if not values:
            if points:
                rejected_reasons.append(
                    f"{tag}: no candidate matched date, accession, flow context, filing form, and monetary unit."
                )
            continue
        if prefer == "quarter":
            selected = [p for p in values if is_quarter_flow(p)]
            if not selected:
                rejected_reasons.append(f"{tag}: available flow context is not a validated standalone quarter.")
                continue
            selected.sort(key=lambda p: (p.get("filed", ""), p.get("accn", "")))
            chosen = selected[-1]
            _record_selection(
                audit_log,
                metric_name=metric_name,
                requested_period=end,
                expected_context="FLOW",
                expected_period_type="quarter",
                tags=tags,
                status="SELECTED",
                chosen=chosen,
                rejected_reasons=rejected_reasons,
            )
            return chosen
        if prefer == "ytd":
            selected = [p for p in values if is_ytd_flow(p)]
            if not selected:
                rejected_reasons.append(f"{tag}: available flow context is not a validated YTD period.")
                continue
            selected.sort(key=lambda p: (days_between(p.get("start"), p.get("end")) or 0, p.get("filed", "")))
            chosen = selected[-1]
            _record_selection(
                audit_log,
                metric_name=metric_name,
                requested_period=end,
                expected_context="FLOW",
                expected_period_type="YTD",
                tags=tags,
                status="SELECTED",
                chosen=chosen,
                rejected_reasons=rejected_reasons,
            )
            return chosen
        if prefer == "annual":
            selected = [p for p in values if is_annual_flow(p)]
            if not selected:
                rejected_reasons.append(f"{tag}: available flow context is not a validated FY period.")
                continue
            selected.sort(key=lambda p: (days_between(p.get("start"), p.get("end")) or 0, p.get("filed", "")))
            chosen = selected[-1]
            _record_selection(
                audit_log,
                metric_name=metric_name,
                requested_period=end,
                expected_context="FLOW",
                expected_period_type="FY",
                tags=tags,
                status="SELECTED",
                chosen=chosen,
                rejected_reasons=rejected_reasons,
            )
            return chosen
    _record_selection(
        audit_log,
        metric_name=metric_name,
        requested_period=end,
        expected_context="FLOW",
        expected_period_type=prefer.upper(),
        tags=tags,
        status="MISSING_XBRL_TAG" if not rejected_reasons else "INCOMPATIBLE_XBRL_CONTEXT",
        chosen=None,
        rejected_reasons=rejected_reasons,
    )
    return None


def dp_from_fact(metric_name: str, fact: dict[str, Any], source_url: str, source_location: str, period_type: str, notes: str = "") -> DataPoint:
    start = fact.get("start", "")
    end = fact.get("end", "")
    profile = unit_profile(fact.get("unit", ""))
    return DataPoint(
        metric_name=metric_name,
        value=fact.get("val"),
        unit=fact.get("unit", ""),
        currency=profile["currency"],
        period_start=start,
        period_end=end,
        period_type=period_type,
        duration_days=days_between(start, end) if start else "",
        fiscal_period=f"FY{fact.get('fy', '')} {fact.get('fp', '')}".strip(),
        filing_type=fact.get("form", ""),
        filing_date=fact.get("filed", ""),
        source_location=source_location,
        source_tag=f"{fact.get('taxonomy', 'us-gaap')}:{fact.get('tag', '')}",
        source_url=source_url,
        evidence_type="FACT",
        reported_or_calculated="reported",
        confidence="High",
        validation_status="auto-checked",
        notes=notes,
    )


def manual_dp(
    metric_name: str,
    value: Any,
    *,
    unit: str = "USD",
    currency: str = "USD",
    period_start: str = "",
    period_end: str = "",
    period_type: str = "instant",
    duration_days_value: Any = "",
    fiscal_period: str = "",
    filing_type: str = "",
    filing_date: str = "",
    source_location: str = "",
    source_tag: str = "",
    source_url: str = "",
    evidence_type: str = "CALC",
    reported_or_calculated: str = "calculated",
    confidence: str = "High",
    validation_status: str = "auto-checked",
    notes: str = "",
) -> DataPoint:
    return DataPoint(
        metric_name=metric_name,
        value=value,
        unit=unit,
        currency=currency,
        period_start=period_start,
        period_end=period_end,
        period_type=period_type,
        duration_days=duration_days_value,
        fiscal_period=fiscal_period,
        filing_type=filing_type,
        filing_date=filing_date,
        source_location=source_location,
        source_tag=source_tag,
        source_url=source_url,
        evidence_type=evidence_type,
        reported_or_calculated=reported_or_calculated,
        confidence=confidence,
        validation_status=validation_status,
        notes=notes,
    )


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<script.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style.*?</style>", " ", raw)
    raw = re.sub(r"(?is)<ix:hidden.*?</ix:hidden>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_number_text(text: str, scale: int = 0, negative: bool = False) -> float | None:
    text = html.unescape(re.sub(r"<.*?>", "", text)).strip()
    text = text.replace(",", "").replace("$", "").replace("%", "")
    text = text.replace("(", "").replace(")", "").strip()
    if not text:
        return None
    try:
        value = float(text) * (10**scale)
        return -value if negative else value
    except ValueError:
        return None


def extract_inline_row_value(raw: str, label: str) -> tuple[float, str] | None:
    for match in re.finditer(r"(?is)<tr\b[^>]*>.*?</tr>", raw):
        row_html = match.group(0)
        if label.lower() not in html_to_text(row_html).lower():
            continue
        facts = re.findall(r"<ix:nonFraction\b([^>]*)>(.*?)</ix:nonFraction>", row_html, flags=re.S)
        for attrs, value_html in facts:
            if 'xsi:nil="true"' in attrs:
                continue
            scale_match = re.search(r'scale="(-?\d+)"', attrs)
            name_match = re.search(r'name="([^"]+)"', attrs)
            fact_name = name_match.group(1) if name_match else "inline-xbrl"
            if "accountspayable" not in fact_name.lower() or "increasedecrease" in fact_name.lower():
                continue
            scale = int(scale_match.group(1)) if scale_match else 0
            negative = 'sign="-"' in attrs
            value = clean_number_text(value_html, scale, negative)
            if value is not None and value >= 0:
                return value, fact_name
    return None


def extract_ap_proxy_from_html(url: str) -> tuple[float, str, str] | None:
    raw = fetch_text(url)
    for label in AP_LABELS:
        value = extract_inline_row_value(raw, label)
        if value:
            return value[0], value[1], label
    return None


def find_snippet(text: str, patterns: tuple[str, ...], window: int = 600) -> str:
    lower = text.lower()
    for pattern in patterns:
        idx = lower.find(pattern.lower())
        if idx != -1:
            return text[max(0, idx - window) : idx + window].strip()
    return ""


def money_phrase_to_usd(number_text: str, scale_word: str) -> float | None:
    value = clean_number_text(number_text)
    if value is None:
        return None
    scale = scale_word.lower()
    if scale.startswith("b"):
        return value * 1_000_000_000
    if scale.startswith("m"):
        return value * 1_000_000
    return value


def extract_amount_phrase(text: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return money_phrase_to_usd(match.group(1), match.group(2))
    return None


def numbers_after_label(text: str, label: str, window: int = 240) -> list[float]:
    idx = text.lower().find(label.lower())
    if idx == -1:
        return []
    chunk = text[idx : idx + window]
    out: list[float] = []
    for raw in re.findall(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", chunk):
        value = clean_number_text(raw)
        if value is not None:
            out.append(value)
    return out


def scaled_table_amount_after_label(text: str, label: str, context_window: int = 320) -> float | None:
    """Read a filing table amount only when an explicit nearby unit scale exists."""

    for match in re.finditer(rf"{re.escape(label)}\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text, flags=re.I):
        prefix = text[max(0, match.start() - context_window) : match.start()]
        scale_matches = list(re.finditer(r"\(\s*in\s+(thousands|millions|billions)\s*\)", prefix, flags=re.I))
        if not scale_matches:
            continue
        unit = scale_matches[-1].group(1).lower()
        value = clean_number_text(match.group(1))
        if value is None:
            continue
        multiplier = {
            "thousands": 1_000,
            "millions": 1_000_000,
            "billions": 1_000_000_000,
        }[unit]
        return value * multiplier
    return None


FILING_DATE_PATTERN = (
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+\d{4}"
)


def filing_date_phrase_to_iso(value: str) -> str | None:
    normalized = re.sub(r"\s+", " ", value).strip()
    for pattern in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(normalized, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def respectively_linked_letters_of_credit(
    text: str,
    *,
    as_of_date: str | None,
) -> tuple[float, str] | None:
    """Select the amount linked to its date in an explicit respectively sentence."""

    pattern = re.compile(
        rf"(?:there\s+were|we\s+had)\s+\$?\s*"
        rf"(?P<amount_one>[0-9,.]+)\s*(?P<scale_one>billion|million)\s+and\s+\$?\s*"
        rf"(?P<amount_two>[0-9,.]+)\s*(?P<scale_two>billion|million)\s+"
        rf"(?:in|of)?\s*outstanding\s+letters\s+of\s+credit\s+at\s+"
        rf"(?P<date_one>{FILING_DATE_PATTERN})\s+and\s+"
        rf"(?P<date_two>{FILING_DATE_PATTERN})\s*,?\s*respectively",
        flags=re.I,
    )
    candidates: list[tuple[str, float]] = []
    for match in pattern.finditer(text):
        for amount_group, scale_group, date_group in (
            ("amount_one", "scale_one", "date_one"),
            ("amount_two", "scale_two", "date_two"),
        ):
            linked_date = filing_date_phrase_to_iso(match.group(date_group))
            amount = money_phrase_to_usd(
                match.group(amount_group),
                match.group(scale_group),
            )
            if linked_date and amount is not None:
                candidates.append((linked_date, amount))
    if not candidates:
        return None
    if as_of_date:
        exact = [candidate for candidate in candidates if candidate[0] == as_of_date]
        if not exact:
            return None
        selected_date, selected_amount = exact[0]
    else:
        selected_date, selected_amount = max(candidates, key=lambda candidate: candidate[0])
    return selected_amount, selected_date


def dated_facility_availability(
    text: str,
    *,
    as_of_date: str | None,
) -> tuple[float, str] | None:
    pattern = re.compile(
        rf"(?:as\s+of|at)\s+(?P<date>{FILING_DATE_PATTERN})\s*,?\s*"
        rf"(?:we\s+)?(?:had|have)\s+\$?\s*(?P<amount>[0-9,.]+)\s*"
        rf"(?P<scale>billion|million)\s+(?:of\s+)?"
        rf"(?:(?:remaining\s+)?borrowing\s+availability|available\s+borrowing\s+capacity|"
        rf"unused\s+borrowing\s+capacity)\s+under\s+(?:the\s+)?"
        rf"(?:credit\s+agreement|revolving\s+credit\s+facility|revolving\s+facility|credit\s+facility)",
        flags=re.I,
    )
    candidates: list[tuple[str, float]] = []
    for match in pattern.finditer(text):
        linked_date = filing_date_phrase_to_iso(match.group("date"))
        amount = money_phrase_to_usd(match.group("amount"), match.group("scale"))
        if linked_date and amount is not None:
            candidates.append((linked_date, amount))
    if not candidates:
        return None
    if as_of_date:
        exact = [candidate for candidate in candidates if candidate[0] == as_of_date]
        if not exact:
            return None
        return exact[0][1], exact[0][0]
    selected_date, selected_amount = max(candidates, key=lambda candidate: candidate[0])
    return selected_amount, selected_date


def assess_facility_reconciliation(
    values: dict[str, tuple[float, str]],
    *,
    tolerance: float = 1_000_000,
) -> dict[str, Any]:
    """Check that reported availability and known reductions do not exceed commitment."""

    def amount(name: str) -> float | None:
        item = values.get(name)
        return item[0] if item else None

    commitment = amount("facility_commitment")
    availability = amount("facility_availability_reported")
    if commitment is None or availability is None:
        return {
            "status": "NOT_TESTED",
            "commitment": commitment,
            "availability": availability,
            "known_reductions": {},
            "known_component_total": None,
            "gap": None,
            "reason": "Both facility commitment and availability are required.",
        }

    reductions = {
        name: value
        for name in (
            "facility_borrowings",
            "facility_letters_of_credit",
            "facility_lender_reserves",
        )
        if (value := amount(name)) is not None
    }
    known_component_total = availability + sum(reductions.values())
    gap = commitment - known_component_total
    if gap < -tolerance:
        status = "FAIL"
        reason = (
            "Commitment is below availability plus known borrowings, letters of "
            "credit, and reserves."
        )
    elif abs(gap) <= tolerance:
        status = "PASS"
        reason = "Commitment reconciles to availability plus known reductions."
    else:
        status = "PROVISIONAL"
        reason = (
            "The positive residual may represent undisclosed borrowings, reserves, "
            "or another availability reduction."
        )
    return {
        "status": status,
        "commitment": commitment,
        "availability": availability,
        "known_reductions": reductions,
        "known_component_total": known_component_total,
        "gap": gap,
        "reason": reason,
    }


def extract_facility_values(
    text: str,
    *,
    as_of_date: str | None = None,
) -> dict[str, tuple[float, str]]:
    """Extract common facility values from filing text.

    The output is deliberately medium-confidence. It gives the memo a better
    liquidity starting point, but the validation report still requires note
    reading before final investment conclusions.
    """

    values: dict[str, tuple[float, str]] = {}
    exact_table_commitment = scaled_table_amount_after_label(
        text,
        "Credit Agreement limit",
    )
    commitment = exact_table_commitment or extract_amount_phrase(
        text,
        (
            r"(?:provides for|consists of|maintains?)\s+(?:an?\s+)?\$?\s*([0-9,.]+)\s*(billion|million)\s+(?:secured\s+|unsecured\s+)?(?:asset-based\s+)?(?:revolving\s+)?credit\s+facility",
            r"(?:entered into|amended|replaced)(?:[^.;]{0,120})?\$?\s*([0-9,.]+)\s*(billion|million)\s+(?:secured\s+|unsecured\s+)?(?:asset-based\s+)?(?:revolving\s+)?credit\s+(?:agreement|facility)",
            r"(?:credit agreement|revolving credit facility|revolving facility|credit facility)(?:[^.;]{0,220})?to\s+(?:an?\s+)?aggregate\s+of\s+\$?\s*([0-9,.]+)\s*(billion|million)",
            r"(?:credit agreement|revolving credit facility|revolving facility|credit facility)(?:[^.;]{0,160})?(?:provides for|commitments? (?:of|totaling|equal to)|capacity of)\s+\$?\s*([0-9,.]+)\s*(billion|million)",
            r"\$?\s*([0-9,.]+)\s*(billion|million)\s+(?:secured\s+|unsecured\s+)?(?:asset-based\s+)?revolving\s+credit\s+facility",
        ),
    )
    if commitment is not None:
        commitment_note = (
            "parsed from the explicitly scaled Credit Agreement limit table"
            if exact_table_commitment is not None
            else "parsed only from a direct credit-facility commitment phrase"
        )
        values["facility_commitment"] = (
            commitment,
            commitment_note,
        )

    dated_availability = dated_facility_availability(
        text,
        as_of_date=as_of_date,
    )
    availability_phrase = (
        dated_availability[0]
        if dated_availability is not None
        else extract_amount_phrase(
            text,
            (
                r"excess availability(?:[^.]{0,120})?\$?\s*([0-9,.]+)\s*(billion|million)",
                r"available (?:for borrowing|under [^.]{0,80})(?:[^.]{0,80})?\$?\s*([0-9,.]+)\s*(billion|million)",
                r"had \$?\s*([0-9,.]+)\s*(billion|million)(?:[^.]{0,100})?of (?:remaining )?borrowing availability under (?:the )?(?:credit agreement|revolving facility|credit facility)",
                r"had \$?\s*([0-9,.]+)\s*(billion|million)(?:[^.]{0,100})?of available borrowing capacity under (?:the )?(?:credit agreement|revolving facility|credit facility)",
                r"unused (?:borrowing )?capacity(?:[^.]{0,80})?\$?\s*([0-9,.]+)\s*(billion|million)",
                r"undrawn (?:commitments?|capacity|availability)(?:[^.]{0,80})?\$?\s*([0-9,.]+)\s*(billion|million)",
            ),
        )
    )
    if availability_phrase is not None:
        availability_note = (
            f"parsed from a dated availability phrase for {dated_availability[1]}"
            if dated_availability is not None
            else "parsed from an availability phrase without a date link"
        )
        values["facility_availability_reported"] = (
            availability_phrase,
            availability_note,
        )
    else:
        nums = numbers_after_label(text, "Excess availability")
        if nums:
            values["facility_availability_reported"] = (max(nums) * 1_000_000, "parsed from excess availability table; assumes table in millions")

    exact_table_availability = scaled_table_amount_after_label(text, "Available borrowings")
    total_availability = exact_table_availability or extract_amount_phrase(
        text,
        (
            r"up to \$?\s*([0-9,.]+)\s*(billion|million) of available borrowings",
        ),
    )
    if total_availability is not None:
        source_note = "parsed from scaled liquidity table" if exact_table_availability is not None else "parsed from liquidity discussion"
        values["total_available_borrowings_reported"] = (total_availability, source_note)

    outstanding_borrowings = extract_amount_phrase(
        text,
        (
            r"had \$?\s*([0-9,.]+)\s*(billion|million) in outstanding borrowings(?:[^.]{0,80})?under the (?:revolving )?facility",
            r"\$?\s*([0-9,.]+)\s*(billion|million) in outstanding borrowings(?:[^.]{0,80})?under the (?:revolving )?facility",
        ),
    )
    if outstanding_borrowings is not None:
        values["facility_borrowings"] = (outstanding_borrowings, "parsed from outstanding-borrowings sentence")

    respectively_linked_lc = respectively_linked_letters_of_credit(
        text,
        as_of_date=as_of_date,
    )
    letters_of_credit = (
        respectively_linked_lc[0]
        if respectively_linked_lc is not None
        else extract_amount_phrase(
            text,
            (
                r"(?:as of [^.]{0,40},?\s*)?(?:we had|there were)\s+\$?\s*([0-9,.]+)\s*(billion|million)\s+(?:in|of)\s+outstanding letters of credit",
                r"outstanding letters of credit(?:[^.]{0,50})?(?:were|totaled)\s+\$?\s*([0-9,.]+)\s*(billion|million)",
            ),
        )
    )
    if letters_of_credit is not None:
        lc_note = (
            f"parsed from a respectively-linked amount/date pair for {respectively_linked_lc[1]}"
            if respectively_linked_lc is not None
            else "parsed from a single outstanding-letters-of-credit statement"
        )
        values["facility_letters_of_credit"] = (letters_of_credit, lc_note)

    for label in ("lenders’ reserves", "lenders' reserves"):
        nums = numbers_after_label(text, label)
        if nums:
            values["facility_lender_reserves"] = (nums[0] * 1_000_000, f"parsed from {label} table; assumes table in millions")
            break

    return values


def add_validation(
    validations: list[dict[str, Any]],
    id_: str,
    result: str,
    severity: str,
    evidence: str,
    impact: str,
    remediation: str,
    *,
    category: str = "data_integrity",
    issue_class: str | None = None,
    evidence_ids: list[str] | None = None,
) -> None:
    if issue_class is None:
        if result in {"FAIL", "BLOCKED"} and severity == "Critical":
            issue_class = "HARD_STOP"
        elif result in {"FAIL", "BLOCKED", "MISSING", "PROVISIONAL", "WARNING"}:
            issue_class = "WARNING"
        else:
            issue_class = "INFO"
    validations.append(
        {
            "id": id_,
            "check_id": id_,
            "category": category,
            "result": result,
            "status": result,
            "issue_class": issue_class,
            "severity": severity,
            "evidence": evidence,
            "message": evidence,
            "impact": impact,
            "decision_impact": impact,
            "remediation": remediation,
            "evidence_ids": evidence_ids or [],
            "scope": "shared_data_engine",
        }
    )


CALCULATION_INPUTS: dict[str, tuple[str, ...]] = {
    "total_liabilities": ("total_assets", "shareholders_equity"),
    "available_liquidity_before_facility_notes": ("unrestricted_cash", "short_term_investments"),
    "current_lease_obligations_total": ("finance_lease_current", "operating_lease_current"),
    "latest_ytd_fcf": ("latest_ytd_cfo", "latest_ytd_capex"),
    "derived_latest_quarter_fcf": ("derived_latest_quarter_cfo", "derived_latest_quarter_capex"),
    "latest_quarter_fcf": ("latest_quarter_cfo", "latest_quarter_capex"),
    "dso_avg_ar": ("accounts_receivable_net", "prior_accounts_receivable_net", "latest_quarter_revenue"),
    "dio_avg_inventory": ("inventory_net", "prior_inventory_net", "latest_quarter_cogs"),
    "dpo_avg_ap": ("accounts_payable", "prior_accounts_payable", "latest_quarter_cogs"),
    "cash_conversion_cycle": ("dso_avg_ar", "dio_avg_inventory", "dpo_avg_ap"),
    "available_liquidity_including_reported_facility": (
        "available_liquidity_before_facility_notes",
        "total_available_borrowings_reported",
        "facility_availability_reported",
    ),
}


CALCULATION_FORMULAS: dict[str, str] = {
    "total_liabilities": "total_assets - shareholders_equity",
    "available_liquidity_before_facility_notes": "unrestricted_cash + short_term_investments",
    "current_lease_obligations_total": "finance_lease_current + operating_lease_current",
    "latest_ytd_fcf": "latest_ytd_cfo - latest_ytd_capex",
    "derived_latest_quarter_fcf": "derived_latest_quarter_cfo - derived_latest_quarter_capex",
    "latest_quarter_fcf": "latest_quarter_cfo - latest_quarter_capex",
    "dso_avg_ar": "average(accounts_receivable_net, prior_accounts_receivable_net) / latest_quarter_revenue * duration_days",
    "dio_avg_inventory": "average(inventory_net, prior_inventory_net) / latest_quarter_cogs * duration_days",
    "dpo_avg_ap": "average(accounts_payable, prior_accounts_payable) / latest_quarter_cogs * duration_days",
    "cash_conversion_cycle": "dso_avg_ar + dio_avg_inventory - dpo_avg_ap",
    "available_liquidity_including_reported_facility": "cash_and_short_term_investments + reported_available_borrowings",
}


WORKING_CAPITAL_COMPONENT_METRICS: dict[str, str] = {
    "DSO": "dso_avg_ar",
    "DIO": "dio_avg_inventory",
    "DPO": "dpo_avg_ap",
    "CCC": "cash_conversion_cycle",
}


def working_capital_component_coverage(
    metric_names: set[str] | list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Classify component availability without treating an absent metric as zero."""

    observed = set(metric_names)
    components = {
        label: (
            "AVAILABLE"
            if metric_name in observed
            else "MISSING_PENDING_CLASSIFICATION"
        )
        for label, metric_name in WORKING_CAPITAL_COMPONENT_METRICS.items()
    }
    available = [
        label for label, status in components.items() if status == "AVAILABLE"
    ]
    unavailable = [
        label
        for label, status in components.items()
        if status == "MISSING_PENDING_CLASSIFICATION"
    ]
    return {
        "status": (
            "COMPLETE"
            if not unavailable
            else "PARTIAL"
            if available
            else "UNAVAILABLE"
        ),
        "components": components,
        "available": available,
        "unavailable": unavailable,
        "absent_values_assumed_zero": False,
        "not_applicable_requires_analyst_review": bool(unavailable),
    }


def enrich_data_points(company: dict[str, Any], rows: list[DataPoint]) -> None:
    retrieval_date = datetime.now(UTC).date().isoformat()
    for row in rows:
        row.as_of_date = row.as_of_date or row.period_end
        row.publication_date = row.publication_date or row.filing_date
        row.retrieval_date = row.retrieval_date or retrieval_date
        row.source_locator = row.source_locator or row.source_location
        row.evidence_class = row.evidence_type if row.evidence_type in {"FACT", "CALC", "INFERENCE", "JUDGMENT", "MISSING"} else "FACT"
        if row.source_url.startswith("https://www.sec.gov") or row.source_url.startswith("https://data.sec.gov"):
            row.source_level = 1
            row.source_type = "regulatory_filing" if row.reported_or_calculated == "reported" else "calculation_from_primary"
            row.source_name = "U.S. Securities and Exchange Commission"
        if row.reported_or_calculated == "calculated":
            row.measurement_basis = "calculated_from_reported"
        status_map = {
            "auto-checked": "PASS",
            "analyst-review-needed": "PROVISIONAL",
            "exception": "FAIL",
            "missing": "MISSING",
        }
        row.validation_status = status_map.get(row.validation_status, row.validation_status)
        row.formula = row.formula or CALCULATION_FORMULAS.get(row.metric_name, "")
        if row.metric_name.startswith("derived_latest_quarter_") and row.metric_name != "derived_latest_quarter_fcf":
            base_metric = row.metric_name.removeprefix("derived_latest_quarter_")
            row.formula = row.formula or f"latest_ytd_{base_metric} - prior_same_fiscal_year_ytd_{base_metric}"
        row.evidence_id = row.evidence_id or make_evidence_id(
            company["ticker"],
            row.metric_name,
            row.period_start,
            row.period_end,
            row.source_tag,
            row.source_locator,
        )
        row.source_id = row.source_id or stable_id(
            "SRC",
            row.source_level,
            row.source_type,
            row.source_url,
            row.publication_date,
        )

    by_name = {row.metric_name: row for row in rows}
    for row in rows:
        if row.input_evidence_ids is None:
            row.input_evidence_ids = []
        if row.reported_or_calculated != "calculated":
            continue
        input_names = CALCULATION_INPUTS.get(row.metric_name, ())
        if row.metric_name == "available_liquidity_before_facility_notes":
            input_names = tuple(name for name in ("unrestricted_cash", "short_term_investments") if name in by_name)
            row.formula = " + ".join(input_names)
        elif row.metric_name == "current_lease_obligations_total":
            input_names = tuple(name for name in ("finance_lease_current", "operating_lease_current") if name in by_name)
            row.formula = " + ".join(input_names)
        elif row.metric_name == "available_liquidity_including_reported_facility":
            facility_input = (
                "total_available_borrowings_reported"
                if "total_available_borrowings_reported" in by_name
                else "facility_availability_reported"
            )
            input_names = ("available_liquidity_before_facility_notes", facility_input)
            row.formula = " + ".join(input_names)
        if row.metric_name.startswith("derived_latest_quarter_") and row.metric_name != "derived_latest_quarter_fcf":
            base_metric = row.metric_name.removeprefix("derived_latest_quarter_")
            input_names = (f"latest_ytd_{base_metric}", f"prior_same_fiscal_year_ytd_{base_metric}")
        for input_name in input_names:
            source_row = by_name.get(input_name)
            if source_row and source_row.evidence_id not in row.input_evidence_ids:
                row.input_evidence_ids.append(source_row.evidence_id)


def subsequent_event_filings(submissions: dict[str, Any], after_date: str) -> list[dict[str, str]]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    events: list[dict[str, str]] = []
    for i, form in enumerate(forms):
        filing_date = recent.get("filingDate", [""] * len(forms))[i]
        if form not in {"8-K", "8-K/A"} or not filing_date or filing_date <= after_date:
            continue
        accession = recent.get("accessionNumber", [""] * len(forms))[i]
        primary_doc = recent.get("primaryDocument", [""] * len(forms))[i]
        accession_path = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_short(submissions['cik'])}/{accession_path}/{primary_doc}"
        items = recent.get("items", [""] * len(forms))[i] if recent.get("items") else ""
        events.append(
            {
                "form": form,
                "filing_date": filing_date,
                "report_date": recent.get("reportDate", [""] * len(forms))[i],
                "items": items,
                "accession": accession,
                "source_url": url,
                "review_status": "REVIEW_REQUIRED",
            }
        )
    return sorted(events, key=lambda row: row["filing_date"])


def build_cash_flow_ledger(rows: list[DataPoint]) -> tuple[list[CashFlowLedgerLine], list[dict[str, Any]]]:
    by_name = {row.metric_name: row for row in rows}
    lines: list[CashFlowLedgerLine] = []

    def add(
        metric_name: str,
        label: str,
        treatment: str,
        *,
        embedded_in_cfo: bool,
        separately_modeled: bool,
        notes: str,
    ) -> None:
        row = by_name.get(metric_name)
        if not row:
            return
        lines.append(
            CashFlowLedgerLine(
                line_id=stable_id("CFL", metric_name, row.period_start, row.period_end),
                label=label,
                amount=safe_float(row.value),
                period_start=row.period_start,
                period_end=row.period_end,
                treatment=treatment,
                embedded_in_cfo=embedded_in_cfo,
                separately_modeled=separately_modeled,
                evidence_ids=[row.evidence_id],
                notes=notes,
            )
        )

    add(
        "latest_ytd_cfo",
        "Historical YTD CFO",
        "HISTORICAL_SOURCE",
        embedded_in_cfo=False,
        separately_modeled=True,
        notes="Historical CFO is not a forward liquidity source without an explicit forecast.",
    )
    add(
        "latest_ytd_capex",
        "Historical YTD cash capex",
        "HISTORICAL_USE",
        embedded_in_cfo=False,
        separately_modeled=True,
        notes="Capex is outside CFO and may be deducted once in a CFO-based FCF bridge.",
    )
    add(
        "latest_ytd_interest_paid",
        "Historical cash interest",
        "EMBEDDED_IN_CFO",
        embedded_in_cfo=True,
        separately_modeled=False,
        notes="Do not deduct again from CFO-based FCF unless CFO is explicitly reversed and rebuilt.",
    )
    add(
        "current_lease_obligations_total",
        "Current lease liability carrying value",
        "OBSERVATION_ONLY",
        embedded_in_cfo=False,
        separately_modeled=False,
        notes="Carrying value is not a contractual cash-payment schedule and is not inserted as a liquidity use.",
    )
    add(
        "current_debt",
        "Current debt carrying value",
        "OBSERVATION_ONLY",
        embedded_in_cfo=False,
        separately_modeled=False,
        notes="Use as a balance-sheet warning until maturity dates and contractual cash amounts are reconciled.",
    )

    issues = [issue.to_dict() for issue in validate_cash_flow_ledger(lines)]
    return lines, issues


def write_csv(path: Path, rows: list[DataPoint]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def metric_map(rows: list[DataPoint]) -> dict[str, DataPoint]:
    return {row.metric_name: row for row in rows}


def val(rows_by_name: dict[str, DataPoint], name: str) -> float | None:
    if name not in rows_by_name:
        return None
    return safe_float(rows_by_name[name].value)


def build_pack_markdown(company: dict[str, Any], filings: dict[str, Filing | None], rows: list[DataPoint], validations: list[dict[str, Any]]) -> str:
    m = metric_map(rows)
    latest_q = filings.get("latest_q")
    latest_k = filings.get("latest_k")
    failed = [v for v in validations if v["result"] == "FAIL"]
    missing = [v for v in validations if v["result"] in {"MISSING", "PROVISIONAL"}]
    blocked = [v for v in validations if v["result"] == "BLOCKED"]
    action = "Data Blocked" if failed else "Watch / Need More Work"

    available_liquidity = val(m, "available_liquidity_including_reported_facility")
    liquidity_label = "including reported facility availability"
    if available_liquidity is None:
        available_liquidity = val(m, "available_liquidity_before_facility_notes")
        liquidity_label = "before facility-note availability review"
    current_lease_uses = val(m, "current_lease_obligations_total")
    qtr_fcf = val(m, "derived_latest_quarter_fcf")
    if qtr_fcf is None:
        qtr_fcf = val(m, "latest_quarter_fcf")
    ytd_fcf = val(m, "latest_ytd_fcf")

    key_lines = [
        "| Metric | Value | Period | Evidence | Decision Use |",
        "|---|---:|---|---|---|",
    ]
    for name, label, use in [
        ("unrestricted_cash", "Unrestricted cash", "Immediate cash, before restricted-cash caveat"),
        ("cash_and_restricted_cash", "Cash + restricted cash", "Cash-flow reconciliation, not fully available liquidity"),
        ("short_term_investments", "Short-term investments", "Adds to liquid resources if present"),
        ("available_liquidity_before_facility_notes", "Cash + short-term investments", "Liquidity before revolver/facility note review"),
        ("total_available_borrowings_reported", "Total reported available borrowings", "Reported borrowing sources across disclosed facilities"),
        ("facility_availability_reported", "Reported facility availability", "Committed liquidity source if note parse is confirmed"),
        ("available_liquidity_including_reported_facility", "Cash/STI + reported available borrowings", "Preliminary liquidity source before downside haircut"),
        ("current_debt", "Current debt", "12-month funded debt pressure"),
        ("current_lease_obligations_total", "Current lease obligations", "Mandatory uses not captured by current debt"),
        ("latest_ytd_fcf", "YTD FCF", "Cash generation, period-specific"),
        ("derived_latest_quarter_fcf", "Derived latest-quarter FCF", "Same-period cash conversion if derivable"),
        ("dso_avg_ar", "DSO", "Receivables collection pressure"),
        ("dio_avg_inventory", "DIO", "Inventory pressure"),
        ("dpo_avg_ap", "DPO", "Payables timing; check AP definition"),
        ("cash_conversion_cycle", "CCC", "Working-capital cycle baseline"),
    ]:
        if name in m:
            row = m[name]
            raw = safe_float(row.value)
            if row.unit == "USD" and raw is not None:
                display = fmt_usd(raw)
            elif row.unit == "days" and raw is not None:
                display = fmt_num(raw, " days")
            else:
                display = str(row.value)
            period = row.period_end if not row.period_start else f"{row.period_start} to {row.period_end}"
            key_lines.append(f"| {label} | {display} | {period} | {row.evidence_type}/{row.period_type} | {use} |")

    validation_lines = ["| Check | Result | Evidence | Impact |", "|---|---:|---|---|"]
    for item in validations:
        validation_lines.append(f"| {item['id']} | {item['result']} | {item['evidence']} | {item['impact']} |")

    source_lines = []
    if latest_q:
        source_lines.append(f"- Latest 10-Q: {latest_q.url}")
    if latest_k:
        source_lines.append(f"- Latest 10-K: {latest_k.url}")
    source_lines.append(f"- SEC companyfacts: https://data.sec.gov/api/xbrl/companyfacts/CIK{company['cik']}.json")

    return "\n".join(
        [
            f"# {company['name']} ({company['ticker']}) Public Company Decision-Support Data Pack",
            "",
            f"Review date: {datetime.now(UTC).strftime('%Y-%m-%d')}",
            f"Exchange: {company.get('exchange', '')}",
            "Scope: SEC public filings only. This is a data-integrity and credit/liquidity support pack, not a formal investment recommendation.",
            "",
            "## Decision Strip",
            "",
            f"- Action view: {action}",
            "- Confidence: Medium if core statements and validation pass; lower where facility, covenant, lease, valuation, or consensus data is missing.",
            f"- Latest quarterly filing: {latest_q.form if latest_q else 'missing'} filed {latest_q.filed if latest_q else 'n/a'}, period {latest_q.period if latest_q else 'n/a'}.",
            f"- Latest annual filing: {latest_k.form if latest_k else 'missing'} filed {latest_k.filed if latest_k else 'n/a'}, period {latest_k.period if latest_k else 'n/a'}.",
            f"- Validation: {len(failed)} fail, {len(blocked)} blocked, {len(missing)} missing/provisional checks.",
            "",
            "## Core View",
            "",
            "- The pack can support a preliminary credit/liquidity view only after data validation.",
            f"- Visible liquid resources {liquidity_label} are {fmt_usd(available_liquidity)}." if available_liquidity is not None else "- Visible liquid resources could not be fully calculated from standardized tags.",
            f"- Current lease obligations identified are {fmt_usd(current_lease_uses)}; current debt alone should not be treated as total near-term obligations." if current_lease_uses is not None else "- Current lease obligations are missing or not standardized; near-term obligations need note review.",
            f"- YTD FCF is {fmt_usd(ytd_fcf)}; latest-quarter FCF is {fmt_usd(qtr_fcf)} where derivable." if (ytd_fcf is not None or qtr_fcf is not None) else "- CFO/FCF is missing or not derivable; cash conversion confidence is low.",
            "- Formal investment action remains blocked until earnings drivers, normalized EBITDA/FCF, consensus, valuation, scenarios, catalysts, and risk/reward are sourced.",
            "",
            "## Key Metrics",
            "",
            *key_lines,
            "",
            "## Validation Report",
            "",
            *validation_lines,
            "",
            "## Required Follow-Up Before Full Investment Memo",
            "",
            "- Read debt/facility notes for commitment, availability, letters of credit, reserves, borrowing-base mechanics, maturity, and covenant trigger.",
            "- Build 12/24-month sources and uses: cash, revolver availability, debt maturities, leases, cash interest, maintenance capex, committed payments, and working-capital stress.",
            "- Build 8-quarter DSO/DIO/DPO/CCC trend where filings allow.",
            "- Source LTM adjusted EBITDA and reconcile management adjustments before using leverage ratios.",
            "- Add consensus, peer multiples, historical valuation range, base/bull/bear scenarios, catalysts, and thesis-break thresholds before any investment action.",
            "",
            "## Sources",
            "",
            *source_lines,
            "",
        ]
    )


def write_unsupported_diagnostic_pack(
    company: dict[str, Any],
    support_assessment: dict[str, Any],
    out_root: Path,
) -> Path:
    """Write a renderable Gate 0 diagnostic instead of failing without output."""

    validations: list[dict[str, Any]] = []
    add_validation(
        validations,
        "P0-supported-universe",
        "BLOCKED",
        "Critical",
        "; ".join(support_assessment.get("reasons", [])) or "The issuer is outside the supported core.",
        "The shared non-financial US GAAP rules cannot produce a reliable underwriting conclusion for this issuer.",
        f"Use the {support_assessment.get('overlay_required', 'specialized')} overlay before formal analysis.",
        category="supported_universe",
        issue_class="HARD_STOP",
    )
    slug = f"{company['ticker'].lower()}_{slugify(company['name'])}"
    out_dir = out_root / slug
    data_dir = out_dir / "data"
    validation_dir = out_dir / "validation"
    data_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)
    retrieval_time = utc_now()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "engine": "shared_data_and_evidence_engine",
        "report_id": stable_id("RPT", company["cik"], "unsupported", retrieval_time),
        "company": company,
        "build_date": retrieval_time,
        "supported_universe": support_assessment,
        "as_of_registry": {
            "financial_statement_date": None,
            "latest_financial_filing_date": None,
            "latest_annual_period": None,
            "latest_interim_period": None,
            "subsequent_event_index_review_through": datetime.now(UTC).date().isoformat(),
            "market_price_date": None,
            "share_count_date": None,
            "retrieval_timestamp": retrieval_time,
        },
        "filings": {"latest_q": None, "prior_q": None, "latest_k": None},
        "subsequent_event_filings": [],
        "source_registry": [],
        "data_points": [],
        "evidence_records": [],
        "cash_flow_ledger": [],
        "validation_tests": validations,
        "data_gate": {"level": 0, "label": "Gate 0 - Unsupported core workflow", "hard_stop_ids": ["P0-supported-universe"]},
        "hard_stops": validations,
        "warnings": [],
    }
    (data_dir / "normalized_data.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (data_dir / "data_evidence_pack.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (validation_dir / "validation_report.md").write_text(
        "\n".join(
            [
                f"# {company['name']} ({company['ticker']}) Validation Report",
                "",
                "- Status: Gate 0 / formal analysis blocked.",
                f"- Required overlay: {support_assessment.get('overlay_required', 'specialized')}.",
                *[f"- {reason}" for reason in support_assessment.get("reasons", [])],
                "",
            ]
        ),
        encoding="utf-8",
    )
    (out_dir / "investment_data_pack.md").write_text(
        build_pack_markdown(company, {"latest_q": None, "prior_q": None, "latest_k": None}, [], validations),
        encoding="utf-8",
    )
    return out_dir


def build_company_pack(query: str, out_root: Path = DEFAULT_OUT_ROOT) -> Path:
    company = resolve_company(query)
    submissions = fetch_json(f"{SEC_BASE}/submissions/CIK{company['cik']}.json")
    latest_q, prior_q, latest_k = latest_filings(submissions)
    facts = fetch_json(f"{SEC_BASE}/api/xbrl/companyfacts/CIK{company['cik']}.json")
    support_assessment = assess_supported_universe(
        forms=submissions.get("filings", {}).get("recent", {}).get("form", []),
        taxonomies=facts.get("facts", {}).keys(),
        sic=submissions.get("sic"),
    )
    if not latest_q and not latest_k:
        return write_unsupported_diagnostic_pack(company, support_assessment, out_root)

    filing_for_period = latest_q or latest_k
    assert filing_for_period is not None

    rows: list[DataPoint] = []
    validations: list[dict[str, Any]] = []
    xbrl_selection_log: list[dict[str, Any]] = []
    denominator_control_log: list[dict[str, Any]] = []

    if support_assessment["status"] != "SUPPORTED_CORE":
        add_validation(
            validations,
            "P0-supported-universe",
            "BLOCKED",
            "Critical",
            "; ".join(support_assessment["reasons"]),
            "The shared non-financial US GAAP rules may produce invalid accounting or liquidity conclusions.",
            f"Use the {support_assessment['overlay_required']} overlay before formal analysis.",
            category="supported_universe",
            issue_class="HARD_STOP",
        )
    else:
        add_validation(
            validations,
            "P0-supported-universe",
            "PASS",
            "Critical",
            support_assessment["reasons"][0],
            "The issuer is inside the current core accounting scope.",
            "Apply specialized overlays if the issuer's reporting model changes.",
            category="supported_universe",
        )

    # Instant facts for the latest period and the opening balance sheet used by
    # quarter-based working-capital calculations. For Q1, the opening balance
    # is the latest 10-K date, not the previous 10-Q date.
    latest_end = filing_for_period.period
    latest_accn = filing_for_period.accession
    latest_url = filing_for_period.url

    for metric, tags in INSTANT_TAGS.items():
        fact = choose_instant(
            facts,
            tags,
            latest_end,
            latest_accn,
            metric_name=metric,
            audit_log=xbrl_selection_log,
        )
        if fact:
            rows.append(dp_from_fact(metric, fact, latest_url, "Balance sheet / instant fact", "instant"))

    prior_balance_candidates = [
        filing
        for filing in (prior_q, latest_k)
        if filing is not None and filing.period < latest_end
    ]
    prior_balance_filing = max(prior_balance_candidates, key=lambda filing: filing.period, default=None)
    prior_balance_end = prior_balance_filing.period if prior_balance_filing else ""

    if prior_balance_filing:
        for metric, tags in [
            ("prior_accounts_receivable_net", INSTANT_TAGS["accounts_receivable_net"]),
            ("prior_inventory_net", INSTANT_TAGS["inventory_net"]),
            ("prior_accounts_payable", INSTANT_TAGS["accounts_payable"]),
        ]:
            # A Q1 10-Q often repeats the December 31 balance sheet. Prefer the
            # current filing's comparative fact, then the filing that originally
            # reported the opening balance, then the latest filed matching fact.
            fact = choose_instant(
                facts,
                tags,
                prior_balance_end,
                latest_accn,
                metric_name=metric,
                audit_log=xbrl_selection_log,
            )
            if not fact:
                fact = choose_instant(
                    facts,
                    tags,
                    prior_balance_end,
                    prior_balance_filing.accession,
                    metric_name=metric,
                    audit_log=xbrl_selection_log,
                )
            if not fact:
                fact = choose_instant(
                    facts,
                    tags,
                    prior_balance_end,
                    metric_name=metric,
                    audit_log=xbrl_selection_log,
                )
            if fact:
                source_url = latest_url if fact.get("accn") == latest_accn else prior_balance_filing.url
                rows.append(
                    dp_from_fact(
                        metric,
                        fact,
                        source_url,
                        "Opening balance sheet for quarter / instant fact",
                        "instant",
                        notes=f"Opening balance date for working-capital days: {prior_balance_end}.",
                    )
                )

    # Try HTML AP extraction where standardized AP tag is missing.
    if "accounts_payable" not in {r.metric_name for r in rows} and latest_q:
        ap = extract_ap_proxy_from_html(latest_q.url)
        if ap:
            rows.append(
                manual_dp(
                    "accounts_payable",
                    ap[0],
                    period_end=latest_q.period,
                    fiscal_period="latest quarter",
                    filing_type=latest_q.form,
                    filing_date=latest_q.filed,
                    source_location=f"Inline filing row: {ap[2]}",
                    source_tag=ap[1],
                    source_url=latest_q.url,
                    evidence_type="FACT",
                    reported_or_calculated="reported",
                    confidence="Medium",
                    validation_status="analyst-review-needed",
                    notes="AP proxy extracted from filing row; verify definition before peer comparison.",
                )
            )
    if prior_balance_filing and "prior_accounts_payable" not in {r.metric_name for r in rows}:
        ap = extract_ap_proxy_from_html(prior_balance_filing.url)
        if ap:
            rows.append(
                manual_dp(
                    "prior_accounts_payable",
                    ap[0],
                    period_end=prior_balance_end,
                    fiscal_period="quarter opening balance",
                    filing_type=prior_balance_filing.form,
                    filing_date=prior_balance_filing.filed,
                    source_location=f"Inline filing row: {ap[2]}",
                    source_tag=ap[1],
                    source_url=prior_balance_filing.url,
                    evidence_type="FACT",
                    reported_or_calculated="reported",
                    confidence="Medium",
                    validation_status="analyst-review-needed",
                    notes=f"Opening balance date {prior_balance_end}; AP proxy extracted from filing row and requires definition review.",
                )
            )

    for row in rows:
        if row.metric_name not in {"accounts_payable", "prior_accounts_payable"}:
            continue
        if ap_balance_is_trade_compatible(row.source_tag):
            continue
        row.confidence = "Medium"
        row.validation_status = "PROVISIONAL"
        row.notes = (
            (row.notes + " ") if row.notes else ""
        ) + "Composite payable/accrual balance is retained as a liquidity fact but excluded from DPO and CCC."

    # Flow metrics.
    if latest_q:
        for metric, tags in FLOW_TAGS.items():
            quarter = choose_duration(
                facts,
                tags,
                latest_q.period,
                form="10-Q",
                accn=latest_q.accession,
                prefer="quarter",
                metric_name=f"latest_quarter_{metric}",
                audit_log=xbrl_selection_log,
            )
            ytd = choose_duration(
                facts,
                tags,
                latest_q.period,
                form="10-Q",
                accn=latest_q.accession,
                prefer="ytd",
                metric_name=f"latest_ytd_{metric}",
                audit_log=xbrl_selection_log,
            )
            if quarter:
                rows.append(dp_from_fact(f"latest_quarter_{metric}", quarter, latest_q.url, "Income statement / flow fact", "quarter"))
            if ytd and (not quarter or ytd.get("start") != quarter.get("start")):
                rows.append(dp_from_fact(f"latest_ytd_{metric}", ytd, latest_q.url, "Cash flow or income statement / flow fact", "YTD"))

            # Derive standalone quarter from YTD when useful and prior YTD exists.
            if ytd and prior_q:
                prior_ytd = choose_duration(
                    facts,
                    tags,
                    prior_q.period,
                    form="10-Q",
                    accn=prior_q.accession,
                    prefer="ytd",
                    metric_name=f"prior_same_fiscal_year_ytd_{metric}",
                    audit_log=xbrl_selection_log,
                )
                same_concept_and_unit = (
                    prior_ytd
                    and prior_ytd.get("tag") == ytd.get("tag")
                    and prior_ytd.get("unit") == ytd.get("unit")
                )
                if prior_ytd and prior_ytd.get("start") == ytd.get("start") and prior_ytd.get("end") != ytd.get("end") and same_concept_and_unit:
                    rows.append(
                        dp_from_fact(
                            f"prior_same_fiscal_year_ytd_{metric}",
                            prior_ytd,
                            prior_q.url,
                            "Prior same-fiscal-year YTD input for standalone-quarter derivation",
                            "YTD",
                        )
                    )
                    latest_val = safe_float(ytd.get("val"))
                    prior_val = safe_float(prior_ytd.get("val"))
                    if latest_val is not None and prior_val is not None:
                        derived_start_date = parse_date(prior_q.period)
                        derived_start = (derived_start_date + timedelta(days=1)).isoformat() if derived_start_date else ""
                        derived_duration = days_between(derived_start, latest_q.period) if derived_start else ""
                        if (
                            isinstance(derived_duration, int)
                            and QUARTER_MIN_DAYS <= derived_duration <= QUARTER_MAX_DAYS
                        ):
                            rows.append(
                                manual_dp(
                                    f"derived_latest_quarter_{metric}",
                                    latest_val - prior_val,
                                    unit=ytd.get("unit", ""),
                                    currency=unit_profile(ytd.get("unit"))["currency"],
                                    period_start=derived_start,
                                    period_end=latest_q.period,
                                    period_type="derived-quarter",
                                    duration_days_value=derived_duration,
                                    fiscal_period="latest quarter derived from YTD delta",
                                    filing_type=latest_q.form,
                                    filing_date=latest_q.filed,
                                    source_location=f"latest YTD {metric} - prior YTD {metric}",
                                    source_tag="calculation",
                                    source_url=latest_q.url,
                                    notes="Derived from same-concept, same-unit YTD facts; the derived interval passes 70-105 day quarter control.",
                                )
                            )
                        else:
                            add_validation(
                                validations,
                                f"P0-quarter-derivation-duration-{metric}",
                                "MISSING",
                                "High",
                                f"Standalone-quarter {metric} was suppressed because the derived interval was {derived_duration or 'invalid'} days.",
                                "The system does not force an irregular interval into a quarter label.",
                                "Reconcile the issuer's fiscal calendar and the two YTD contexts before deriving the quarter.",
                                category="period_validation",
                                issue_class="WARNING",
                            )
                elif prior_ytd and prior_ytd.get("start") == ytd.get("start") and prior_ytd.get("end") != ytd.get("end"):
                    add_validation(
                        validations,
                        f"P0-quarter-derivation-concept-{metric}",
                        "MISSING",
                        "High",
                        f"Standalone-quarter {metric} was not derived because current and prior YTD inputs use different concepts or units.",
                        "The system avoids combining non-comparable XBRL facts.",
                        "Reconcile the filing statement concepts manually before deriving a standalone quarter.",
                        category="period_validation",
                        issue_class="WARNING",
                    )
    elif latest_k:
        for metric, tags in FLOW_TAGS.items():
            annual = choose_duration(
                facts,
                tags,
                latest_k.period,
                form="10-K",
                accn=latest_k.accession,
                prefer="annual",
                metric_name=f"latest_annual_{metric}",
                audit_log=xbrl_selection_log,
            )
            if annual:
                rows.append(dp_from_fact(f"latest_annual_{metric}", annual, latest_k.url, "Annual statement / flow fact", "annual"))

    annual_anchor: dict[str, Any] | None = None
    if latest_k:
        for anchor_metric in ("revenue", "cfo", "net_income"):
            annual_anchor = choose_duration(
                facts,
                FLOW_TAGS[anchor_metric],
                latest_k.period,
                form="10-K",
                accn=latest_k.accession,
                prefer="annual",
            )
            if annual_anchor:
                break
    fiscal_profile = fiscal_calendar_profile(annual_anchor)

    ltm_control_results = {
        metric: build_ltm_metric(
            facts,
            metric,
            latest_q.period if latest_q else None,
            latest_k.period if latest_k else None,
        )
        for metric in ("revenue", "net_income", "cfo", "capex")
    }

    share_count_result = latest_share_count_fact(
        facts,
        datetime.now(UTC).date().isoformat(),
    )
    if share_count_result["status"] == "PASS" and share_count_result.get("point"):
        rows.append(
            dp_from_fact(
                "point_in_time_shares_outstanding",
                share_count_result["point"],
                f"{SEC_BASE}/api/xbrl/companyfacts/CIK{company['cik']}.json",
                "DEI cover-page point-in-time share count",
                "instant",
                notes="Point-in-time share count; do not substitute weighted-average EPS shares.",
            )
        )

    m = metric_map(rows)

    # Some filings present total liabilities and stockholders' equity without a
    # standalone total-liabilities fact. Preserve the accounting equation as a
    # transparent calculation instead of treating the missing tag as missing
    # economics.
    if "total_liabilities" not in m:
        total_assets_row = m.get("total_assets")
        equity_row = m.get("shareholders_equity")
        derived_liabilities = derive_total_liabilities(
            total_assets_row.value if total_assets_row else None,
            equity_row.value if equity_row else None,
        )
        dates_match = bool(
            total_assets_row
            and equity_row
            and total_assets_row.period_end
            and total_assets_row.period_end == equity_row.period_end
        )
        liability_basis = compatible_monetary_inputs(total_assets_row, equity_row)
        if derived_liabilities is not None and dates_match and liability_basis["status"] == "PASS":
            rows.append(
                manual_dp(
                    "total_liabilities",
                    derived_liabilities,
                    unit=liability_basis["unit"],
                    currency=liability_basis["currency"],
                    period_end=total_assets_row.period_end,
                    period_type="instant",
                    fiscal_period="latest period",
                    filing_type=filing_for_period.form,
                    filing_date=filing_for_period.filed,
                    source_location="total assets - shareholders' equity",
                    source_tag="calculation",
                    source_url=latest_url,
                    evidence_type="CALC",
                    reported_or_calculated="calculated",
                    notes="Derived from same-date balance-sheet facts using assets = liabilities + equity.",
                )
            )

    m = metric_map(rows)

    # Calculations.
    cash = val(m, "unrestricted_cash")
    sti = val(m, "short_term_investments")
    liquid_rows = [m.get(name) for name in ("unrestricted_cash", "short_term_investments") if m.get(name)]
    liquid_basis = compatible_monetary_inputs(*liquid_rows)
    observed_liquid_inputs = [value for value in (cash, sti) if value is not None]
    if observed_liquid_inputs and liquid_basis["status"] == "PASS":
        rows.append(
            manual_dp(
                "available_liquidity_before_facility_notes",
                sum(observed_liquid_inputs),
                unit=liquid_basis["unit"],
                currency=liquid_basis["currency"],
                period_end=latest_end,
                fiscal_period="latest period",
                filing_type=filing_for_period.form,
                filing_date=filing_for_period.filed,
                source_location="cash + short-term investments",
                source_tag="calculation",
                source_url=latest_url,
                notes="Sum of separately identified cash and short-term-investment inputs; excludes facility availability until note review.",
            )
        )

    m = metric_map(rows)
    lease_rows = [m.get(name) for name in ("finance_lease_current", "operating_lease_current") if m.get(name)]
    lease_basis = compatible_monetary_inputs(*lease_rows)
    lease_inputs = [val(m, "finance_lease_current"), val(m, "operating_lease_current")]
    observed_lease_inputs = [value for value in lease_inputs if value is not None]
    current_lease_total = sum(observed_lease_inputs) if observed_lease_inputs else None
    if current_lease_total is not None and lease_basis["status"] == "PASS":
        rows.append(
            manual_dp(
                "current_lease_obligations_total",
                current_lease_total,
                unit=lease_basis["unit"],
                currency=lease_basis["currency"],
                period_end=latest_end,
                fiscal_period="latest period",
                filing_type=filing_for_period.form,
                filing_date=filing_for_period.filed,
                source_location="current finance lease + current operating lease",
                source_tag="calculation",
                source_url=latest_url,
                notes="Mandatory uses not captured by current funded debt.",
            )
        )

    m = metric_map(rows)
    cfo_ytd = val(m, "latest_ytd_cfo")
    capex_ytd = val(m, "latest_ytd_capex")
    ytd_fcf_basis = compatible_monetary_inputs(m.get("latest_ytd_cfo"), m.get("latest_ytd_capex"))
    if cfo_ytd is not None and capex_ytd is not None and ytd_fcf_basis["status"] == "PASS":
        ytd_row = m["latest_ytd_cfo"]
        rows.append(
            manual_dp(
                "latest_ytd_fcf",
                cfo_ytd - capex_ytd,
                unit=ytd_fcf_basis["unit"],
                currency=ytd_fcf_basis["currency"],
                period_start=ytd_row.period_start,
                period_end=ytd_row.period_end,
                period_type="YTD",
                duration_days_value=ytd_row.duration_days,
                fiscal_period=ytd_row.fiscal_period,
                filing_type=ytd_row.filing_type,
                filing_date=ytd_row.filing_date,
                source_location="YTD CFO - YTD capex",
                source_tag="calculation",
                source_url=latest_url,
                notes="YTD FCF; not standalone quarter and not necessarily normalized maintenance FCF.",
            )
        )
    quarter_fcf_metric = ""
    q_cfo_row = None
    q_capex_row = None
    if "derived_latest_quarter_cfo" in m and "derived_latest_quarter_capex" in m:
        quarter_fcf_metric = "derived_latest_quarter_fcf"
        q_cfo_row = m["derived_latest_quarter_cfo"]
        q_capex_row = m["derived_latest_quarter_capex"]
    elif "latest_quarter_cfo" in m and "latest_quarter_capex" in m:
        quarter_fcf_metric = "latest_quarter_fcf"
        q_cfo_row = m["latest_quarter_cfo"]
        q_capex_row = m["latest_quarter_capex"]
    q_cfo = safe_float(q_cfo_row.value) if q_cfo_row else None
    q_capex = safe_float(q_capex_row.value) if q_capex_row else None
    quarter_periods_match = bool(
        q_cfo_row
        and q_capex_row
        and q_cfo_row.period_start == q_capex_row.period_start
        and q_cfo_row.period_end == q_capex_row.period_end
        and q_cfo_row.duration_days == q_capex_row.duration_days
    )
    quarter_fcf_basis = compatible_monetary_inputs(q_cfo_row, q_capex_row)
    if (
        q_cfo is not None
        and q_capex is not None
        and q_cfo_row
        and quarter_periods_match
        and quarter_fcf_basis["status"] == "PASS"
    ):
        rows.append(
            manual_dp(
                quarter_fcf_metric,
                q_cfo - q_capex,
                unit=quarter_fcf_basis["unit"],
                currency=quarter_fcf_basis["currency"],
                period_start=q_cfo_row.period_start,
                period_end=q_cfo_row.period_end,
                period_type=q_cfo_row.period_type,
                duration_days_value=q_cfo_row.duration_days,
                fiscal_period=q_cfo_row.fiscal_period,
                filing_type=q_cfo_row.filing_type,
                filing_date=q_cfo_row.filing_date,
                source_location="same-period CFO - capex",
                source_tag="calculation",
                source_url=latest_url,
                notes="Same-period FCF; still inspect working-capital timing and capex type.",
            )
        )
    elif q_cfo_row or q_capex_row:
        add_validation(
            validations,
            "P0-quarter-fcf-period-alignment",
            "MISSING",
            "High",
            "Standalone-quarter CFO and capex were not combined because both comparable inputs were not available on the same period basis.",
            "The system avoids a mixed-period quarterly FCF calculation.",
            "Reconcile standalone-quarter CFO and capex from the same reporting interval.",
            category="period_validation",
            issue_class="WARNING",
        )

    m = metric_map(rows)
    latest_rev_row = m.get("latest_quarter_revenue")
    latest_cogs_row = m.get("latest_quarter_cogs")
    if latest_rev_row and latest_rev_row.period_start and latest_rev_row.period_end:
        rev = val(m, "latest_quarter_revenue")
        period_days = days_between(latest_rev_row.period_start, latest_rev_row.period_end) or 90
        ar_now = val(m, "accounts_receivable_net")
        ar_prior = val(m, "prior_accounts_receivable_net")
        dso_result = controlled_ratio(
            ((ar_now + ar_prior) / 2) if ar_now is not None and ar_prior is not None else None,
            rev,
            multiplier=period_days,
        )
        denominator_control_log.append(
            {
                "metric_name": "dso_avg_ar",
                "denominator_metric": "latest_quarter_revenue",
                **dso_result,
            }
        )
        if dso_result["status"] == "PASS":
            rows.append(
                manual_dp(
                    "dso_avg_ar",
                    dso_result["value"],
                    unit="days",
                    currency="",
                    period_start=latest_rev_row.period_start,
                    period_end=latest_rev_row.period_end,
                    period_type="quarter",
                    duration_days_value=period_days,
                    filing_type=latest_rev_row.filing_type,
                    filing_date=latest_rev_row.filing_date,
                    source_location="average AR / revenue x days",
                    source_tag="calculation",
                    source_url=latest_url,
                    notes="Average-balance DSO; period-aligned.",
                )
            )
    if latest_cogs_row and latest_cogs_row.period_start and latest_cogs_row.period_end:
        cogs = val(m, "latest_quarter_cogs")
        period_days = days_between(latest_cogs_row.period_start, latest_cogs_row.period_end) or 90
        inv_now = val(m, "inventory_net")
        inv_prior = val(m, "prior_inventory_net")
        ap_now = val(m, "accounts_payable")
        ap_prior = val(m, "prior_accounts_payable")
        dio_result = controlled_ratio(
            ((inv_now + inv_prior) / 2) if inv_now is not None and inv_prior is not None else None,
            cogs,
            multiplier=period_days,
        )
        denominator_control_log.append(
            {
                "metric_name": "dio_avg_inventory",
                "denominator_metric": "latest_quarter_cogs",
                **dio_result,
            }
        )
        if dio_result["status"] == "PASS":
            rows.append(
                manual_dp(
                    "dio_avg_inventory",
                    dio_result["value"],
                    unit="days",
                    currency="",
                    period_start=latest_cogs_row.period_start,
                    period_end=latest_cogs_row.period_end,
                    period_type="quarter",
                    duration_days_value=period_days,
                    filing_type=latest_cogs_row.filing_type,
                    filing_date=latest_cogs_row.filing_date,
                    source_location="average inventory / COGS x days",
                    source_tag="calculation",
                    source_url=latest_url,
                    notes="Average-balance DIO; period-aligned.",
                )
            )
        ap_rows_trade_compatible = bool(
            m.get("accounts_payable")
            and m.get("prior_accounts_payable")
            and ap_balance_is_trade_compatible(m["accounts_payable"].source_tag)
            and ap_balance_is_trade_compatible(m["prior_accounts_payable"].source_tag)
        )
        dpo_result = controlled_ratio(
            ((ap_now + ap_prior) / 2)
            if ap_now is not None and ap_prior is not None and ap_rows_trade_compatible
            else None,
            cogs,
            multiplier=period_days,
        )
        denominator_control_log.append(
            {
                "metric_name": "dpo_avg_ap",
                "denominator_metric": "latest_quarter_cogs",
                **dpo_result,
            }
        )
        if dpo_result["status"] == "PASS":
            rows.append(
                manual_dp(
                    "dpo_avg_ap",
                    dpo_result["value"],
                    unit="days",
                    currency="",
                    period_start=latest_cogs_row.period_start,
                    period_end=latest_cogs_row.period_end,
                    period_type="quarter",
                    duration_days_value=period_days,
                    filing_type=latest_cogs_row.filing_type,
                    filing_date=latest_cogs_row.filing_date,
                    source_location="average AP / COGS x days",
                    source_tag="calculation",
                    source_url=latest_url,
                    confidence="Medium" if "analyst-review-needed" in [r.validation_status for r in rows if r.metric_name in {"accounts_payable", "prior_accounts_payable"}] else "High",
                    notes="Check AP definition; some filings include accrued expenses or outstanding checks.",
                )
            )
    m = metric_map(rows)
    if all(name in m for name in ("dso_avg_ar", "dio_avg_inventory", "dpo_avg_ap")):
        rows.append(
            manual_dp(
                "cash_conversion_cycle",
                val(m, "dso_avg_ar") + val(m, "dio_avg_inventory") - val(m, "dpo_avg_ap"),
                unit="days",
                currency="",
                period_start=m["dso_avg_ar"].period_start,
                period_end=m["dso_avg_ar"].period_end,
                period_type="quarter",
                duration_days_value=m["dso_avg_ar"].duration_days,
                filing_type=m["dso_avg_ar"].filing_type,
                filing_date=m["dso_avg_ar"].filing_date,
                source_location="DSO + DIO - DPO",
                source_tag="calculation",
                source_url=latest_url,
                confidence="Medium",
                notes="Compare trend and peers before drawing an investment conclusion.",
            )
        )

    # Filing-note snippets: useful but not enough for final facility/covenant conclusions.
    raw_text = fetch_text(latest_url)
    filing_text = html_to_text(raw_text)
    facility_values = extract_facility_values(
        filing_text,
        as_of_date=latest_end,
    )
    for metric_name, (metric_value, metric_note) in facility_values.items():
        rows.append(
            manual_dp(
                metric_name,
                metric_value,
                period_end=latest_end,
                fiscal_period="latest period",
                filing_type=filing_for_period.form,
                filing_date=filing_for_period.filed,
                source_location="Latest filing debt/facility note",
                source_tag="regex-note-parse",
                source_url=latest_url,
                evidence_type="FACT",
                reported_or_calculated="reported",
                confidence="Medium",
                validation_status="analyst-review-needed",
                notes=metric_note,
            )
        )
    m = metric_map(rows)
    total_available_borrowings = val(m, "total_available_borrowings_reported")
    facility_availability = val(m, "facility_availability_reported")
    borrowing_availability = total_available_borrowings if total_available_borrowings is not None else facility_availability
    liquidity_before_facility = val(m, "available_liquidity_before_facility_notes")
    facility_metric_name = (
        "total_available_borrowings_reported"
        if total_available_borrowings is not None
        else "facility_availability_reported"
    )
    facility_liquidity_basis = compatible_monetary_inputs(
        m.get("available_liquidity_before_facility_notes"),
        m.get(facility_metric_name),
    )
    if (
        borrowing_availability is not None
        and liquidity_before_facility is not None
        and facility_liquidity_basis["status"] == "PASS"
    ):
        rows.append(
            manual_dp(
                "available_liquidity_including_reported_facility",
                liquidity_before_facility + borrowing_availability,
                unit=facility_liquidity_basis["unit"],
                currency=facility_liquidity_basis["currency"],
                period_end=latest_end,
                fiscal_period="latest period",
                filing_type=filing_for_period.form,
                filing_date=filing_for_period.filed,
                source_location="cash/STI + reported available borrowings",
                source_tag="calculation",
                source_url=latest_url,
                evidence_type="CALC",
                reported_or_calculated="calculated",
                confidence="Medium",
                validation_status="analyst-review-needed",
                notes="Preliminary liquidity source; verify availability, restrictions, LC, reserves, borrowing base, and maturity in the debt note.",
            )
        )

    facility_snippet = find_snippet(
        filing_text,
        ("revolving credit facility", "ABL Facility", "credit agreement", "credit facility", "excess availability", "letters of credit"),
    )
    covenant_snippet = find_snippet(filing_text, ("covenant", "fixed charge coverage", "minimum liquidity", "borrowing base"))
    if facility_snippet:
        rows.append(
            manual_dp(
                "facility_note_snippet",
                facility_snippet[:1200],
                unit="text",
                currency="",
                period_end=latest_end,
                period_type="note-snippet",
                filing_type=filing_for_period.form,
                filing_date=filing_for_period.filed,
                source_location="Latest filing text search",
                source_tag="keyword-snippet",
                source_url=latest_url,
                evidence_type="FACT",
                reported_or_calculated="reported",
                confidence="Medium",
                validation_status="analyst-review-needed",
                notes="Snippet only. Full debt/facility note reading is required for high-confidence facility analysis.",
            )
        )
    if covenant_snippet:
        rows.append(
            manual_dp(
                "covenant_note_snippet",
                covenant_snippet[:1200],
                unit="text",
                currency="",
                period_end=latest_end,
                period_type="note-snippet",
                filing_type=filing_for_period.form,
                filing_date=filing_for_period.filed,
                source_location="Latest filing text search",
                source_tag="keyword-snippet",
                source_url=latest_url,
                evidence_type="FACT",
                reported_or_calculated="reported",
                confidence="Medium",
                validation_status="analyst-review-needed",
                notes="Snippet only. Full covenant analysis requires note/legal document review.",
            )
        )

    # Validation gates.
    m = metric_map(rows)
    if fiscal_profile["status"] == "PASS":
        calendar_labels = [
            fiscal_profile["calendar_basis"],
            fiscal_profile["week_structure"],
            f"{fiscal_profile['duration_days']} days",
        ]
        add_validation(
            validations,
            "P0-fiscal-calendar-control",
            "PASS",
            "Critical",
            "Validated fiscal-year context: " + ", ".join(calendar_labels) + ".",
            "Quarter, YTD, FY, and LTM controls use reported fiscal dates instead of assuming a December year-end or 365-day year.",
            "Re-evaluate the profile after every annual filing or restatement.",
            category="period_validation",
        )
    else:
        add_validation(
            validations,
            "P0-fiscal-calendar-control",
            "MISSING",
            "High",
            fiscal_profile.get("reason", "Fiscal-calendar profile is unavailable."),
            "Non-calendar and 53-week period comparability cannot be confirmed automatically.",
            "Source a validated annual flow context before constructing FY or LTM metrics.",
            category="period_validation",
            issue_class="WARNING",
        )

    context_issues: list[str] = []
    for row in rows:
        if row.period_type == "instant" and row.period_start:
            context_issues.append(f"{row.metric_name}: instant row has a start date")
        elif row.period_type in {"quarter", "derived-quarter"}:
            duration = safe_float(row.duration_days)
            if (
                not row.period_start
                or not row.period_end
                or duration is None
                or not QUARTER_MIN_DAYS <= duration <= QUARTER_MAX_DAYS
            ):
                context_issues.append(f"{row.metric_name}: invalid quarter context")
        elif row.period_type == "YTD":
            fiscal_period_label = str(row.fiscal_period or "").split()
            point = {
                "start": row.period_start,
                "end": row.period_end,
                "form": row.filing_type,
                "fp": fiscal_period_label[-1] if fiscal_period_label else "",
            }
            if not is_ytd_flow(point):
                context_issues.append(f"{row.metric_name}: invalid YTD context")
        elif row.period_type == "annual":
            duration = safe_float(row.duration_days)
            if (
                not row.period_start
                or not row.period_end
                or duration is None
                or not ANNUAL_MIN_DAYS <= duration <= ANNUAL_MAX_DAYS
            ):
                context_issues.append(f"{row.metric_name}: invalid FY context")
    if context_issues:
        add_validation(
            validations,
            "P0-instant-flow-period-control",
            "FAIL",
            "Critical",
            "; ".join(context_issues),
            "A point-in-time fact or flow metric has an incompatible context or period label.",
            "Correct the shared context selector before generating a report.",
            category="period_validation",
            issue_class="HARD_STOP",
        )
    else:
        add_validation(
            validations,
            "P0-instant-flow-period-control",
            "PASS",
            "Critical",
            "Every selected instant, quarter, YTD, derived-quarter, and FY row has a compatible XBRL context and duration.",
            "Prevents instant/flow contamination and quarter/YTD/FY relabeling.",
            "Keep the shared selector as the only financial-fact ingestion path.",
            category="period_validation",
        )

    xbrl_rows = [
        row
        for row in rows
        if row.reported_or_calculated == "reported"
        and row.source_tag.startswith(("us-gaap:", "dei:"))
    ]
    unit_issues: list[str] = []
    monetary_currencies: set[str] = set()
    for row in xbrl_rows:
        profile = unit_profile(row.unit)
        expected_category = "SHARES" if row.metric_name == "point_in_time_shares_outstanding" else "MONETARY"
        if profile["category"] != expected_category:
            unit_issues.append(
                f"{row.metric_name}: expected {expected_category}, received {row.unit or 'blank'}"
            )
        if profile["category"] == "MONETARY":
            monetary_currencies.add(profile["currency"])
    if "" in monetary_currencies or len(monetary_currencies) > 1:
        unit_issues.append(
            "Selected monetary facts contain an unknown currency or more than one reporting currency."
        )
    if unit_issues:
        add_validation(
            validations,
            "P0-unit-currency-control",
            "FAIL",
            "Critical",
            "; ".join(unit_issues),
            "A material calculation could combine incompatible units or currencies.",
            "Reconcile the source units and reporting currency in the shared Data and Evidence Layer.",
            category="unit_currency_validation",
            issue_class="HARD_STOP",
        )
    else:
        currency_label = next(iter(monetary_currencies), "not observed")
        add_validation(
            validations,
            "P0-unit-currency-control",
            "PASS",
            "Critical",
            f"All selected financial facts use validated semantic units and one reporting currency ({currency_label}); share count uses shares.",
            "Prevents silent unit, currency, and share-count basis mixing.",
            "Require explicit conversion evidence before combining another currency.",
            category="unit_currency_validation",
        )

    if share_count_result["status"] == "CONFLICT":
        add_validation(
            validations,
            "P0-share-count-control",
            "FAIL",
            "Critical",
            share_count_result["reason"],
            "Market capitalization and per-share outputs would be unreproducible.",
            "Reconcile share classes, dimensions, filing date, and the point-in-time share-count source.",
            category="share_count_validation",
            issue_class="HARD_STOP",
        )
    elif share_count_result["status"] == "PASS":
        add_validation(
            validations,
            "P0-share-count-control",
            "PASS",
            "Critical",
            (
                f"Point-in-time shares were selected as of {share_count_result['share_count_date']} "
                f"from a filing published {share_count_result['publication_date']}."
            ),
            "The system separates point-in-time shares from weighted-average EPS shares and blocks future-publication leakage.",
            "Re-select shares against the exact market-price date before valuation.",
            category="share_count_validation",
        )
    else:
        add_validation(
            validations,
            "P0-share-count-control",
            "MISSING",
            "High",
            share_count_result["reason"],
            "Market capitalization and per-share valuation must remain unavailable.",
            "Source a published point-in-time cover-page share count on or before the market date.",
            category="share_count_validation",
            issue_class="WARNING",
        )

    ltm_pass = [
        metric
        for metric, result in ltm_control_results.items()
        if result.get("period_type") == "LTM" and result.get("validation_status") == "PASS"
    ]
    if ltm_pass:
        add_validation(
            validations,
            "P0-ltm-construction-control",
            "PASS",
            "Critical",
            "Validated LTM construction is available for: " + ", ".join(sorted(ltm_pass)) + ".",
            "Each LTM value uses one concept, one unit/currency, a validated FY, and comparable current/prior YTD contexts.",
            "Keep annual fallback clearly labeled for metrics that do not pass LTM construction.",
            category="period_validation",
        )
    else:
        add_validation(
            validations,
            "P0-ltm-construction-control",
            "MISSING",
            "High",
            "No key metric passed the complete shared LTM construction control; annual fallback or missing status is retained.",
            "The system does not fabricate LTM values from non-comparable periods.",
            "Reconcile annual, current YTD, and prior comparable YTD contexts using one XBRL concept.",
            category="period_validation",
            issue_class="WARNING",
        )

    required_selection_names = {
        "unrestricted_cash",
        "accounts_receivable_net",
        "current_assets",
        "current_liabilities",
        "total_assets",
        "shareholders_equity",
    }
    if latest_q:
        required_selection_names.update(
            {
                "latest_quarter_revenue",
                "latest_ytd_cfo",
                "latest_ytd_capex",
            }
        )
    else:
        required_selection_names.update(
            {
                "latest_annual_revenue",
                "latest_annual_cfo",
                "latest_annual_capex",
            }
        )
    selected_names = {
        item["metric_name"]
        for item in xbrl_selection_log
        if item["status"] == "SELECTED"
    }
    unresolved_required = sorted(required_selection_names - selected_names)
    unsafe_missing_defaults = [
        item["metric_name"]
        for item in xbrl_selection_log
        if item.get("missing_value_assumed_zero")
    ]
    if unsafe_missing_defaults:
        add_validation(
            validations,
            "P0-missing-xbrl-safe-handling",
            "FAIL",
            "Critical",
            "Missing XBRL selections were assigned numeric defaults: " + ", ".join(unsafe_missing_defaults) + ".",
            "Missing disclosure may be misrepresented as a zero balance or zero cash flow.",
            "Remove the default and preserve MISSING or NOT_APPLICABLE pending analyst review.",
            category="xbrl_coverage",
            issue_class="HARD_STOP",
        )
    elif unresolved_required:
        add_validation(
            validations,
            "P0-missing-xbrl-safe-handling",
            "MISSING",
            "High",
            "Required selections remain missing or incompatible: " + ", ".join(unresolved_required) + "; none was assumed to be zero.",
            "Affected calculations and conclusions remain suppressed or qualified.",
            "Inspect the filing taxonomy, statement table, and company-specific extension tags before analyst validation.",
            category="xbrl_coverage",
            issue_class="WARNING",
        )
    else:
        add_validation(
            validations,
            "P0-missing-xbrl-safe-handling",
            "PASS",
            "High",
            "Required shared selections were found and no missing XBRL fact was converted to zero.",
            "Preserves the distinction between a reported zero and unavailable disclosure.",
            "Retain explicit MISSING status for optional or future metrics.",
            category="xbrl_coverage",
        )

    suppressed_denominators = [
        item for item in denominator_control_log if item["status"] == "SUPPRESSED"
    ]
    if suppressed_denominators:
        add_validation(
            validations,
            "P0-negative-denominator-control",
            "WARNING",
            "High",
            "; ".join(
                f"{item['metric_name']}: {item['reason']}" for item in suppressed_denominators
            ),
            "The affected ratio is suppressed instead of presenting an economically invalid working-capital metric.",
            "Use a valid positive same-period denominator or classify the metric as not meaningful.",
            category="ratio_validation",
            issue_class="WARNING",
        )
    else:
        add_validation(
            validations,
            "P0-negative-denominator-control",
            "PASS",
            "High",
            "No calculated working-capital ratio used a zero, negative, missing, or non-finite denominator.",
            "Prevents invalid DSO, DIO, or DPO outputs.",
            "Apply the same shared ratio control to every future denominator-based metric.",
            category="ratio_validation",
        )

    nonnegative_balance_metrics = {
        "unrestricted_cash",
        "cash_and_restricted_cash",
        "short_term_investments",
        "accounts_receivable_net",
        "inventory_net",
        "accounts_payable",
        "current_assets",
        "current_liabilities",
        "total_assets",
        "total_liabilities",
        "current_debt",
        "long_term_debt",
        "finance_lease_current",
        "finance_lease_noncurrent",
        "operating_lease_current",
        "operating_lease_noncurrent",
    }
    invalid_balance_rows = [
        row
        for row in rows
        if row.metric_name.removeprefix("prior_") in nonnegative_balance_metrics
        and (
            (safe_float(row.value) is not None and (safe_float(row.value) or 0.0) < 0)
            or "increasedecrease" in str(row.source_tag).lower()
        )
    ]
    if invalid_balance_rows:
        add_validation(
            validations,
            "P0-instant-balance-semantic-check",
            "FAIL",
            "Critical",
            "Invalid instant balance extraction: "
            + "; ".join(
                f"{row.metric_name}={row.value} via {row.source_tag}" for row in invalid_balance_rows
            ),
            "A cash-flow movement or negative balance may have been mislabeled as a point-in-time asset or liability.",
            "Correct the shared XBRL concept map or HTML fallback before using the data pack.",
            evidence_ids=[row.evidence_id for row in invalid_balance_rows if row.evidence_id],
        )
    else:
        add_validation(
            validations,
            "P0-instant-balance-semantic-check",
            "PASS",
            "Critical",
            "No nonnegative balance-sheet metric uses a negative value or IncreaseDecrease cash-flow concept.",
            "Protects point-in-time balances from cash-flow tag contamination.",
            "Keep this validation active for every supported issuer.",
        )
    assets = val(m, "total_assets")
    liabilities = val(m, "total_liabilities")
    equity = val(m, "shareholders_equity")
    if assets is not None and liabilities is not None and equity is not None:
        add_validation(
            validations,
            "P0-balance-sheet-check",
            "PASS" if near(assets, liabilities + equity, max(5_000_000, abs(assets) * 0.001)) else "FAIL",
            "Critical",
            f"Assets {fmt_usd(assets)}; liabilities + equity {fmt_usd(liabilities + equity)}.",
            "Confirms statement extraction integrity.",
            "Investigate tag selection or noncontrolling-interest equity if fail.",
        )
    else:
        add_validation(validations, "P0-balance-sheet-check", "MISSING", "High", "Assets/liabilities/equity tags incomplete.", "Cannot fully validate balance-sheet extraction.", "Inspect filing tables manually.")

    ni_q = m.get("latest_quarter_net_income")
    cfo_y = m.get("latest_ytd_cfo")
    if ni_q and cfo_y and (ni_q.period_start != cfo_y.period_start or ni_q.period_end != cfo_y.period_end):
        add_validation(
            validations,
            "P0-period-mismatch-block",
            "PASS",
            "Critical",
            f"Incompatible inputs were detected and not combined: quarter net income {ni_q.period_start} to {ni_q.period_end}; YTD CFO {cfo_y.period_start} to {cfo_y.period_end}.",
            "The engine correctly prevents invalid CFO/net income or FCF/profit ratios.",
            "Continue to use YTD/YTD, quarter/quarter, or validated derived-quarter metrics only.",
            category="period_alignment",
        )
    else:
        add_validation(validations, "P0-period-mismatch-block", "PASS", "Critical", "No quarter/YTD mixed-flow ratio was generated.", "Flow ratios are period-gated.", "Keep validation before memo drafting.", category="period_alignment")

    if "cash_and_restricted_cash" in m and "unrestricted_cash" in m:
        add_validation(
            validations,
            "P0-cash-definition-check",
            "PASS",
            "High",
            f"Cash {fmt_usd(val(m, 'unrestricted_cash'))}; cash + restricted cash {fmt_usd(val(m, 'cash_and_restricted_cash'))}.",
            "Prevents overstating usable cash.",
            "Use unrestricted cash for liquidity unless restricted cash is verified usable.",
        )
    else:
        add_validation(validations, "P0-cash-definition-check", "MISSING", "Medium", "Restricted cash or combined cash tag missing.", "Cash availability may need filing-table review.", "Separate cash, restricted cash, and cash equivalents manually if material.")

    if "latest_ytd_fcf" in m:
        add_validation(validations, "P0-fcf-classification", "PASS", "High", f"YTD FCF tagged as {m['latest_ytd_fcf'].period_type}.", "Stops YTD FCF from being mislabeled as standalone quarter.", "Show period type in memo.")
    if "derived_latest_quarter_fcf" in m or "latest_quarter_fcf" in m:
        row = m.get("derived_latest_quarter_fcf") or m.get("latest_quarter_fcf")
        add_validation(validations, "P0-quarter-fcf-check", "PASS", "High", f"Latest-quarter FCF is tagged as {row.period_type}.", "Supports same-period cash conversion analysis.", "Do not annualize mechanically.")
    else:
        add_validation(validations, "P0-quarter-fcf-check", "MISSING", "Medium", "Standalone quarter FCF not derivable from available tags.", "Cash conversion confidence is lower.", "Use YTD view and inspect cash-flow statement.")

    quarter_flow_row = m.get("latest_quarter_revenue") or m.get("latest_quarter_cogs")
    expected_opening_end = ""
    if quarter_flow_row and quarter_flow_row.period_start:
        quarter_start = parse_date(quarter_flow_row.period_start)
        expected_opening_end = (quarter_start - timedelta(days=1)).isoformat() if quarter_start else ""
    opening_rows = [
        m[name]
        for name in ("prior_accounts_receivable_net", "prior_inventory_net", "prior_accounts_payable")
        if name in m
    ]
    opening_dates = sorted({row.period_end for row in opening_rows if row.period_end})
    if expected_opening_end and opening_rows:
        aligned = all(row.period_end == expected_opening_end for row in opening_rows)
        add_validation(
            validations,
            "P0-working-capital-opening-balance-alignment",
            "PASS" if aligned else "FAIL",
            "Critical",
            f"Expected opening balance date {expected_opening_end}; extracted dates {', '.join(opening_dates) or 'none'}.",
            "Prevents DSO/DIO/DPO from averaging non-adjacent balance-sheet dates.",
            "Use the balance sheet dated one day before the quarter starts before calculating working-capital days.",
        )
    else:
        add_validation(
            validations,
            "P0-working-capital-opening-balance-alignment",
            "MISSING",
            "High",
            "Quarter start or opening working-capital balances are unavailable.",
            "Average-balance working-capital days cannot be date-validated.",
            "Extract the immediately preceding balance sheet before calculating DSO/DIO/DPO.",
        )

    if "dso_avg_ar" in m or "dio_avg_inventory" in m or "dpo_avg_ap" in m:
        add_validation(validations, "P0-working-capital-days", "PASS", "Medium", "At least one average-balance working-capital day metric calculated.", "Improves monitoring vs single-point ratios.", "Add 8-quarter trend before final memo.")
    else:
        add_validation(validations, "P0-working-capital-days", "MISSING", "Medium", "Could not calculate average-balance DSO/DIO/DPO.", "Working-capital pressure cannot be assessed fully.", "Extract prior quarter balances or note definitions.")

    working_capital_coverage = working_capital_component_coverage(set(m))
    if working_capital_coverage["status"] == "COMPLETE":
        add_validation(
            validations,
            "P1-working-capital-component-coverage",
            "PASS",
            "High",
            "DSO, DIO, DPO, and CCC are all available; no absent component was assumed to be zero.",
            "The working-capital cycle has complete component coverage at the current reporting date.",
            "Retain business-model and note-definition review before peer comparison.",
            category="working_capital_coverage",
        )
    elif working_capital_coverage["status"] == "PARTIAL":
        add_validation(
            validations,
            "P1-working-capital-component-coverage",
            "PROVISIONAL",
            "High",
            (
                f"Available components: {', '.join(working_capital_coverage['available'])}; "
                f"missing pending classification: {', '.join(working_capital_coverage['unavailable'])}. "
                "No absent component is assumed to be zero."
            ),
            "A partial cycle must not be presented as complete cash-conversion analysis.",
            (
                "Review the business model and filing definitions, then classify each unavailable "
                "component as NOT_APPLICABLE or MISSING before final underwriting."
            ),
            category="working_capital_coverage",
            issue_class="WARNING",
        )

    ap_rows = [m.get("accounts_payable"), m.get("prior_accounts_payable")]
    ap_rows = [row for row in ap_rows if row]
    if ap_rows and not all(ap_balance_is_trade_compatible(row.source_tag) for row in ap_rows):
        add_validation(
            validations,
            "P1-ap-definition-for-dpo",
            "PROVISIONAL",
            "High",
            "Accounts payable is disclosed through a composite payable/accrual concept; DPO and CCC are suppressed.",
            "Prevents accrued compensation or other liabilities from being treated as supplier financing.",
            "Source a trade-payables-only balance before calculating DPO or CCC.",
            evidence_ids=[row.evidence_id for row in ap_rows if row.evidence_id],
        )
    elif len(ap_rows) == 2:
        add_validation(
            validations,
            "P1-ap-definition-for-dpo",
            "PASS",
            "High",
            "Current and opening accounts-payable balances use trade-compatible concepts.",
            "DPO can be calculated without known accrued-liability contamination.",
            "Retain note-level definition review for material peer comparisons.",
            evidence_ids=[row.evidence_id for row in ap_rows if row.evidence_id],
        )

    current_debt = val(m, "current_debt")
    current_leases_raw = val(m, "current_lease_obligations_total")
    current_leases = current_leases_raw if current_leases_raw is not None else 0.0
    has_current_lease_tags = "finance_lease_current" in m or "operating_lease_current" in m or "current_lease_obligations_total" in m
    if current_debt is None:
        add_validation(validations, "P0-current-debt-vs-lease-check", "MISSING", "High", "A standardized current-debt value was not identified; absence of a tag is not treated as zero.", "Near-term funded debt and total fixed obligations cannot be confirmed.", "Inspect the balance sheet and debt note before stating that current debt is zero.")
    elif current_debt == 0 and current_leases > 0:
        add_validation(validations, "P0-current-debt-vs-lease-check", "PASS", "High", f"Current debt is {fmt_usd(current_debt)}; current leases are {fmt_usd(current_leases)}.", "Stops current debt = 0 from becoming a false positive.", "Show leases in 12-month uses.")
    elif current_debt == 0 and current_leases == 0:
        add_validation(validations, "P0-current-debt-vs-lease-check", "MISSING", "Medium", "Current funded debt is zero and current leases are missing or zero.", "May understate fixed obligations.", "Inspect lease note and commitments.")
    elif current_debt > 0 and not has_current_lease_tags:
        add_validation(validations, "P0-current-debt-vs-lease-check", "MISSING", "Medium", f"Current debt is {fmt_usd(current_debt)}, but standardized current lease tags were not found.", "Near-term obligations may be understated if leases are material.", "Inspect lease note and commitments before final memo.")
    else:
        add_validation(validations, "P0-current-debt-vs-lease-check", "PASS", "Medium", f"Current debt {fmt_usd(current_debt)}; current leases {fmt_usd(current_leases)}.", "Near-term obligations are visible at high level.", "Still include cash interest and capex.")

    facility_reconciliation = assess_facility_reconciliation(facility_values)
    if facility_reconciliation["status"] == "FAIL":
        add_validation(
            validations,
            "P0-facility-reconciliation",
            "FAIL",
            "Critical",
            (
                f"Facility commitment {fmt_usd(facility_reconciliation['commitment'])} is below "
                f"availability plus known reductions "
                f"{fmt_usd(facility_reconciliation['known_component_total'])}; "
                f"gap {fmt_usd(facility_reconciliation['gap'])}."
            ),
            "At least one facility amount is linked to the wrong instrument, period, or disclosure context.",
            "Suppress the conflicting facility values and re-extract them from same-instrument, same-date filing evidence.",
            category="facility_reconciliation",
            issue_class="HARD_STOP",
            evidence_ids=[
                row.evidence_id
                for name in (
                    "facility_commitment",
                    "facility_availability_reported",
                    "facility_borrowings",
                    "facility_letters_of_credit",
                    "facility_lender_reserves",
                )
                if (row := m.get(name)) is not None and row.evidence_id
            ],
        )
    elif facility_reconciliation["status"] == "PASS":
        add_validation(
            validations,
            "P0-facility-reconciliation",
            "PASS",
            "Critical",
            (
                f"Facility commitment {fmt_usd(facility_reconciliation['commitment'])} "
                f"reconciles to availability and known reductions within "
                f"{fmt_usd(1_000_000)}."
            ),
            "The extracted facility amounts pass the internal arithmetic consistency check.",
            "Retain note-level review for conditions, maturity, borrowing-base mechanics, and undisclosed restrictions.",
            category="facility_reconciliation",
            evidence_ids=[
                row.evidence_id
                for name in (
                    "facility_commitment",
                    "facility_availability_reported",
                    "facility_borrowings",
                    "facility_letters_of_credit",
                    "facility_lender_reserves",
                )
                if (row := m.get(name)) is not None and row.evidence_id
            ],
        )
    elif facility_reconciliation["status"] == "PROVISIONAL":
        add_validation(
            validations,
            "P1-facility-reconciliation",
            "PROVISIONAL",
            "High",
            (
                f"Facility commitment exceeds availability plus known reductions by "
                f"{fmt_usd(facility_reconciliation['gap'])}; the residual is not explained."
            ),
            "Liquidity may be overstated if an unidentified reserve, borrowing, or other restriction is omitted.",
            "Identify every availability reduction in the debt note before treating the facility as fully usable.",
            category="facility_reconciliation",
            issue_class="WARNING",
        )

    if "facility_availability_reported" in m:
        add_validation(validations, "P1-facility-note-check", "PROVISIONAL", "High", f"Reported facility availability parsed as {fmt_usd(val(m, 'facility_availability_reported'))}; full note still needs review.", "Liquidity view can include a preliminary facility source, but restrictions and borrowing-base mechanics remain analyst-review items.", "Read debt note and confirm commitment, availability, LC, reserves, maturity, borrowing base, and conditions.")
    elif "facility_note_snippet" in m:
        add_validation(validations, "P1-facility-note-check", "PROVISIONAL", "High", "Facility/credit agreement snippet found, but not fully parsed.", "Availability/covenant conclusions require note-level review.", "Read debt note and extract commitment, availability, LC, reserves, maturity, borrowing base.")
    else:
        add_validation(validations, "P1-facility-note-check", "MISSING", "High", "No facility snippet found by generic search.", "Do not rely on cash/current liabilities alone.", "Read debt/liquidity notes manually.")

    if "covenant_note_snippet" in m:
        add_validation(validations, "P1-covenant-check", "PROVISIONAL", "High", "Covenant-related snippet found, but trigger/headroom not fully parsed.", "Covenant risk cannot be rated high-confidence yet.", "Extract trigger, headroom, compliance, and springing conditions.")
    else:
        add_validation(validations, "P1-covenant-check", "MISSING", "High", "No covenant snippet found by generic search.", "Cannot confirm covenant pressure.", "Read credit agreement/debt note manually if leverage is material.")

    add_validation(
        validations,
        "P2-investment-action-gate",
        "BLOCKED",
        "High",
        "This generic data pack does not source consensus, peer valuation, target price, normalized EBITDA, or scenario return.",
        "Prevents a credit screen from being presented as a complete investment recommendation.",
        "Add valuation, earnings quality, scenario, catalyst, and risk/reward layers before Buy/Sell/Hold.",
        category="decision_gate",
        issue_class="WARNING",
    )

    events = subsequent_event_filings(submissions, filing_for_period.filed)
    if events:
        add_validation(
            validations,
            "P1-subsequent-event-review",
            "PROVISIONAL",
            "High",
            f"{len(events)} Form 8-K/8-K/A filing(s) were filed after the latest financial filing; content review remains required.",
            "A later event may change debt, liquidity, shares, guidance, or the displayed current state.",
            "Review each listed subsequent filing and link any effect to a new evidence record before a partner-ready memo.",
            category="subsequent_events",
            issue_class="WARNING",
        )
    else:
        add_validation(
            validations,
            "P1-subsequent-event-review",
            "PASS",
            "High",
            "No later Form 8-K/8-K/A filing was listed after the latest financial filing as of retrieval.",
            "No unreviewed subsequent filing was identified by the submissions index.",
            "Re-run the index review immediately before publication.",
            category="subsequent_events",
        )

    for index, event in enumerate(events, start=1):
        rows.append(
            manual_dp(
                f"subsequent_event_filing_{index}",
                event.get("items") or event.get("form"),
                unit="filing",
                currency="",
                period_end=event.get("filing_date", ""),
                period_type="filing_event",
                fiscal_period=event.get("report_date", ""),
                filing_type=event.get("form", ""),
                filing_date=event.get("filing_date", ""),
                source_location=f"SEC submissions index; accession {event.get('accession', '')}",
                source_tag=f"SEC:{event.get('form', '')}:{event.get('accession', '')}",
                source_url=event.get("source_url", ""),
                evidence_type="FACT",
                reported_or_calculated="reported",
                confidence="High",
                validation_status="review-required",
                notes="Filing existence is validated; filing content and decision impact remain unreviewed.",
            )
        )

    enrich_data_points(company, rows)
    rows_by_evidence_id = {row.evidence_id: row for row in rows}
    calculation_basis_issues: list[str] = []
    for row in rows:
        if row.reported_or_calculated != "calculated":
            continue
        inputs = [
            rows_by_evidence_id[evidence_id]
            for evidence_id in (row.input_evidence_ids or [])
            if evidence_id in rows_by_evidence_id
        ]
        monetary_inputs = [
            input_row
            for input_row in inputs
            if unit_profile(input_row.unit)["category"] == "MONETARY"
        ]
        input_currencies = {unit_profile(input_row.unit)["currency"] for input_row in monetary_inputs}
        output_profile = unit_profile(row.unit)
        if "" in input_currencies or len(input_currencies) > 1:
            calculation_basis_issues.append(
                f"{row.metric_name}: upstream monetary currencies are missing or inconsistent"
            )
        elif output_profile["category"] == "MONETARY" and input_currencies:
            if output_profile["currency"] not in input_currencies:
                calculation_basis_issues.append(
                    f"{row.metric_name}: output currency does not match upstream evidence"
                )
    if calculation_basis_issues:
        add_validation(
            validations,
            "P0-calculation-unit-currency-lineage",
            "FAIL",
            "Critical",
            "; ".join(calculation_basis_issues),
            "A calculated metric cannot be reproduced on a consistent unit and currency basis.",
            "Correct the shared calculation inputs and suppress the affected output.",
            category="unit_currency_validation",
            issue_class="HARD_STOP",
        )
    else:
        add_validation(
            validations,
            "P0-calculation-unit-currency-lineage",
            "PASS",
            "Critical",
            "Every calculated metric preserves a consistent monetary currency across its linked input evidence.",
            "Prevents a renderer or downstream module from hiding unit or currency mismatches.",
            "Retain linked input evidence for every future calculation.",
            category="unit_currency_validation",
        )

    missing_lineage = [
        row.metric_name
        for row in rows
        if row.reported_or_calculated == "calculated" and (not row.formula or not row.input_evidence_ids)
    ]
    if missing_lineage:
        add_validation(
            validations,
            "P0-calculation-lineage",
            "FAIL",
            "Critical",
            f"Calculated rows lack a formula or upstream evidence IDs: {sorted(missing_lineage)}.",
            "The affected values cannot be independently reproduced and must not enter a formal report.",
            "Add the formula and every upstream evidence ID in the shared Data and Evidence Engine.",
            category="calculation_reproducibility",
            issue_class="HARD_STOP",
            evidence_ids=[row.evidence_id for row in rows if row.metric_name in missing_lineage],
        )
    else:
        add_validation(
            validations,
            "P0-calculation-lineage",
            "PASS",
            "Critical",
            "Every calculated row has an explicit formula and upstream evidence IDs.",
            "All displayed calculations are structurally reproducible from the evidence registry.",
            "Retain this check for every new calculation module.",
            category="calculation_reproducibility",
        )
    evidence_records = [asdict(row) for row in rows]
    for issue in detect_material_conflicts(evidence_records):
        validations.append(
            {
                **issue.to_dict(),
                "id": issue.check_id,
                "result": issue.status,
                "evidence": issue.message,
                "impact": issue.decision_impact,
            }
        )

    cash_flow_ledger, ledger_issues = build_cash_flow_ledger(rows)
    for issue in ledger_issues:
        validations.append(
            {
                **issue,
                "id": issue["check_id"],
                "result": issue["status"],
                "evidence": issue["message"],
                "impact": issue["decision_impact"],
            }
        )
    if not ledger_issues:
        add_validation(
            validations,
            "P0-cash-flow-double-count-ledger",
            "PASS",
            "Critical",
            "No line is both embedded in CFO and separately modeled without an explicit reversal.",
            "CFO-based FCF and liquidity calculations pass the structural double-counting check.",
            "Keep every future source/use line in the shared cash-flow ledger.",
            category="double_counting",
        )

    hard_stops = [
        item
        for item in validations
        if item.get("issue_class") == "HARD_STOP" and item.get("status") in {"FAIL", "BLOCKED"}
    ]
    warning_items = [
        item
        for item in validations
        if item.get("issue_class") == "WARNING"
        and item.get("status") in {"FAIL", "BLOCKED", "MISSING", "PROVISIONAL", "WARNING"}
    ]
    data_gate = {
        "level": 0 if hard_stops else 1,
        "label": "Gate 0 - Data not validated" if hard_stops else "Gate 1 - Core financial data validated",
        "hard_stop_ids": [item["check_id"] for item in hard_stops],
    }

    sources_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        sources_by_id.setdefault(
            row.source_id,
            {
                "source_id": row.source_id,
                "source_level": row.source_level,
                "source_type": row.source_type,
                "source_name": row.source_name,
                "source_url": row.source_url,
                "publication_date": row.publication_date,
                "retrieval_date": row.retrieval_date,
            },
        )

    as_of_registry = {
        "financial_statement_date": latest_end,
        "latest_financial_filing_date": filing_for_period.filed,
        "latest_annual_period": latest_k.period if latest_k else None,
        "latest_interim_period": latest_q.period if latest_q else None,
        "subsequent_event_index_review_through": datetime.now(UTC).date().isoformat(),
        "market_price_date": None,
        "share_count_date": share_count_result.get("share_count_date"),
        "retrieval_timestamp": utc_now(),
    }

    slug = f"{company['ticker'].lower()}_{slugify(company['name'])}"
    out_dir = out_root / slug
    data_dir = out_dir / "data"
    validation_dir = out_dir / "validation"
    data_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)

    rows.sort(key=lambda r: (str(r.period_end), r.metric_name))
    write_csv(data_dir / "normalized_data.csv", rows)
    data_payload = {
        "schema_version": SCHEMA_VERSION,
        "engine": "shared_data_and_evidence_engine",
        "data_control_version": S06_DATA_CONTROL_VERSION,
        "report_id": stable_id("RPT", company["cik"], latest_end, utc_now()),
        "company": company,
        "build_date": utc_now(),
        "supported_universe": support_assessment,
        "as_of_registry": as_of_registry,
        "fiscal_calendar_profile": fiscal_profile,
        "xbrl_selection_log": xbrl_selection_log,
        "ltm_control_results": ltm_control_results,
        "share_count_control": {
            key: value
            for key, value in share_count_result.items()
            if key != "point"
        },
        "denominator_control_log": denominator_control_log,
        "filings": {k: asdict(v) if v else None for k, v in {"latest_q": latest_q, "prior_q": prior_q, "latest_k": latest_k}.items()},
        "subsequent_event_filings": events,
        "source_registry": sorted(sources_by_id.values(), key=lambda row: row["source_id"]),
        "data_points": [asdict(row) for row in rows],
        "evidence_records": [asdict(row) for row in rows],
        "cash_flow_ledger": [line.to_dict() for line in cash_flow_ledger],
        "validation_tests": validations,
        "data_gate": data_gate,
        "hard_stops": hard_stops,
        "warnings": warning_items,
    }
    serialized_data = json.dumps(data_payload, indent=2, ensure_ascii=False)
    (data_dir / "normalized_data.json").write_text(serialized_data, encoding="utf-8")
    (data_dir / "data_evidence_pack.json").write_text(serialized_data, encoding="utf-8")
    (validation_dir / "validation_report.md").write_text(
        "\n".join(
            [
                f"# {company['name']} ({company['ticker']}) Validation Report",
                "",
                f"Data Gate: **{data_gate['label']}**",
                "",
                "| ID | Result | Class | Severity | Evidence | Remediation |",
                "|---|---:|---:|---:|---|---|",
                *[
                    f"| {v['id']} | {v['result']} | {v.get('issue_class', 'INFO')} | {v['severity']} | {v['evidence']} | {v['remediation']} |"
                    for v in validations
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )
    (out_dir / "investment_data_pack.md").write_text(
        build_pack_markdown(company, {"latest_q": latest_q, "prior_q": prior_q, "latest_k": latest_k}, rows, validations),
        encoding="utf-8",
    )
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a generic SEC public-company decision-support data pack.")
    parser.add_argument("company", help="Ticker or company name, e.g. AAPL or 'Apple Inc.'")
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT), help="Output root directory.")
    args = parser.parse_args()
    out_dir = build_company_pack(args.company, Path(args.out_root))
    print(out_dir)
    print(out_dir / "investment_data_pack.md")
    print(out_dir / "validation" / "validation_report.md")
    print(out_dir / "data" / "normalized_data.csv")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
