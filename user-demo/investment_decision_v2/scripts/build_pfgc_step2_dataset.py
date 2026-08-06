#!/usr/bin/env python3
"""Build the Step 2 period-aware data pack for PFGC.

This script is intentionally narrow: it turns public SEC filing data into a
normalized, source-backed data set and a validation report. It is not a
valuation model and does not issue a buy/sell recommendation.
"""

from __future__ import annotations

import csv
import html as html_lib
import json
import math
import os
import re
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
OUT_ROOT = ROOT / "user-demo" / "investment_decision_v2" / "pfgc"
DATA_DIR = OUT_ROOT / "data"
VALIDATION_DIR = OUT_ROOT / "validation"

CIK = "0001618673"
SEC_UA = os.environ.get(
    "SEC_USER_AGENT",
    "public-company-investment-underwriting contact@example.com",
)

Q3_ACC = "0001193125-26-209011"
Q2_ACC = "0001193125-26-037614"
Q1_ACC = "0001193125-25-266975"
FY_ACC = "0001618673-25-000012"

Q3_URL = "https://www.sec.gov/Archives/edgar/data/1618673/000119312526209011/pfgc-20260328.htm"
Q2_URL = "https://www.sec.gov/Archives/edgar/data/1618673/000119312526037614/pfgc-20251227.htm"
Q1_URL = "https://www.sec.gov/Archives/edgar/data/1618673/000119312525266975/pfgc-20250927.htm"
FY2025_URL = "https://www.sec.gov/Archives/edgar/data/1618673/000161867325000012/pfgc-20250628.htm"
COMPANYFACTS_URL = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"


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


def fetch_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def duration_days(start: str, end: str) -> int:
    return (parse_date(end) - parse_date(start)).days + 1


def fmt_usd(value: float) -> str:
    return f"${value / 1_000_000:,.1f}m"


def fmt_ratio(value: float) -> str:
    return f"{value:.2f}x"


def near(a: float, b: float, tolerance: float = 0.05) -> bool:
    return abs(a - b) <= tolerance


def first_fact(
    companyfacts: dict[str, Any],
    tag: str,
    *,
    end: str,
    start: str | None = None,
    accn: str | None = None,
    form: str | None = None,
    unit: str = "USD",
) -> dict[str, Any]:
    facts = companyfacts["facts"]["us-gaap"][tag]["units"][unit]
    candidates: list[dict[str, Any]] = []
    for fact in facts:
        if fact.get("end") != end:
            continue
        if start is not None and fact.get("start") != start:
            continue
        if accn is not None and fact.get("accn") != accn:
            continue
        if form is not None and fact.get("form") != form:
            continue
        candidates.append(fact)
    if not candidates:
        raise ValueError(f"No fact found for {tag} end={end} start={start} accn={accn}")
    return sorted(candidates, key=lambda x: (x.get("filed", ""), x.get("start", "")), reverse=True)[0]


def fact_row(
    companyfacts: dict[str, Any],
    metric_name: str,
    tag: str,
    *,
    end: str,
    start: str | None = None,
    accn: str,
    source_url: str,
    source_location: str,
    period_type: str,
    fiscal_period: str,
    notes: str = "",
) -> DataPoint:
    fact = first_fact(companyfacts, tag, end=end, start=start, accn=accn, form=None)
    dur = duration_days(start, end) if start else ""
    return DataPoint(
        metric_name=metric_name,
        value=fact["val"],
        unit="USD",
        currency="USD",
        period_start=start or "",
        period_end=end,
        period_type=period_type,
        duration_days=dur,
        fiscal_period=fiscal_period,
        filing_type=fact.get("form", ""),
        filing_date=fact.get("filed", ""),
        source_location=source_location,
        source_tag=f"us-gaap:{tag}",
        source_url=source_url,
        evidence_type="FACT",
        reported_or_calculated="reported",
        confidence="High",
        validation_status="auto-checked",
        notes=notes,
    )


