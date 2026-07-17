#!/usr/bin/env python3
"""Quick SEC public-company screen for blind validation.

This script samples SEC-listed companies, filters out financial-sector and
thin-disclosure targets, and prints a compact CSV of recent filing metadata and
basic liquidity / working-capital indicators. It is intentionally a screening
aid, not a rating model.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "public-company-investment-underwriting contact@example.com",
)
BASE = "https://data.sec.gov"
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

EXCLUDED_NAME_TERMS = (
    " acquisition",
    " spac",
    " etf",
    " fund",
    " trust",
    " notes",
    " warrant",
    " rights",
    " units",
)


def fetch_json(url: str) -> Any:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cik10(cik: int | str) -> str:
    return str(cik).zfill(10)


def latest_form(sub: dict[str, Any], forms: set[str]) -> dict[str, str] | None:
    recent = sub.get("filings", {}).get("recent", {})
    for i, form in enumerate(recent.get("form", [])):
        if form in forms:
            return {
                "form": form,
                "filed": recent["filingDate"][i],
                "period": recent["reportDate"][i],
                "accession": recent["accessionNumber"][i],
                "doc": recent["primaryDocument"][i],
            }
    return None


def is_excluded_company(name: str, sub: dict[str, Any]) -> bool:
    lower = f" {name.lower()} "
    if any(term in lower for term in EXCLUDED_NAME_TERMS):
        return True
    sic = sub.get("sic")
    if sic:
        try:
            sic_int = int(sic)
        except ValueError:
            sic_int = -1
        if 6000 <= sic_int <= 6999:
            return True
    return False


def fact_units(facts: dict[str, Any], tag: str) -> list[dict[str, Any]]:
    item = facts.get("facts", {}).get("us-gaap", {}).get(tag)
    if not item:
        return []
    out: list[dict[str, Any]] = []
    for unit, values in item.get("units", {}).items():
        if "USD" not in unit and unit not in {"shares", "pure"}:
            continue
        out.extend(values)
    return out


def instant_value(facts: dict[str, Any], tags: tuple[str, ...], end: str) -> float | None:
    for tag in tags:
        vals = [
            v
            for v in fact_units(facts, tag)
            if v.get("end") == end and v.get("form") in {"10-K", "10-Q"} and "start" not in v
        ]
        if vals:
            vals.sort(key=lambda v: v.get("filed", ""))
            return float(vals[-1]["val"])
    return None


def duration_value(
    facts: dict[str, Any],
    tags: tuple[str, ...],
    end: str,
    form: str | None = None,
) -> float | None:
    for tag in tags:
        vals = [
            v
            for v in fact_units(facts, tag)
            if v.get("end") == end
            and v.get("form") in {"10-K", "10-Q"}
            and "start" in v
            and (form is None or v.get("form") == form)
        ]
        if vals:
            vals.sort(key=lambda v: (v.get("filed", ""), v.get("start", "")))
            return float(vals[-1]["val"])
    return None


def ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0):
        return None
    return num / den


def fmt(value: float | None, scale: float = 1_000_000) -> str:
    if value is None:
        return ""
    return f"{value / scale:.1f}"


def fmt_ratio(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def screen_company(row: list[Any]) -> dict[str, str] | None:
    cik_raw, name, ticker, exchange = row[0], row[1], row[2], row[3]
    cik = cik10(cik_raw)
    sub = fetch_json(f"{BASE}/submissions/CIK{cik}.json")
    if is_excluded_company(name, sub):
        return None

    latest_10k = latest_form(sub, {"10-K", "20-F"})
    latest_10q = latest_form(sub, {"10-Q", "6-K"})
    if not latest_10k or not latest_10q:
        return None
    if latest_10k["filed"] < "2025-01-01" or latest_10q["filed"] < "2025-01-01":
        return None

    facts = fetch_json(f"{BASE}/api/xbrl/companyfacts/CIK{cik}.json")
    end = latest_10q["period"] or latest_10k["period"]
    fy_end = latest_10k["period"]

    cash = instant_value(facts, ("CashAndCashEquivalentsAtCarryingValue",), end)
    short_inv = instant_value(facts, ("ShortTermInvestments", "MarketableSecuritiesCurrent"), end)
    ar = instant_value(
        facts,
        ("AccountsReceivableNetCurrent", "ContractWithCustomerReceivableBeforeAllowanceForCreditLossCurrent"),
        end,
    )
    inv = instant_value(facts, ("InventoryNet", "InventoryGross"), end)
    ca = instant_value(facts, ("AssetsCurrent",), end)
    cl = instant_value(facts, ("LiabilitiesCurrent",), end)
    debt_cur = instant_value(facts, ("DebtCurrent", "LongTermDebtCurrent", "ConvertibleDebtCurrent"), end)
    debt_long = instant_value(
        facts,
        ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "ConvertibleDebtNoncurrent"),
        end,
    )
    allowance = instant_value(
        facts,
        ("AllowanceForDoubtfulAccountsReceivableCurrent", "AllowanceForDoubtfulAccountsReceivable"),
        end,
    )
    revenue = duration_value(
        facts,
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
        latest_10q["period"],
        "10-Q",
    )
    net_income = duration_value(facts, ("NetIncomeLoss",), latest_10q["period"], "10-Q")
    cfo = duration_value(facts, ("NetCashProvidedByUsedInOperatingActivities",), latest_10q["period"], "10-Q")
    capex = duration_value(facts, ("PaymentsToAcquirePropertyPlantAndEquipment",), latest_10q["period"], "10-Q")
    fy_cfo = duration_value(facts, ("NetCashProvidedByUsedInOperatingActivities",), fy_end, "10-K")

    completeness = sum(v is not None for v in [cash, ar, ca, cl, revenue, net_income, cfo])
    if completeness < 5:
        return None

    current_ratio = ratio(ca, cl)
    liquidity_to_cl = ratio((cash or 0) + (short_inv or 0), cl)
    cfo_to_ni = ratio(cfo, net_income)
    ar_to_rev = ratio(ar, revenue)
    allowance_to_ar = ratio(allowance, ar)
    total_debt = (debt_cur or 0) + (debt_long or 0)

    signals = []
    if current_ratio is not None and current_ratio < 1.0:
        signals.append("current_ratio<1")
    if liquidity_to_cl is not None and liquidity_to_cl < 0.2:
        signals.append("low_liquidity_vs_CL")
    if cfo is not None and cfo < 0:
        signals.append("negative_CFO")
    if net_income is not None and net_income < 0:
        signals.append("net_loss")
    if ar_to_rev is not None and ar_to_rev > 0.35:
        signals.append("AR_high_vs_revenue")
    if allowance_to_ar is not None and allowance_to_ar > 0.05:
        signals.append("allowance_high")
    if total_debt and cash and total_debt > 3 * cash:
        signals.append("debt_gt_3x_cash")

    return {
        "ticker": ticker,
        "name": name,
        "exchange": exchange,
        "cik": cik,
        "sic": str(sub.get("sic", "")),
        "sicDescription": str(sub.get("sicDescription", "")),
        "latest_10k": latest_10k["filed"],
        "latest_10q": latest_10q["filed"],
        "period": end,
        "cash_m": fmt(cash),
        "short_inv_m": fmt(short_inv),
        "ar_m": fmt(ar),
        "inventory_m": fmt(inv),
        "current_assets_m": fmt(ca),
        "current_liabilities_m": fmt(cl),
        "current_debt_m": fmt(debt_cur),
        "total_debt_m": fmt(total_debt),
        "revenue_m": fmt(revenue),
        "net_income_m": fmt(net_income),
        "cfo_m": fmt(cfo),
        "fy_cfo_m": fmt(fy_cfo),
        "current_ratio": fmt_ratio(current_ratio),
        "liquidity_to_cl": fmt_ratio(liquidity_to_cl),
        "ar_to_rev": fmt_ratio(ar_to_rev),
        "allowance_to_ar": fmt_ratio(allowance_to_ar),
        "signals": ";".join(signals),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-size", type=int, default=80)
    parser.add_argument("--keep", type=int, default=20)
    parser.add_argument("--seed", type=int, default=int(date.today().strftime("%Y%m%d")))
    parser.add_argument("--sleep", type=float, default=0.12)
    args = parser.parse_args()

    data = fetch_json(TICKERS_URL)
    rows = data["data"]
    random.seed(args.seed)
    random.shuffle(rows)

    results = []
    for row in rows[: args.sample_size]:
        try:
            result = screen_company(row)
        except (HTTPError, URLError, TimeoutError, KeyError, ValueError, json.JSONDecodeError):
            result = None
        if result:
            results.append(result)
            if len(results) >= args.keep:
                break
        time.sleep(args.sleep)

    if not results:
        return 1

    writer = csv.DictWriter(sys.stdout, fieldnames=list(results[0].keys()))
    writer.writeheader()
    writer.writerows(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
