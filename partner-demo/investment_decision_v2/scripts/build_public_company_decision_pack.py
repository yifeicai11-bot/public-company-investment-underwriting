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
        if "USD" not in unit and unit not in {"shares", "pure"}:
            continue
        for value in values:
            point = dict(value)
            point["unit"] = unit
            point["tag"] = tag
            out.append(point)
    return out


def choose_instant(companyfacts: dict[str, Any], tags: tuple[str, ...], end: str, accn: str | None = None) -> dict[str, Any] | None:
    for tag in tags:
        values = [
            p
            for p in fact_points(companyfacts, tag)
            if p.get("end") == end
            and p.get("form") in {"10-Q", "10-K"}
            and not p.get("start")
            and (accn is None or p.get("accn") == accn)
        ]
        if values:
            values.sort(key=lambda p: (p.get("filed", ""), p.get("accn", "")))
            return values[-1]
    return None


def choose_duration(
    companyfacts: dict[str, Any],
    tags: tuple[str, ...],
    end: str,
    *,
    form: str | None = None,
    accn: str | None = None,
    prefer: str = "quarter",
) -> dict[str, Any] | None:
    for tag in tags:
        values = [
            p
            for p in fact_points(companyfacts, tag)
            if p.get("end") == end
            and p.get("start")
            and p.get("form") in {"10-Q", "10-K"}
            and (form is None or p.get("form") == form)
            and (accn is None or p.get("accn") == accn)
        ]
        if not values:
            continue
        if prefer == "quarter":
            selected = [p for p in values if 60 <= (days_between(p.get("start"), p.get("end")) or 0) <= 130]
            if not selected:
                continue
            selected.sort(key=lambda p: (p.get("filed", ""), p.get("accn", "")))
            return selected[-1]
        if prefer == "ytd":
            values.sort(key=lambda p: (days_between(p.get("start"), p.get("end")) or 0, p.get("filed", "")))
            return values[-1]
        if prefer == "annual":
            selected = [p for p in values if (days_between(p.get("start"), p.get("end")) or 0) >= 300]
            if not selected:
                continue
            selected.sort(key=lambda p: (days_between(p.get("start"), p.get("end")) or 0, p.get("filed", "")))
            return selected[-1]
    return None


def dp_from_fact(metric_name: str, fact: dict[str, Any], source_url: str, source_location: str, period_type: str, notes: str = "") -> DataPoint:
    start = fact.get("start", "")
    end = fact.get("end", "")
    return DataPoint(
        metric_name=metric_name,
        value=fact.get("val"),
        unit=fact.get("unit", "USD"),
        currency="USD" if "USD" in fact.get("unit", "USD") else "",
        period_start=start,
        period_end=end,
        period_type=period_type,
        duration_days=days_between(start, end) if start else "",
        fiscal_period=f"FY{fact.get('fy', '')} {fact.get('fp', '')}".strip(),
        filing_type=fact.get("form", ""),
        filing_date=fact.get("filed", ""),
        source_location=source_location,
        source_tag=f"us-gaap:{fact.get('tag', '')}",
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
        fact = choose_instant(facts, tags, latest_end, latest_accn)
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
            fact = choose_instant(facts, tags, prior_balance_end, latest_accn)
            if not fact:
                fact = choose_instant(facts, tags, prior_balance_end, prior_balance_filing.accession)
            if not fact:
                fact = choose_instant(facts, tags, prior_balance_end)
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
            quarter = choose_duration(facts, tags, latest_q.period, form="10-Q", accn=latest_q.accession, prefer="quarter")
            ytd = choose_duration(facts, tags, latest_q.period, form="10-Q", accn=latest_q.accession, prefer="ytd")
            if quarter:
                rows.append(dp_from_fact(f"latest_quarter_{metric}", quarter, latest_q.url, "Income statement / flow fact", "quarter"))
            if ytd and (not quarter or ytd.get("start") != quarter.get("start")):
                rows.append(dp_from_fact(f"latest_ytd_{metric}", ytd, latest_q.url, "Cash flow or income statement / flow fact", "YTD"))

            # Derive standalone quarter from YTD when useful and prior YTD exists.
            if ytd and prior_q:
                prior_ytd = choose_duration(facts, tags, prior_q.period, form="10-Q", accn=prior_q.accession, prefer="ytd")
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
                        rows.append(
                            manual_dp(
                                f"derived_latest_quarter_{metric}",
                                latest_val - prior_val,
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
                                notes="Derived from two YTD filings; inspect fiscal calendar for 53-week/restatement/acquisition issues.",
                            )
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
            annual = choose_duration(facts, tags, latest_k.period, form="10-K", accn=latest_k.accession, prefer="annual")
            if annual:
                rows.append(dp_from_fact(f"latest_annual_{metric}", annual, latest_k.url, "Annual statement / flow fact", "annual"))

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
        if derived_liabilities is not None and dates_match:
            rows.append(
                manual_dp(
                    "total_liabilities",
                    derived_liabilities,
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
    observed_liquid_inputs = [value for value in (cash, sti) if value is not None]
    if observed_liquid_inputs:
        rows.append(
            manual_dp(
                "available_liquidity_before_facility_notes",
                sum(observed_liquid_inputs),
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
    lease_inputs = [val(m, "finance_lease_current"), val(m, "operating_lease_current")]
    observed_lease_inputs = [value for value in lease_inputs if value is not None]
    current_lease_total = sum(observed_lease_inputs) if observed_lease_inputs else None
    if current_lease_total is not None:
        rows.append(
            manual_dp(
                "current_lease_obligations_total",
                current_lease_total,
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
    if cfo_ytd is not None and capex_ytd is not None:
        ytd_row = m["latest_ytd_cfo"]
        rows.append(
            manual_dp(
                "latest_ytd_fcf",
                cfo_ytd - capex_ytd,
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
    if q_cfo is not None and q_capex is not None and q_cfo_row and quarter_periods_match:
        rows.append(
            manual_dp(
                quarter_fcf_metric,
                q_cfo - q_capex,
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
        if rev and ar_now is not None and ar_prior is not None:
            dso = ((ar_now + ar_prior) / 2) / rev * period_days
            rows.append(
                manual_dp(
                    "dso_avg_ar",
                    dso,
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
        if cogs and inv_now is not None and inv_prior is not None:
            dio = ((inv_now + inv_prior) / 2) / cogs * period_days
            rows.append(
                manual_dp(
                    "dio_avg_inventory",
                    dio,
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
        if cogs and ap_now is not None and ap_prior is not None and ap_rows_trade_compatible:
            dpo = ((ap_now + ap_prior) / 2) / cogs * period_days
            rows.append(
                manual_dp(
                    "dpo_avg_ap",
                    dpo,
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
    if borrowing_availability is not None and liquidity_before_facility is not None:
        rows.append(
            manual_dp(
                "available_liquidity_including_reported_facility",
                liquidity_before_facility + borrowing_availability,
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
        "share_count_date": None,
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
        "report_id": stable_id("RPT", company["cik"], latest_end, utc_now()),
        "company": company,
        "build_date": utc_now(),
        "supported_universe": support_assessment,
        "as_of_registry": as_of_registry,
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