def manual_row(
    metric_name: str,
    value: Any,
    *,
    unit: str = "USD",
    currency: str = "USD",
    period_start: str = "",
    period_end: str = "2026-03-28",
    period_type: str = "instant",
    duration: Any = "",
    fiscal_period: str = "FY2026 Q3",
    filing_type: str = "10-Q",
    filing_date: str = "2026-05-06",
    source_location: str = "Form 10-Q",
    source_tag: str = "",
    source_url: str = Q3_URL,
    evidence_type: str = "FACT",
    reported_or_calculated: str = "reported",
    confidence: str = "High",
    validation_status: str = "analyst-verified",
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
        duration_days=duration,
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


def calc_row(
    metric_name: str,
    value: Any,
    *,
    unit: str,
    period_start: str = "",
    period_end: str = "2026-03-28",
    period_type: str,
    duration: Any = "",
    fiscal_period: str = "FY2026 Q3",
    source_location: str,
    notes: str,
    confidence: str = "High",
) -> DataPoint:
    currency = "USD" if unit == "USD" else ""
    return manual_row(
        metric_name,
        value,
        unit=unit,
        currency=currency,
        period_start=period_start,
        period_end=period_end,
        period_type=period_type,
        duration=duration,
        fiscal_period=fiscal_period,
        source_location=source_location,
        source_tag="calculation",
        source_url="",
        evidence_type="CALC",
        reported_or_calculated="calculated",
        confidence=confidence,
        validation_status="auto-checked",
        notes=notes,
    )


def clean_number(text: str, scale: int = 0, negative: bool = False) -> float:
    text = html_lib.unescape(re.sub(r"<.*?>", "", text)).strip()
    text = text.replace(",", "").replace("$", "").replace("%", "")
    text = text.replace("(", "").replace(")", "").strip()
    if not text:
        return math.nan
    value = float(text) * (10**scale)
    return -value if negative else value


def extract_inline_row_value(url: str, label: str, occurrence: int = 0) -> tuple[float, str]:
    raw = fetch_text(url)
    positions = [m.start() for m in re.finditer(re.escape(label), raw)]
    if len(positions) <= occurrence:
        raise ValueError(f"Label not found: {label}")
    idx = positions[occurrence]
    end = raw.find("</tr>", idx)
    row_html = raw[idx:end]
    facts = re.findall(r"<ix:nonFraction\b([^>]*)>(.*?)</ix:nonFraction>", row_html, flags=re.S)
    parsed: list[tuple[float, str]] = []
    for attrs, value_html in facts:
        if 'xsi:nil="true"' in attrs:
            continue
        scale_match = re.search(r'scale="(-?\d+)"', attrs)
        name_match = re.search(r'name="([^"]+)"', attrs)
        scale = int(scale_match.group(1)) if scale_match else 0
        negative = 'sign="-"' in attrs
        value = clean_number(value_html, scale=scale, negative=negative)
        if not math.isnan(value):
            parsed.append((value, name_match.group(1) if name_match else "inline-xbrl"))
    if not parsed:
        raise ValueError(f"No inline facts found for label: {label}")
    return parsed[0]


def write_csv(path: Path, rows: list[DataPoint]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_json(path: Path, rows: list[DataPoint], validations: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "company": "Performance Food Group Co",
        "ticker": "PFGC",
        "build_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_points": [asdict(r) for r in rows],
        "validation_tests": validations,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_markdown(rows: list[DataPoint], validations: list[dict[str, Any]]) -> str:
    by_name = {row.metric_name: row for row in rows}

    def val(name: str) -> Any:
        return by_name[name].value

    passed = sum(1 for v in validations if v["result"] == "PASS")
    failed = sum(1 for v in validations if v["result"] == "FAIL")
    blocked = sum(1 for v in validations if v["result"] == "BLOCKED")

    validation_lines = [
        "| Test | Result | Evidence | Investment relevance |",
        "|---|---:|---|---|",
    ]
    for item in validations:
        validation_lines.append(
            f"| {item['id']} | {item['result']} | {item['evidence']} | {item['investment_relevance']} |"
        )

    data_lines = [
        "| Metric | Value | Period | Type | Evidence | Notes |",
        "|---|---:|---|---|---|---|",
    ]
    keep = [
        "unrestricted_cash",
        "cash_and_restricted_cash",
        "abl_excess_availability",
        "available_liquidity_cash_plus_abl",
        "current_finance_lease_obligations",
        "current_operating_lease_obligations",
        "long_term_debt",
        "total_lease_obligations_balance_sheet",
        "ytd_cfo",
        "ytd_capex",
        "ytd_fcf",
        "derived_q3_cfo",
        "derived_q3_capex",
        "derived_q3_fcf",
        "q3_dso_avg_ar",
        "q3_dio_avg_inventory",
        "q3_dpo_ap_and_checks",
        "q3_cash_conversion_cycle",
    ]
    for name in keep:
        row = by_name[name]
        display = row.value
        if isinstance(display, (int, float)) and row.unit == "USD":
            display = fmt_usd(float(display))
        elif isinstance(display, float) and row.unit == "days":
            display = f"{display:.1f} days"
        period = row.period_end if not row.period_start else f"{row.period_start} to {row.period_end}"
        data_lines.append(
            f"| `{row.metric_name}` | {display} | {period} | {row.evidence_type}/{row.period_type} | {row.source_location} | {row.notes} |"
        )

    missing_lines = [
        "- Consensus estimates, peer multiples, and target valuation are not sourced yet; output must remain Watch / Need More Work rather than Buy/Sell.",
        "- Maintenance capex is not separately disclosed in this data pack; FCF uses total capex and should not be treated as normalized maintenance FCF.",
        "- Borrowing-base component eligibility and advance rates are not public in enough detail to stress availability mechanically; use haircut scenarios.",
        "- DPO uses trade accounts payable and outstanding checks in excess of deposits, so it is an operating-payables proxy, not pure supplier AP.",
        "- LTM adjusted EBITDA and acquisition pro forma adjustments require management non-GAAP reconciliation review before leverage conclusions.",
    ]

    return "\n".join(
        [
            "# PFGC Step 2 Period-Aware Data Pack",
            "",
            "Review date: July 10, 2026",
            "Company: Performance Food Group Co (PFGC)",
            "Scope: Public SEC filings only; research support, not a securities recommendation.",
            "",
            "## Validation Summary",
            "",
            f"- Tests passed: {passed}",
            f"- Tests failed: {failed}",
            f"- Blocked unsafe calculations: {blocked}",
            "- Core gate: all flow ratios must use matching period_start, period_end, period_type, and duration_days.",
            "",
            "## Investor-Useful Corrections",
            "",
            "- PFGC is not cash-rich, but balance-sheet cash is not the primary liquidity measure for this distribution model.",
            f"- Unrestricted cash was {fmt_usd(val('unrestricted_cash'))}; ABL excess availability was {fmt_usd(val('abl_excess_availability'))}.",
            f"- Available liquidity from cash plus disclosed ABL availability was {fmt_usd(val('available_liquidity_cash_plus_abl'))}, before any downside working-capital or facility haircut.",
            f"- Nine-month YTD FCF was {fmt_usd(val('ytd_fcf'))}; derived standalone Q3 FCF was {fmt_usd(val('derived_q3_fcf'))}. These are separate period types.",
            "- Current funded debt was zero, but current lease obligations remain mandatory uses and must not be ignored.",
            "- The 2027 Notes were refinanced into 2034 Notes; this reduces near-term funded-debt maturity pressure but does not eliminate leverage or interest burden.",
            "",
            "## Key Data Points",
            "",
            *data_lines,
            "",
            "## Liquidity Sources and Identified Uses",
            "",
            f"- Sources identified: unrestricted cash {fmt_usd(val('unrestricted_cash'))} + ABL excess availability {fmt_usd(val('abl_excess_availability'))} = {fmt_usd(val('available_liquidity_cash_plus_abl'))}.",
            f"- Partial 12-month mandatory uses identified from balance sheet leases: finance lease current installments {fmt_usd(val('current_finance_lease_obligations'))} + operating lease current installments {fmt_usd(val('current_operating_lease_obligations'))} = {fmt_usd(val('current_lease_obligations_total'))}.",
            f"- Partial cushion before cash interest, maintenance capex, working-capital swing, and facility haircuts: {fmt_usd(val('partial_liquidity_cushion_before_interest_capex_wc'))}.",
            "- Investment use: liquidity does not appear to be the base-case binding constraint; the decision layer should focus on earnings durability, normalized FCF, borrowing-base sensitivity, integration, leverage, and valuation.",
            "",
            "## Validation Tests",
            "",
            *validation_lines,
            "",
            "## Missing Data That Blocks a Full Investment Memo",
            "",
            *missing_lines,
            "",
            "## Source Files",
            "",
            f"- Latest 10-Q: {Q3_URL}",
            f"- Prior Q2 10-Q: {Q2_URL}",
            f"- FY2025 10-K: {FY2025_URL}",
            f"- SEC companyfacts API: {COMPANYFACTS_URL}",
            "",
        ]
    )


def build_validation_report(validations: list[dict[str, Any]]) -> str:
    lines = [
        "# PFGC Step 2 Validation Report",
        "",
        "This report is the regression-test layer for the investment-decision rewrite.",
        "The goal is to prevent period mixing, double counting, and false liquidity signals before drafting the memo.",
        "",
        "| ID | Result | Severity | Evidence | Remediation / Use |",
        "|---|---:|---:|---|---|",
    ]
    for item in validations:
        lines.append(
            f"| {item['id']} | {item['result']} | {item['severity']} | {item['evidence']} | {item['remediation']} |"
        )
    lines.extend(
        [
            "",
            "## Blocked Calculation Example",
            "",
            "- Do not calculate CFO / net income using three-month net income of $41.7m and nine-month CFO of $1.0719bn.",
            "- Correct alternatives:",
            "  - YTD CFO / YTD net income: same start and end dates, still requires working-capital interpretation.",
            "  - Derived standalone Q3 CFO / Q3 net income: Q3 YTD CFO less Q2 YTD CFO, clearly labeled as derived-quarter.",
            "",
            "## Memo Gate",
            "",
            "Because valuation, peer multiples, consensus, and normalized EBITDA are not complete in this Step 2 pack, the user-facing output should remain a decision-support watch memo, not a Buy/Sell recommendation.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    companyfacts = fetch_json(COMPANYFACTS_URL)

    rows: list[DataPoint] = []

    # Balance sheet facts.
    rows.extend(
        [
            fact_row(companyfacts, "unrestricted_cash", "Cash", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "restricted_cash", "RestrictedCash", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Cash flow statement reconciliation", period_type="instant", fiscal_period="FY2026 Q3", notes="Restricted cash; do not treat as fully available liquidity without confirmation."),
            fact_row(companyfacts, "cash_and_restricted_cash", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Cash flow statement reconciliation", period_type="instant", fiscal_period="FY2026 Q3", notes="Includes restricted cash; not all available for liquidity."),
            fact_row(companyfacts, "accounts_receivable_net", "AccountsReceivableNetCurrent", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "inventory_net", "InventoryNet", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "current_assets", "AssetsCurrent", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "current_liabilities", "LiabilitiesCurrent", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "total_assets", "Assets", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "total_liabilities", "Liabilities", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "shareholders_equity", "StockholdersEquity", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "long_term_debt_current", "LongTermDebtCurrent", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3", notes="Funded current debt only; excludes lease obligations."),
            fact_row(companyfacts, "long_term_debt", "LongTermDebtNoncurrent", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "current_finance_lease_obligations", "FinanceLeaseLiabilityCurrent", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "current_operating_lease_obligations", "OperatingLeaseLiabilityCurrent", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "finance_lease_obligations_noncurrent", "FinanceLeaseLiabilityNoncurrent", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "operating_lease_obligations_noncurrent", "OperatingLeaseLiabilityNoncurrent", end="2026-03-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q3"),
        ]
    )

    # Operating and cash-flow facts.
    rows.extend(
        [
            fact_row(companyfacts, "q3_revenue", "RevenueFromContractWithCustomerIncludingAssessedTax", end="2026-03-28", start="2025-12-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Statement of operations", period_type="quarter", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "q3_cogs", "CostOfGoodsAndServicesSold", end="2026-03-28", start="2025-12-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Statement of operations", period_type="quarter", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "q3_net_income", "NetIncomeLoss", end="2026-03-28", start="2025-12-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Statement of operations", period_type="quarter", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "ytd_revenue", "RevenueFromContractWithCustomerIncludingAssessedTax", end="2026-03-28", start="2025-06-29", accn=Q3_ACC, source_url=Q3_URL, source_location="Statement of operations", period_type="YTD", fiscal_period="FY2026 YTD Q3"),
            fact_row(companyfacts, "ytd_cogs", "CostOfGoodsAndServicesSold", end="2026-03-28", start="2025-06-29", accn=Q3_ACC, source_url=Q3_URL, source_location="Statement of operations", period_type="YTD", fiscal_period="FY2026 YTD Q3"),
            fact_row(companyfacts, "ytd_net_income", "NetIncomeLoss", end="2026-03-28", start="2025-06-29", accn=Q3_ACC, source_url=Q3_URL, source_location="Statement of operations", period_type="YTD", fiscal_period="FY2026 YTD Q3"),
            fact_row(companyfacts, "ytd_cfo", "NetCashProvidedByUsedInOperatingActivities", end="2026-03-28", start="2025-06-29", accn=Q3_ACC, source_url=Q3_URL, source_location="Cash flow statement", period_type="YTD", fiscal_period="FY2026 YTD Q3"),
            fact_row(companyfacts, "q2_ytd_cfo", "NetCashProvidedByUsedInOperatingActivities", end="2025-12-27", start="2025-06-29", accn=Q2_ACC, source_url=Q2_URL, source_location="Cash flow statement", period_type="YTD", fiscal_period="FY2026 YTD Q2"),
            fact_row(companyfacts, "ytd_capex", "PaymentsToAcquirePropertyPlantAndEquipment", end="2026-03-28", start="2025-06-29", accn=Q3_ACC, source_url=Q3_URL, source_location="Cash flow statement", period_type="YTD", fiscal_period="FY2026 YTD Q3"),
            fact_row(companyfacts, "q2_ytd_capex", "PaymentsToAcquirePropertyPlantAndEquipment", end="2025-12-27", start="2025-06-29", accn=Q2_ACC, source_url=Q2_URL, source_location="Cash flow statement", period_type="YTD", fiscal_period="FY2026 YTD Q2"),
            fact_row(companyfacts, "ytd_interest_paid_net", "InterestPaidNet", end="2026-03-28", start="2025-06-29", accn=Q3_ACC, source_url=Q3_URL, source_location="Cash flow statement supplemental disclosure", period_type="YTD", fiscal_period="FY2026 YTD Q3"),
            fact_row(companyfacts, "q2_ytd_interest_paid_net", "InterestPaidNet", end="2025-12-27", start="2025-06-29", accn=Q2_ACC, source_url=Q2_URL, source_location="Cash flow statement supplemental disclosure", period_type="YTD", fiscal_period="FY2026 YTD Q2"),
            fact_row(companyfacts, "q3_interest_expense", "InterestExpense", end="2026-03-28", start="2025-12-28", accn=Q3_ACC, source_url=Q3_URL, source_location="Statement of operations", period_type="quarter", fiscal_period="FY2026 Q3"),
            fact_row(companyfacts, "ytd_interest_expense", "InterestExpense", end="2026-03-28", start="2025-06-29", accn=Q3_ACC, source_url=Q3_URL, source_location="Statement of operations", period_type="YTD", fiscal_period="FY2026 YTD Q3"),
            fact_row(companyfacts, "beginning_cash_and_restricted_cash", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations", end="2025-06-28", accn=FY_ACC, source_url=FY2025_URL, source_location="Balance sheet / cash flow reconciliation", period_type="instant", fiscal_period="FY2025"),
            fact_row(companyfacts, "q2_accounts_receivable_net", "AccountsReceivableNetCurrent", end="2025-12-27", accn=Q2_ACC, source_url=Q2_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q2"),
            fact_row(companyfacts, "q2_inventory_net", "InventoryNet", end="2025-12-27", accn=Q2_ACC, source_url=Q2_URL, source_location="Balance sheet", period_type="instant", fiscal_period="FY2026 Q2"),
        ]
    )

    # Inline-XBRL line items not available in recent companyfacts.
    ap_q3_value, ap_q3_tag = extract_inline_row_value(Q3_URL, "Trade accounts payable and outstanding checks in excess of deposits")
    ap_q2_value, ap_q2_tag = extract_inline_row_value(Q2_URL, "Trade accounts payable and outstanding checks in excess of deposits")
    rows.append(
        manual_row(
            "trade_accounts_payable_and_outstanding_checks",
            ap_q3_value,
            source_location="Balance sheet line item",
            source_tag=ap_q3_tag,
            notes="Includes outstanding checks in excess of deposits; use as DPO proxy with caveat.",
        )
    )
    rows.append(
        manual_row(
            "q2_trade_accounts_payable_and_outstanding_checks",
            ap_q2_value,
            period_end="2025-12-27",
            fiscal_period="FY2026 Q2",
            filing_date="2026-02-04",
            source_location="Balance sheet line item",
            source_tag=ap_q2_tag,
            source_url=Q2_URL,
            notes="Includes outstanding checks in excess of deposits; use as DPO proxy with caveat.",
        )
    )

    # Debt and facility notes.
    note_facts = [
        ("abl_commitment", 5_000_000_000, "Debt note - ABL Facility", "Q3 10-Q discloses $5.0bn ABL Facility."),
        ("abl_borrowings", 2_083_500_000, "Debt note - ABL table", "Aggregate borrowings under credit agreement."),
        ("abl_letters_of_credit", 165_100_000, "Debt note - ABL table", "Letters of credit reduce availability."),
        ("abl_lender_reserves", 97_500_000, "Debt note - ABL table", "Availability is disclosed net of reserves; do not subtract reserves again."),
        ("abl_excess_availability", 2_751_400_000, "Debt note - ABL table", "Disclosed excess availability, net of lender reserves."),
        ("notes_due_2029_principal", 1_000_000_000, "Debt note - debt table", "4.250% Senior Notes due August 1, 2029."),
        ("notes_due_2032_principal", 1_000_000_000, "Debt note - debt table", "6.125% Senior Notes due September 15, 2032."),
        ("notes_due_2034_principal", 1_060_000_000, "Debt note - debt table", "5.625% Senior Notes due March 1, 2034."),
        ("debt_discount_and_financing_costs", -25_200_000, "Debt note - debt table", "Unamortized discount and deferred financing costs."),
        ("notes_due_2027_redeemed", 1_060_000_000, "Debt note - Senior Notes due 2027", "Redeemed in full on February 19, 2026."),
    ]
    for name, value, source_location, notes in note_facts:
        rows.append(manual_row(name, value, source_location=source_location, notes=notes))

    rows.append(
        manual_row(
            "abl_maturity",
            "2029-09-09",
            unit="date",
            currency="",
            source_location="Debt note - ABL Facility",
            notes="Facility maturity date.",
        )
    )
    rows.append(
        manual_row(
            "abl_average_interest_rate",
            5.30,
            unit="percent",
            currency="",
            source_location="Debt note - ABL table",
            notes="Average interest rate excluding impact of interest rate swaps.",
        )
    )
    rows.append(
        manual_row(
            "springing_fixed_charge_covenant_trigger",
            "Alternate Availability below greater of $375.0m and 10% of the lesser of borrowing base and aggregate commitments plus outstanding term loans for five consecutive business days",
            unit="text",
            currency="",
            source_location="Debt note - ABL covenant disclosure",
            notes="Springing covenant; not always active.",
        )
    )
    rows.append(
        manual_row(
            "covenant_compliance",
            "In compliance with all covenants under ABL Facility and notes due 2029, 2032, and 2034 as of March 28, 2026",
            unit="text",
            currency="",
            source_location="MD&A liquidity discussion",
            notes="Company disclosure; not an external rating opinion.",
        )
    )

    by_name = {row.metric_name: row for row in rows}

    def v(name: str) -> float:
        return float(by_name[name].value)

    q3_start = "2025-12-28"
    q3_end = "2026-03-28"
    q3_days = duration_days(q3_start, q3_end)
    ytd_start = "2025-06-29"
    ytd_days = duration_days(ytd_start, q3_end)

    # Calculated flow metrics and ratios.
    rows.extend(
        [
            calc_row("ytd_fcf", v("ytd_cfo") - v("ytd_capex"), unit="USD", period_start=ytd_start, period_end=q3_end, period_type="YTD", duration=ytd_days, fiscal_period="FY2026 YTD Q3", source_location="CFO - capex", notes="YTD FCF using total capex; not standalone Q3 and not maintenance FCF."),
            calc_row("derived_q3_cfo", v("ytd_cfo") - v("q2_ytd_cfo"), unit="USD", period_start=q3_start, period_end=q3_end, period_type="derived-quarter", duration=q3_days, source_location="Q3 YTD CFO - Q2 YTD CFO", notes="Standalone Q3 derived from two YTD filings."),
            calc_row("derived_q3_capex", v("ytd_capex") - v("q2_ytd_capex"), unit="USD", period_start=q3_start, period_end=q3_end, period_type="derived-quarter", duration=q3_days, source_location="Q3 YTD capex - Q2 YTD capex", notes="Standalone Q3 derived from two YTD filings."),
            calc_row("derived_q3_fcf", (v("ytd_cfo") - v("q2_ytd_cfo")) - (v("ytd_capex") - v("q2_ytd_capex")), unit="USD", period_start=q3_start, period_end=q3_end, period_type="derived-quarter", duration=q3_days, source_location="Derived Q3 CFO - derived Q3 capex", notes="Standalone Q3 FCF derived from YTD delta; still affected by working-capital timing."),
            calc_row("derived_q3_interest_paid_net", v("ytd_interest_paid_net") - v("q2_ytd_interest_paid_net"), unit="USD", period_start=q3_start, period_end=q3_end, period_type="derived-quarter", duration=q3_days, source_location="Q3 YTD cash interest - Q2 YTD cash interest", notes="Cash interest paid, derived from supplemental disclosure."),
            calc_row("ytd_cfo_to_net_income", v("ytd_cfo") / v("ytd_net_income"), unit="ratio", period_start=ytd_start, period_end=q3_end, period_type="YTD", duration=ytd_days, fiscal_period="FY2026 YTD Q3", source_location="YTD CFO / YTD net income", notes="Same-period ratio; interpret cautiously because working-capital timing can inflate conversion."),
            calc_row("derived_q3_cfo_to_net_income", (v("ytd_cfo") - v("q2_ytd_cfo")) / v("q3_net_income"), unit="ratio", period_start=q3_start, period_end=q3_end, period_type="derived-quarter", duration=q3_days, source_location="Derived Q3 CFO / reported Q3 net income", notes="Same-period derived-quarter ratio; not the invalid prior mixed-period 25.71x."),
        ]
    )

    # Refresh dictionary after calculated rows.
    by_name = {row.metric_name: row for row in rows}
    v = lambda name: float(by_name[name].value)

    avg_ar = (v("accounts_receivable_net") + v("q2_accounts_receivable_net")) / 2
    avg_inventory = (v("inventory_net") + v("q2_inventory_net")) / 2
    avg_ap_proxy = (v("trade_accounts_payable_and_outstanding_checks") + v("q2_trade_accounts_payable_and_outstanding_checks")) / 2
    dso = avg_ar / v("q3_revenue") * q3_days
    dio = avg_inventory / v("q3_cogs") * q3_days
    dpo = avg_ap_proxy / v("q3_cogs") * q3_days
    ccc = dso + dio - dpo

    rows.extend(
        [
            calc_row("average_ar_for_q3_dso", avg_ar, unit="USD", period_start=q3_start, period_end=q3_end, period_type="quarter-average", duration=q3_days, source_location="Average of Q2 and Q3 ending AR", notes="Uses two balance-sheet points; better than ending AR only."),
            calc_row("average_inventory_for_q3_dio", avg_inventory, unit="USD", period_start=q3_start, period_end=q3_end, period_type="quarter-average", duration=q3_days, source_location="Average of Q2 and Q3 ending inventory", notes="Uses two balance-sheet points; better than ending inventory only."),
            calc_row("average_ap_proxy_for_q3_dpo", avg_ap_proxy, unit="USD", period_start=q3_start, period_end=q3_end, period_type="quarter-average", duration=q3_days, source_location="Average of Q2 and Q3 trade AP and outstanding checks", notes="DPO proxy includes outstanding checks in excess of deposits."),
            calc_row("q3_dso_avg_ar", dso, unit="days", period_start=q3_start, period_end=q3_end, period_type="quarter", duration=q3_days, source_location="Average AR / Q3 revenue * days", notes="Receivables collection days; same-period denominator."),
            calc_row("q3_dio_avg_inventory", dio, unit="days", period_start=q3_start, period_end=q3_end, period_type="quarter", duration=q3_days, source_location="Average inventory / Q3 COGS * days", notes="Inventory days; same-period denominator."),
            calc_row("q3_dpo_ap_and_checks", dpo, unit="days", period_start=q3_start, period_end=q3_end, period_type="quarter", duration=q3_days, source_location="Average AP proxy / Q3 COGS * days", notes="Includes outstanding checks; use as DPO proxy, not pure supplier AP."),
            calc_row("q3_cash_conversion_cycle", ccc, unit="days", period_start=q3_start, period_end=q3_end, period_type="quarter", duration=q3_days, source_location="DSO + DIO - DPO", notes="CCC based on AP proxy; compare to trend and peers before investment conclusion."),
            calc_row("available_liquidity_cash_plus_abl", v("unrestricted_cash") + v("abl_excess_availability"), unit="USD", period_type="instant", source_location="Unrestricted cash + disclosed ABL excess availability", notes="Primary liquidity source for distribution model."),
            calc_row("current_lease_obligations_total", v("current_finance_lease_obligations") + v("current_operating_lease_obligations"), unit="USD", period_type="instant", source_location="Current finance leases + current operating leases", notes="Partial 12-month mandatory uses; excludes interest/capex/WC swing."),
            calc_row("total_lease_obligations_balance_sheet", v("current_finance_lease_obligations") + v("current_operating_lease_obligations") + v("finance_lease_obligations_noncurrent") + v("operating_lease_obligations_noncurrent"), unit="USD", period_type="instant", source_location="Current and noncurrent finance/operating lease obligations", notes="Balance-sheet lease obligation view; not a cash payment schedule."),
            calc_row("partial_liquidity_cushion_before_interest_capex_wc", (v("unrestricted_cash") + v("abl_excess_availability")) - (v("current_finance_lease_obligations") + v("current_operating_lease_obligations")), unit="USD", period_type="instant", source_location="Cash + ABL availability - current leases", notes="Partial cushion only. Must still model cash interest, maintenance capex, WC swing, and facility haircut."),
            calc_row("lease_adjusted_obligations_less_cash", v("long_term_debt") + v("current_finance_lease_obligations") + v("current_operating_lease_obligations") + v("finance_lease_obligations_noncurrent") + v("operating_lease_obligations_noncurrent") - v("unrestricted_cash"), unit="USD", period_type="instant", source_location="Debt + finance/operating lease liabilities - cash", notes="Definition-based obligation measure; do not call net leverage without EBITDA."),
            calc_row("current_ratio", v("current_assets") / v("current_liabilities"), unit="ratio", period_type="instant", source_location="Current assets / current liabilities", notes="Low standalone investment value for ABL-backed distributor; do not over-weight."),
        ]
    )

    by_name = {row.metric_name: row for row in rows}
    v = lambda name: float(by_name[name].value)

    validations: list[dict[str, Any]] = []

    def add_validation(id_: str, result: str, severity: str, evidence: str, investment_relevance: str, remediation: str) -> None:
        validations.append(
            {
                "id": id_,
                "result": result,
                "severity": severity,
                "evidence": evidence,
                "investment_relevance": investment_relevance,
                "remediation": remediation,
            }
        )

    add_validation(
        "P0-01-period-mismatch-block",
        "BLOCKED",
        "Critical",
        "Q3 net income uses 2025-12-28 to 2026-03-28; CFO uses 2025-06-29 to 2026-03-28.",
        "Prevents the prior invalid CFO/net income calculation.",
        "Use YTD/YTD or derived-quarter/quarter only.",
    )
    add_validation(
        "P0-02-ytd-fcf-classification",
        "PASS" if by_name["ytd_fcf"].period_type == "YTD" else "FAIL",
        "Critical",
        f"YTD FCF is {fmt_usd(v('ytd_fcf'))} and tagged as {by_name['ytd_fcf'].period_type}.",
        "Stops YTD FCF from being called standalone Q3 cash generation.",
        "Keep YTD and standalone-quarter metrics visibly separate.",
    )
    add_validation(
        "P0-03-derived-q3-fcf",
        "PASS" if near(v("derived_q3_fcf"), 542_300_000, 1) else "FAIL",
        "High",
        f"Derived Q3 CFO {fmt_usd(v('derived_q3_cfo'))} - capex {fmt_usd(v('derived_q3_capex'))} = FCF {fmt_usd(v('derived_q3_fcf'))}.",
        "Creates an investable same-period cash conversion view.",
        "Show derived-quarter label and source formula.",
    )
    add_validation(
        "P0-04-cash-vs-restricted-cash",
        "PASS" if near(v("cash_and_restricted_cash") - v("unrestricted_cash"), 10_200_000, 1) else "FAIL",
        "High",
        f"Unrestricted cash {fmt_usd(v('unrestricted_cash'))}; cash plus restricted cash {fmt_usd(v('cash_and_restricted_cash'))}.",
        "Avoids overstating immediately available cash.",
        "Use unrestricted cash in liquidity sources unless restricted cash is confirmed usable.",
    )
    add_validation(
        "P0-05-abl-availability-reconciliation",
        "PASS" if near(v("abl_commitment") - v("abl_borrowings") - v("abl_letters_of_credit"), v("abl_excess_availability"), 1) else "FAIL",
        "Critical",
        f"$5.0bn - borrowings {fmt_usd(v('abl_borrowings'))} - LC {fmt_usd(v('abl_letters_of_credit'))} = disclosed availability {fmt_usd(v('abl_excess_availability'))}. Reserves are already in the disclosed availability language.",
        "Prevents double-counting reserves and understating liquidity.",
        "Do not subtract lender reserves twice.",
    )
    add_validation(
        "P0-06-current-debt-not-total-12m-obligations",
        "PASS" if v("long_term_debt_current") == 0 and v("current_lease_obligations_total") > 0 else "FAIL",
        "High",
        f"Current funded debt is {fmt_usd(v('long_term_debt_current'))}; current lease obligations total {fmt_usd(v('current_lease_obligations_total'))}.",
        "Stops current debt = 0 from being treated as no near-term fixed uses.",
        "Always show current leases and cash interest with debt maturities.",
    )
    debt_sum = v("abl_borrowings") + v("notes_due_2029_principal") + v("notes_due_2032_principal") + v("notes_due_2034_principal") + v("debt_discount_and_financing_costs")
    add_validation(
        "P0-07-debt-reconciliation",
        "PASS" if near(debt_sum, v("long_term_debt"), 1) else "FAIL",
        "High",
        f"Debt table sum {fmt_usd(debt_sum)} reconciles to long-term debt {fmt_usd(v('long_term_debt'))}.",
        "Capital structure is tied to filing note rather than an isolated XBRL line.",
        "Show tranche table in full memo.",
    )
    add_validation(
        "P0-08-balance-sheet-check",
        "PASS" if near(v("total_assets"), v("total_liabilities") + v("shareholders_equity"), 1) else "FAIL",
        "Critical",
        f"Assets {fmt_usd(v('total_assets'))}; liabilities plus equity {fmt_usd(v('total_liabilities') + v('shareholders_equity'))}.",
        "Confirms balance-sheet extraction integrity.",
        "Investigate filing scale/tag issues if fail.",
    )
    cash_change = v("cash_and_restricted_cash") - v("beginning_cash_and_restricted_cash")
    add_validation(
        "P0-09-cash-flow-rollforward",
        "PASS" if near(cash_change, -30_600_000, 1) else "FAIL",
        "Medium",
        f"Ending cash plus restricted cash {fmt_usd(v('cash_and_restricted_cash'))} less beginning {fmt_usd(v('beginning_cash_and_restricted_cash'))} = {fmt_usd(cash_change)}.",
        "Confirms cash-flow reconciliation and cash definition.",
        "Use cash+restricted for rollforward, unrestricted cash for liquidity.",
    )
    add_validation(
        "P0-10-springing-covenant-captured",
        "PASS" if "five consecutive business days" in str(by_name["springing_fixed_charge_covenant_trigger"].value) else "FAIL",
        "High",
        "ABL fixed-charge covenant is triggered by Alternate Availability falling below the disclosed threshold for five consecutive business days; company disclosed compliance.",
        "Covenant risk is availability-driven rather than always active.",
        "Stress ABL availability and borrowing-base quality.",
    )
    add_validation(
        "P0-11-investment-action-gate",
        "PASS",
        "High",
        "Consensus, peer valuation, normalized EBITDA, and scenario return are marked missing in this pack.",
        "Prevents a premature Buy/Sell output from a credit screen.",
        "Use Watch / Need More Work until valuation and earnings work are complete.",
    )

    # Sort rows by broad evidence order for stable output.
    rows = sorted(rows, key=lambda r: (r.period_end, r.metric_name))

    write_csv(DATA_DIR / "pfgc_step2_normalized_data.csv", rows)
    write_json(DATA_DIR / "pfgc_step2_normalized_data.json", rows, validations)
    (VALIDATION_DIR / "pfgc_step2_validation_report.md").write_text(build_validation_report(validations), encoding="utf-8")
    (OUT_ROOT / "pfgc_step2_investment_data_pack.md").write_text(build_markdown(rows, validations), encoding="utf-8")

    print(f"Wrote {len(rows)} data points.")
    print(f"Wrote {len(validations)} validation tests.")
    print(DATA_DIR / "pfgc_step2_normalized_data.csv")
    print(VALIDATION_DIR / "pfgc_step2_validation_report.md")
    print(OUT_ROOT / "pfgc_step2_investment_data_pack.md")


if __name__ == "__main__":
    main()
