#!/usr/bin/env python3
"""Build a compact SEC metric pack for one public-company review.

The script fetches public SEC submissions and XBRL company facts for a ticker,
then prints the latest quarterly and annual metrics needed by the
public-firm-credit-liquidity skill. It is a data-gathering helper, not a
rating model.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import Any
from urllib.request import Request, urlopen


USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "public-company-investment-underwriting contact@example.com",
)
BASE = "https://data.sec.gov"
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"


INSTANT_METRICS: dict[str, tuple[str, ...]] = {
    "Cash and cash equivalents": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
    ),
    "Current marketable securities / short-term investments": (
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
    ),
    "Accounts receivable, net": (
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
        "ContractWithCustomerReceivableBeforeAllowanceForCreditLossCurrent",
    ),
    "Inventory": ("InventoryNet", "InventoryGross"),
    "Current assets": ("AssetsCurrent",),
    "Current liabilities": ("LiabilitiesCurrent",),
    "Accounts payable": ("AccountsPayableCurrent",),
    "Current debt": (
        "DebtCurrent",
        "ShortTermBorrowings",
        "ShortTermDebtCurrent",
        "LongTermDebtCurrent",
        "ConvertibleDebtCurrent",
    ),
    "Non-current debt": (
        "LongTermDebtNoncurrent",
        "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
        "ConvertibleDebtNoncurrent",
    ),
    "Allowance for doubtful accounts / credit losses": (
        "AllowanceForDoubtfulAccountsReceivableCurrent",
        "AllowanceForDoubtfulAccountsReceivable",
        "AllowanceForCreditLossesOnAccountsReceivable",
        "FinancingReceivableAllowanceForCreditLosses",
    ),
}


DURATION_METRICS: dict[str, tuple[str, ...]] = {
    "Revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ),
    "Net income": ("NetIncomeLoss",),
    "Operating cash flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "Capital expenditures": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "Interest expense": ("InterestExpenseNonOperating", "InterestExpense", "InterestExpenseDebt"),
}


def fetch_json(url: str) -> Any:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cik10(cik: int | str) -> str:
    return str(cik).zfill(10)


def ticker_map() -> dict[str, dict[str, Any]]:
    data = fetch_json(TICKERS_URL)
    out: dict[str, dict[str, Any]] = {}
    for row in data["data"]:
        cik, name, ticker, exchange = row[:4]
        out[str(ticker).upper()] = {
            "cik": cik10(cik),
            "name": name,
            "ticker": str(ticker).upper(),
            "exchange": exchange,
        }
    return out


def latest_form(sub: dict[str, Any], forms: set[str]) -> dict[str, str] | None:
    recent = sub.get("filings", {}).get("recent", {})
    for i, form in enumerate(recent.get("form", [])):
        if form in forms:
            accession = recent["accessionNumber"][i]
            cik_short = str(sub["cik"]).lstrip("0")
            accession_path = accession.replace("-", "")
            doc = recent["primaryDocument"][i]
            return {
                "form": form,
                "filed": recent["filingDate"][i],
                "period": recent["reportDate"][i],
                "accession": accession,
                "doc": doc,
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik_short}/{accession_path}/{doc}",
            }
    return None


def fact_points(facts: dict[str, Any], tag: str) -> list[dict[str, Any]]:
    item = facts.get("facts", {}).get("us-gaap", {}).get(tag)
    if not item:
        return []
    out: list[dict[str, Any]] = []
    for unit, values in item.get("units", {}).items():
        if "USD" not in unit and unit not in {"shares", "pure"}:
            continue
        for value in values:
            if "val" in value and value.get("end"):
                point = dict(value)
                point["unit"] = unit
                point["tag"] = tag
                out.append(point)
    return out


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def duration_days(point: dict[str, Any]) -> int | None:
    start = parse_date(point.get("start"))
    end = parse_date(point.get("end"))
    if not start or not end:
        return None
    return (end - start).days


def instant_point(facts: dict[str, Any], tags: tuple[str, ...], end: str) -> dict[str, Any] | None:
    for tag in tags:
        vals = [
            p
            for p in fact_points(facts, tag)
            if p.get("end") == end and p.get("form") in {"10-K", "10-Q"} and "start" not in p
        ]
        if vals:
            vals.sort(key=lambda p: p.get("filed", ""))
            return vals[-1]
    return None


def duration_point(
    facts: dict[str, Any],
    tags: tuple[str, ...],
    end: str,
    form: str,
) -> dict[str, Any] | None:
    for tag in tags:
        vals = [
            p
            for p in fact_points(facts, tag)
            if p.get("end") == end and p.get("form") == form and "start" in p
        ]
        if not vals:
            continue
        if form == "10-K":
            annual = [p for p in vals if (duration_days(p) or 0) >= 270]
            vals = annual or vals
        elif form == "10-Q":
            quarterly = [p for p in vals if 60 <= (duration_days(p) or 0) <= 130]
            vals = quarterly or vals
        vals.sort(key=lambda p: (p.get("filed", ""), duration_days(p) or 0))
        return vals[-1]
    return None


def value(point: dict[str, Any] | None) -> float | None:
    if not point:
        return None
    try:
        return float(point["val"])
    except (TypeError, ValueError):
        return None


def ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0):
        return None
    return num / den


def usd_m(point: dict[str, Any] | None) -> str:
    raw = value(point)
    if raw is None:
        return "n/a"
    scaled = raw / 1_000_000
    if scaled and abs(scaled) < 1:
        return f"{scaled:.3f}"
    return f"{scaled:.1f}"


def raw_value(point: dict[str, Any] | None) -> str:
    raw = value(point)
    if raw is None:
        return "n/a"
    return f"{raw:.4f}" if abs(raw) < 10 else f"{raw:,.0f}"


def ratio_text(raw: float | None) -> str:
    if raw is None:
        return "n/a"
    return f"{raw:.2f}x"


def pct_text(raw: float | None) -> str:
    if raw is None:
        return "n/a"
    return f"{raw * 100:.1f}%"


def tag_name(point: dict[str, Any] | None) -> str:
    return "n/a" if not point else str(point.get("tag", "n/a"))


def source_note(point: dict[str, Any] | None) -> str:
    if not point:
        return "n/a"
    return f"{point.get('form', 'n/a')} filed {point.get('filed', 'n/a')}"


def build_pack(ticker: str) -> dict[str, Any]:
    company = ticker_map().get(ticker.upper())
    if not company:
        raise ValueError(f"Ticker not found in SEC ticker list: {ticker}")

    cik = company["cik"]
    sub = fetch_json(f"{BASE}/submissions/CIK{cik}.json")
    facts = fetch_json(f"{BASE}/api/xbrl/companyfacts/CIK{cik}.json")
    latest_quarter = latest_form(sub, {"10-Q", "6-K"})
    latest_annual = latest_form(sub, {"10-K", "20-F"})
    if not latest_quarter or not latest_annual:
        raise ValueError(f"Could not find latest annual and quarterly filings for {ticker}")

    q_end = latest_quarter["period"]
    fy_end = latest_annual["period"]
    instant: dict[str, dict[str, Any | None]] = {}
    for label, tags in INSTANT_METRICS.items():
        instant[label] = {
            "quarter": instant_point(facts, tags, q_end),
            "annual": instant_point(facts, tags, fy_end),
        }

    duration: dict[str, dict[str, Any | None]] = {}
    for label, tags in DURATION_METRICS.items():
        duration[label] = {
            "quarter": duration_point(facts, tags, q_end, "10-Q"),
            "annual": duration_point(facts, tags, fy_end, "10-K"),
        }

    q_cash = value(instant["Cash and cash equivalents"]["quarter"])
    q_short_inv = value(instant["Current marketable securities / short-term investments"]["quarter"])
    q_ar = value(instant["Accounts receivable, net"]["quarter"])
    q_ca = value(instant["Current assets"]["quarter"])
    q_cl = value(instant["Current liabilities"]["quarter"])
    q_debt_cur = value(instant["Current debt"]["quarter"])
    q_debt_long = value(instant["Non-current debt"]["quarter"])
    q_allowance = value(instant["Allowance for doubtful accounts / credit losses"]["quarter"])
    q_revenue = value(duration["Revenue"]["quarter"])
    q_net_income = value(duration["Net income"]["quarter"])
    q_cfo = value(duration["Operating cash flow"]["quarter"])
    q_capex = value(duration["Capital expenditures"]["quarter"])

    total_debt = (q_debt_cur or 0) + (q_debt_long or 0)
    liquidity = (q_cash or 0) + (q_short_inv or 0)
    return {
        "company": company,
        "submissions": sub,
        "latest_quarter": latest_quarter,
        "latest_annual": latest_annual,
        "instant": instant,
        "duration": duration,
        "derived": {
            "current_ratio": ratio(q_ca, q_cl),
            "cash_and_short_investments_to_current_liabilities": ratio(liquidity, q_cl),
            "ar_to_quarterly_revenue": ratio(q_ar, q_revenue),
            "allowance_to_ar": ratio(q_allowance, q_ar),
            "cfo_to_net_income": ratio(q_cfo, q_net_income),
            "free_cash_flow": None if q_cfo is None else q_cfo - (q_capex or 0),
            "total_debt": total_debt,
            "total_debt_to_cash": ratio(total_debt, q_cash),
        },
    }


def print_markdown(pack: dict[str, Any]) -> None:
    company = pack["company"]
    q = pack["latest_quarter"]
    k = pack["latest_annual"]
    print(f"# SEC Metric Pack: {company['name']} ({company['ticker']})")
    print()
    print(f"- CIK: {company['cik']}")
    print(f"- Exchange: {company['exchange']}")
    print(f"- Latest interim filing: {q['form']} filed {q['filed']}, period ended {q['period']} ({q['url']})")
    print(f"- Latest annual filing: {k['form']} filed {k['filed']}, period ended {k['period']} ({k['url']})")
    print()
    print("## Balance Sheet Metrics (USD millions)")
    print()
    print("| Metric | Latest interim | Annual comparison | Interim tag | Source note |")
    print("|---|---:|---:|---|---|")
    for label, points in pack["instant"].items():
        print(
            f"| {label} | {usd_m(points['quarter'])} | {usd_m(points['annual'])} | "
            f"{tag_name(points['quarter'])} | {source_note(points['quarter'])} |"
        )
    print()
    print("## Income and Cash Flow Metrics (USD millions)")
    print()
    print("| Metric | Latest interim | Annual comparison | Interim tag | Source note |")
    print("|---|---:|---:|---|---|")
    for label, points in pack["duration"].items():
        print(
            f"| {label} | {usd_m(points['quarter'])} | {usd_m(points['annual'])} | "
            f"{tag_name(points['quarter'])} | {source_note(points['quarter'])} |"
        )
    print()
    d = pack["derived"]
    print("## Derived Indicators")
    print()
    print("| Indicator | Value |")
    print("|---|---:|")
    print(f"| Current ratio | {ratio_text(d['current_ratio'])} |")
    print(f"| Cash + short investments / current liabilities | {pct_text(d['cash_and_short_investments_to_current_liabilities'])} |")
    print(f"| AR / quarterly revenue | {pct_text(d['ar_to_quarterly_revenue'])} |")
    print(f"| Allowance / AR | {pct_text(d['allowance_to_ar'])} |")
    print(f"| CFO / net income | {ratio_text(d['cfo_to_net_income'])} |")
    print(f"| Free cash flow (USD) | {raw_value({'val': d['free_cash_flow']} if d['free_cash_flow'] is not None else None)} |")
    print(f"| Total extracted debt (USD) | {raw_value({'val': d['total_debt']})} |")
    print(f"| Total debt / cash | {ratio_text(d['total_debt_to_cash'])} |")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", help="Public company ticker, e.g. AAPL")
    args = parser.parse_args()

    try:
        pack = build_pack(args.ticker)
    except Exception as exc:  # noqa: BLE001 - CLI should return a clear error.
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print_markdown(pack)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
