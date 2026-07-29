#!/usr/bin/env python3
"""Build a generic Step 3 investment decision-support layer.

This script sits on top of the Step 2 SEC public-company data pack. It adds
public market data, trailing valuation metrics, a clearly labeled scenario
shell, investment-committee-style synthesis, and validation gates.

Design principle: do not let placeholder scenario math become a trade call.
For an arbitrary company, the default output is decision support and usually
remains "Watch / Need More Work" until consensus, analyst-supplied scenarios,
downside, and portfolio context are complete.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[3]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_public_company_decision_pack import (  # noqa: E402
    DEFAULT_OUT_ROOT,
    FLOW_TAGS,
    SEC_UA,
    build_ltm_metric as build_shared_ltm_metric,
    build_company_pack,
    fetch_json,
    flow_points_for_tags as shared_flow_points_for_tags,
    fmt_usd,
    is_annual_flow,
    latest_share_count_fact,
    metric_map,
    safe_float,
    select_latest_annual_from_points,
    select_latest_ytd_from_points,
    select_prior_comparable_ytd_from_points,
    working_capital_component_coverage,
)
from equity_valuation_contract import (  # noqa: E402
    build_shared_valuation_contract,
    legacy_return_context,
    normalize_valuation_period,
)
from underwriting_contract import (  # noqa: E402
    FCF_NORMALIZATION_STATUSES,
    PEER_COMPARABILITY_STATUSES,
    PROBABILITY_METHOD_REQUIRED_DETAILS,
    PROBABILITY_METHOD_TYPES,
    PUBLIC_DATA_INVESTMENT_VIEWS,
    SCHEMA_VERSION,
    determine_data_gate,
    determine_decision_confidence,
    finalize_output_contract,
    stable_id,
)


YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range}&interval={interval}"
TICKER_SOURCE = "https://www.sec.gov/files/company_tickers_exchange.json"
SPY_TICKER = "SPY"
APPROVED_MARKET_DATA_STATUSES = {"APPROVED_FOR_RESEARCH", "APPROVED_BY_PARTNER"}


def market_data_is_approved(snapshot: dict[str, Any]) -> bool:
    """Return whether the provider is approved for the stated analysis scope."""

    return snapshot.get("provider_approval_status") in APPROVED_MARKET_DATA_STATUSES


@dataclass
class Scenario:
    name: str
    probability: float | None
    metric: str
    metric_per_share: float | None
    growth_assumption: float | None
    exit_multiple_factor: float | None
    exit_multiple: float | None
    target_price: float | None
    total_return: float | None
    evidence_type: str
    assumption_status: str
    confidence: str
    key_driver: str
    falsification_trigger: str
    notes: str
    assumption_sources: list[str] = field(default_factory=list)
    probability_rationale: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    share_count_basis_value: float | None = None
    share_count_basis_date: str = ""
    forecast_period: dict[str, Any] = field(default_factory=dict)
    metric_period: dict[str, Any] = field(default_factory=dict)
    metric_unit: str = ""
    metric_currency: str = ""
    formula: str = (
        "implied_price = metric_value_total / scenario_share_count_basis * exit_multiple; "
        "price_change_vs_current = implied_price / current_price - 1"
    )


@dataclass
class ValidationGate:
    gate_id: str
    result: str
    severity: str
    evidence: str
    decision_impact: str
    remediation: str
    issue_class: str = "INFO"
    category: str = "investment_validation"


@dataclass
class CommitteeRole:
    role: str
    view: str
    evidence: str
    decision_impact: str
    confidence: str
    falsification_trigger: str


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def request_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


def yahoo_url(ticker: str, range_: str = "2y", interval: str = "1d") -> str:
    quoted = urllib.parse.quote(ticker.upper(), safe="")
    return YAHOO_CHART.format(ticker=quoted, range=range_, interval=interval)


def get_price_snapshot(ticker: str, range_: str = "2y", interval: str = "1d") -> dict[str, Any]:
    source_url = yahoo_url(ticker, range_, interval)
    try:
        data = request_json(source_url)
    except Exception as exc:  # noqa: BLE001 - external market source should not crash the pack
        return {
            "ticker": ticker.upper(),
            "provider": "Yahoo Finance chart endpoint",
            "status": "MISSING",
            "error": str(exc),
            "source_url": source_url,
            "history": [],
        }

    chart = data.get("chart", {})
    if chart.get("error"):
        return {
            "ticker": ticker.upper(),
            "provider": "Yahoo Finance chart endpoint",
            "status": "MISSING",
            "error": json.dumps(chart.get("error")),
            "source_url": source_url,
            "history": [],
        }

    result = chart.get("result") or []
    if not result:
        return {
            "ticker": ticker.upper(),
            "provider": "Yahoo Finance chart endpoint",
            "status": "MISSING",
            "error": "No chart result returned.",
            "source_url": source_url,
            "history": [],
        }

    payload = result[0]
    meta = payload.get("meta", {})
    timestamps = payload.get("timestamp", []) or []
    closes = payload.get("indicators", {}).get("quote", [{}])[0].get("close", []) or []
    adjusted_closes = payload.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", []) or []
    history: list[dict[str, Any]] = []
    for index, (timestamp, close) in enumerate(zip(timestamps, closes)):
        close_v = safe_float(close)
        if close_v is None:
            continue
        adjusted_close = safe_float(adjusted_closes[index]) if index < len(adjusted_closes) else None
        history.append(
            {
                "timestamp": timestamp,
                "date": datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%d"),
                "close": close_v,
                "adjusted_close": adjusted_close if adjusted_close is not None else close_v,
            }
        )

    price = safe_float(history[-1]["close"]) if history else None
    price_date = history[-1]["date"] if history else ""

    market_time = meta.get("regularMarketTime")
    market_time_label = (
        datetime.fromtimestamp(market_time, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        if isinstance(market_time, int)
        else ""
    )

    return {
        "ticker": ticker.upper(),
        "provider": "Yahoo Finance chart endpoint",
        "source_level": 5,
        "provider_approval_status": "NOT_APPROVED_BY_PARTNER",
        "status": "PASS" if price is not None else "MISSING",
        "price": price,
        "price_type": "unadjusted daily close",
        "price_date": price_date,
        "currency": meta.get("currency", "USD"),
        "regular_market_price": safe_float(meta.get("regularMarketPrice")),
        "regular_market_time": market_time_label,
        "fifty_two_week_high": safe_float(meta.get("fiftyTwoWeekHigh")),
        "fifty_two_week_low": safe_float(meta.get("fiftyTwoWeekLow")),
        "regular_market_volume": safe_float(meta.get("regularMarketVolume")),
        "source_url": source_url,
        "history": history,
    }


def aligned_return_pair(
    stock_history: list[dict[str, Any]],
    benchmark_history: list[dict[str, Any]],
    *,
    lookback_days: int = 365,
) -> dict[str, Any]:
    """Calculate returns from the same exact start and end trading dates."""

    stock_by_date = {row.get("date"): row for row in stock_history if row.get("date")}
    benchmark_by_date = {row.get("date"): row for row in benchmark_history if row.get("date")}
    common_dates = sorted(set(stock_by_date).intersection(benchmark_by_date))
    if len(common_dates) < 2:
        return {"status": "MISSING", "reason": "Fewer than two common trading dates."}

    end_date = date.fromisoformat(common_dates[-1])
    target_date = end_date - timedelta(days=lookback_days)
    candidates = [value for value in common_dates[:-1] if date.fromisoformat(value) >= target_date]
    if not candidates:
        return {"status": "MISSING", "reason": "No common trading date at the requested lookback."}
    start_label = candidates[0]
    end_label = common_dates[-1]

    stock_start = safe_float(stock_by_date[start_label].get("adjusted_close"))
    stock_end = safe_float(stock_by_date[end_label].get("adjusted_close"))
    benchmark_start = safe_float(benchmark_by_date[start_label].get("adjusted_close"))
    benchmark_end = safe_float(benchmark_by_date[end_label].get("adjusted_close"))
    if None in {stock_start, stock_end, benchmark_start, benchmark_end} or stock_start == 0 or benchmark_start == 0:
        return {"status": "MISSING", "reason": "Adjusted-close input is missing or zero."}

    stock_return = stock_end / stock_start - 1
    benchmark_return = benchmark_end / benchmark_start - 1
    return {
        "status": "PASS",
        "start_date": start_label,
        "end_date": end_label,
        "lookback_calendar_days": (end_date - date.fromisoformat(start_label)).days,
        "return_basis": "adjusted close on exact common trading dates",
        "stock_start_adjusted_close": stock_start,
        "stock_end_adjusted_close": stock_end,
        "benchmark_start_adjusted_close": benchmark_start,
        "benchmark_end_adjusted_close": benchmark_end,
        "stock_return": stock_return,
        "benchmark_return": benchmark_return,
        "relative_return": stock_return - benchmark_return,
    }


def latest_shares(companyfacts: dict[str, Any], as_of_date: str | None = None) -> tuple[float | None, dict[str, Any] | None]:
    selection = latest_share_count_fact(companyfacts, as_of_date)
    if selection["status"] != "PASS":
        return None, None
    return safe_float(selection["value"]), selection["point"]


def duration_days(point: dict[str, Any]) -> int:
    start = point.get("start")
    end = point.get("end")
    if not start or not end:
        return 0
    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
        return (e - s).days + 1
    except ValueError:
        return 0


def flow_points(companyfacts: dict[str, Any], tags: tuple[str, ...]) -> list[dict[str, Any]]:
    return shared_flow_points_for_tags(companyfacts, tags)


def flow_points_for_tag(companyfacts: dict[str, Any], tag: str) -> list[dict[str, Any]]:
    return flow_points(companyfacts, (tag,))


def source_summary(point: dict[str, Any] | None) -> dict[str, Any] | None:
    if not point:
        return None
    return {
        "tag": point.get("tag"),
        "taxonomy": point.get("taxonomy"),
        "unit": point.get("unit"),
        "value": point.get("val"),
        "form": point.get("form"),
        "fy": point.get("fy"),
        "fp": point.get("fp"),
        "start": point.get("start"),
        "end": point.get("end"),
        "filed": point.get("filed"),
        "accn": point.get("accn"),
    }


def latest_annual_from_points(points: list[dict[str, Any]], annual_period: str | None) -> dict[str, Any] | None:
    return select_latest_annual_from_points(points, annual_period)


def latest_ytd_from_points(points: list[dict[str, Any]], latest_q_period: str | None) -> dict[str, Any] | None:
    return select_latest_ytd_from_points(points, latest_q_period)


def prior_year_ytd_from_points(points: list[dict[str, Any]], current_ytd: dict[str, Any] | None) -> dict[str, Any] | None:
    return select_prior_comparable_ytd_from_points(points, current_ytd)


def ltm_metric(companyfacts: dict[str, Any], metric: str, latest_q_period: str | None, annual_period: str | None) -> dict[str, Any]:
    return build_shared_ltm_metric(companyfacts, metric, latest_q_period, annual_period)


def annual_history(companyfacts: dict[str, Any], metric: str, annual_period: str | None, max_points: int = 5) -> dict[str, Any]:
    best_points: list[dict[str, Any]] = []
    best_tag = ""
    for tag in FLOW_TAGS[metric]:
        points = flow_points_for_tag(companyfacts, tag)
        annuals = [p for p in points if is_annual_flow(p)]
        if annual_period:
            annuals = [p for p in annuals if p.get("end", "") <= annual_period]
        annuals.sort(key=lambda p: (p.get("end", ""), p.get("filed", ""), p.get("accn", "")))
        deduped: dict[str, dict[str, Any]] = {}
        for point in annuals:
            deduped[point.get("end", "")] = point
        ordered = [deduped[k] for k in sorted(deduped)]
        if len(ordered) > len(best_points):
            best_points = ordered
            best_tag = tag
    best_points = best_points[-max_points:]
    rows = [
        {
            "period_end": p.get("end"),
            "value": safe_float(p.get("val")),
            "source": source_label(source_summary(p)),
        }
        for p in best_points
    ]
    latest = safe_float(best_points[-1].get("val")) if best_points else None
    prior = safe_float(best_points[-2].get("val")) if len(best_points) >= 2 else None
    return {
        "metric": metric,
        "tag": best_tag,
        "rows": rows,
        "latest": latest,
        "prior": prior,
        "latest_growth": change_ratio(latest, prior),
        "status": "PASS" if len(best_points) >= 2 else "MISSING",
    }


def ytd_growth(companyfacts: dict[str, Any], metric: str, latest_q_period: str | None) -> dict[str, Any]:
    if not latest_q_period:
        return {"metric": metric, "status": "MISSING", "growth": None, "source": ""}
    for tag in FLOW_TAGS[metric]:
        points = flow_points_for_tag(companyfacts, tag)
        current = latest_ytd_from_points(points, latest_q_period)
        prior = prior_year_ytd_from_points(points, current)
        current_v = safe_float(current.get("val")) if current else None
        prior_v = safe_float(prior.get("val")) if prior else None
        growth = change_ratio(current_v, prior_v)
        if growth is not None:
            return {
                "metric": metric,
                "tag": tag,
                "status": "PASS",
                "growth": growth,
                "current_value": current_v,
                "prior_value": prior_v,
                "current_source": source_label(source_summary(current)),
                "prior_source": source_label(source_summary(prior)),
            }
    return {"metric": metric, "status": "MISSING", "growth": None, "source": ""}


def read_step2_json(out_dir: Path) -> dict[str, Any]:
    path = out_dir / "data" / "normalized_data.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def calc_ratio(num: float | None, den: float | None, *, positive_denominator_only: bool = False) -> float | None:
    if num is None or den in (None, 0):
        return None
    if positive_denominator_only and den <= 0:
        return None
    return num / den


def multiple_label(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}x"


def percent_label(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def price_label(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"


def source_label(source: dict[str, Any] | None) -> str:
    if not source:
        return "n/a"
    taxonomy = source.get("taxonomy") or "xbrl"
    tag = source.get("tag") or "unknown-tag"
    form = source.get("form") or "n/a"
    period = source.get("end") or source.get("instant") or "n/a"
    filed = source.get("filed") or "n/a"
    return f"{taxonomy}:{tag}; form={form}; period={period}; filed={filed}"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def median_or_none(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return statistics.median(clean)


def change_ratio(current: float | None, prior: float | None) -> float | None:
    if current is None or prior in (None, 0):
        return None
    if prior < 0 and current > 0:
        return None
    return current / prior - 1


def metric_value(metrics: dict[str, Any], name: str) -> float | None:
    row = metrics.get(name)
    return safe_float(getattr(row, "value", None)) if row else None


def metric_source(metrics: dict[str, Any], name: str) -> dict[str, Any] | None:
    row = metrics.get(name)
    if not row:
        return None
    return {
        "metric_name": getattr(row, "metric_name", name),
        "period_start": getattr(row, "period_start", ""),
        "period_end": getattr(row, "period_end", ""),
        "period_type": getattr(row, "period_type", ""),
        "source_location": getattr(row, "source_location", ""),
        "source_tag": getattr(row, "source_tag", ""),
        "source_url": getattr(row, "source_url", ""),
        "evidence_type": getattr(row, "evidence_type", ""),
        "confidence": getattr(row, "confidence", ""),
    }


def build_valuation(
    step2: dict[str, Any],
    companyfacts: dict[str, Any],
    market_snapshot: dict[str, Any],
) -> dict[str, Any]:
    filings = step2.get("filings", {})
    latest_q = filings.get("latest_q") or {}
    latest_k = filings.get("latest_k") or {}
    latest_q_period = latest_q.get("period")
    latest_k_period = latest_k.get("period")

    rows = [SimpleNamespace(**point) for point in step2.get("data_points", [])]
    step2_metrics = metric_map(rows)

    price = safe_float(market_snapshot.get("price"))
    shares, shares_fact = latest_shares(companyfacts, market_snapshot.get("price_date"))
    market_cap = price * shares if price is not None and shares is not None else None

    cash_sti = metric_value(step2_metrics, "available_liquidity_before_facility_notes")
    if cash_sti is None:
        unrestricted_cash = metric_value(step2_metrics, "unrestricted_cash") or 0.0
        short_term_investments = metric_value(step2_metrics, "short_term_investments") or 0.0
        cash_sti = unrestricted_cash + short_term_investments

    debt = 0.0
    for name in ("current_debt", "long_term_debt"):
        debt += metric_value(step2_metrics, name) or 0.0

    leases = 0.0
    for name in (
        "finance_lease_current",
        "finance_lease_noncurrent",
        "operating_lease_current",
        "operating_lease_noncurrent",
    ):
        leases += metric_value(step2_metrics, name) or 0.0

    ltm = {
        metric: ltm_metric(companyfacts, metric, latest_q_period, latest_k_period)
        for metric in ("revenue", "operating_income", "net_income", "cfo", "capex")
    }
    ltm_fcf = None
    if ltm["cfo"].get("value") is not None and ltm["capex"].get("value") is not None:
        ltm_fcf = ltm["cfo"]["value"] - ltm["capex"]["value"]

    enterprise_value_proxy = market_cap + debt + leases - cash_sti if market_cap is not None else None
    net_debt_before_facility = debt + leases - cash_sti

    pe = calc_ratio(market_cap, ltm["net_income"].get("value"), positive_denominator_only=True)
    p_fcf = calc_ratio(market_cap, ltm_fcf, positive_denominator_only=True)
    fcf_yield = calc_ratio(ltm_fcf, market_cap)
    ev_sales = calc_ratio(enterprise_value_proxy, ltm["revenue"].get("value"), positive_denominator_only=True)
    ev_operating_income = calc_ratio(
        enterprise_value_proxy,
        ltm["operating_income"].get("value"),
        positive_denominator_only=True,
    )
    net_debt_to_fcf = calc_ratio(net_debt_before_facility, ltm_fcf, positive_denominator_only=True)

    if ltm_fcf is not None and ltm_fcf > 0 and p_fcf is not None:
        scenario_metric = "FCF"
        scenario_metric_value = ltm_fcf
        scenario_multiple = p_fcf
        scenario_basis = "P/FCF"
    elif ltm["net_income"].get("value") is not None and ltm["net_income"]["value"] > 0 and pe is not None:
        scenario_metric = "Net income"
        scenario_metric_value = ltm["net_income"]["value"]
        scenario_multiple = pe
        scenario_basis = "P/E"
    else:
        scenario_metric = "n/a"
        scenario_metric_value = None
        scenario_multiple = None
        scenario_basis = "blocked"

    return {
        "price": price,
        "price_currency": market_snapshot.get("currency", "USD"),
        "price_date": market_snapshot.get("price_date", ""),
        "price_type": market_snapshot.get("price_type", ""),
        "shares": shares,
        "shares_as_of_date": (shares_fact or {}).get("end") or (shares_fact or {}).get("instant") or "",
        "shares_source": source_summary(shares_fact),
        "market_cap": market_cap,
        "cash_and_short_term_investments": cash_sti,
        "cash_source": metric_source(step2_metrics, "available_liquidity_before_facility_notes"),
        "total_debt": debt,
        "lease_liabilities": leases,
        "net_debt_before_facility": net_debt_before_facility,
        "enterprise_value_proxy": enterprise_value_proxy,
        "ltm": ltm,
        "ltm_revenue": ltm["revenue"].get("value"),
        "ltm_operating_income": ltm["operating_income"].get("value"),
        "ltm_net_income": ltm["net_income"].get("value"),
        "ltm_cfo": ltm["cfo"].get("value"),
        "ltm_capex": ltm["capex"].get("value"),
        "ltm_fcf": ltm_fcf,
        "pe": pe,
        "p_fcf": p_fcf,
        "fcf_yield": fcf_yield,
        "ev_sales": ev_sales,
        "ev_operating_income": ev_operating_income,
        "net_debt_to_fcf": net_debt_to_fcf,
        "scenario_metric": scenario_metric,
        "scenario_metric_value": scenario_metric_value,
        "scenario_multiple": scenario_multiple,
        "scenario_basis": scenario_basis,
    }


def build_public_data_drivers(step2: dict[str, Any], companyfacts: dict[str, Any], valuation: dict[str, Any]) -> dict[str, Any]:
    filings = step2.get("filings", {})
    latest_q = filings.get("latest_q") or {}
    latest_k = filings.get("latest_k") or {}
    latest_q_period = latest_q.get("period")
    latest_k_period = latest_k.get("period")

    annual = {
        metric: annual_history(companyfacts, metric, latest_k_period)
        for metric in ("revenue", "operating_income", "net_income", "cfo", "capex")
    }
    ytd = {
        metric: ytd_growth(companyfacts, metric, latest_q_period)
        for metric in ("revenue", "operating_income", "net_income", "cfo", "capex")
    }

    revenue = valuation.get("ltm_revenue")
    operating_margin = calc_ratio(valuation.get("ltm_operating_income"), revenue)
    net_margin = calc_ratio(valuation.get("ltm_net_income"), revenue)
    fcf_margin = calc_ratio(valuation.get("ltm_fcf"), revenue)
    fcf_conversion_net_income = calc_ratio(valuation.get("ltm_fcf"), valuation.get("ltm_net_income"), positive_denominator_only=True)
    fcf_conversion_operating_income = calc_ratio(valuation.get("ltm_fcf"), valuation.get("ltm_operating_income"), positive_denominator_only=True)
    reported_net_income = safe_float(valuation.get("ltm_net_income"))
    conversion_value = fcf_conversion_net_income or fcf_conversion_operating_income
    conversion_requires_normalization = (
        reported_net_income is not None
        and reported_net_income <= 0
    ) or (
        conversion_value is not None
        and conversion_value >= 2.5
    )

    revenue_growth_inputs = [
        annual["revenue"].get("latest_growth"),
        ytd["revenue"].get("growth"),
    ]
    cfo_growth_inputs = [
        annual["cfo"].get("latest_growth"),
        ytd["cfo"].get("growth"),
    ]
    revenue_growth = median_or_none(revenue_growth_inputs)
    cfo_growth = median_or_none(cfo_growth_inputs)

    if conversion_requires_normalization:
        cash_conversion_signal = "reported FCF is high; normalization required"
    elif fcf_margin is not None and fcf_margin >= 0.08:
        cash_conversion_signal = "strong"
    elif fcf_margin is not None and fcf_margin >= 0.03:
        cash_conversion_signal = "adequate"
    elif fcf_margin is not None:
        cash_conversion_signal = "thin"
    else:
        cash_conversion_signal = "missing"

    leverage = valuation.get("net_debt_to_fcf")
    if leverage is not None and leverage >= 4.0:
        balance_sheet_signal = "levered"
    elif leverage is not None and leverage <= 1.5:
        balance_sheet_signal = "flexible"
    elif leverage is not None:
        balance_sheet_signal = "moderate"
    else:
        balance_sheet_signal = "not meaningful"

    rows = [
        {
            "driver": "Revenue growth",
            "value": revenue_growth,
            "display": percent_label(revenue_growth),
            "evidence": f"Annual={percent_label(annual['revenue'].get('latest_growth'))}; YTD={percent_label(ytd['revenue'].get('growth'))}",
            "decision_use": "Top-line trend for base/bull/bear growth assumptions.",
        },
        {
            "driver": "CFO growth",
            "value": cfo_growth,
            "display": percent_label(cfo_growth),
            "evidence": f"Annual={percent_label(annual['cfo'].get('latest_growth'))}; YTD={percent_label(ytd['cfo'].get('growth'))}",
            "decision_use": "Cash-generation trend for FCF scenario confidence.",
        },
        {
            "driver": "Operating margin",
            "value": operating_margin,
            "display": percent_label(operating_margin),
            "evidence": f"LTM operating income / LTM revenue = {fmt_usd(valuation.get('ltm_operating_income'))} / {fmt_usd(revenue)}",
            "decision_use": "Margin level for earnings-quality and downside sensitivity.",
        },
        {
            "driver": "FCF margin",
            "value": fcf_margin,
            "display": percent_label(fcf_margin),
            "evidence": f"LTM FCF / LTM revenue = {fmt_usd(valuation.get('ltm_fcf'))} / {fmt_usd(revenue)}",
            "decision_use": f"Cash-conversion signal: {cash_conversion_signal}.",
        },
        {
            "driver": "FCF conversion",
            "value": None if conversion_requires_normalization else conversion_value,
            "display": "n/m - normalization required" if conversion_requires_normalization else multiple_label(conversion_value),
            "evidence": "FCF / net income if positive, otherwise FCF / operating income if positive.",
            "decision_use": (
                "Reported earnings denominator is negative or unusually depressed; reconcile impairments, working capital, and other non-cash items before judging durability."
                if conversion_requires_normalization
                else "Tests whether accounting earnings translate into cash."
            ),
        },
        {
            "driver": "Net debt / FCF",
            "value": leverage,
            "display": multiple_label(leverage),
            "evidence": f"Net debt before facility={fmt_usd(valuation.get('net_debt_before_facility'))}; LTM FCF={fmt_usd(valuation.get('ltm_fcf'))}",
            "decision_use": f"Balance-sheet signal: {balance_sheet_signal}.",
        },
    ]

    return {
        "annual_history": annual,
        "ytd_growth": ytd,
        "rows": rows,
        "revenue_growth_reference": revenue_growth,
        "cfo_growth_reference": cfo_growth,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "fcf_margin": fcf_margin,
        "fcf_conversion_net_income": fcf_conversion_net_income,
        "fcf_conversion_operating_income": fcf_conversion_operating_income,
        "conversion_requires_normalization": conversion_requires_normalization,
        "cash_conversion_signal": cash_conversion_signal,
        "balance_sheet_signal": balance_sheet_signal,
    }


def build_market_expectations(
    valuation: dict[str, Any],
    market_snapshot: dict[str, Any],
    opportunity: dict[str, Any],
    research_input: dict[str, Any] | None = None,
    evidence_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    research_input = research_input or {}
    supplied = research_input.get("market_expectations", {})
    price = safe_float(valuation.get("price"))
    high = safe_float(market_snapshot.get("fifty_two_week_high"))
    low = safe_float(market_snapshot.get("fifty_two_week_low"))
    if (high is None or low is None) and market_snapshot.get("history"):
        recent = market_snapshot["history"][-12:]
        closes = [safe_float(p.get("close")) for p in recent if safe_float(p.get("close")) is not None]
        if closes:
            high = max(closes)
            low = min(closes)

    range_position = None
    if price is not None and high is not None and low is not None and high != low:
        range_position = (price - low) / (high - low)

    p_fcf = valuation.get("p_fcf")
    pe = valuation.get("pe")
    ev_sales = valuation.get("ev_sales")
    relative_return = opportunity.get("relative_12m_return")

    indicators = [
        {
            "indicator": "P/FCF",
            "value": p_fcf,
            "display": multiple_label(p_fcf),
            "interpretation": "Trailing reported FCF multiple; it is not a sourced forecast or proof of what the market expects.",
            "evidence_type": "CALC",
            "source": "SEC LTM FCF plus Yahoo market price",
        },
        {
            "indicator": "P/E",
            "value": pe,
            "display": multiple_label(pe),
            "interpretation": "Trailing reported earnings multiple when positive net income is meaningful; normalization remains separate.",
            "evidence_type": "CALC",
            "source": "SEC LTM net income plus Yahoo market price",
        },
        {
            "indicator": "EV/Sales",
            "value": ev_sales,
            "display": multiple_label(ev_sales),
            "interpretation": "Trailing revenue multiple observation; it does not establish an appropriate exit multiple.",
            "evidence_type": "CALC",
            "source": "SEC revenue/debt/cash plus Yahoo market price",
        },
        {
            "indicator": "52-week range position",
            "value": range_position,
            "display": percent_label(range_position),
            "interpretation": "Historical price-range observation only. A high or low position does not establish whether recovery or deterioration is fully priced.",
            "evidence_type": "MARKET_PROXY",
            "source": market_snapshot.get("source_url"),
        },
        {
            "indicator": f"12-month relative return vs {SPY_TICKER}",
            "value": relative_return,
            "display": percent_label(relative_return),
            "interpretation": f"Adjusted-close return on exact common dates {opportunity.get('start_date') or 'n/a'} to {opportunity.get('end_date') or 'n/a'}; not a valuation conclusion.",
            "evidence_type": "MARKET_PROXY",
            "source": opportunity.get("benchmark_source_url"),
        },
    ]

    expectations_source = supplied.get("source", {})
    source_valid = (
        isinstance(expectations_source, dict)
        and expectations_source.get("source_level") in {2, 4}
        and bool(expectations_source.get("source_type"))
        and bool(expectations_source.get("source_name"))
        and bool(expectations_source.get("source_locator"))
        and valid_iso_date(expectations_source.get("publication_date"))
        and valid_iso_date(expectations_source.get("retrieval_date"))
    )
    consensus_sourced = (
        supplied.get("status") == "SOURCED"
        and source_valid
        and valid_iso_date(supplied.get("as_of_date"))
        and bool(supplied.get("summary"))
        and bool(supplied.get("reviewed_by"))
    )
    known_ids, key_to_id, metric_to_id = _evidence_maps(evidence_records or [])
    market_evidence_ids, market_unknown = resolve_evidence_references(
        supplied.get("market_evidence_ids", []),
        supplied.get("market_evidence_keys", []),
        known_ids,
        key_to_id,
        supplied.get("market_evidence_metrics", []),
        metric_to_id,
    )
    public_evidence_ids, public_unknown = resolve_evidence_references(
        supplied.get("public_evidence_ids", []),
        supplied.get("public_evidence_keys", []),
        known_ids,
        key_to_id,
        supplied.get("public_evidence_metrics", []),
        metric_to_id,
    )
    variant_evidence_ids, variant_unknown = resolve_evidence_references(
        supplied.get("variant_evidence_ids", []),
        supplied.get("variant_evidence_keys", []),
        known_ids,
        key_to_id,
        supplied.get("variant_evidence_metrics", []),
        metric_to_id,
    )
    disconfirming_evidence_ids, disconfirming_unknown = resolve_evidence_references(
        supplied.get("disconfirming_evidence_ids", []),
        supplied.get("disconfirming_evidence_keys", []),
        known_ids,
        key_to_id,
        supplied.get("disconfirming_evidence_metrics", []),
        metric_to_id,
    )
    current_public_evidence = supplied.get("current_public_evidence")
    potential_variant = supplied.get("potential_variant") or supplied.get("variant_perception")
    disconfirming_evidence = supplied.get("disconfirming_evidence")
    structured_unknown = market_unknown + public_unknown + variant_unknown + disconfirming_unknown
    variant_defined = consensus_sourced and all(
        (
            supplied.get("variant_question"),
            potential_variant,
            current_public_evidence,
            disconfirming_evidence,
            supplied.get("reviewed_by"),
            market_evidence_ids,
            public_evidence_ids,
            variant_evidence_ids,
            disconfirming_evidence_ids,
            not structured_unknown,
        )
    )
    summary_view = supplied.get("summary") if consensus_sourced else "Not Sourced. Trailing multiples and price history are observations, not a consensus substitute."
    variant_question = supplied.get("variant_question") if consensus_sourced else "Not Defined"

    validation_issues: list[dict[str, Any]] = []
    if supplied.get("status") == "SOURCED" and not consensus_sourced:
        validation_issues.append(
            {
                "check_id": "G2.5-market-expectations-input-integrity",
                "category": "market_expectations",
                "status": "FAIL",
                "issue_class": "HARD_STOP",
                "severity": "Critical",
                "message": "Market expectations were marked SOURCED but source hierarchy, dates, summary, or reviewer ownership is incomplete.",
                "decision_impact": "Consensus and variant-perception claims are not auditable and cannot unlock valuation outputs.",
                "remediation": "Provide a Level 2 or Level 4 source with name/type/locator/publication/retrieval dates, an as-of date, summary, and named reviewer.",
                "evidence_ids": [],
                "scope": "shared_investment_analysis_engine",
            }
        )
    elif consensus_sourced and not variant_defined:
        validation_issues.append(
            {
                "check_id": "G2.5-variant-perception-structure",
                "category": "market_expectations",
                "status": "WARNING",
                "issue_class": "WARNING",
                "severity": "P1",
                "message": f"Consensus is sourced, but structured variant perception or evidence links are incomplete. Unknown={structured_unknown}.",
                "decision_impact": "The report can show consensus, but cannot claim a differentiated investment view.",
                "remediation": "Provide market expectation, current public evidence, exact variant question, potential variant, disconfirming evidence, and evidence links for each component.",
                "evidence_ids": sorted(market_evidence_ids | public_evidence_ids | variant_evidence_ids | disconfirming_evidence_ids),
                "scope": "shared_investment_analysis_engine",
            }
        )

    return {
        "status": "SOURCED_AND_REVIEWED" if variant_defined else "SOURCED" if consensus_sourced else "OBSERVATIONS_ONLY",
        "consensus_status": "SOURCED" if consensus_sourced else "NOT_SOURCED",
        "variant_status": "ANALYST_DEFINED" if variant_defined else "NOT_DEFINED",
        "confidence": "High" if variant_defined else "Medium" if consensus_sourced else "Low",
        "summary_view": summary_view,
        "market_expectation": summary_view,
        "current_public_evidence": current_public_evidence if variant_defined else "Not Formed",
        "variant_question": variant_question,
        "variant_perception": potential_variant if variant_defined else "Not Formed",
        "potential_variant": potential_variant if variant_defined else "Not Formed",
        "disconfirming_evidence": disconfirming_evidence if variant_defined else "Not Formed",
        "market_evidence_ids": sorted(market_evidence_ids),
        "public_evidence_ids": sorted(public_evidence_ids),
        "variant_evidence_ids": sorted(variant_evidence_ids),
        "disconfirming_evidence_ids": sorted(disconfirming_evidence_ids),
        "variant_structure_status": "COMPLETE" if variant_defined else "INCOMPLETE",
        "source": expectations_source if consensus_sourced else None,
        "as_of_date": supplied.get("as_of_date") if consensus_sourced else None,
        "reviewed_by": supplied.get("reviewed_by") if consensus_sourced else None,
        "indicators": indicators,
        "validation_issues": validation_issues,
        "limitations": [
            "No consensus statement is created from price momentum, a 52-week range, or a trailing multiple.",
            "Trailing multiples do not reveal complete market expectations for growth, margins, cash conversion, or capital allocation.",
        ],
    }


def scenario_set(
    valuation: dict[str, Any],
    drivers: dict[str, Any],
    market_expectations: dict[str, Any],
    research_input: dict[str, Any] | None = None,
    share_count_basis: dict[str, Any] | None = None,
) -> tuple[list[Scenario], str]:
    """Build scenarios only from validated, analyst-owned assumptions.

    Historical growth, trailing multiples, price-range position, and leverage
    may inform research questions. They may not silently become scenario
    probabilities, exit multiples, target prices, or expected returns.
    """

    del drivers, market_expectations
    research_input = research_input or {}
    model = research_input.get("scenario_model", {})
    price = safe_float(valuation.get("price"))
    price_currency = str(valuation.get("price_currency") or "").upper()
    metric = str(model.get("metric") or "Normalized FCF").strip()
    metric_key = metric.upper()
    fcf_metric = metric_key in {
        "NORMALIZED FCF",
        "PUBLIC-DATA FCF UNDERWRITING BASE",
    }
    if fcf_metric:
        normalized_fcf = research_input.get("normalized_fcf", {})
        if normalized_fcf.get("status") != "VALIDATED":
            return [], "blocked_normalized_fcf_not_validated"
    if model.get("status") != "ANALYST_VALIDATED" or not model.get("reviewed_by"):
        return [], "blocked_scenario_assumptions_not_analyst_validated"
    if not metric:
        return [], "blocked_scenario_metric_not_defined"
    if fcf_metric:
        base_metric_value = safe_float(normalized_fcf.get("value"))
        base_metric_reviewer = normalized_fcf.get("reviewed_by")
        metric_currency = str(model.get("metric_currency") or price_currency).upper()
        metric_unit = str(model.get("metric_unit") or metric_currency).strip()
    else:
        metric_basis = (
            model.get("metric_basis", {})
            if isinstance(model.get("metric_basis"), dict)
            else {}
        )
        if (
            metric_basis.get("status") != "VALIDATED"
            or not metric_basis.get("reviewed_by")
            or not metric_basis.get("evidence_ids")
        ):
            return [], "blocked_scenario_metric_basis_not_validated"
        base_metric_value = safe_float(metric_basis.get("value"))
        base_metric_reviewer = metric_basis.get("reviewed_by")
        metric_currency = str(
            metric_basis.get("currency") or model.get("metric_currency") or ""
        ).upper()
        metric_unit = str(
            metric_basis.get("unit") or model.get("metric_unit") or ""
        ).strip()
    if (
        base_metric_value is None
        or base_metric_value <= 0
        or not base_metric_reviewer
    ):
        return [], "blocked_scenario_metric_basis_missing_or_nonpositive"
    if (
        not price_currency
        or not metric_currency
        or metric_currency != price_currency
        or not metric_unit
    ):
        return [], "blocked_scenario_metric_unit_or_currency_mismatch"

    share_count_basis = share_count_basis or {}
    shares = safe_float(
        share_count_basis.get("share_count_value")
        if share_count_basis.get("point_in_time_or_forward") == "FORWARD"
        and share_count_basis.get("forward_share_count_bridge_status") == "COMPLETED"
        else valuation.get("shares")
    )
    shares_date = str(
        share_count_basis.get("share_count_date")
        if share_count_basis.get("point_in_time_or_forward") == "FORWARD"
        and share_count_basis.get("forward_share_count_bridge_status") == "COMPLETED"
        else valuation.get("shares_as_of_date")
        or ""
    )
    valuation_contract_input = research_input.get("valuation_contract", {})
    if not isinstance(valuation_contract_input, dict):
        valuation_contract_input = {}
    forecast_period = normalize_valuation_period(
        valuation_contract_input.get("forecast_period")
    )
    metric_period = normalize_valuation_period(
        valuation_contract_input.get("metric_period")
    )
    assumptions = model.get("scenarios", [])
    if price is None or shares in (None, 0):
        return [], "blocked_missing_price_or_share_count"
    if len(assumptions) != 3 or {row.get("name") for row in assumptions} != {"Bear", "Base", "Bull"}:
        return [], "blocked_scenarios_must_include_bear_base_bull"
    current_multiple = safe_float(
        model.get("current_multiple")
        if model.get("current_multiple") is not None
        else valuation.get("p_fcf")
        if fcf_metric
        else None
    )
    scenarios: list[Scenario] = []
    for row in assumptions:
        name = str(row.get("name"))
        probability = safe_float(row.get("probability"))
        metric_value_total = safe_float(row.get("metric_value_total"))
        growth_assumption = safe_float(row.get("growth_assumption"))
        exit_multiple = safe_float(row.get("exit_multiple"))
        if metric_value_total is None or metric_value_total <= 0 or exit_multiple is None or exit_multiple <= 0:
            return [], f"blocked_invalid_{name.lower()}_metric_or_multiple"
        if growth_assumption is None:
            return [], f"blocked_missing_{name.lower()}_growth_assumption"
        if not row.get("key_driver") or not row.get("falsification_trigger"):
            return [], f"blocked_missing_{name.lower()}_driver_or_falsification_trigger"
        expected_metric_value = base_metric_value * (1 + growth_assumption)
        if abs(metric_value_total - expected_metric_value) > max(
            1.0,
            abs(metric_value_total) * 1e-9,
        ):
            return [], f"blocked_{name.lower()}_metric_growth_bridge_does_not_reconcile"
        metric_per_share = metric_value_total / shares
        target_price = metric_per_share * exit_multiple
        total_return = target_price / price - 1
        multiple_factor = exit_multiple / current_multiple if current_multiple not in (None, 0) else None
        scenarios.append(
            Scenario(
                name=name,
                probability=probability,
                metric=metric,
                metric_per_share=metric_per_share,
                growth_assumption=growth_assumption,
                exit_multiple_factor=multiple_factor,
                exit_multiple=exit_multiple,
                target_price=target_price,
                total_return=total_return,
                evidence_type="JUDGMENT",
                assumption_status="ANALYST_VALIDATED",
                confidence=str(row.get("confidence") or "Medium"),
                key_driver=str(row.get("key_driver") or "MISSING"),
                falsification_trigger=str(row.get("falsification_trigger") or "MISSING"),
                notes=str(row.get("notes") or ""),
                assumption_sources=[str(value) for value in row.get("assumption_sources", []) if value],
                probability_rationale=str(row.get("probability_rationale") or ""),
                share_count_basis_value=shares,
                share_count_basis_date=shares_date,
                forecast_period=forecast_period,
                metric_period=metric_period,
                metric_unit=metric_unit,
                metric_currency=metric_currency,
            )
        )
    return scenarios, "scenario_assumptions_validated"


def legacy_weighted_price_change(scenarios: list[Scenario]) -> float | None:
    """Retained only for unreachable deprecated render/action code."""

    usable = [s for s in scenarios if s.probability is not None and s.total_return is not None]
    if not usable:
        return None
    return sum((s.probability or 0.0) * (s.total_return or 0.0) for s in usable)


def weighted_implied_price(scenarios: list[Scenario]) -> float | None:
    usable = [
        scenario
        for scenario in scenarios
        if scenario.probability is not None and scenario.target_price is not None
    ]
    if not usable:
        return None
    return sum(
        float(scenario.probability) * float(scenario.target_price)
        for scenario in usable
    )


def build_opportunity_cost(market_snapshot: dict[str, Any], benchmark_snapshot: dict[str, Any]) -> dict[str, Any]:
    aligned = aligned_return_pair(
        market_snapshot.get("history", []),
        benchmark_snapshot.get("history", []),
        lookback_days=365,
    )
    stock_12m = aligned.get("stock_return")
    benchmark_12m = aligned.get("benchmark_return")
    return {
        "benchmark": SPY_TICKER,
        "stock_12m_return": stock_12m,
        "benchmark_12m_return": benchmark_12m,
        "relative_12m_return": aligned.get("relative_return"),
        "start_date": aligned.get("start_date"),
        "end_date": aligned.get("end_date"),
        "return_basis": aligned.get("return_basis"),
        "lookback_calendar_days": aligned.get("lookback_calendar_days"),
        "stock_start_adjusted_close": aligned.get("stock_start_adjusted_close"),
        "stock_end_adjusted_close": aligned.get("stock_end_adjusted_close"),
        "benchmark_start_adjusted_close": aligned.get("benchmark_start_adjusted_close"),
        "benchmark_end_adjusted_close": aligned.get("benchmark_end_adjusted_close"),
        "provider": benchmark_snapshot.get("provider"),
        "source_level": benchmark_snapshot.get("source_level", 5),
        "provider_approval_status": benchmark_snapshot.get("provider_approval_status", "NOT_APPROVED_BY_PARTNER"),
        "benchmark_source_url": benchmark_snapshot.get("source_url"),
        "status": aligned.get("status", "MISSING"),
        "reason": aligned.get("reason", ""),
    }


def load_research_input(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Research input must be a JSON object.")
    return payload


def valuation_input_is_structurally_complete(research_input: dict[str, Any]) -> bool:
    valuation_input = research_input.get("valuation_framework", {})
    reverse = valuation_input.get("reverse_valuation", {})
    sensitivity = valuation_input.get("sensitivity_table", [])
    supported_method = valuation_input.get("method") in {"EQUITY_FCF_MULTIPLE", "EQUITY_EARNINGS_MULTIPLE"}
    sensitivity_complete = (
        isinstance(sensitivity, list)
        and len(sensitivity) >= 3
        and all(
            safe_float(row.get("metric_value")) is not None
            and safe_float(row.get("multiple")) is not None
            and safe_float(row.get("implied_price")) is not None
            for row in sensitivity
            if isinstance(row, dict)
        )
        and all(isinstance(row, dict) for row in sensitivity)
    )
    return bool(
        valuation_input.get("status") == "VALIDATED"
        and supported_method
        and valuation_input.get("reviewed_by")
        and valuation_input.get("sensitivity_completed")
        and sensitivity_complete
        and reverse.get("status") == "VALIDATED"
        and reverse.get("formula") == "required_metric_value = market_cap / selected_multiple"
        and safe_float(reverse.get("selected_multiple")) not in (None, 0)
        and safe_float(reverse.get("required_metric_value")) is not None
        and reverse.get("assumptions")
        and bool(reverse.get("evidence_ids") or reverse.get("evidence_keys") or reverse.get("evidence_metrics"))
    )


def evidence_ids_for(step2: dict[str, Any], *metric_names: str) -> list[str]:
    wanted = set(metric_names)
    return [
        str(row.get("evidence_id"))
        for row in step2.get("evidence_records", step2.get("data_points", []))
        if row.get("metric_name") in wanted and row.get("evidence_id")
    ]


def valid_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def build_external_evidence(
    company: dict[str, Any],
    research_input: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize analyst-entered public evidence into the shared evidence schema."""

    supplied = research_input.get("external_evidence", [])
    if not isinstance(supplied, list):
        supplied = []
    records: list[dict[str, Any]] = []
    sources: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for index, row in enumerate(supplied, start=1):
        if not isinstance(row, dict) or not any(value not in (None, "", [], {}) for value in row.values()):
            continue
        external_key = str(row.get("external_key") or "").strip()
        source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
        try:
            source_level = int(source.get("source_level"))
        except (TypeError, ValueError):
            source_level = -1
        period_end = str(row.get("period_end") or "")
        as_of_date = str(row.get("as_of_date") or period_end)
        evidence_class = str(row.get("evidence_class") or "FACT").upper()
        required_valid = all(
            (
                external_key,
                row.get("metric_name"),
                row.get("unit"),
                row.get("reviewed_by"),
                source_level in {1, 2, 3, 4, 5},
                source.get("source_type"),
                source.get("source_name"),
                source.get("source_locator"),
                valid_iso_date(source.get("publication_date")),
                valid_iso_date(source.get("retrieval_date")),
                valid_iso_date(as_of_date),
                evidence_class in {"FACT", "INFERENCE"},
            )
        )
        duplicate_key = external_key in seen_keys
        if not required_valid or duplicate_key:
            issue_class = "HARD_STOP" if row.get("status") == "VALIDATED" else "WARNING"
            issues.append(
                {
                    "check_id": stable_id("VAL", company.get("ticker"), "external-evidence", index),
                    "category": "source_validation",
                    "status": "FAIL" if issue_class == "HARD_STOP" else "WARNING",
                    "issue_class": issue_class,
                    "severity": "Critical" if issue_class == "HARD_STOP" else "High",
                    "message": f"External evidence row {index} is incomplete or duplicates external_key={external_key!r}.",
                    "decision_impact": "The item cannot support issuer underwriting, market expectations, or valuation.",
                    "remediation": "Provide a unique external_key, metric/value/unit/as-of date, source level/type/name/locator/publication/retrieval dates, evidence class, and named reviewer.",
                    "evidence_ids": [],
                    "scope": "shared_data_and_evidence_engine",
                }
            )
            continue

        seen_keys.add(external_key)
        source_id = stable_id(
            "SRC",
            source_level,
            source.get("source_type"),
            source.get("source_name"),
            source.get("source_url", ""),
            source.get("source_locator"),
            source.get("publication_date"),
        )
        evidence_id = stable_id(
            "EV",
            company.get("ticker"),
            row.get("metric_name"),
            row.get("period_start", ""),
            period_end,
            as_of_date,
            external_key,
            source.get("source_locator"),
        )
        sources.setdefault(
            source_id,
            {
                "source_id": source_id,
                "source_level": source_level,
                "source_type": source.get("source_type"),
                "source_name": source.get("source_name"),
                "source_url": source.get("source_url", ""),
                "source_locator": source.get("source_locator"),
                "publication_date": source.get("publication_date"),
                "retrieval_date": source.get("retrieval_date"),
            },
        )
        records.append(
            {
                "evidence_id": evidence_id,
                "external_key": external_key,
                "metric_name": row.get("metric_name"),
                "value": row.get("value"),
                "unit": row.get("unit"),
                "currency": row.get("currency", ""),
                "scale": row.get("scale", 1.0),
                "period_start": row.get("period_start", ""),
                "period_end": period_end,
                "period_type": row.get("period_type", "instant"),
                "duration_days": row.get("duration_days", ""),
                "as_of_date": as_of_date,
                "measurement_basis": row.get("measurement_basis", "reported_or_sourced"),
                "fiscal_period": row.get("fiscal_period", ""),
                "filing_type": row.get("filing_type", ""),
                "publication_date": source.get("publication_date"),
                "retrieval_date": source.get("retrieval_date"),
                "source_level": source_level,
                "source_type": source.get("source_type"),
                "source_name": source.get("source_name"),
                "source_id": source_id,
                "source_locator": source.get("source_locator"),
                "source_location": source.get("source_locator"),
                "source_tag": external_key,
                "source_url": source.get("source_url", ""),
                "evidence_class": evidence_class,
                "evidence_type": evidence_class,
                "reported_or_calculated": "reported" if evidence_class == "FACT" else "analyst_inference",
                "formula": row.get("formula", ""),
                "input_evidence_ids": row.get("input_evidence_ids", []),
                "confidence": row.get("confidence", "Medium"),
                "validation_status": "PASS",
                "subsequent_event_status": row.get("subsequent_event_status", "NOT_APPLICABLE"),
                "reviewed_by": row.get("reviewed_by"),
                "notes": row.get("notes", ""),
            }
        )

    return records, sorted(sources.values(), key=lambda item: item["source_id"]), issues


def resolve_evidence_references(
    supplied_ids: list[Any],
    supplied_keys: list[Any],
    known_ids: set[str],
    key_to_id: dict[str, str],
    supplied_metrics: list[Any] | None = None,
    metric_to_id: dict[str, str] | None = None,
) -> tuple[set[str], list[str]]:
    ids = {str(value) for value in supplied_ids if value}
    keys = {str(value) for value in supplied_keys if value}
    metrics = {str(value) for value in supplied_metrics or [] if value}
    metric_map = metric_to_id or {}
    resolved = (
        ids
        | {key_to_id[key] for key in keys if key in key_to_id}
        | {metric_map[metric] for metric in metrics if metric in metric_map}
    )
    unknown = sorted(
        (ids - known_ids)
        | {f"external_key:{key}" for key in keys if key not in key_to_id}
        | {f"metric_name:{metric}" for metric in metrics if metric not in metric_map}
    )
    return resolved, unknown


def _evidence_maps(records: list[dict[str, Any]]) -> tuple[set[str], dict[str, str], dict[str, str]]:
    known_ids = {str(row.get("evidence_id")) for row in records if row.get("evidence_id")}
    key_to_id = {
        str(row.get("external_key")): str(row.get("evidence_id"))
        for row in records
        if row.get("external_key") and row.get("evidence_id")
    }
    metric_to_id = {
        str(row.get("metric_name")): str(row.get("evidence_id"))
        for row in records
        if row.get("metric_name") and row.get("evidence_id")
    }
    return known_ids, key_to_id, metric_to_id


def build_probability_validation(
    research_input: dict[str, Any],
    scenarios: list[Scenario],
    records: list[dict[str, Any]],
    analysis_date: str,
) -> dict[str, Any]:
    """Validate probability ownership separately from reproducible scenario prices."""

    supplied = research_input.get("probability_framework", {})
    if not isinstance(supplied, dict):
        supplied = {}
    scenario_probabilities = {scenario.name: scenario.probability for scenario in scenarios}
    probabilities_provided = any(value is not None for value in scenario_probabilities.values())
    base = {
        "status": "NOT_PROVIDED",
        "weighted_return_allowed": False,
        "method_type": None,
        "methodology": None,
        "method_details": {},
        "method_evidence_ids": [],
        "scenario_rationales": {},
        "as_of_date": None,
        "expiration_review_date": None,
        "freshness_status": "NOT_APPLICABLE",
        "review_triggers": [],
        "reviewed_by": None,
        "approval": {"status": "NOT_APPROVED", "approved_by": None},
        "sensitivity_table": [],
        "limitations": [],
        "validation_issues": [],
    }
    if not probabilities_provided:
        base["limitations"] = [
            "Scenario prices may be shown, but no probability-weighted return is available. / 可展示情景价格，但不提供概率加权回报。"
        ]
        return base

    method_type = str(supplied.get("method_type") or "").upper()
    methodology = str(supplied.get("methodology") or "").strip()
    method_details = supplied.get("method_details", {}) if isinstance(supplied.get("method_details"), dict) else {}
    required_details = PROBABILITY_METHOD_REQUIRED_DETAILS.get(method_type, set())
    method_text_is_substantive = bool(methodology) and methodology.lower() not in {
        "analyst judgment",
        "scenario judgment",
        "judgment",
    }
    method_valid = (
        method_type in PROBABILITY_METHOD_TYPES
        and method_text_is_substantive
        and all(method_details.get(key) not in (None, "", [], {}) for key in required_details)
    )

    known_ids, key_to_id, metric_to_id = _evidence_maps(records)
    evidence_ids, unknown_references = resolve_evidence_references(
        supplied.get("evidence_ids", []),
        supplied.get("evidence_keys", []),
        known_ids,
        key_to_id,
        supplied.get("evidence_metrics", []),
        metric_to_id,
    )

    rationales_input = supplied.get("scenario_rationales", {})
    rationales: dict[str, str] = {}
    if isinstance(rationales_input, dict):
        for name in ("Bear", "Base", "Bull"):
            value = rationales_input.get(name)
            if isinstance(value, dict):
                value = value.get("rationale")
            if value:
                rationales[name] = str(value)
    for scenario in scenarios:
        if scenario.probability_rationale and scenario.name not in rationales:
            rationales[scenario.name] = scenario.probability_rationale

    probability_values = list(scenario_probabilities.values())
    numeric_probabilities = [safe_float(value) for value in probability_values]
    probability_math_valid = (
        len(numeric_probabilities) == 3
        and all(value is not None and 0 <= value <= 1 for value in numeric_probabilities)
        and abs(sum(value or 0.0 for value in numeric_probabilities) - 1.0) <= 1e-9
    )

    as_of_date = supplied.get("as_of_date")
    expiration_date = supplied.get("probability_expiration_review_date")
    dates_valid = valid_iso_date(as_of_date) and valid_iso_date(expiration_date)
    freshness_status = "NOT_APPLICABLE"
    if dates_valid:
        analysis_day = date.fromisoformat(analysis_date) if valid_iso_date(analysis_date) else datetime.now(UTC).date()
        as_of_day = date.fromisoformat(str(as_of_date))
        expiration_day = date.fromisoformat(str(expiration_date))
        if expiration_day < as_of_day or analysis_day > expiration_day:
            freshness_status = "STALE"
        elif (expiration_day - analysis_day).days <= 30:
            freshness_status = "EXPIRING_SOON"
        else:
            freshness_status = "CURRENT"

        triggers = {str(value).upper() for value in supplied.get("review_triggers", []) if value}
        if "NEW_EARNINGS_OR_GUIDANCE" in triggers:
            later_material_dates = [
                str(row.get("publication_date"))
                for row in records
                if row.get("source_level") in {1, 2}
                and valid_iso_date(row.get("publication_date"))
                and str(row.get("publication_date")) > str(as_of_date)
            ]
            if later_material_dates:
                freshness_status = "SUPERSEDED"

    approval = supplied.get("approval", {}) if isinstance(supplied.get("approval"), dict) else {}
    approval_valid = approval.get("status") == "APPROVED" and bool(approval.get("approved_by"))
    reviewer_valid = bool(supplied.get("reviewed_by"))
    rationales_valid = all(rationales.get(name) for name in ("Bear", "Base", "Bull"))

    scenario_prices = {scenario.name: scenario.target_price for scenario in scenarios}
    sensitivity_table: list[dict[str, Any]] = []
    for row in supplied.get("sensitivity_cases", []):
        if not isinstance(row, dict):
            continue
        weights = row.get("probabilities", {}) if isinstance(row.get("probabilities"), dict) else {}
        numeric = {name: safe_float(weights.get(name)) for name in ("Bear", "Base", "Bull")}
        if any(value is None or value < 0 or value > 1 for value in numeric.values()):
            continue
        if abs(sum(value or 0.0 for value in numeric.values()) - 1.0) > 1e-9:
            continue
        if any(scenario_prices.get(name) is None for name in numeric):
            continue
        result = sum(
            (numeric[name] or 0.0) * (scenario_prices[name] or 0.0)
            for name in numeric
        )
        sensitivity_table.append(
            {
                "label": row.get("label") or f"Sensitivity {len(sensitivity_table) + 1}",
                "probabilities": numeric,
                "weighted_implied_price_sensitivity": result,
                "formal_weighted_expected_return": None,
                "formula": "sum(scenario_probability * scenario_implied_price)",
            }
        )
    sensitivity_valid = bool(method_details.get("sensitivity_completed")) and len(sensitivity_table) >= 3
    if method_type != "SCENARIO_JUDGMENT":
        sensitivity_valid = bool(supplied.get("sensitivity_completed", sensitivity_table))

    requested_status = str(supplied.get("status") or "ILLUSTRATIVE").upper()
    formal_valid = all(
        (
            requested_status == "VALIDATED",
            probability_math_valid,
            method_valid,
            bool(evidence_ids),
            not unknown_references,
            rationales_valid,
            dates_valid,
            freshness_status in {"CURRENT", "EXPIRING_SOON"},
            reviewer_valid,
            approval_valid,
            sensitivity_valid,
        )
    )
    if freshness_status in {"STALE", "SUPERSEDED"}:
        status = "STALE"
    elif formal_valid:
        status = "VALIDATED"
    elif requested_status == "VALIDATED":
        status = "INVALID"
    else:
        status = "ILLUSTRATIVE"

    limitations: list[str] = []
    if not method_valid:
        limitations.append("Probability method type, substantive methodology, or method-specific details are incomplete.")
    if not probability_math_valid:
        limitations.append("Scenario probabilities are missing, outside [0,1], or do not total 100%.")
    if not evidence_ids or unknown_references:
        limitations.append(f"Probability evidence is incomplete or unresolved: {unknown_references}.")
    if not rationales_valid:
        limitations.append("Bear, Base, and Bull probability rationales are incomplete.")
    if not dates_valid or freshness_status in {"STALE", "SUPERSEDED"}:
        limitations.append("Probability dates are invalid, expired, or superseded by later earnings/guidance evidence.")
    if not approval_valid:
        limitations.append("Named human approval has not been provided.")
    if not sensitivity_valid:
        limitations.append("Method-appropriate probability sensitivity has not been completed.")

    issues: list[dict[str, Any]] = []
    if status != "VALIDATED":
        issues.append(
            {
                "check_id": "G3-probability-methodology",
                "category": "scenario_probability",
                "status": "WARNING" if status in {"ILLUSTRATIVE", "STALE"} else "FAIL",
                "issue_class": "WARNING",
                "severity": "P1",
                "message": f"Probability status={status}; method={method_type or 'MISSING'}; freshness={freshness_status}.",
                "decision_impact": "Scenario prices remain available, but probability-weighted expected return is suppressed.",
                "remediation": "Provide a controlled method type, method-specific details, evidence, scenario rationales, review dates, sensitivity, and named human approval.",
                "evidence_ids": sorted(evidence_ids),
                "scope": "shared_investment_analysis_engine",
            }
        )

    return {
        "status": status,
        "weighted_return_allowed": status == "VALIDATED",
        "method_type": method_type or None,
        "methodology": methodology or None,
        "method_details": method_details,
        "method_evidence_ids": sorted(evidence_ids),
        "unknown_evidence_references": unknown_references,
        "scenario_rationales": rationales,
        "as_of_date": as_of_date,
        "expiration_review_date": expiration_date,
        "freshness_status": freshness_status,
        "review_triggers": supplied.get("review_triggers", []),
        "reviewed_by": supplied.get("reviewed_by"),
        "approval": {
            "status": approval.get("status", "NOT_APPROVED"),
            "approved_by": approval.get("approved_by"),
            "approval_date": approval.get("approval_date"),
        },
        "sensitivity_table": sensitivity_table,
        "limitations": limitations,
        "validation_issues": issues,
    }


def build_peer_valuation_context(
    research_input: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply metric-level comparability gates before any peer ranking."""

    supplied = research_input.get("peer_valuation_context", {})
    if not isinstance(supplied, dict):
        supplied = {}
    known_ids, key_to_id, metric_to_id = _evidence_maps(records)
    subject = supplied.get("subject", {}) if isinstance(supplied.get("subject"), dict) else {}
    subject_definitions = subject.get("metric_definitions", {}) if isinstance(subject.get("metric_definitions"), dict) else {}
    rows: list[dict[str, Any]] = []
    blocking_flags = {
        "negative_ebitda",
        "negative_fcf",
        "different_fiscal_period",
        "currency_mismatch",
        "accounting_definition_mismatch",
        "missing_denominator",
        "missing_evidence",
        "value_evidence_mismatch",
    }
    for peer in supplied.get("peers", []):
        if not isinstance(peer, dict):
            continue
        for metric in peer.get("metrics", []):
            if not isinstance(metric, dict):
                continue
            metric_name = str(metric.get("metric") or "").upper().replace(" ", "_")
            value = safe_float(metric.get("value"))
            denominator = safe_float(metric.get("denominator_value"))
            evidence_ids, unknown = resolve_evidence_references(
                metric.get("evidence_ids", []),
                metric.get("evidence_keys", []),
                known_ids,
                key_to_id,
                metric.get("evidence_metrics", []),
                metric_to_id,
            )
            flags: list[str] = []
            if not evidence_ids or unknown:
                flags.append("missing_evidence")
            evidence_values = [
                safe_float(row.get("value"))
                for row in records
                if row.get("evidence_id") in evidence_ids and safe_float(row.get("value")) is not None
            ]
            if value is not None and evidence_values and all(
                abs(value - evidence_value) > max(1e-9, abs(value) * 1e-6) for evidence_value in evidence_values
            ):
                flags.append("value_evidence_mismatch")
            if metric_name == "EV/EBITDA":
                if denominator is None:
                    flags.append("missing_denominator")
                elif denominator <= 0:
                    flags.append("negative_ebitda")
            if metric_name in {"P/FCF", "FCF_YIELD"}:
                if denominator is None:
                    flags.append("missing_denominator")
                elif denominator <= 0:
                    flags.append("negative_fcf")
            period_aligned = bool(metric.get("period_alignment_status") == "ALIGNED_LTM") or (
                metric.get("fiscal_period_end")
                and metric.get("fiscal_period_end") == subject.get("fiscal_period_end")
            )
            if not period_aligned:
                flags.append("different_fiscal_period")
            peer_currency = metric.get("currency") or peer.get("currency")
            subject_currency = subject.get("currency")
            if peer_currency and subject_currency and peer_currency != subject_currency and not metric.get("currency_normalized"):
                flags.append("currency_mismatch")
            expected_definition = subject_definitions.get(metric_name)
            if expected_definition and metric.get("accounting_definition") != expected_definition:
                flags.append("accounting_definition_mismatch")
            if peer.get("business_model_fit") == "LIMITED":
                flags.append("limited_business_model_fit")

            unique_flags = sorted(set(flags))
            if set(unique_flags).intersection(blocking_flags) or value is None:
                comparability = "NOT_COMPARABLE"
            elif "limited_business_model_fit" in unique_flags:
                comparability = "LIMITED"
            else:
                comparability = "COMPARABLE"
            rows.append(
                {
                    "ticker": peer.get("ticker"),
                    "company_name": peer.get("company_name"),
                    "industry_fit": peer.get("industry_fit"),
                    "metric": metric_name,
                    "value": value,
                    "denominator_value": denominator,
                    "fiscal_period_end": metric.get("fiscal_period_end"),
                    "currency": peer_currency,
                    "accounting_definition": metric.get("accounting_definition"),
                    "comparability_status": comparability,
                    "comparability_flags": unique_flags,
                    "auto_rank_allowed": comparability == "COMPARABLE",
                    "evidence_ids": sorted(evidence_ids),
                }
            )

    summaries: list[dict[str, Any]] = []
    for metric_name in sorted({row.get("metric") for row in rows if row.get("metric")}):
        usable = [row for row in rows if row.get("metric") == metric_name and row.get("auto_rank_allowed")]
        values = [safe_float(row.get("value")) for row in usable if safe_float(row.get("value")) is not None]
        summaries.append(
            {
                "metric": metric_name,
                "comparable_peer_count": len(values),
                "median": statistics.median(values) if len(values) >= 3 else None,
                "ranking_status": "AVAILABLE" if len(values) >= 3 else "SUPPRESSED_INSUFFICIENT_COMPARABLE_PEERS",
            }
        )
    validated = (
        supplied.get("status") == "VALIDATED"
        and bool(supplied.get("reviewed_by"))
        and bool(supplied.get("selection_rationale"))
        and bool(rows)
        and any(row.get("comparability_status") == "COMPARABLE" for row in rows)
    )
    issues: list[dict[str, Any]] = []
    if supplied.get("status") == "VALIDATED" and not validated:
        issues.append(
            {
                "check_id": "G3-peer-valuation-comparability",
                "category": "peer_valuation",
                "status": "WARNING",
                "issue_class": "WARNING",
                "severity": "P1",
                "message": "Peer context was marked VALIDATED but no auditable comparable row passed the forced-comparison controls.",
                "decision_impact": "Peer medians, rankings, and percentiles are suppressed; reverse valuation remains analyst-owned.",
                "remediation": "Align periods, currencies, and accounting definitions; exclude negative EBITDA/FCF denominators and link every value to evidence.",
                "evidence_ids": sorted({value for row in rows for value in row.get("evidence_ids", [])}),
                "scope": "shared_investment_analysis_engine",
            }
        )
    return {
        "status": "VALIDATED" if validated else "UNAVAILABLE",
        "as_of_date": supplied.get("as_of_date"),
        "selection_rationale": supplied.get("selection_rationale") if validated else "Peer valuation context unavailable or not sufficiently comparable.",
        "reviewed_by": supplied.get("reviewed_by") if validated else None,
        "subject": subject,
        "rows": rows,
        "metric_summaries": summaries,
        "historical_context": supplied.get("historical_context", {"status": "UNAVAILABLE"}),
        "interpretation": supplied.get("interpretation") if validated else "No peer-derived fair-value conclusion is permitted.",
        "limitations": supplied.get("limitations", []) + [
            "Negative EBITDA/FCF, period mismatch, currency mismatch, or accounting-definition mismatch prevents automatic ranking."
        ],
        "validation_issues": issues,
    }


def build_fcf_quality_assessment(
    research_input: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    supplied = research_input.get("fcf_quality_assessment", {})
    if not isinstance(supplied, dict):
        supplied = {}
    known_ids, key_to_id, metric_to_id = _evidence_maps(records)
    evidence_ids, unknown = resolve_evidence_references(
        supplied.get("evidence_ids", []),
        supplied.get("evidence_keys", []),
        known_ids,
        key_to_id,
        supplied.get("evidence_metrics", []),
        metric_to_id,
    )
    rating = supplied.get("rating")
    cash_confidence = supplied.get("cash_conversion_confidence")
    validated = all(
        (
            supplied.get("status") == "VALIDATED",
            rating in {"High", "Medium", "Low"},
            cash_confidence in {"High", "Medium", "Low"},
            bool(supplied.get("source_of_fcf")),
            bool(supplied.get("sustainability_assessment")),
            bool(supplied.get("conclusion")),
            bool(supplied.get("reviewed_by")),
            bool(evidence_ids),
            not unknown,
        )
    )
    issues: list[dict[str, Any]] = []
    if supplied.get("status") == "VALIDATED" and not validated:
        issues.append(
            {
                "check_id": "G2.5-fcf-quality-integrity",
                "category": "fcf_quality",
                "status": "WARNING",
                "issue_class": "WARNING",
                "severity": "P1",
                "message": f"FCF quality was marked VALIDATED but rating, durability analysis, reviewer, or evidence is incomplete. Unknown={unknown}.",
                "decision_impact": "Normalized FCF may be reproducible, but its durability cannot support a strong investment conclusion.",
                "remediation": "Classify the source of FCF, sustainability, cash-conversion confidence, limitations, and evidence without creating a new FCF number.",
                "evidence_ids": sorted(evidence_ids),
                "scope": "shared_investment_analysis_engine",
            }
        )
    if not validated:
        return {
            "status": "NOT_VALIDATED",
            "rating": "Not Evaluated",
            "cash_conversion_confidence": "Low",
            "source_of_fcf": [],
            "sustainability_assessment": "Not Evaluated",
            "conclusion": "FCF durability has not been analyst-validated.",
            "dimensions": [],
            "evidence_ids": sorted(evidence_ids),
            "limitations": ["Do not infer durable FCF from a normalized point estimate alone."],
            "evidence_class": "MISSING",
            "validation_issues": issues,
        }
    return {
        "status": "VALIDATED",
        "rating": rating,
        "cash_conversion_confidence": cash_confidence,
        "source_of_fcf": supplied.get("source_of_fcf", []),
        "sustainability_assessment": supplied.get("sustainability_assessment"),
        "conclusion": supplied.get("conclusion"),
        "dimensions": supplied.get("dimensions", []),
        "evidence_ids": sorted(evidence_ids),
        "limitations": supplied.get("limitations", []),
        "reviewed_by": supplied.get("reviewed_by"),
        "evidence_class": "JUDGMENT",
        "validation_issues": issues,
    }


PUBLIC_DATA_ACTIONS = PUBLIC_DATA_INVESTMENT_VIEWS


def build_investment_decision_summary(
    research_input: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    supplied = research_input.get("investment_decision_summary", {})
    if not isinstance(supplied, dict):
        supplied = {}
    known_ids, key_to_id, metric_to_id = _evidence_maps(records)
    evidence_ids, unknown = resolve_evidence_references(
        supplied.get("evidence_ids", []),
        supplied.get("evidence_keys", []),
        known_ids,
        key_to_id,
        supplied.get("evidence_metrics", []),
        metric_to_id,
    )
    validated = all(
        (
            supplied.get("status") == "VALIDATED",
            supplied.get("current_action") in PUBLIC_DATA_ACTIONS,
            bool(supplied.get("current_view")),
            bool(supplied.get("what_would_make_attractive")),
            bool(supplied.get("what_would_invalidate")),
            bool(supplied.get("what_to_monitor_next")),
            bool(supplied.get("reviewed_by")),
            bool(evidence_ids),
            not unknown,
        )
    )
    issues: list[dict[str, Any]] = []
    if supplied.get("status") == "VALIDATED" and not validated:
        issues.append(
            {
                "check_id": "G3-investment-decision-summary-integrity",
                "category": "decision_summary",
                "status": "WARNING",
                "issue_class": "WARNING",
                "severity": "P1",
                "message": f"Investment Decision Summary is incomplete or uses an unauthorized action label. Unknown={unknown}.",
                "decision_impact": "The report can show research workflow status but not a concise public-data investment action.",
                "remediation": "Use an allowed research action, measurable attractiveness/invalidation/monitoring conditions, evidence, and a named reviewer.",
                "evidence_ids": sorted(evidence_ids),
                "scope": "shared_investment_analysis_engine",
            }
        )
    if not validated:
        return {
            "status": "NOT_VALIDATED",
            "current_action": "Continue Research",
            "current_view": "The issuer-level research package is incomplete.",
            "what_would_make_attractive": [],
            "what_would_invalidate": [],
            "what_to_monitor_next": [],
            "evidence_ids": sorted(evidence_ids),
            "evidence_class": "MISSING",
            "validation_issues": issues,
        }
    return {
        "status": "VALIDATED",
        "current_action": supplied.get("current_action"),
        "current_view": supplied.get("current_view"),
        "what_would_make_attractive": supplied.get("what_would_make_attractive", []),
        "what_would_invalidate": supplied.get("what_would_invalidate", []),
        "what_to_monitor_next": supplied.get("what_to_monitor_next", []),
        "evidence_ids": sorted(evidence_ids),
        "reviewed_by": supplied.get("reviewed_by"),
        "evidence_class": "JUDGMENT",
        "validation_issues": issues,
    }


def _unique_text(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value not in (None, "")))


def _rewrite_incomplete_fcf_language(value: Any) -> Any:
    """Keep analytical narratives from overstating incomplete normalization."""

    if isinstance(value, dict):
        return {key: _rewrite_incomplete_fcf_language(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_incomplete_fcf_language(item) for item in value]
    if not isinstance(value, str):
        return value
    replacements = (
        ("Normalized FCF status=VALIDATED", "FCF underwriting-base calculation status=VALIDATED"),
        ("normalized FCF point estimate", "FCF underwriting-base point estimate"),
        ("what normalized FCF", "what FCF"),
        ("public-data normalization", "public-data underwriting bridge"),
        ("normalized amount", "FCF underwriting-base amount"),
        ("underestimating normalized FCF", "underestimating durable FCF"),
        ("validated normalized FCF base", "calculation-validated Public-Data FCF Underwriting Base"),
        ("validated normalized FCF", "calculation-validated Public-Data FCF Underwriting Base"),
        ("normalized FCF base", "Public-Data FCF Underwriting Base"),
        ("Normalized FCF", "Public-Data FCF Underwriting Base"),
        ("normalized FCF", "FCF underwriting base"),
        ("normalized cash generation", "durable cash generation"),
        ("normalized base", "FCF underwriting base"),
        ("已验证的标准化 FCF 基准", "经计算验证的公开数据FCF分析基准"),
        ("已验证标准化 FCF", "经计算验证的公开数据FCF分析基准"),
        ("已验证的公开数据标准化", "经计算验证的公开数据桥接"),
        ("标准化金额", "FCF分析基准金额"),
        ("低估了标准化 FCF", "低估了可持续FCF"),
        ("标准化 FCF", "FCF分析基准"),
        ("标准化FCF", "FCF分析基准"),
        ("标准化现金流", "可持续现金流"),
        ("标准化基准", "FCF分析基准"),
    )
    output = value
    for old, new in replacements:
        output = output.replace(old, new)
    return output


def _metric_record_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("metric_name")): row
        for row in contract.get("evidence_records", [])
        if row.get("metric_name")
    }


def _migrate_friday_v1_evidence_semantics(contract: dict[str, Any]) -> None:
    """Replace horizon-dependent names while preserving every raw evidence ID."""

    for scenario in contract.get("scenarios", []):
        if scenario.get("metric") == "Normalized FCF":
            scenario["metric"] = "Public-Data FCF Underwriting Base"
        scenario["assumption_sources"] = [
            "public_data_fcf_underwriting_base"
            if value == "normalized_fcf_analyst_validated"
            else value
            for value in scenario.get("assumption_sources", [])
        ]
        if "implied_price" not in scenario:
            scenario["implied_price"] = scenario.pop("target_price", None)
        else:
            scenario.pop("target_price", None)
        if "price_change_vs_current" not in scenario:
            scenario["price_change_vs_current"] = scenario.pop("total_return", None)
        else:
            scenario.pop("total_return", None)
        scenario["formula"] = (
            "implied_price = scenario_metric_value / share_count_basis * scenario_multiple; "
            "price_change_vs_current = implied_price / dated_market_price - 1"
        )

    for row in contract.get("evidence_records", []):
        metric_name = str(row.get("metric_name") or "")
        if metric_name == "normalized_fcf_analyst_validated":
            row["metric_name"] = "public_data_fcf_underwriting_base"
            row["measurement_basis"] = "public-data FCF underwriting bridge"
            row["notes"] = (
                "Calculation validation is separate from economic normalization status. "
                + str(row.get("notes") or "")
            ).strip()
        elif metric_name.endswith("_target_price"):
            row["metric_name"] = metric_name.removesuffix("_target_price") + "_implied_price"
            row["source_locator"] = str(row.get("source_locator") or "").replace("target price", "implied price")
            row["formula"] = str(row.get("formula") or "").replace("target_price", "implied_price")
        elif metric_name.startswith("scenario_") and metric_name.endswith("_total_return"):
            row["metric_name"] = metric_name.removesuffix("_total_return") + "_price_change_vs_current"
            row["source_locator"] = str(row.get("source_locator") or "").replace(
                "total return", "price change versus current price"
            )
            row["formula"] = (
                str(row.get("formula") or "")
                .replace("scenario_target_price", "scenario_implied_price")
                .replace("target_price", "implied_price")
            )


def build_share_count_basis(
    contract: dict[str, Any],
    research_input: dict[str, Any],
) -> dict[str, Any]:
    valuation = contract.get("valuation", {})
    supplied = research_input.get("share_count_basis", {})
    if not isinstance(supplied, dict):
        supplied = {}
    reported_value = safe_float(valuation.get("shares"))
    reported_date = str(valuation.get("shares_as_of_date") or "")
    price_date = str(valuation.get("price_date") or contract.get("report_dates", {}).get("market_price_date") or "")
    reported_source_detail = (
        valuation.get("shares_source", {})
        if isinstance(valuation.get("shares_source"), dict)
        else {}
    )
    reported_source = str(supplied.get("share_count_source") or "").strip()
    if not reported_source and reported_source_detail:
        reported_source = (
            f"{reported_source_detail.get('form') or 'SEC filing'} cover page, accession "
            f"{reported_source_detail.get('accn') or 'n/a'}, "
            f"filed {reported_source_detail.get('filed') or 'n/a'}"
        )
    known_event_status = str(supplied.get("known_subsequent_event_status") or "NOT_REVIEWED").upper()
    known_event_note = str(
        supplied.get("known_subsequent_event_note")
        or "No structured subsequent-event conclusion was supplied for the share-count basis."
    )
    limitations = list(supplied.get("limitations", []))
    requested_forward_status = str(
        supplied.get("forward_share_count_bridge_status") or "NOT_COMPLETED"
    ).upper()
    if requested_forward_status not in {"MISSING", "NOT_COMPLETED", "PROVISIONAL", "COMPLETED"}:
        requested_forward_status = "NOT_COMPLETED"
    forward_value = safe_float(supplied.get("forward_share_count_value"))
    forward_date = str(supplied.get("forward_share_count_date") or "")
    forward_source = str(supplied.get("forward_share_count_source") or "").strip()
    forward_reviewer = str(supplied.get("reviewed_by") or "").strip()
    forward_evidence_ids = sorted(
        {
            str(value)
            for value in supplied.get("forward_share_count_evidence_ids", [])
            if value
        }
    )
    known_evidence_ids = {
        str(row.get("evidence_id"))
        for row in contract.get("evidence_records", [])
        if row.get("evidence_id")
    }
    forward_complete = (
        requested_forward_status == "COMPLETED"
        and forward_value is not None
        and forward_value > 0
        and valid_iso_date(forward_date)
        and bool(forward_source)
        and bool(forward_reviewer)
        and bool(forward_evidence_ids)
        and set(forward_evidence_ids).issubset(known_evidence_ids)
        and known_event_status
        in {"REVIEWED_NO_QUANTIFIED_CHANGE", "REVIEWED_CHANGE_REFLECTED"}
    )
    forward_status = "COMPLETED" if forward_complete else requested_forward_status
    if requested_forward_status == "COMPLETED" and not forward_complete:
        forward_status = "NOT_COMPLETED"
        limitations.append(
            "A COMPLETED forward share bridge requires a positive forward share count, ISO date, "
            "source, linked evidence, named reviewer, and completed subsequent-event review. / "
            "COMPLETED前瞻股数桥必须包含正数股数、ISO日期、来源、关联证据、具名复核人及"
            "已完成的后续事项复核。"
        )
    share_value = forward_value if forward_complete else reported_value
    share_date = forward_date if forward_complete else reported_date
    source_text = forward_source if forward_complete else reported_source
    source_detail = (
        supplied.get("forward_share_count_source_detail", {})
        if forward_complete and isinstance(supplied.get("forward_share_count_source_detail"), dict)
        else reported_source_detail
    )
    basis_type = "FORWARD" if forward_complete else "POINT_IN_TIME"
    proxy_status = "CURRENT" if share_date == price_date or forward_complete else "PROXY"
    if proxy_status == "PROXY":
        limitations.append(
            "The share-count date differs from the dated market price and no validated forward share-count bridge is complete. / "
            "股数日期与市场价格日期不同，且尚未完成经验证的前瞻股数桥接。"
        )
    metric_map = _metric_record_map(contract)
    share_record = metric_map.get("shares_outstanding_point_in_time", {})
    evidence_ids = (
        forward_evidence_ids
        if forward_complete
        else ([share_record.get("evidence_id")] if share_record.get("evidence_id") else [])
    )
    return {
        "status": "PROVISIONAL" if proxy_status == "PROXY" else "COMPLETED",
        "share_count_value": share_value,
        "share_count_date": share_date,
        "share_count_type": str(supplied.get("share_count_type") or "COMMON_SHARES_OUTSTANDING"),
        "share_count_source": source_text,
        "share_count_source_detail": source_detail,
        "point_in_time_or_forward": basis_type,
        "proxy_status": proxy_status,
        "forward_share_count_bridge_status": forward_status,
        "known_subsequent_event_status": known_event_status,
        "known_subsequent_event_note": known_event_note,
        "market_price_date": price_date,
        "per_share_output_label": "PROXY" if proxy_status == "PROXY" else "CURRENT",
        "evidence_ids": evidence_ids,
        "latest_reported_share_count": {
            "value": reported_value,
            "date": reported_date,
            "source": reported_source,
            "evidence_ids": [share_record.get("evidence_id")] if share_record.get("evidence_id") else [],
        },
        "forward_share_count_bridge": {
            "status": forward_status,
            "value": forward_value if forward_complete else None,
            "date": forward_date if forward_complete else None,
            "source": forward_source if forward_complete else None,
            "evidence_ids": forward_evidence_ids if forward_complete else [],
            "reviewed_by": forward_reviewer if forward_complete else None,
        },
        "limitations": _unique_text(limitations),
    }


def build_fcf_underwriting_base(
    contract: dict[str, Any],
    research_input: dict[str, Any],
) -> dict[str, Any]:
    supplied = research_input.get("normalized_fcf", {})
    if not isinstance(supplied, dict):
        supplied = {}
    metric_map = _metric_record_map(contract)
    base_record = metric_map.get("public_data_fcf_underwriting_base", {})
    bridge_lines = list(supplied.get("bridge_lines", []))
    normalization_status = str(supplied.get("normalization_status") or "").upper()
    if normalization_status not in FCF_NORMALIZATION_STATUSES:
        normalization_status = "PARTIALLY_NORMALIZED" if bridge_lines else "UNADJUSTED_PUBLIC_BASE"
    quality = contract.get("fcf_quality_assessment", {})
    unresolved_items = list(supplied.get("normalization_unresolved_items", []))
    if not unresolved_items:
        unresolved_items = list(quality.get("limitations", []))
    return {
        "status": supplied.get("status", "NOT_VALIDATED"),
        "value": safe_float(supplied.get("value")),
        "period_end": supplied.get("period_end"),
        "source_data_validation_status": "VALIDATED" if contract.get("validation_status") != "FAIL" else "FAILED",
        "calculation_validation_status": (
            "VALIDATED" if supplied.get("status") == "VALIDATED" and base_record.get("evidence_id") else "NOT_VALIDATED"
        ),
        "normalization_status": normalization_status,
        "economic_normalization_complete": normalization_status == "FULLY_NORMALIZED",
        "normalization_scope": supplied.get("normalization_scope")
        or "Public-data LTM FCF underwriting base for scenario price sensitivity; not a durable forward forecast.",
        "bridge_lines": bridge_lines,
        "no_adjustments_rationale": supplied.get("no_adjustments_rationale", ""),
        "unresolved_items": _unique_text(unresolved_items),
        "confidence": supplied.get("confidence", "Low"),
        "reviewed_by": supplied.get("reviewed_by"),
        "evidence_ids": [base_record.get("evidence_id")] if base_record.get("evidence_id") else [],
    }


def build_valuation_scope_status(
    contract: dict[str, Any],
    research_input: dict[str, Any],
    share_count_basis: dict[str, Any],
    return_context: dict[str, Any],
) -> dict[str, Any]:
    supplied = research_input.get("valuation_completion", {})
    if not isinstance(supplied, dict):
        supplied = {}
    peer_status = "COMPLETED" if contract.get("peer_valuation_context", {}).get("status") == "VALIDATED" else "NOT_COMPLETED"
    historical_raw = contract.get("peer_valuation_context", {}).get("historical_context", {}).get("status")
    components = {
        "peer_valuation": peer_status,
        "historical_valuation": "COMPLETED" if historical_raw == "VALIDATED" else "NOT_COMPLETED",
        "dcf_cross_check": str(supplied.get("dcf_cross_check") or "NOT_COMPLETED").upper(),
        "driver_based_forward_forecast": str(
            supplied.get("driver_based_forward_forecast") or "NOT_COMPLETED"
        ).upper(),
        "forward_share_count_bridge": share_count_basis.get("forward_share_count_bridge_status", "NOT_COMPLETED"),
    }
    allowed_components = {"MISSING", "NOT_COMPLETED", "PROVISIONAL", "COMPLETED"}
    components = {
        key: value if value in allowed_components else "NOT_COMPLETED"
        for key, value in components.items()
    }
    completed = sum(value == "COMPLETED" for value in components.values())
    if return_context.get("formal_return_language_allowed") and completed == len(components):
        status = "MULTI_METHOD_VALIDATED"
    elif components["driver_based_forward_forecast"] == "COMPLETED" and completed >= 2:
        status = "PARTIALLY_VALIDATED"
    else:
        status = "RANGE_ONLY"
    multiples = sorted(
        {
            float(value)
            for value in (safe_float(row.get("exit_multiple")) for row in contract.get("scenarios", []))
            if value is not None
        }
    )
    multiple_text = ", ".join(f"{value:g}x" for value in multiples) or "the displayed"
    return {
        "status": status,
        "calculation_framework_status": contract.get("valuation_framework", {}).get("status", "NOT_VALIDATED"),
        "components": components,
        "selected_multiple_status": "ANALYST_OWNED_REFERENCE",
        "scenario_multiple_set": multiples,
        "disclosure": (
            f"The selected {multiple_text} multiples are analyst-owned sensitivity references. "
            "They are not validated fair-value multiples. / "
            f"所选{multiple_text}倍数为分析师设定的敏感性参考，并非经验证的公允价值倍数。"
        ),
        "limitations": [
            "Independent peer, historical, DCF, driver-based forecast, and forward share-count support remain incomplete where marked NOT_COMPLETED. / "
            "标记为NOT_COMPLETED的同业、历史估值、DCF、驱动型预测及前瞻股数支持尚未完成。"
        ],
    }


def build_what_is_priced_in(
    contract: dict[str, Any],
    research_input: dict[str, Any],
    fcf_base: dict[str, Any],
) -> dict[str, Any]:
    metric_map = _metric_record_map(contract)
    reverse = contract.get("valuation_framework", {}).get("reverse_valuation", {})
    multiple = safe_float(reverse.get("selected_multiple"))
    required = safe_float(reverse.get("required_metric_value"))
    base = safe_float(fcf_base.get("value"))
    supplied = research_input.get("what_is_priced_in", {})
    if not isinstance(supplied, dict):
        supplied = {}
    if multiple is None or required is None or base in (None, 0):
        return {
            "status": "NOT_VALIDATED",
            "multiple_status": "ANALYST_OWNED_REFERENCE",
            "conditional_conclusion": "Not Evaluated / 未评估",
            "evidence_ids": [],
        }
    gap = required - base
    gap_percent = gap / base
    if gap > 0:
        direction_en = "above"
        direction_zh = "高出"
        implication_en = "the dated price requires operating and cash-flow improvement beyond the public-data base"
        implication_zh = "时点价格要求经营与现金流改善超过公开数据基准"
    else:
        direction_en = "below"
        direction_zh = "低于"
        implication_en = "the public-data base exceeds the FCF required by this conditional reference"
        implication_zh = "公开数据基准高于该条件性参考所需的FCF"
    conclusion = (
        f"At the analyst-owned {multiple:g}x sensitivity reference, the dated market capitalization requires "
        f"approximately USD {required / 1_000_000:,.3f} million of FCF, {abs(gap_percent) * 100:,.1f}% {direction_en} "
        f"the Public-Data FCF Underwriting Base of USD {base / 1_000_000:,.3f} million; {implication_en}. "
        "This conclusion is conditional on the selected reference multiple and is not a fair-value claim. / "
        f"按分析师设定的{multiple:g}倍敏感性参考，时点市值要求约{required / 100_000_000:,.3f}亿元FCF，"
        f"较{base / 100_000_000:,.3f}亿元的公开数据FCF分析基准{direction_zh}{abs(gap_percent) * 100:,.1f}%；"
        f"{implication_zh}。该结论取决于所选参考倍数，并非公允价值判断。"
    )
    evidence_ids = [
        metric_map.get(name, {}).get("evidence_id")
        for name in (
            "market_price_unadjusted_close",
            "market_cap_point_in_time",
            "public_data_fcf_underwriting_base",
            "reverse_valuation_selected_multiple",
            "reverse_valuation_required_metric_value",
        )
    ]
    evidence_ids.extend(contract.get("market_expectations", {}).get("market_evidence_ids", []))
    return {
        "status": "VALIDATED",
        "selected_multiple": multiple,
        "multiple_status": "ANALYST_OWNED_REFERENCE",
        "required_fcf": required,
        "fcf_underwriting_base": base,
        "difference": gap,
        "difference_percent": gap_percent,
        "conditional_conclusion": conclusion,
        "risk_interpretation": supplied.get("risk_interpretation")
        or "The apparent requirement or discount must be tested against management guidance, consensus, cash-flow durability, liquidity, and dilution. / "
        "表面要求或折价仍须结合管理层指引、一致预期、现金流可持续性、流动性与稀释进行检验。",
        "formula": "required_fcf = dated_market_cap / analyst_owned_reference_multiple; difference = required_fcf - public_data_fcf_underwriting_base",
        "evidence_ids": _unique_text(evidence_ids),
        "evidence_class": "CALC_AND_INFERENCE",
    }


def build_evidence_presentation(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = sorted(
        contract.get("evidence_records", []),
        key=lambda row: (
            int(row.get("source_level", 99)),
            str(row.get("metric_name") or ""),
            str(row.get("period_end") or row.get("as_of_date") or ""),
            str(row.get("evidence_id") or ""),
        ),
    )
    display_index = [
        {"display_id": f"E{index:03d}", "evidence_id": row.get("evidence_id")}
        for index, row in enumerate(records, start=1)
        if row.get("evidence_id")
    ]
    alias_by_id = {row["evidence_id"]: row["display_id"] for row in display_index}
    record_by_id = {str(row.get("evidence_id")): row for row in records if row.get("evidence_id")}
    metric_map = _metric_record_map(contract)

    def section_ids(section: dict[str, Any], fields: tuple[str, ...] = ("evidence_ids",)) -> list[str]:
        output: list[Any] = []
        for field in fields:
            output.extend(section.get(field, []) if isinstance(section.get(field), list) else [])
        return _unique_text(output)

    debate_ids: list[str] = []
    for debate in contract.get("key_debates", []):
        debate_ids.extend(debate.get("market_evidence_ids", []))
        debate_ids.extend(debate.get("alternative_evidence_ids", []))
    scenario_ids: list[str] = []
    for scenario in contract.get("scenarios", []):
        scenario_ids.extend(scenario.get("evidence_ids", []))
    liquidity_ids: list[str] = []
    modules = contract.get("issuer_underwriting", {}).get("modules", {})
    for name in ("liquidity_sources_and_uses", "debt_leases_covenants_refinancing", "stress_test"):
        liquidity_ids.extend(modules.get(name, {}).get("evidence_ids", []))
    market_fields = (
        "market_evidence_ids",
        "public_evidence_ids",
        "variant_evidence_ids",
        "disconfirming_evidence_ids",
    )
    metric_ids = lambda names: [metric_map.get(name, {}).get("evidence_id") for name in names]
    definitions = [
        (
            "B1",
            "executive_view",
            "Executive view and priced-in test / 核心观点与定价检验",
            section_ids(contract.get("investment_decision_summary", {}))
            + section_ids(contract.get("what_is_priced_in", {})),
        ),
        ("B2", "key_debates", "Key debates / 核心争议", debate_ids),
        (
            "B3",
            "fcf_underwriting_base",
            "FCF underwriting base and quality / FCF分析基准与质量",
            section_ids(contract.get("fcf_quality_assessment", {}))
            + metric_ids(["reported_ltm_fcf", "public_data_fcf_underwriting_base"]),
        ),
        ("B4", "liquidity_credit", "Liquidity, debt and refinancing / 流动性、债务与再融资", liquidity_ids),
        (
            "B5",
            "valuation_market",
            "Market expectations and valuation sensitivity / 市场预期与估值敏感性",
            section_ids(contract.get("market_expectations", {}), market_fields)
            + metric_ids(
                [
                    "market_price_unadjusted_close",
                    "shares_outstanding_point_in_time",
                    "market_cap_point_in_time",
                    "reverse_valuation_selected_multiple",
                    "reverse_valuation_required_metric_value",
                ]
            ),
        ),
        ("B6", "scenario_sensitivity", "Scenario price sensitivity / 情景价格敏感性", scenario_ids),
    ]
    bundles: list[dict[str, Any]] = []
    for bundle_id, section_key, label, raw_ids in definitions:
        evidence_ids = [value for value in _unique_text(raw_ids) if value in record_by_id]
        if not evidence_ids:
            continue
        source_ids = _unique_text(record_by_id[value].get("source_id") for value in evidence_ids)
        bundles.append(
            {
                "bundle_id": bundle_id,
                "section_key": section_key,
                "label": label,
                "status": "COMPLETE",
                "evidence_ids": evidence_ids,
                "display_ids": [alias_by_id[value] for value in evidence_ids],
                "source_ids": source_ids,
                "record_count": len(evidence_ids),
            }
        )
    return display_index, bundles


def apply_friday_v1_contract_semantics(
    contract: dict[str, Any],
    research_input: dict[str, Any],
) -> dict[str, Any]:
    """Apply shared Friday V1 decision-boundary semantics to any company contract."""

    contract.pop("contract_hash", None)
    contract.pop("contract_validation", None)
    prior_report_id = str(contract.get("report_id") or "")
    if contract.get("schema_version") != SCHEMA_VERSION:
        contract["prior_report_id"] = prior_report_id
        contract["report_id"] = stable_id("RPT", prior_report_id, SCHEMA_VERSION)
    _migrate_friday_v1_evidence_semantics(contract)

    summary = contract.get("investment_decision_summary", {})
    action_map = {
        "Investment Case Strengthening": "Case Strengthening",
        "Investment Case Weakening": "Case Weakening",
    }
    public_view = action_map.get(str(summary.get("current_action")), str(summary.get("current_action") or "Continue Research"))
    summary["current_action"] = public_view
    contract["investment_decision_summary"] = summary

    gate_level = float(contract.get("data_gate", {}).get("level", 0))
    if contract.get("hard_stops") or gate_level < 1:
        workflow_status = "Data Review Required"
    elif gate_level >= 3:
        workflow_status = "Ready for Human Review"
    else:
        workflow_status = "Underwriting In Progress"

    share_basis = build_share_count_basis(contract, research_input)
    contract["share_count_basis"] = share_basis
    valuation_contract = build_shared_valuation_contract(
        contract,
        research_input.get("valuation_contract", {}),
    )
    return_context = legacy_return_context(valuation_contract)
    fcf_base = build_fcf_underwriting_base(contract, research_input)
    if fcf_base.get("normalization_status") != "FULLY_NORMALIZED":
        for field in (
            "investment_question",
            "key_debates",
            "core_investment_view",
            "public_data_conclusion",
            "issuer_underwriting",
            "market_expectations",
            "fcf_quality_assessment",
            "investment_decision_summary",
            "scenarios",
            "valuation_framework",
            "decision_rules",
            "catalysts",
            "thesis_breaks",
            "validation_gates",
            "committee",
            "validation_issues",
            "warnings",
            "missing_information",
        ):
            if field in contract:
                contract[field] = _rewrite_incomplete_fcf_language(contract[field])
    valuation_status = build_valuation_scope_status(contract, research_input, share_basis, return_context)
    priced_in = build_what_is_priced_in(contract, research_input, fcf_base)

    probability = contract.get("probability_validation", {})
    formal_weighted_allowed = (
        valuation_contract.get("outputs", {})
        .get("probability_weighted_return", {})
        .get("status")
        == "VALIDATED"
    )
    probability["weighted_return_allowed"] = formal_weighted_allowed
    probability["formal_probability_weighted_expected_return_status"] = (
        "VALIDATED" if formal_weighted_allowed else "NOT_EVALUATED"
    )
    for row in probability.get("sensitivity_table", []):
        row.pop("probability_weighted_return", None)
        row["formal_weighted_expected_return"] = None
        if not return_context.get("formal_return_language_allowed"):
            row["formula"] = (
                "sum(scenario_probability * scenario_implied_price); "
                "formal expected return not evaluated without a horizon"
            )
    contract["probability_validation"] = probability

    confidence = determine_decision_confidence(
        gate_level=gate_level,
        issues=contract.get("validation_issues", []),
        investment_question_defined=contract.get("investment_question", {}).get("status") == "ANALYST_DEFINED",
        critical_assumptions_transparent=(
            contract.get("valuation_framework", {}).get("status") == "VALIDATED"
            and contract.get("scenario_status") == "scenario_assumptions_validated"
        ),
        disconfirming_evidence_considered=(
            contract.get("market_expectations", {}).get("variant_structure_status") == "COMPLETE"
        ),
    )
    if fcf_base.get("normalization_status") != "FULLY_NORMALIZED":
        confidence["constraints"].append(
            f"FCF Normalization Status is {fcf_base.get('normalization_status')}; economic durability remains incomplete. / "
            f"FCF标准化状态为{fcf_base.get('normalization_status')}，经济可持续性尚未完整验证。"
        )
    if valuation_status.get("status") == "RANGE_ONLY":
        confidence["constraints"].append(
            "Valuation Status is RANGE_ONLY; independent valuation methods and a forward operating model are incomplete. / "
            "估值状态为RANGE_ONLY，独立估值方法与前瞻经营模型尚未完成。"
        )
    if share_basis.get("proxy_status") == "PROXY":
        confidence["constraints"].append(
            "Per-share sensitivities use a point-in-time share-count proxy. / 每股敏感性使用时点股数proxy。"
        )
    if probability.get("status") != "VALIDATED":
        confidence["constraints"].append(
            "Scenario probabilities are not formally validated and no weighted expected return is available. / "
            "情景概率尚未正式验证，不提供概率加权预期回报。"
        )
    confidence["constraints"] = _unique_text(confidence["constraints"])

    valuation_outputs = valuation_contract.get("outputs", {})
    base_return_validated = valuation_outputs.get("base_case_return", {}).get("status") == "VALIDATED"
    weighted_return_validated = (
        valuation_outputs.get("probability_weighted_return", {}).get("status") == "VALIDATED"
    )
    what_can_be_concluded = [
        "Whether the issuer deserves further research under the current public-data evidence set. / 当前公开证据下发行人是否值得继续研究。",
        "What operating and cash-flow outcome is required by the dated market valuation under the analyst-owned reference multiple. / 在分析师设定的参考倍数下，时点市场估值要求何种经营与现金流结果。",
        "The reproducible Bear, Base, and Bull scenario price-sensitivity range. / 可复算的悲观、基准与乐观情景价格敏感性区间。",
    ]
    if base_return_validated:
        what_can_be_concluded.append(
            "The dated Base-Case Return under the validated public valuation horizon. / 经验证公开估值时间口径下的基准情景回报。"
        )
    if weighted_return_validated:
        what_can_be_concluded.append(
            "The public-data Probability-Weighted Return under approved and current scenario probabilities. / 经审批且仍有效的情景概率下，公开数据概率加权回报。"
        )
    what_cannot_be_concluded = [
        "Whether the fund should buy or sell the security. / 基金是否应买入或卖出该证券。",
        "Position size, portfolio weight, risk budget, or opportunity-cost ranking. / 仓位、组合权重、风险预算或机会成本排名。",
        "Partner Internal Return or a portfolio action without the private Gate 4 overlay. / 缺少私有Gate 4叠加层时的Partner内部回报或组合动作。",
    ]
    if not base_return_validated:
        what_cannot_be_concluded.append(
            "A formal Base-Case Return until the complete dated valuation horizon validates. / 完整估值时间口径通过验证前的正式基准情景回报。"
        )
    if not weighted_return_validated:
        what_cannot_be_concluded.append(
            "A formal Probability-Weighted Return until both the horizon and probability governance validate. / 估值时间口径与概率治理均通过前的正式概率加权回报。"
        )

    contract.update(
        {
            "product_positioning": "Public-Data Issuer Underwriting and IC Pre-Read System - Friday V1",
            "research_workflow_status": workflow_status,
            "public_data_investment_view": public_view,
            "decision_confidence": confidence,
            "valuation_contract": valuation_contract,
            "return_context": return_context,
            "fcf_underwriting_base": fcf_base,
            "normalized_fcf_status": fcf_base,
            "valuation_status": valuation_status,
            "share_count_basis": share_basis,
            "what_is_priced_in": priced_in,
            "current_action": workflow_status,
            "current_action_rationale": (
                "Research readiness measures whether issuer-level analysis is ready for human review. "
                "It does not measure investment attractiveness and does not authorize a trade."
            ),
            "probability_weighted_expected_return": None,
            "probability_weighted_return": None,
            "target_price": None,
            "final_investment_action": "Not Evaluated",
            "portfolio_action": "Not Evaluated",
            "position_sizing": None,
            "what_can_be_concluded": what_can_be_concluded,
            "what_cannot_be_concluded": what_cannot_be_concluded,
        }
    )
    contract.setdefault("report_dates", {})["analysis_generated_at"] = utc_now()
    contract["build_date"] = utc_now()
    display_index, bundles = build_evidence_presentation(contract)
    contract["evidence_display_index"] = display_index
    contract["evidence_bundles"] = bundles
    return contract


def build_investment_question(research_input: dict[str, Any]) -> dict[str, Any]:
    supplied = research_input.get("investment_question", {})
    text = str(supplied.get("text") or "").strip()
    analyst_defined = supplied.get("status") == "ANALYST_DEFINED" and bool(text) and bool(supplied.get("reviewed_by"))
    return {
        "text": text if analyst_defined else "Not Defined",
        "status": "ANALYST_DEFINED" if analyst_defined else "NOT_DEFINED",
        "evidence_class": "JUDGMENT" if analyst_defined else "MISSING",
        "reviewed_by": supplied.get("reviewed_by") if analyst_defined else None,
        "decision_supported": supplied.get("decision_supported") if analyst_defined else "Research scope must be defined before a strong conclusion.",
    }


def build_key_debates(
    step2: dict[str, Any],
    research_input: dict[str, Any],
    additional_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    supplied = research_input.get("key_debates", [])
    required = {
        "title",
        "market_view",
        "alternative_view",
        "market_evidence_ids",
        "alternative_evidence_ids",
        "missing_evidence",
        "resolution_kpi_or_event",
        "decision_impact",
        "reviewed_by",
    }
    all_records = list(step2.get("evidence_records", step2.get("data_points", []))) + list(additional_records or [])
    known_ids = {
        row.get("evidence_id")
        for row in all_records
        if row.get("evidence_id")
    }
    key_to_id = {str(row.get("external_key")): str(row.get("evidence_id")) for row in all_records if row.get("external_key")}
    metric_to_id = {
        str(row.get("metric_name")): str(row.get("evidence_id"))
        for row in all_records
        if row.get("metric_name") and row.get("evidence_id")
    }
    validated: list[dict[str, Any]] = []
    if isinstance(supplied, list) and 2 <= len(supplied) <= 3:
        for index, debate in enumerate(supplied, start=1):
            if not isinstance(debate, dict) or not required.issubset(debate):
                validated = []
                break
            market_ids, market_unknown = resolve_evidence_references(
                debate.get("market_evidence_ids", []),
                debate.get("market_evidence_keys", []),
                known_ids,
                key_to_id,
                debate.get("market_evidence_metrics", []),
                metric_to_id,
            )
            alternative_ids, alternative_unknown = resolve_evidence_references(
                debate.get("alternative_evidence_ids", []),
                debate.get("alternative_evidence_keys", []),
                known_ids,
                key_to_id,
                debate.get("alternative_evidence_metrics", []),
                metric_to_id,
            )
            if market_unknown or alternative_unknown or not (market_ids or alternative_ids):
                validated = []
                break
            validated.append(
                {
                    **debate,
                    "market_evidence_ids": sorted(market_ids),
                    "alternative_evidence_ids": sorted(alternative_ids),
                    "debate_id": debate.get("debate_id") or f"DEBATE-{index}",
                    "status": "ANALYST_DEFINED",
                    "evidence_class": "JUDGMENT",
                }
            )
    if validated:
        return validated

    return [
        {
            "debate_id": "DEBATE-1",
            "title": "Is reported cash conversion durable after normalization? / 报告现金转化在标准化后是否可持续？",
            "market_view": "Not Sourced",
            "alternative_view": "Not Formed",
            "market_evidence_ids": [],
            "alternative_evidence_ids": evidence_ids_for(step2, "latest_ytd_cfo", "latest_ytd_capex", "latest_ytd_fcf"),
            "missing_evidence": "Validated normalized FCF bridge, working-capital normalization, and maintenance capex.",
            "resolution_kpi_or_event": "A reproducible normalized FCF bridge across comparable periods.",
            "decision_impact": "Determines whether trailing FCF can support valuation or only describe historical cash flow.",
            "status": "SYSTEM_PROPOSED_ANALYST_REVIEW_REQUIRED",
            "evidence_class": "INFERENCE",
        },
        {
            "debate_id": "DEBATE-2",
            "title": "Could liquidity, covenants, or refinancing become a binding constraint? / 流动性、契约或再融资会否成为约束？",
            "market_view": "Not Sourced",
            "alternative_view": "Not Formed",
            "market_evidence_ids": [],
            "alternative_evidence_ids": evidence_ids_for(
                step2,
                "unrestricted_cash",
                "short_term_investments",
                "facility_availability_reported",
                "current_debt",
                "current_lease_obligations_total",
            ),
            "missing_evidence": "Validated 12/24-month sources and uses, debt maturity schedule, covenant trigger, and numerical headroom.",
            "resolution_kpi_or_event": "Reconciled liquidity sources and contractual uses under a downside stress.",
            "decision_impact": "Determines whether balance-sheet risk limits equity or credit upside.",
            "status": "SYSTEM_PROPOSED_ANALYST_REVIEW_REQUIRED",
            "evidence_class": "INFERENCE",
        },
        {
            "debate_id": "DEBATE-3",
            "title": "Does current valuation compensate for the unresolved operating and balance-sheet risks? / 当前估值是否充分补偿未解决风险？",
            "market_view": "Not Sourced",
            "alternative_view": "Not Formed",
            "market_evidence_ids": [],
            "alternative_evidence_ids": [],
            "missing_evidence": "Sourced market expectations, reverse valuation, analyst-owned scenarios, and reproducible implied prices.",
            "resolution_kpi_or_event": "Validated reverse valuation and Bear/Base/Bull model with disclosed probabilities.",
            "decision_impact": "Determines whether issuer quality translates into an attractive investment return.",
            "status": "SYSTEM_PROPOSED_ANALYST_REVIEW_REQUIRED",
            "evidence_class": "INFERENCE",
        },
    ]


def build_issuer_underwriting(
    step2: dict[str, Any],
    valuation: dict[str, Any],
    drivers: dict[str, Any],
    research_input: dict[str, Any],
    additional_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    records = list(step2.get("evidence_records", step2.get("data_points", []))) + list(additional_records or [])
    known_ids = {row.get("evidence_id") for row in records if row.get("evidence_id")}
    key_to_id = {str(row.get("external_key")): str(row.get("evidence_id")) for row in records if row.get("external_key")}
    metric_to_id = {
        str(row.get("metric_name")): str(row.get("evidence_id"))
        for row in records
        if row.get("metric_name") and row.get("evidence_id")
    }
    working_capital_coverage = working_capital_component_coverage(
        set(metric_to_id)
    )
    working_capital_limitations = [
        (
            f"Available components: {', '.join(working_capital_coverage['available']) or 'none'}; "
            f"missing pending classification: "
            f"{', '.join(working_capital_coverage['unavailable']) or 'none'}."
        ),
        (
            "Unavailable components are not treated as zero. Business-model and filing review "
            "must classify each one as NOT_APPLICABLE or MISSING."
        ),
        "An 8-quarter trend and note-level reserve, inventory, and payable definitions are not universally available.",
    ]
    overrides = research_input.get("issuer_underwriting", {})
    validation_issues: list[dict[str, Any]] = []

    automatic: dict[str, dict[str, Any]] = {
        "business_and_industry": {
            "status": "INCOMPLETE",
            "conclusion": "Issuer identity and filing scope are known, but the business model and operating drivers have not been analyst-validated.",
            "evidence_ids": [],
            "limitations": ["Item 1 business model, segments, customers, channels, and industry structure require sourced analysis."],
        },
        "earnings_quality": {
            "status": "PRELIMINARY" if valuation.get("ltm_net_income") is not None and valuation.get("ltm_cfo") is not None else "INCOMPLETE",
            "conclusion": "Reported earnings and CFO are period-constructed, but normalized earnings and normalized FCF are not yet validated.",
            "evidence_ids": evidence_ids_for(step2, "latest_ytd_net_income", "latest_ytd_cfo", "latest_ytd_fcf"),
            "limitations": ["Impairments, acquisitions, stock compensation, restructuring, and working-capital timing require a transparent normalization bridge."],
        },
        "working_capital_and_cash_conversion": {
            "status": "PRELIMINARY" if any(row.get("driver") == "FCF margin" and row.get("value") is not None for row in drivers.get("rows", [])) else "INCOMPLETE",
            "conclusion": "Same-period and average-balance metrics are used where available; trend and business-model interpretation remain incomplete.",
            "evidence_ids": evidence_ids_for(step2, "dso_avg_ar", "dio_avg_inventory", "dpo_avg_ap", "cash_conversion_cycle", "latest_ytd_fcf"),
            "limitations": working_capital_limitations,
        },
        "liquidity_sources_and_uses": {
            "status": "PRELIMINARY",
            "conclusion": "Static cash and disclosed borrowing availability may be observable, but a forward 12/24-month sources-and-uses model is not assumed from historical CFO.",
            "evidence_ids": evidence_ids_for(step2, "unrestricted_cash", "short_term_investments", "facility_availability_reported", "total_available_borrowings_reported"),
            "limitations": ["Forward CFO, contractual maturities, lease cash payments, cash interest, maintenance capex, commitments, and stress assumptions require validation."],
        },
        "debt_leases_covenants_refinancing": {
            "status": "PRELIMINARY",
            "conclusion": "Balance-sheet debt and lease carrying values are observations only until tranches, contractual cash payments, covenants, and subsequent refinancing events are reconciled.",
            "evidence_ids": evidence_ids_for(step2, "current_debt", "long_term_debt", "operating_lease_current", "operating_lease_noncurrent", "finance_lease_current", "finance_lease_noncurrent", "facility_note_snippet", "covenant_note_snippet"),
            "limitations": ["Compliance does not establish adequate headroom; carrying values do not equal contractual payment schedules."],
        },
        "capital_allocation": {
            "status": "PRELIMINARY" if evidence_ids_for(step2, "latest_ytd_share_repurchases", "latest_ytd_dividends_paid", "latest_ytd_debt_issuance", "latest_ytd_debt_repayment", "latest_ytd_business_acquisitions") else "INCOMPLETE",
            "conclusion": "Reported financing and investing cash flows are observations; buyback, dividend, acquisition, and deleveraging priorities remain to be reconciled with balance-sheet capacity and management policy.",
            "evidence_ids": evidence_ids_for(step2, "latest_ytd_share_repurchases", "latest_ytd_dividends_paid", "latest_ytd_debt_issuance", "latest_ytd_debt_repayment", "latest_ytd_business_acquisitions"),
            "limitations": ["Authorization is not cash deployment; compare actual uses, debt reduction, acquisitions, dilution, and downside liquidity."],
        },
        "management_guidance_and_subsequent_events": {
            "status": "PRELIMINARY" if evidence_ids_for(step2, "subsequent_event_filing_1") else "INCOMPLETE",
            "conclusion": "The SEC subsequent-filing index is checked, but management guidance and the decision impact of later filings require source-level review.",
            "evidence_ids": [
                str(row.get("evidence_id"))
                for row in records
                if str(row.get("metric_name", "")).startswith("subsequent_event_filing_") and row.get("evidence_id")
            ],
            "limitations": ["A filing index proves that a filing exists; it does not validate guidance, transaction terms, refinancing, or other decision impacts."],
        },
        "stress_test": {
            "status": "INCOMPLETE",
            "conclusion": "No generic downside percentages are invented. Stress assumptions must be company-specific and analyst-owned.",
            "evidence_ids": [],
            "limitations": ["Revenue, margin, working capital, facility haircut, refinancing cost, and covenant stress inputs are missing."],
        },
    }

    for module_name, module in automatic.items():
        supplied = overrides.get(module_name, {}) if isinstance(overrides, dict) else {}
        referenced, unknown_references = resolve_evidence_references(
            supplied.get("evidence_ids", []) if isinstance(supplied, dict) else [],
            supplied.get("evidence_keys", []) if isinstance(supplied, dict) else [],
            known_ids,
            key_to_id,
            supplied.get("evidence_metrics", []) if isinstance(supplied, dict) else [],
            metric_to_id,
        )
        valid_override = (
            isinstance(supplied, dict)
            and supplied.get("status") == "VALIDATED"
            and bool(supplied.get("reviewed_by"))
            and bool(supplied.get("conclusion"))
            and bool(referenced)
            and not unknown_references
        )
        if valid_override:
            automatic[module_name] = {
                "status": "VALIDATED",
                "conclusion": supplied["conclusion"],
                "evidence_ids": sorted(referenced),
                "limitations": supplied.get("limitations", []),
                "reviewed_by": supplied["reviewed_by"],
                "evidence_class": "JUDGMENT",
            }
        else:
            automatic[module_name]["evidence_class"] = "INFERENCE"
            if isinstance(supplied, dict) and supplied.get("status") == "VALIDATED":
                validation_issues.append(
                    {
                        "check_id": f"G2-{module_name}-input-integrity",
                        "category": "issuer_underwriting",
                        "status": "FAIL",
                        "issue_class": "HARD_STOP",
                        "severity": "Critical",
                        "message": f"{module_name} was marked VALIDATED but reviewer, conclusion, or evidence links are invalid. Unknown references={unknown_references}.",
                        "decision_impact": "The module cannot be treated as completed.",
                        "remediation": "Provide a conclusion, valid evidence IDs, limitations, and a named reviewer.",
                        "evidence_ids": sorted(referenced),
                        "scope": "shared_investment_analysis_engine",
                    }
                )

    required = list(automatic)
    complete = all(automatic[name]["status"] == "VALIDATED" for name in required)
    return {
        "status": "COMPLETE" if complete else "INCOMPLETE",
        "required_modules": required,
        "modules": automatic,
        "complete": complete,
        "validation_issues": validation_issues,
    }


def analyst_input_template(company: dict[str, Any], evidence_records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    evidence_records = evidence_records or []
    reported_fcf_id = next(
        (row.get("evidence_id") for row in evidence_records if row.get("metric_name") == "reported_ltm_fcf"),
        "",
    )
    modules = [
        "business_and_industry",
        "earnings_quality",
        "working_capital_and_cash_conversion",
        "liquidity_sources_and_uses",
        "debt_leases_covenants_refinancing",
        "capital_allocation",
        "management_guidance_and_subsequent_events",
        "stress_test",
    ]
    return {
        "company": company,
        "external_evidence": [
            {
                "status": "NOT_VALIDATED",
                "external_key": "",
                "metric_name": "",
                "value": None,
                "unit": "text, USD, shares, pure, or other explicit unit",
                "currency": "",
                "scale": 1.0,
                "period_start": "",
                "period_end": "",
                "period_type": "instant, quarter, YTD, annual, forecast, or event",
                "as_of_date": "",
                "measurement_basis": "reported_or_sourced",
                "evidence_class": "FACT",
                "confidence": "Medium",
                "subsequent_event_status": "NOT_APPLICABLE",
                "source": {
                    "source_level": 2,
                    "source_type": "official_company_material",
                    "source_name": "",
                    "source_url": "",
                    "source_locator": "page, section, table, paragraph, or dataset field",
                    "publication_date": "",
                    "retrieval_date": "",
                },
                "reviewed_by": "",
                "notes": "",
            }
        ],
        "investment_question": {
            "status": "NOT_DEFINED",
            "text": "",
            "decision_supported": "",
            "reviewed_by": "",
        },
        "key_debates": [],
        "key_debate_schema": {
            "title": "",
            "market_view": "",
            "alternative_view": "",
            "market_evidence_ids": [],
            "market_evidence_keys": [],
            "market_evidence_metrics": [],
            "alternative_evidence_ids": [],
            "alternative_evidence_keys": [],
            "alternative_evidence_metrics": [],
            "missing_evidence": "",
            "resolution_kpi_or_event": "",
            "decision_impact": "",
            "reviewed_by": "",
        },
        "issuer_underwriting": {
            name: {
                "status": "NOT_VALIDATED",
                "conclusion": "",
                "evidence_ids": [],
                "evidence_keys": [],
                "evidence_metrics": [],
                "limitations": [],
                "reviewed_by": "",
            }
            for name in modules
        },
        "normalized_fcf": {
            "status": "NOT_VALIDATED",
            "value": None,
            "period_end": "",
            "base_evidence_id": reported_fcf_id,
            "bridge_lines": [],
            "bridge_line_schema": {
                "label": "",
                "amount": None,
                "evidence_id": "",
                "evidence_key": "",
                "evidence_class": "JUDGMENT",
                "embedded_in_cfo": False,
                "separately_modeled": True,
                "reversal_id": "",
                "rationale": "",
            },
            "no_adjustments_rationale": "",
            "confidence": "Low",
            "reviewed_by": "",
        },
        "market_data_approval": {
            "status": "NOT_APPROVED",
            "provider": "Yahoo Finance chart endpoint",
            "scope": "dated close and adjusted-close return inputs",
            "reviewed_by": "",
        },
        "market_expectations": {
            "status": "NOT_SOURCED",
            "summary": "",
            "current_public_evidence": "",
            "variant_question": "",
            "variant_perception": "",
            "potential_variant": "",
            "disconfirming_evidence": "",
            "market_evidence_ids": [],
            "market_evidence_keys": [],
            "market_evidence_metrics": [],
            "public_evidence_ids": [],
            "public_evidence_keys": [],
            "public_evidence_metrics": [],
            "variant_evidence_ids": [],
            "variant_evidence_keys": [],
            "variant_evidence_metrics": [],
            "disconfirming_evidence_ids": [],
            "disconfirming_evidence_keys": [],
            "disconfirming_evidence_metrics": [],
            "source": {
                "source_level": 4,
                "source_type": "institutional_consensus",
                "source_name": "",
                "source_url": "",
                "source_locator": "",
                "publication_date": "",
                "retrieval_date": "",
            },
            "as_of_date": "",
            "reviewed_by": "",
        },
        "valuation_framework": {
            "status": "NOT_VALIDATED",
            "method": "EQUITY_FCF_MULTIPLE or EQUITY_EARNINGS_MULTIPLE",
            "reverse_valuation": {
                "status": "NOT_VALIDATED",
                "formula": "required_metric_value = market_cap / selected_multiple",
                "selected_multiple": None,
                "required_metric_value": None,
                "assumptions": [],
                "evidence_ids": [],
                "evidence_keys": [],
                "evidence_metrics": [],
            },
            "sensitivity_completed": False,
            "sensitivity_table": [
                {"metric_value": None, "multiple": None, "implied_price": None},
                {"metric_value": None, "multiple": None, "implied_price": None},
                {"metric_value": None, "multiple": None, "implied_price": None},
            ],
            "reviewed_by": "",
        },
        "share_count_basis": {
            "share_count_type": "COMMON_SHARES_OUTSTANDING",
            "share_count_source": "",
            "forward_share_count_bridge_status": "NOT_COMPLETED",
            "forward_share_count_value": None,
            "forward_share_count_date": "",
            "forward_share_count_source": "",
            "forward_share_count_source_detail": {},
            "forward_share_count_evidence_ids": [],
            "known_subsequent_event_status": "NOT_REVIEWED",
            "known_subsequent_event_note": "",
            "limitations": [],
            "reviewed_by": "",
        },
        "valuation_contract": {
            "status": "NOT_DEFINED",
            "valuation_as_of_date": "",
            "target_date": "",
            "holding_period_days": None,
            "forecast_period": {
                "status": "NOT_DEFINED",
                "start_date": "",
                "end_date": "",
                "label": "",
                "period_type": "FORECAST",
                "basis": "HOLDING_PERIOD_FORECAST",
                "evidence_ids": [],
            },
            "metric_period": {
                "status": "NOT_DEFINED",
                "start_date": "",
                "end_date": "",
                "label": "",
                "period_type": "FORWARD_METRIC",
                "basis": "FORWARD_PERIOD_ENDING_AT_TARGET",
                "evidence_ids": [],
            },
            "dividend_assumption": {
                "status": "NOT_DEFINED",
                "amount_per_share": None,
                "currency": "",
                "basis": "",
                "payment_timing": "",
                "reinvestment": False,
                "evidence_ids": [],
                "reviewed_by": "",
            },
            "exit_basis": {
                "status": "NOT_DEFINED",
                "method": "",
                "metric": "",
                "terminal_or_exit": "EXIT",
                "evidence_ids": [],
                "reviewed_by": "",
            },
            "reviewed_by": "",
            "partner_internal_return": None,
        },
        "scenario_model": {
            "status": "NOT_VALIDATED",
            "metric": "Normalized FCF",
            "metric_unit": "",
            "metric_currency": "",
            "current_multiple": None,
            "metric_basis": {
                "status": "NOT_VALIDATED",
                "value": None,
                "unit": "",
                "currency": "",
                "period_end": "",
                "evidence_ids": [],
                "reviewed_by": "",
            },
            "reviewed_by": "",
            "scenarios": [
                {
                    "name": name,
                    "probability": None,
                    "metric_value_total": None,
                    "growth_assumption": None,
                    "exit_multiple": None,
                    "key_driver": "",
                    "falsification_trigger": "",
                    "confidence": "Low",
                    "assumption_sources": [],
                    "probability_rationale": "",
                    "notes": "",
                }
                for name in ("Bear", "Base", "Bull")
            ],
        },
        "probability_framework": {
            "status": "ILLUSTRATIVE",
            "method_type": "SCENARIO_JUDGMENT",
            "methodology": "",
            "method_details": {
                "allocation_rationale": "",
                "sensitivity_completed": False,
            },
            "evidence_ids": [],
            "evidence_keys": [],
            "evidence_metrics": [],
            "scenario_rationales": {"Bear": "", "Base": "", "Bull": ""},
            "as_of_date": "",
            "probability_expiration_review_date": "",
            "review_triggers": ["NEW_EARNINGS_OR_GUIDANCE"],
            "sensitivity_cases": [],
            "reviewed_by": "",
            "approval": {"status": "NOT_APPROVED", "approved_by": "", "approval_date": ""},
        },
        "peer_valuation_context": {
            "status": "NOT_VALIDATED",
            "as_of_date": "",
            "selection_rationale": "",
            "subject": {
                "fiscal_period_end": "",
                "currency": "USD",
                "metric_definitions": {
                    "EV/SALES": "GAAP_REVENUE",
                    "EV/EBITDA": "GAAP_OR_RECONCILED_EBITDA",
                    "P/FCF": "REPORTED_CFO_MINUS_CAPEX",
                    "FCF_YIELD": "REPORTED_CFO_MINUS_CAPEX",
                    "REVENUE_GROWTH": "GAAP_REVENUE_GROWTH",
                    "OPERATING_MARGIN": "GAAP_OPERATING_MARGIN",
                    "EBITDA_MARGIN": "GAAP_OR_RECONCILED_EBITDA_MARGIN",
                },
            },
            "peers": [],
            "historical_context": {"status": "UNAVAILABLE"},
            "interpretation": "",
            "limitations": [],
            "reviewed_by": "",
        },
        "fcf_quality_assessment": {
            "status": "NOT_VALIDATED",
            "rating": "Medium",
            "cash_conversion_confidence": "Medium",
            "source_of_fcf": [],
            "sustainability_assessment": "",
            "conclusion": "",
            "dimensions": [],
            "evidence_ids": [],
            "evidence_keys": [],
            "evidence_metrics": [],
            "limitations": [],
            "reviewed_by": "",
        },
        "investment_decision_summary": {
            "status": "NOT_VALIDATED",
            "current_action": "Continue Research",
            "current_view": "",
            "what_would_make_attractive": [],
            "what_would_invalidate": [],
            "what_to_monitor_next": [],
            "evidence_ids": [],
            "evidence_keys": [],
            "evidence_metrics": [],
            "reviewed_by": "",
        },
        "decision_rules": {
            "status": "NOT_DEFINED",
            "upgrade_conditions": [],
            "downgrade_conditions": [],
            "thesis_invalidation_conditions": [],
            "reviewed_by": "",
        },
        "portfolio_context": {
            "status": "DISABLED",
            "note": "Fund-specific inputs not provided.",
        },
        "human_approval": {"status": "NOT_REVIEWED", "reviewed_by": ""},
    }


def build_system_validation_gates(
    step2: dict[str, Any],
    market_snapshot: dict[str, Any],
    valuation: dict[str, Any],
    opportunity: dict[str, Any],
    investment_question: dict[str, Any],
    key_debates: list[dict[str, Any]],
    issuer_underwriting: dict[str, Any],
    market_expectations: dict[str, Any],
    scenario_status: str,
    probability_validation: dict[str, Any],
    peer_valuation_context: dict[str, Any],
    fcf_quality_assessment: dict[str, Any],
    investment_decision_summary: dict[str, Any],
    research_input: dict[str, Any],
) -> list[ValidationGate]:
    gates: list[ValidationGate] = []
    step2_hard_stops = step2.get("hard_stops", [])
    support_status = step2.get("supported_universe", {}).get("status")
    gates.append(
        ValidationGate(
            "G0-data-evidence-foundation",
            "PASS" if not step2_hard_stops and support_status == "SUPPORTED_CORE" else "BLOCKED",
            "P0",
            f"Data hard stops={len(step2_hard_stops)}; supported universe={support_status or 'unknown'}.",
            "Formal underwriting cannot proceed on unsupported or contradictory core data.",
            "Resolve every shared data-engine Hard Stop or apply the required specialized overlay.",
            "HARD_STOP" if step2_hard_stops or support_status != "SUPPORTED_CORE" else "INFO",
            "data_integrity",
        )
    )
    market_ok = market_snapshot.get("status") == "PASS" and valuation.get("price") is not None and bool(valuation.get("price_date"))
    gates.append(
        ValidationGate(
            "G1-market-price-date",
            "PASS" if market_ok else "BLOCKED",
            "P0",
            f"Price={price_label(valuation.get('price'))}; type={valuation.get('price_type') or 'n/a'}; date={valuation.get('price_date') or 'n/a'}.",
            "A dated price is required for market cap and any per-share valuation.",
            "Provide a sourced unadjusted price and exact as-of date.",
            "INFO" if market_ok else "HARD_STOP",
            "market_data",
        )
    )
    shares_ok = valuation.get("shares") not in (None, 0) and bool(valuation.get("shares_as_of_date"))
    if shares_ok and valuation.get("price_date"):
        shares_ok = valuation["shares_as_of_date"] <= valuation["price_date"]
    gates.append(
        ValidationGate(
            "G1-share-count-date",
            "PASS" if shares_ok else "BLOCKED",
            "P0",
            f"Shares={valuation.get('shares') or 'n/a'}; share date={valuation.get('shares_as_of_date') or 'n/a'}; price date={valuation.get('price_date') or 'n/a'}.",
            "Market cap must use a sourced share count available on or before the price date.",
            "Use the latest SEC cover-page shares outstanding available by the price date and label the basis.",
            "INFO" if shares_ok else "HARD_STOP",
            "market_data",
        )
    )
    provider_approved = market_data_is_approved(market_snapshot)
    gates.append(
        ValidationGate(
            "G1-market-provider-approval",
            "PASS" if provider_approved else "WARNING",
            "P1",
            f"Provider={market_snapshot.get('provider')}; source level={market_snapshot.get('source_level')}; approval={market_snapshot.get('provider_approval_status')}.",
            "Market data must be reviewed for the scope in which valuation outputs will be used.",
            "Approve the provider for research use or reconcile to a partner-approved production feed.",
            "INFO" if provider_approved else "WARNING",
            "source_quality",
        )
    )
    gates.append(
        ValidationGate(
            "G1-exact-date-return",
            "PASS" if opportunity.get("status") == "PASS" else "WARNING",
            "P1",
            f"Return basis={opportunity.get('return_basis') or 'missing'}; dates={opportunity.get('start_date') or 'n/a'} to {opportunity.get('end_date') or 'n/a'}.",
            "Relative return is descriptive only and must use exact common dates and adjusted closes.",
            "Retrieve aligned daily histories or suppress the relative-return field.",
            "INFO" if opportunity.get("status") == "PASS" else "WARNING",
            "market_data",
        )
    )
    question_defined = investment_question.get("status") == "ANALYST_DEFINED"
    gates.append(
        ValidationGate(
            "G2-investment-question",
            "PASS" if question_defined else "MISSING",
            "P1",
            investment_question.get("text", "Not Defined"),
            "Without a decision question, the report can describe the issuer but cannot claim to resolve an investment debate.",
            "Define the uncertainty and decision the work is intended to support.",
            "INFO" if question_defined else "WARNING",
            "decision_scope",
        )
    )
    debates_valid = 2 <= len(key_debates) <= 3 and all(
        debate.get("status") == "ANALYST_DEFINED" for debate in key_debates
    )
    gates.append(
        ValidationGate(
            "G2-key-debates",
            "PASS" if debates_valid else "MISSING",
            "P1",
            f"Analyst-defined debates={sum(debate.get('status') == 'ANALYST_DEFINED' for debate in key_debates)}/{len(key_debates)}.",
            "System-proposed questions can guide research but cannot establish a differentiated investment view.",
            "Define two or three debates with both-side evidence, missing evidence, resolving KPI/event, and decision impact.",
            "INFO" if debates_valid else "WARNING",
            "decision_scope",
        )
    )
    gates.append(
        ValidationGate(
            "G2-issuer-underwriting",
            "PASS" if issuer_underwriting.get("complete") else "MISSING",
            "P1",
            f"Validated modules={sum(module.get('status') == 'VALIDATED' for module in issuer_underwriting.get('modules', {}).values())}/{len(issuer_underwriting.get('required_modules', []))}.",
            "Issuer-level credit, liquidity, and operating conclusions require every shared module to be completed or explicitly qualified.",
            "Complete business, earnings quality, working capital, liquidity, debt/lease/covenant/refinancing, capital allocation, guidance/subsequent events, and stress modules.",
            "INFO" if issuer_underwriting.get("complete") else "WARNING",
            "issuer_underwriting",
        )
    )
    normalized_valid = research_input.get("normalized_fcf", {}).get("status") == "VALIDATED"
    valuation_input = research_input.get("valuation_framework", {})
    reverse_valuation = valuation_input.get("reverse_valuation", {})
    valuation_valid = valuation_input_is_structurally_complete(research_input)
    gates.append(
        ValidationGate(
            "G2.5-normalized-fcf",
            "PASS" if normalized_valid else "MISSING",
            "P1",
            f"Normalized FCF status={research_input.get('normalized_fcf', {}).get('status', 'NOT_PROVIDED')}.",
            "Reported CFO minus capex is not automatically normalized FCF.",
            "Provide a transparent bridge with sourced adjustments and no CFO double counting.",
            "INFO" if normalized_valid else "WARNING",
            "valuation",
        )
    )
    gates.append(
        ValidationGate(
            "G2.5-fcf-quality",
            "PASS" if fcf_quality_assessment.get("status") == "VALIDATED" else "MISSING",
            "P1",
            f"FCF quality status={fcf_quality_assessment.get('status')}; rating={fcf_quality_assessment.get('rating')}.",
            "A reproducible normalized FCF point estimate does not establish cash-flow durability.",
            "Assess operating-earnings support, working-capital effects, temporary benefits, cost reductions, capex adequacy, and cash-conversion confidence.",
            "INFO" if fcf_quality_assessment.get("status") == "VALIDATED" else "WARNING",
            "fcf_quality",
        )
    )
    gates.append(
        ValidationGate(
            "G2.5-market-expectations",
            "PASS" if market_expectations.get("consensus_status") == "SOURCED" else "MISSING",
            "P1",
            f"Consensus/expectations status={market_expectations.get('consensus_status')}.",
            "Price history and trailing multiples cannot be presented as sourced consensus.",
            "Add sourced consensus, management guidance, or clearly labeled internal expectations.",
            "INFO" if market_expectations.get("consensus_status") == "SOURCED" else "WARNING",
            "valuation",
        )
    )
    gates.append(
        ValidationGate(
            "G2.5-variant-perception",
            "PASS" if market_expectations.get("variant_status") == "ANALYST_DEFINED" else "MISSING",
            "P1",
            f"Variant-perception status={market_expectations.get('variant_status', 'NOT_DEFINED')}.",
            "A sourced conventional view is not a differentiated thesis until the analyst states the alternative view and its evidence burden.",
            "Define the variant question and variant perception, then link both to the Key Debates and measurable decision rules.",
            "INFO" if market_expectations.get("variant_status") == "ANALYST_DEFINED" else "WARNING",
            "valuation",
        )
    )
    gates.append(
        ValidationGate(
            "G3-valuation-framework",
            "PASS" if valuation_valid else "MISSING",
            "P1",
            f"Valuation framework status={valuation_input.get('status', 'NOT_PROVIDED')}; reverse valuation={reverse_valuation.get('status', 'NOT_PROVIDED')}; sensitivity={valuation_input.get('sensitivity_completed', False)}.",
            "A trailing multiple observation is not a validated valuation conclusion.",
            "Complete reverse valuation, method selection, implied prices, and sensitivity analysis.",
            "INFO" if valuation_valid else "WARNING",
            "valuation",
        )
    )
    scenario_valid = scenario_status == "scenario_assumptions_validated"
    gates.append(
        ValidationGate(
            "G3-scenarios",
            "PASS" if scenario_valid else "MISSING",
            "P1",
            f"Scenario status={scenario_status}.",
            "Scenario prices remain hidden until normalized metric, Bear/Base/Bull assumptions, and implied prices are reproducible.",
            "Validate normalized metric, Bear/Base/Bull values, exit multiples, key drivers, and falsification triggers.",
            "INFO" if scenario_valid else "WARNING",
            "scenario_analysis",
        )
    )
    probability_valid = probability_validation.get("status") == "VALIDATED"
    gates.append(
        ValidationGate(
            "G3-probability-validation",
            "PASS" if probability_valid else "MISSING",
            "P1",
            (
                f"Probability status={probability_validation.get('status')}; method={probability_validation.get('method_type')}; "
                f"freshness={probability_validation.get('freshness_status')}; approval={probability_validation.get('approval', {}).get('status')}."
            ),
            "Scenario prices may remain visible, but probability-weighted return is not a formal output without method, freshness, sensitivity, and approval.",
            "Complete the controlled probability method, method-specific details, evidence, rationales, expiration review date, sensitivity, and human approval.",
            "INFO" if probability_valid else "WARNING",
            "scenario_probability",
        )
    )
    peer_valid = peer_valuation_context.get("status") == "VALIDATED"
    gates.append(
        ValidationGate(
            "G3-peer-valuation-context",
            "PASS" if peer_valid else "MISSING",
            "P1",
            f"Peer valuation status={peer_valuation_context.get('status')}; comparable rows={sum(row.get('auto_rank_allowed', False) for row in peer_valuation_context.get('rows', []))}.",
            "A selected multiple remains analyst-owned when peer and historical context is unavailable.",
            "Use only peers and metrics that pass denominator, period, currency, and accounting-definition controls; otherwise state unavailable.",
            "INFO" if peer_valid else "WARNING",
            "peer_valuation",
        )
    )
    decision_rules = research_input.get("decision_rules", {})
    decision_rules_valid = (
        decision_rules.get("status") == "VALIDATED"
        and bool(decision_rules.get("reviewed_by"))
        and bool(decision_rules.get("upgrade_conditions"))
        and bool(decision_rules.get("downgrade_conditions"))
        and bool(decision_rules.get("thesis_invalidation_conditions"))
    )
    gates.append(
        ValidationGate(
            "G3-decision-rules",
            "PASS" if decision_rules_valid else "MISSING",
            "P1",
            f"Decision-rule status={decision_rules.get('status', 'NOT_DEFINED')}.",
            "A reproducible investment view requires measurable upgrade, downgrade, and thesis-invalidation conditions.",
            "Provide analyst-owned thresholds, evidence basis, and reviewer ownership.",
            "INFO" if decision_rules_valid else "WARNING",
            "decision_rules",
        )
    )
    decision_summary_valid = investment_decision_summary.get("status") == "VALIDATED"
    gates.append(
        ValidationGate(
            "G3-investment-decision-summary",
            "PASS" if decision_summary_valid else "MISSING",
            "P1",
            f"Investment Decision Summary status={investment_decision_summary.get('status')}; action={investment_decision_summary.get('current_action')}.",
            "Workflow readiness is not the same as a concise, evidence-linked public-data investment view.",
            "Provide an allowed research action, current view, measurable attractiveness/invalidation conditions, monitoring items, evidence, and reviewer.",
            "INFO" if decision_summary_valid else "WARNING",
            "decision_summary",
        )
    )
    gates.append(
        ValidationGate(
            "G4-portfolio-context",
            "PASS" if research_input.get("portfolio_context", {}).get("status") == "VALIDATED" else "MISSING",
            "P1",
            f"Portfolio context={research_input.get('portfolio_context', {}).get('status', 'DISABLED')}.",
            "Position sizing and portfolio action require fund-specific constraints and opportunity cost.",
            "Complete the partner overlay and obtain human approval.",
            "WARNING",
            "portfolio",
        )
    )
    return gates


def gates_to_issues(gates: list[ValidationGate]) -> list[dict[str, Any]]:
    return [
        {
            "check_id": gate.gate_id,
            "category": gate.category,
            "status": gate.result,
            "issue_class": gate.issue_class,
            "severity": gate.severity,
            "message": gate.evidence,
            "decision_impact": gate.decision_impact,
            "remediation": gate.remediation,
            "evidence_ids": [],
            "scope": "shared_investment_analysis_engine",
        }
        for gate in gates
    ]


def reconcile_upstream_validation_tests(
    step2: dict[str, Any],
    issuer_underwriting: dict[str, Any],
    market_expectations: dict[str, Any],
    scenario_status: str,
    research_input: dict[str, Any],
    external_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Mark upstream research warnings resolved when reviewed downstream evidence supersedes them."""

    resolved_ids: dict[str, str] = {}
    debt_module = issuer_underwriting.get("modules", {}).get("debt_leases_covenants_refinancing", {})
    if debt_module.get("status") == "VALIDATED":
        resolved_ids["P1-facility-note-check"] = "Resolved by the analyst-validated debt, facility, covenant, lease, and refinancing module."
        resolved_ids["P1-covenant-check"] = "Resolved at the disclosed-contract level; any unavailable numerical headroom remains an explicit module limitation."

    valuation_ready = (
        research_input.get("normalized_fcf", {}).get("status") == "VALIDATED"
        and valuation_input_is_structurally_complete(research_input)
        and market_expectations.get("consensus_status") == "SOURCED"
        and market_expectations.get("variant_status") == "ANALYST_DEFINED"
        and market_expectations.get("variant_structure_status") == "COMPLETE"
        and scenario_status == "scenario_assumptions_validated"
        and research_input.get("decision_rules", {}).get("status") == "VALIDATED"
        and bool(research_input.get("decision_rules", {}).get("reviewed_by"))
    )
    if valuation_ready:
        resolved_ids["P2-investment-action-gate"] = "Resolved by the sourced expectations, normalized FCF, reverse valuation, scenarios, and decision rules in the investment layer."

    indexed_filings = [
        row
        for row in step2.get("evidence_records", step2.get("data_points", []))
        if str(row.get("metric_name", "")).startswith("subsequent_event_filing_")
    ]
    reviewed_urls = {
        row.get("source_url")
        for row in external_records
        if row.get("source_url")
        and row.get("subsequent_event_status")
        in {"REVIEWED_NO_MATERIAL_FINANCIAL_CHANGE", "REVIEWED_MATERIAL_CHANGE_REFLECTED"}
    }
    if indexed_filings and all(row.get("source_url") in reviewed_urls for row in indexed_filings):
        resolved_ids["P1-subsequent-event-review"] = "Resolved: every indexed subsequent filing was read and its decision impact was recorded in the evidence layer."

    reconciled: list[dict[str, Any]] = []
    for issue in step2.get("validation_tests", []):
        check_id = issue.get("check_id", issue.get("id"))
        if check_id not in resolved_ids:
            reconciled.append(issue)
            continue
        reconciled.append(
            {
                **issue,
                "result": "PASS",
                "status": "PASS",
                "issue_class": "INFO",
                "severity": "Info",
                "evidence": resolved_ids[check_id],
                "message": resolved_ids[check_id],
                "impact": "The upstream provisional warning no longer constrains the current output.",
                "decision_impact": "The upstream provisional warning no longer constrains the current output.",
                "remediation": "None for the current public-data scope; preserve stated limitations and rerun after new filings.",
            }
        )
    return reconciled


def build_analysis_evidence(
    company: dict[str, Any],
    step2: dict[str, Any],
    market_snapshot: dict[str, Any],
    benchmark_snapshot: dict[str, Any],
    valuation: dict[str, Any],
    opportunity: dict[str, Any],
    market_expectations: dict[str, Any],
    scenarios: list[Scenario],
    probability_validation: dict[str, Any],
    research_input: dict[str, Any],
    additional_records: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Create evidence records for market, LTM, valuation, and scenario outputs."""

    retrieval_date = datetime.now(UTC).date().isoformat()
    records: list[dict[str, Any]] = []
    sources: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []

    def add(
        metric_name: str,
        value: Any,
        *,
        unit: str,
        currency: str = "",
        period_start: str = "",
        period_end: str = "",
        period_type: str = "instant",
        as_of_date: str = "",
        measurement_basis: str = "reported",
        source_level: int,
        source_type: str,
        source_name: str,
        source_url: str,
        source_locator: str,
        source_tag: str,
        publication_date: str = "",
        retrieval_date_override: str = "",
        evidence_class: str = "FACT",
        formula: str = "",
        input_ids: list[str] | None = None,
        confidence: str = "High",
        validation_status: str = "PASS",
        notes: str = "",
    ) -> str:
        record_retrieval_date = retrieval_date_override or retrieval_date
        source_id = stable_id("SRC", source_level, source_type, source_name, source_url, source_locator, publication_date)
        evidence_id = stable_id(
            "EV",
            company["ticker"],
            metric_name,
            period_start,
            period_end,
            as_of_date,
            source_tag,
            source_locator,
        )
        sources.setdefault(
            source_id,
            {
                "source_id": source_id,
                "source_level": source_level,
                "source_type": source_type,
                "source_name": source_name,
                "source_url": source_url,
                "source_locator": source_locator,
                "publication_date": publication_date,
                "retrieval_date": record_retrieval_date,
            },
        )
        records.append(
            {
                "evidence_id": evidence_id,
                "metric_name": metric_name,
                "value": value,
                "unit": unit,
                "currency": currency,
                "scale": 1.0,
                "period_start": period_start,
                "period_end": period_end,
                "period_type": period_type,
                "duration_days": duration_days({"start": period_start, "end": period_end}) if period_start and period_end else "",
                "as_of_date": as_of_date or period_end,
                "measurement_basis": measurement_basis,
                "fiscal_period": "",
                "filing_type": "",
                "publication_date": publication_date,
                "retrieval_date": record_retrieval_date,
                "source_level": source_level,
                "source_type": source_type,
                "source_name": source_name,
                "source_id": source_id,
                "source_locator": source_locator,
                "source_location": source_locator,
                "source_tag": source_tag,
                "source_url": source_url,
                "evidence_class": evidence_class,
                "evidence_type": evidence_class,
                "reported_or_calculated": "reported" if evidence_class == "FACT" else "calculated" if evidence_class == "CALC" else "analyst_input",
                "formula": formula,
                "input_evidence_ids": input_ids or [],
                "confidence": confidence,
                "validation_status": validation_status,
                "subsequent_event_status": "NOT_APPLICABLE",
                "notes": notes,
            }
        )
        return evidence_id

    market_source = market_snapshot.get("source_url", "")
    market_approved = market_data_is_approved(market_snapshot)
    market_source_type = "approved_market_data" if market_approved else "unapproved_public_market_data"
    price_id = add(
        "market_price_unadjusted_close",
        valuation.get("price"),
        unit=valuation.get("price_currency", "USD"),
        currency=valuation.get("price_currency", "USD"),
        period_end=valuation.get("price_date", ""),
        as_of_date=valuation.get("price_date", ""),
        source_level=int(market_snapshot.get("source_level", 5)),
        source_type=market_source_type,
        source_name=market_snapshot.get("provider", "Public market provider"),
        source_url=market_source,
        source_locator="Daily unadjusted close",
        source_tag="market:close",
        publication_date=valuation.get("price_date", ""),
        confidence="Medium",
        validation_status="PASS" if market_approved else "WARNING",
        notes=f"Provider approval={market_snapshot.get('provider_approval_status')}.",
    )
    shares_source = valuation.get("shares_source") or {}
    companyfacts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{company['cik']}.json"
    shares_id = add(
        "shares_outstanding_point_in_time",
        valuation.get("shares"),
        unit="shares",
        period_end=valuation.get("shares_as_of_date", ""),
        as_of_date=valuation.get("shares_as_of_date", ""),
        source_level=1,
        source_type="regulatory_filing",
        source_name="U.S. Securities and Exchange Commission",
        source_url=companyfacts_url,
        source_locator=f"{shares_source.get('form', '')} cover-page shares; accession {shares_source.get('accn', '')}",
        source_tag=f"{shares_source.get('taxonomy', '')}:{shares_source.get('tag', '')}",
        publication_date=shares_source.get("filed", ""),
        notes="Point-in-time common shares outstanding, not diluted weighted-average shares.",
    )
    market_cap_id = add(
        "market_cap_point_in_time",
        valuation.get("market_cap"),
        unit="USD",
        currency="USD",
        period_end=valuation.get("price_date", ""),
        as_of_date=valuation.get("price_date", ""),
        measurement_basis="calculated_from_point_in_time_price_and_shares",
        source_level=int(market_snapshot.get("source_level", 5)),
        source_type="calculation_from_mixed_primary_and_market_sources",
        source_name="Shared investment analysis engine",
        source_url=market_source,
        source_locator="market price x point-in-time shares",
        source_tag="calculation",
        evidence_class="CALC",
        formula="market_price_unadjusted_close * shares_outstanding_point_in_time",
        input_ids=[price_id, shares_id],
        confidence="Medium",
    )

    ltm_ids: dict[str, str] = {}
    ltm_period_ends: dict[str, str] = {}
    for metric, result in valuation.get("ltm", {}).items():
        component_ids: list[str] = []
        for component_name, component in result.get("components", {}).items():
            if not component:
                continue
            component_ids.append(
                add(
                    f"{metric}_{component_name}_component",
                    component.get("value"),
                    unit=component.get("unit", "USD"),
                    currency="USD" if "USD" in str(component.get("unit", "")) else "",
                    period_start=component.get("start", ""),
                    period_end=component.get("end", ""),
                    period_type="annual" if component_name == "annual" else "YTD",
                    source_level=1,
                    source_type="regulatory_filing",
                    source_name="U.S. Securities and Exchange Commission",
                    source_url=companyfacts_url,
                    source_locator=f"{component.get('form', '')} companyfacts; accession {component.get('accn', '')}",
                    source_tag=f"{component.get('taxonomy', '')}:{component.get('tag', '')}",
                    publication_date=component.get("filed", ""),
                )
            )
        result_period_end = (
            result.get("components", {}).get("current_ytd", {}).get("end")
            or result.get("components", {}).get("annual", {}).get("end")
            or ""
        )
        ltm_period_ends[metric] = result_period_end
        evidence_class = "CALC" if result.get("period_type") == "LTM" else "FACT" if result.get("value") is not None else "MISSING"
        ltm_ids[metric] = add(
            f"valuation_basis_{metric}",
            result.get("value"),
            unit="USD",
            currency="USD",
            period_end=result_period_end,
            period_type=result.get("period_type", "missing"),
            as_of_date=result_period_end,
            measurement_basis=result.get("method", "missing"),
            source_level=1,
            source_type="calculation_from_primary" if evidence_class == "CALC" else "regulatory_filing",
            source_name="Shared investment analysis engine",
            source_url=companyfacts_url,
            source_locator=result.get("method", "missing"),
            source_tag="calculation" if evidence_class == "CALC" else "annual_fallback",
            evidence_class=evidence_class,
            formula="annual + current YTD - prior comparable YTD" if evidence_class == "CALC" else "",
            input_ids=component_ids,
            confidence=result.get("confidence", "Low"),
            validation_status="PASS" if result.get("value") is not None else "MISSING",
        )

    reported_ltm_fcf_id = add(
        "reported_ltm_fcf",
        valuation.get("ltm_fcf"),
        unit="USD",
        currency="USD",
        period_end=ltm_period_ends.get("cfo", "") if ltm_period_ends.get("cfo") == ltm_period_ends.get("capex") else "",
        period_type="LTM" if valuation.get("ltm", {}).get("cfo", {}).get("period_type") == "LTM" and valuation.get("ltm", {}).get("capex", {}).get("period_type") == "LTM" else "mixed_or_annual_fallback",
        as_of_date=ltm_period_ends.get("cfo", "") if ltm_period_ends.get("cfo") == ltm_period_ends.get("capex") else "",
        measurement_basis="reported CFO less reported cash capex; not normalized",
        source_level=1,
        source_type="calculation_from_primary",
        source_name="Shared investment analysis engine",
        source_url=companyfacts_url,
        source_locator="valuation_basis_cfo - valuation_basis_capex",
        source_tag="calculation",
        evidence_class="CALC" if valuation.get("ltm_fcf") is not None else "MISSING",
        formula="valuation_basis_cfo - valuation_basis_capex",
        input_ids=[item for item in (ltm_ids.get("cfo"), ltm_ids.get("capex")) if item],
        confidence="High" if valuation.get("ltm", {}).get("cfo", {}).get("period_type") == valuation.get("ltm", {}).get("capex", {}).get("period_type") == "LTM" else "Medium",
        validation_status="PASS" if valuation.get("ltm_fcf") is not None else "MISSING",
        notes="Do not use as normalized FCF without a validated bridge.",
    )

    ratio_specs = {
        "p_fcf": (valuation.get("p_fcf"), "market_cap / reported_ltm_fcf", [market_cap_id, reported_ltm_fcf_id]),
        "pe": (valuation.get("pe"), "market_cap / valuation_basis_net_income", [market_cap_id, ltm_ids.get("net_income")]),
        "fcf_yield": (valuation.get("fcf_yield"), "reported_ltm_fcf / market_cap", [reported_ltm_fcf_id, market_cap_id]),
    }
    for metric_name, (value, formula, inputs) in ratio_specs.items():
        add(
            f"trailing_{metric_name}",
            value,
            unit="pure",
            period_end=valuation.get("price_date", ""),
            as_of_date=valuation.get("price_date", ""),
            measurement_basis="trailing observation, not normalized valuation conclusion",
            source_level=int(market_snapshot.get("source_level", 5)),
            source_type="calculation_from_primary_and_market_sources",
            source_name="Shared investment analysis engine",
            source_url=market_source,
            source_locator=formula,
            source_tag="calculation",
            evidence_class="CALC" if value is not None else "MISSING",
            formula=formula,
            input_ids=[item for item in inputs if item],
            confidence="Medium",
            validation_status="PASS" if value is not None else "MISSING",
        )

    if opportunity.get("status") == "PASS":
        return_input_ids: list[str] = []
        for prefix, snapshot, provider in (
            ("stock", market_snapshot, market_snapshot.get("provider")),
            ("benchmark", benchmark_snapshot, benchmark_snapshot.get("provider")),
        ):
            for point in ("start", "end"):
                return_input_ids.append(
                    add(
                        f"{prefix}_{point}_adjusted_close",
                        opportunity.get(f"{prefix}_{point}_adjusted_close"),
                        unit=snapshot.get("currency", "USD"),
                        currency=snapshot.get("currency", "USD"),
                        period_end=opportunity.get(f"{point}_date", ""),
                        as_of_date=opportunity.get(f"{point}_date", ""),
                        measurement_basis="adjusted close for total-return comparison",
                        source_level=int(snapshot.get("source_level", 5)),
                        source_type="approved_market_data" if market_data_is_approved(snapshot) else "unapproved_public_market_data",
                        source_name=provider or "Public market provider",
                        source_url=snapshot.get("source_url", ""),
                        source_locator=f"{point} adjusted close on common trading date",
                        source_tag="market:adjusted_close",
                        publication_date=opportunity.get(f"{point}_date", ""),
                        confidence="Medium",
                        validation_status="PASS" if market_data_is_approved(snapshot) else "WARNING",
                    )
                )
        add(
            "relative_12m_total_return",
            opportunity.get("relative_12m_return"),
            unit="pure",
            period_start=opportunity.get("start_date", ""),
            period_end=opportunity.get("end_date", ""),
            period_type="return_period",
            measurement_basis=opportunity.get("return_basis", ""),
            source_level=int(market_snapshot.get("source_level", 5)),
            source_type="calculation_from_market_data",
            source_name="Shared investment analysis engine",
            source_url=market_source,
            source_locator="stock total return - benchmark total return",
            source_tag="calculation",
            evidence_class="CALC",
            formula="(stock_end / stock_start - 1) - (benchmark_end / benchmark_start - 1)",
            input_ids=return_input_ids,
            confidence="Medium",
        )

    if market_expectations.get("consensus_status") == "SOURCED":
        expectation_source = market_expectations.get("source") or {}
        expectation_id = add(
            "sourced_market_expectations_summary",
            market_expectations.get("summary_view"),
            unit="text",
            period_end=market_expectations.get("as_of_date", ""),
            as_of_date=market_expectations.get("as_of_date", ""),
            measurement_basis="sourced conventional or consensus view",
            source_level=int(expectation_source.get("source_level")),
            source_type=expectation_source.get("source_type"),
            source_name=expectation_source.get("source_name"),
            source_url=expectation_source.get("source_url", ""),
            source_locator=expectation_source.get("source_locator"),
            source_tag="market_expectations",
            publication_date=expectation_source.get("publication_date", ""),
            retrieval_date_override=expectation_source.get("retrieval_date", ""),
            evidence_class="INFERENCE",
            confidence="High" if int(expectation_source.get("source_level")) == 2 else "Medium",
            notes="This record preserves the sourced market view; it is not the analyst's variant perception.",
        )
        if market_expectations.get("variant_status") == "ANALYST_DEFINED":
            add(
                "analyst_variant_perception",
                market_expectations.get("variant_perception"),
                unit="text",
                period_end=market_expectations.get("as_of_date", ""),
                as_of_date=market_expectations.get("as_of_date", ""),
                measurement_basis="analyst-owned differentiated view",
                source_level=0,
                source_type="analyst_owned_input",
                source_name=market_expectations.get("reviewed_by"),
                source_url="",
                source_locator="research_input.market_expectations.variant_perception",
                source_tag="analyst_input",
                evidence_class="JUDGMENT",
                input_ids=[expectation_id],
                confidence=market_expectations.get("confidence", "Medium"),
                notes=f"Variant question: {market_expectations.get('variant_question')}",
            )

    all_known_records = (
        list(step2.get("evidence_records", step2.get("data_points", [])))
        + list(additional_records or [])
        + records
    )
    known_ids = {
        row.get("evidence_id")
        for row in all_known_records
        if row.get("evidence_id")
    }
    key_to_id = {
        str(row.get("external_key")): str(row.get("evidence_id"))
        for row in all_known_records
        if row.get("external_key") and row.get("evidence_id")
    }
    metric_to_id = {
        str(row.get("metric_name")): str(row.get("evidence_id"))
        for row in all_known_records
        if row.get("metric_name") and row.get("evidence_id")
    }
    normalized = research_input.get("normalized_fcf", {})
    normalized_evidence_id: str | None = None
    scenario_metric_basis_ids: list[str] = []
    if normalized.get("status") == "VALIDATED":
        base_metric = str(normalized.get("base_evidence_metric") or "")
        base_id = str(normalized.get("base_evidence_id") or metric_to_id.get(base_metric, ""))
        bridge_lines = normalized.get("bridge_lines", [])
        bridge_ids: list[str] = []
        for line in bridge_lines:
            resolved_id = str(line.get("evidence_id") or key_to_id.get(str(line.get("evidence_key") or ""), ""))
            if resolved_id:
                bridge_ids.append(resolved_id)
        unknown_keys = [
            f"external_key:{line.get('evidence_key')}"
            for line in bridge_lines
            if line.get("evidence_key") and str(line.get("evidence_key")) not in key_to_id
        ]
        if base_metric and base_metric not in metric_to_id:
            unknown_keys.append(f"metric_name:{base_metric}")
        unknown = sorted((({base_id} | set(bridge_ids)) - known_ids) | set(unknown_keys))
        record_by_id = {
            row.get("evidence_id"): row
            for row in all_known_records
            if row.get("evidence_id")
        }
        base_value = safe_float(record_by_id.get(base_id, {}).get("value"))
        adjustment_values = [safe_float(line.get("amount")) for line in bridge_lines]
        malformed_lines = [
            index
            for index, line in enumerate(bridge_lines, start=1)
            if not line.get("label")
            or not (line.get("evidence_id") or line.get("evidence_key"))
            or safe_float(line.get("amount")) is None
            or line.get("evidence_class") not in {"FACT", "CALC", "JUDGMENT"}
            or not isinstance(line.get("embedded_in_cfo"), bool)
            or not isinstance(line.get("separately_modeled"), bool)
        ]
        double_count_lines = [
            index
            for index, line in enumerate(bridge_lines, start=1)
            if line.get("embedded_in_cfo") and line.get("separately_modeled") and not line.get("reversal_id")
        ]
        normalized_value = safe_float(normalized.get("value"))
        bridge_total = base_value + sum(value or 0.0 for value in adjustment_values) if base_value is not None else None
        bridge_reconciles = (
            normalized_value is not None
            and bridge_total is not None
            and abs(normalized_value - bridge_total) <= max(1.0, abs(normalized_value) * 1e-9)
        )
        base_period_end = record_by_id.get(base_id, {}).get("period_end")
        no_adjustment_support = not bridge_lines and bool(normalized.get("no_adjustments_rationale"))
        integrity_failed = (
            not normalized.get("reviewed_by")
            or normalized_value is None
            or not base_id
            or base_id != reported_ltm_fcf_id
            or bool(unknown)
            or bool(malformed_lines)
            or bool(double_count_lines)
            or not bridge_reconciles
            or normalized.get("period_end") != base_period_end
            or (not bridge_lines and not no_adjustment_support)
        )
        if integrity_failed:
            issues.append(
                {
                    "check_id": "G2.5-normalized-fcf-bridge-integrity",
                    "category": "valuation",
                    "status": "FAIL",
                    "issue_class": "HARD_STOP",
                    "severity": "Critical",
                    "message": (
                        "Normalized FCF was marked VALIDATED but the bridge failed integrity checks. "
                        f"Unknown IDs={unknown}; malformed lines={malformed_lines}; double-count lines={double_count_lines}; "
                        f"base ID matches reported FCF={base_id == reported_ltm_fcf_id}; bridge reconciles={bridge_reconciles}; "
                        f"period matches={normalized.get('period_end') == base_period_end}."
                    ),
                    "decision_impact": "Normalized FCF and all dependent scenario outputs are not reproducible.",
                    "remediation": "Use the reported LTM FCF evidence ID or metric name as the base; provide sourced adjustment lines, signs, CFO treatment, explicit reversals, matching period, reconciliation, and reviewer ownership.",
                    "evidence_ids": [item for item in [base_id, *bridge_ids] if item],
                    "scope": "shared_investment_analysis_engine",
                }
            )
        else:
            normalized_evidence_id = add(
                "public_data_fcf_underwriting_base",
                normalized.get("value"),
                unit=str(valuation.get("price_currency") or "").upper(),
                currency=str(valuation.get("price_currency") or "").upper(),
                period_end=normalized.get("period_end", ""),
                period_type="normalized",
                measurement_basis="public-data FCF underwriting bridge",
                source_level=0,
                source_type="analyst_owned_input",
                source_name=normalized.get("reviewed_by"),
                source_url="",
                source_locator="research_input.normalized_fcf",
                source_tag="analyst_input",
                evidence_class="JUDGMENT",
                input_ids=[base_id, *bridge_ids],
                confidence=normalized.get("confidence", "Medium"),
                notes=(
                    "Calculation validation is separate from economic normalization status; "
                    "inspect bridge lines, unresolved items, and rationale."
                ),
            )
            scenario_metric_basis_ids = [normalized_evidence_id]

    scenario_model_input = research_input.get("scenario_model", {})
    scenario_metric_name = str(scenario_model_input.get("metric") or "").upper()
    if scenarios and scenario_metric_name not in {
        "NORMALIZED FCF",
        "PUBLIC-DATA FCF UNDERWRITING BASE",
    }:
        metric_basis_input = (
            scenario_model_input.get("metric_basis", {})
            if isinstance(scenario_model_input.get("metric_basis"), dict)
            else {}
        )
        scenario_metric_basis_ids = _unique_text(
            metric_basis_input.get("evidence_ids", [])
        )
        unknown_metric_basis_ids = sorted(
            set(scenario_metric_basis_ids) - known_ids
        )
        if (
            metric_basis_input.get("status") != "VALIDATED"
            or not metric_basis_input.get("reviewed_by")
            or not scenario_metric_basis_ids
            or unknown_metric_basis_ids
        ):
            issues.append(
                {
                    "check_id": "G2.5-scenario-metric-basis-integrity",
                    "category": "valuation",
                    "status": "FAIL",
                    "issue_class": "HARD_STOP",
                    "severity": "Critical",
                    "message": (
                        "The non-FCF scenario metric basis is not fully validated or contains "
                        f"unknown evidence IDs: {unknown_metric_basis_ids}."
                    ),
                    "decision_impact": (
                        "Scenario prices cannot be treated as reproducible without a validated "
                        "company-agnostic metric basis."
                    ),
                    "remediation": (
                        "Provide a positive metric-basis value, unit, currency, source evidence, "
                        "period, named reviewer, and a reconciled scenario growth bridge."
                    ),
                    "evidence_ids": [
                        value
                        for value in scenario_metric_basis_ids
                        if value in known_ids
                    ],
                    "scope": "shared_investment_analysis_engine",
                }
            )
            scenario_metric_basis_ids = []

    for scenario in scenarios:
        scenario.evidence_ids = _unique_text(
            [price_id, shares_id, *scenario_metric_basis_ids]
        )

    valuation_input = research_input.get("valuation_framework", {})
    if valuation_input.get("status") == "VALIDATED":
        if not valuation_input_is_structurally_complete(research_input):
            issues.append(
                {
                    "check_id": "G3-valuation-input-integrity",
                    "category": "valuation",
                    "status": "FAIL",
                    "issue_class": "HARD_STOP",
                    "severity": "Critical",
                    "message": "Valuation was marked VALIDATED but method, reverse valuation, sensitivity rows, or reviewer ownership is structurally incomplete.",
                    "decision_impact": "Reverse valuation and implied prices are not reproducible.",
                    "remediation": "Use a supported method and complete the exact reverse-valuation formula, selected multiple, required metric, assumptions, three or more sensitivity rows, and reviewer.",
                    "evidence_ids": [],
                    "scope": "shared_investment_analysis_engine",
                }
            )
        else:
            reverse = valuation_input["reverse_valuation"]
            selected_multiple = safe_float(reverse.get("selected_multiple"))
            required_metric = safe_float(reverse.get("required_metric_value"))
            expected_required_metric = (
                safe_float(valuation.get("market_cap")) / selected_multiple
                if safe_float(valuation.get("market_cap")) is not None and selected_multiple not in (None, 0)
                else None
            )
            reverse_reconciles = (
                required_metric is not None
                and expected_required_metric is not None
                and abs(required_metric - expected_required_metric) <= max(1.0, abs(required_metric) * 1e-9)
            )
            sensitivity_errors: list[int] = []
            for index, row in enumerate(valuation_input.get("sensitivity_table", []), start=1):
                metric_value = safe_float(row.get("metric_value"))
                multiple = safe_float(row.get("multiple"))
                implied_price = safe_float(row.get("implied_price"))
                expected_price = (
                    metric_value * multiple / safe_float(valuation.get("shares"))
                    if metric_value is not None and multiple is not None and safe_float(valuation.get("shares")) not in (None, 0)
                    else None
                )
                if implied_price is None or expected_price is None or abs(implied_price - expected_price) > max(0.01, abs(implied_price) * 1e-9):
                    sensitivity_errors.append(index)
            resolved_reverse_ids, unknown_reverse_ids = resolve_evidence_references(
                reverse.get("evidence_ids", []),
                reverse.get("evidence_keys", []),
                known_ids,
                key_to_id,
                reverse.get("evidence_metrics", []),
                metric_to_id,
            )
            reverse_evidence_ids = sorted(resolved_reverse_ids)
            if not reverse_reconciles or sensitivity_errors or unknown_reverse_ids:
                issues.append(
                    {
                        "check_id": "G3-reverse-valuation-reproducibility",
                        "category": "valuation",
                        "status": "FAIL",
                        "issue_class": "HARD_STOP",
                        "severity": "Critical",
                        "message": f"Reverse valuation failed reproduction. Reverse reconciles={reverse_reconciles}; sensitivity errors={sensitivity_errors}; unknown evidence IDs={unknown_reverse_ids}.",
                        "decision_impact": "Required metric and sensitivity-implied prices cannot support Gate 3.",
                        "remediation": "Recalculate required metric as market cap divided by selected multiple and every sensitivity price as metric value times multiple divided by shares.",
                        "evidence_ids": reverse_evidence_ids,
                        "scope": "shared_investment_analysis_engine",
                    }
                )
            else:
                valuation_currency = str(
                    valuation.get("price_currency") or ""
                ).upper()
                multiple_id = add(
                    "reverse_valuation_selected_multiple",
                    selected_multiple,
                    unit="pure",
                    period_end=valuation.get("price_date", ""),
                    as_of_date=valuation.get("price_date", ""),
                    measurement_basis=valuation_input.get("method"),
                    source_level=0,
                    source_type="analyst_owned_input",
                    source_name=valuation_input.get("reviewed_by"),
                    source_url="",
                    source_locator="research_input.valuation_framework.reverse_valuation.selected_multiple",
                    source_tag="analyst_input",
                    evidence_class="JUDGMENT",
                    input_ids=reverse_evidence_ids,
                    confidence="Medium",
                    notes="Analyst-selected multiple; assumptions=" + json.dumps(reverse.get("assumptions", []), ensure_ascii=False),
                )
                reverse_metric_id = add(
                    "reverse_valuation_required_metric_value",
                    required_metric,
                    unit=valuation_currency,
                    currency=valuation_currency,
                    period_end=valuation.get("price_date", ""),
                    as_of_date=valuation.get("price_date", ""),
                    measurement_basis=valuation_input.get("method"),
                    source_level=0,
                    source_type="calculation_from_analyst_input",
                    source_name="Shared investment analysis engine",
                    source_url="",
                    source_locator="market_cap / selected_multiple",
                    source_tag="calculation",
                    evidence_class="CALC",
                    formula="market_cap_point_in_time / reverse_valuation_selected_multiple",
                    input_ids=[market_cap_id, multiple_id],
                    confidence="Medium",
                )
                for index, row in enumerate(valuation_input.get("sensitivity_table", []), start=1):
                    metric_input_id = add(
                        f"sensitivity_{index}_metric_value",
                        row.get("metric_value"),
                        unit=valuation_currency,
                        currency=valuation_currency,
                        period_end=valuation.get("price_date", ""),
                        as_of_date=valuation.get("price_date", ""),
                        measurement_basis=valuation_input.get("method"),
                        source_level=0,
                        source_type="analyst_owned_input",
                        source_name=valuation_input.get("reviewed_by"),
                        source_url="",
                        source_locator=f"research_input.valuation_framework.sensitivity_table[{index - 1}].metric_value",
                        source_tag="analyst_input",
                        evidence_class="JUDGMENT",
                    )
                    sensitivity_multiple_id = add(
                        f"sensitivity_{index}_multiple",
                        row.get("multiple"),
                        unit="pure",
                        period_end=valuation.get("price_date", ""),
                        as_of_date=valuation.get("price_date", ""),
                        measurement_basis=valuation_input.get("method"),
                        source_level=0,
                        source_type="analyst_owned_input",
                        source_name=valuation_input.get("reviewed_by"),
                        source_url="",
                        source_locator=f"research_input.valuation_framework.sensitivity_table[{index - 1}].multiple",
                        source_tag="analyst_input",
                        evidence_class="JUDGMENT",
                    )
                    add(
                        f"sensitivity_{index}_implied_price",
                        row.get("implied_price"),
                        unit=f"{valuation_currency}/share",
                        currency=valuation_currency,
                        period_end=valuation.get("price_date", ""),
                        as_of_date=valuation.get("price_date", ""),
                        measurement_basis=valuation_input.get("method"),
                        source_level=0,
                        source_type="calculation_from_analyst_input",
                        source_name="Shared investment analysis engine",
                        source_url="",
                        source_locator=f"research_input.valuation_framework.sensitivity_table[{index - 1}]",
                        source_tag="calculation",
                        evidence_class="CALC",
                        formula="metric_value * multiple / shares_outstanding_point_in_time",
                        input_ids=[metric_input_id, sensitivity_multiple_id, shares_id],
                        confidence="Medium",
                    )
                for scenario in scenarios:
                    scenario.evidence_ids.extend([multiple_id, reverse_metric_id])

    scenario_model = research_input.get("scenario_model", {})
    if scenario_model.get("status") == "ANALYST_VALIDATED" and not scenarios:
        issues.append(
            {
                "check_id": "G3-scenario-reproducibility",
                "category": "scenario_analysis",
                "status": "FAIL",
                "issue_class": "HARD_STOP",
                "severity": "Critical",
                "message": f"Scenario model was marked ANALYST_VALIDATED but could not be reproduced: {scenario_model.get('status')} / no validated scenario rows.",
                "decision_impact": "Scenario target prices and returns must remain suppressed.",
                "remediation": "Correct normalized metric, Bear/Base/Bull values, growth bridges, exit multiples, and reviewer ownership.",
                "evidence_ids": [],
                "scope": "shared_investment_analysis_engine",
            }
        )
    elif scenarios and scenario_metric_basis_ids and valuation_input_is_structurally_complete(research_input) and not any(
        issue.get("issue_class") == "HARD_STOP" for issue in issues
    ):
        scenario_rows = {row.get("name"): row for row in scenario_model.get("scenarios", [])}
        share_input = (
            research_input.get("share_count_basis", {})
            if isinstance(research_input.get("share_count_basis"), dict)
            else {}
        )
        forward_share_basis_id = ""
        forward_share_evidence_ids = [
            str(value)
            for value in share_input.get("forward_share_count_evidence_ids", [])
            if value
        ]
        if (
            share_input.get("forward_share_count_bridge_status") == "COMPLETED"
            and forward_share_evidence_ids
            and scenarios
            and all(
                safe_float(row.share_count_basis_value)
                == safe_float(share_input.get("forward_share_count_value"))
                and row.share_count_basis_date
                == str(share_input.get("forward_share_count_date") or "")
                for row in scenarios
            )
        ):
            forward_share_basis_id = add(
                "forward_share_count_basis",
                share_input.get("forward_share_count_value"),
                unit="shares",
                period_end=str(share_input.get("forward_share_count_date") or ""),
                as_of_date=str(share_input.get("forward_share_count_date") or ""),
                measurement_basis="reviewed forward share-count bridge",
                source_level=0,
                source_type="analyst_owned_calculation",
                source_name=share_input.get("reviewed_by"),
                source_url="",
                source_locator="research_input.share_count_basis.forward_share_count_value",
                source_tag="analyst_input",
                evidence_class="CALC",
                formula="reviewed forward share-count bridge output",
                input_ids=forward_share_evidence_ids,
                confidence="Medium",
            )
        weighted_probability_ids: list[str] = []
        weighted_price_ids: list[str] = []
        valuation_contract_input = (
            research_input.get("valuation_contract", {})
            if isinstance(research_input.get("valuation_contract"), dict)
            else {}
        )
        scenario_output_date = (
            valuation_contract_input.get("target_date")
            or valuation.get("price_date", "")
        )
        price_currency = str(valuation.get("price_currency") or "").upper()
        for scenario in scenarios:
            inputs = scenario_rows.get(scenario.name, {})
            metric_period_end = (
                scenario.metric_period.get("end_date")
                or scenario_output_date
            )
            probability_id = ""
            if scenario.probability is not None:
                probability_id = add(
                    f"scenario_{scenario.name.lower()}_probability",
                    scenario.probability,
                    unit="pure",
                    period_end=probability_validation.get("as_of_date") or valuation.get("price_date", ""),
                    as_of_date=probability_validation.get("as_of_date") or valuation.get("price_date", ""),
                    measurement_basis=f"{probability_validation.get('status')} probability input",
                    source_level=0,
                    source_type="analyst_owned_input",
                    source_name=probability_validation.get("reviewed_by") or scenario_model.get("reviewed_by"),
                    source_url="",
                    source_locator=f"research_input.scenario_model.{scenario.name}.probability",
                    source_tag="analyst_input",
                    evidence_class="JUDGMENT",
                    input_ids=probability_validation.get("method_evidence_ids", []),
                    validation_status="PASS" if probability_validation.get("status") == "VALIDATED" else "PROVISIONAL",
                    notes=probability_validation.get("scenario_rationales", {}).get(scenario.name, "Probability rationale not validated."),
                )
                weighted_probability_ids.append(probability_id)
            metric_id = add(
                f"scenario_{scenario.name.lower()}_metric_value",
                inputs.get("metric_value_total"),
                unit=scenario.metric_unit,
                currency=scenario.metric_currency,
                period_end=metric_period_end,
                as_of_date=scenario_output_date,
                measurement_basis="analyst-owned scenario",
                source_level=0,
                source_type="analyst_owned_input",
                source_name=scenario_model.get("reviewed_by"),
                source_url="",
                source_locator=f"research_input.scenario_model.{scenario.name}.metric_value_total",
                source_tag="analyst_input",
                evidence_class="JUDGMENT",
                input_ids=scenario_metric_basis_ids,
            )
            scenario_multiple_id = add(
                f"scenario_{scenario.name.lower()}_exit_multiple",
                scenario.exit_multiple,
                unit="pure",
                period_end=scenario_output_date,
                as_of_date=scenario_output_date,
                measurement_basis="analyst-owned scenario",
                source_level=0,
                source_type="analyst_owned_input",
                source_name=scenario_model.get("reviewed_by"),
                source_url="",
                source_locator=f"research_input.scenario_model.{scenario.name}.exit_multiple",
                source_tag="analyst_input",
                evidence_class="JUDGMENT",
            )
            implied_price_id = add(
                f"scenario_{scenario.name.lower()}_implied_price",
                scenario.target_price,
                unit=f"{price_currency}/share",
                currency=price_currency,
                period_end=scenario_output_date,
                as_of_date=scenario_output_date,
                measurement_basis="analyst-owned scenario",
                source_level=0,
                source_type="calculation_from_analyst_input",
                source_name="Shared investment analysis engine",
                source_url="",
                source_locator=f"scenario {scenario.name} implied price",
                source_tag="calculation",
                evidence_class="CALC",
                formula=(
                    "scenario_metric_value / forward_share_count_basis * scenario_exit_multiple"
                    if forward_share_basis_id
                    else "scenario_metric_value / shares_outstanding_point_in_time * scenario_exit_multiple"
                ),
                input_ids=[
                    metric_id,
                    forward_share_basis_id or shares_id,
                    scenario_multiple_id,
                ],
                confidence=scenario.confidence,
            )
            price_change_id = add(
                f"scenario_{scenario.name.lower()}_price_change_vs_current",
                scenario.total_return,
                unit="pure",
                period_end=scenario_output_date,
                as_of_date=scenario_output_date,
                measurement_basis="analyst-owned scenario",
                source_level=0,
                source_type="calculation_from_analyst_input",
                source_name="Shared investment analysis engine",
                source_url="",
                source_locator=f"scenario {scenario.name} price change versus current price",
                source_tag="calculation",
                evidence_class="CALC",
                formula="scenario_implied_price / market_price_unadjusted_close - 1",
                input_ids=[implied_price_id, price_id],
                confidence=scenario.confidence,
            )
            weighted_price_ids.append(implied_price_id)
            scenario.evidence_ids.extend(
                [
                    value
                    for value in [
                        probability_id,
                        metric_id,
                        scenario_multiple_id,
                        forward_share_basis_id,
                        implied_price_id,
                        price_change_id,
                    ]
                    if value
                ]
            )
        if probability_validation.get("status") == "VALIDATED":
            add(
                "probability_weighted_implied_price_sensitivity",
                weighted_implied_price(scenarios),
                unit=f"{price_currency}/share",
                currency=price_currency,
                period_end=scenario_output_date,
                as_of_date=scenario_output_date,
                measurement_basis="validated probability-weighted price sensitivity",
                source_level=0,
                source_type="calculation_from_analyst_input",
                source_name="Shared investment analysis engine",
                source_url="",
                source_locator="sum(scenario_probability * scenario_implied_price)",
                source_tag="calculation",
                evidence_class="CALC",
                formula="sum(scenario_probability * scenario_implied_price)",
                input_ids=[*weighted_probability_ids, *weighted_price_ids],
                confidence="Medium",
            )
    elif scenario_model.get("status") == "ANALYST_VALIDATED":
        issues.append(
            {
                "check_id": "G3-scenario-dependency-integrity",
                "category": "scenario_analysis",
                "status": "FAIL",
                "issue_class": "HARD_STOP",
                "severity": "Critical",
                "message": "Scenario rows were calculable, but normalized FCF or valuation dependencies did not pass evidence validation.",
                "decision_impact": "Scenario target prices and returns are not added to the evidence layer.",
                "remediation": "Resolve normalized FCF and reverse-valuation Hard Stops before scenario evidence is generated.",
                "evidence_ids": [],
                "scope": "shared_investment_analysis_engine",
            }
        )

    return records, sorted(sources.values(), key=lambda row: row["source_id"]), issues


def build_validation_gates(
    step2: dict[str, Any],
    market_snapshot: dict[str, Any],
    valuation: dict[str, Any],
    scenarios: list[Scenario],
    scenario_status: str,
    opportunity: dict[str, Any],
    market_expectations: dict[str, Any],
) -> list[ValidationGate]:
    raise RuntimeError("Deprecated validation path. Use build_system_validation_gates().")
    gates: list[ValidationGate] = []
    step2_failures = [v for v in step2.get("validation_tests", []) if v.get("result") == "FAIL"]

    gates.append(
        ValidationGate(
            "S3-step2-foundation",
            "PASS" if not step2_failures else "BLOCKED",
            "P0" if step2_failures else "INFO",
            "Step 2 validation failures: " + str(len(step2_failures)),
            "Do not build an investment view on unreconciled filing data." if step2_failures else "Step 3 can use Step 2 data with remaining caveats.",
            "Fix Step 2 validation failures before relying on valuation or scenarios.",
        )
    )
    gates.append(
        ValidationGate(
            "S3-market-price",
            "PASS" if market_snapshot.get("status") == "PASS" and valuation.get("price") is not None else "BLOCKED",
            "P0",
            f"Provider={market_snapshot.get('provider')}; price={price_label(valuation.get('price'))}; date={valuation.get('price_date') or 'n/a'}",
            "Price is required for market cap, current valuation, and scenario return.",
            "Retrieve a current public market price or manually provide a sourced price/date.",
        )
    )
    gates.append(
        ValidationGate(
            "S3-share-count",
            "PASS" if valuation.get("shares") else "BLOCKED",
            "P0",
            f"Shares used={valuation.get('shares') or 'n/a'}; source={source_label(valuation.get('shares_source'))}",
            "Shares are required for market cap and per-share scenario outputs.",
            "Use latest SEC common shares outstanding or manually provide a sourced diluted/share-count basis.",
        )
    )
    core_ltm_ok = valuation.get("ltm_revenue") is not None and (
        valuation.get("ltm_fcf") is not None or valuation.get("ltm_net_income") is not None
    )
    gates.append(
        ValidationGate(
            "S3-ltm-metrics",
            "PASS" if core_ltm_ok else "BLOCKED",
            "P0",
            f"Revenue={fmt_usd(valuation.get('ltm_revenue'))}; FCF={fmt_usd(valuation.get('ltm_fcf'))}; net income={fmt_usd(valuation.get('ltm_net_income'))}",
            "LTM metrics are needed to avoid mixing quarterly, YTD, and annual denominators.",
            "Complete LTM construction from latest annual plus latest YTD minus prior-year YTD, or use a clearly labeled annual fallback.",
        )
    )
    valuation_ok = any(valuation.get(name) is not None for name in ("p_fcf", "pe", "ev_sales", "ev_operating_income"))
    gates.append(
        ValidationGate(
            "S3-valuation-denominators",
            "PASS" if valuation_ok else "BLOCKED",
            "P1",
            f"P/FCF={multiple_label(valuation.get('p_fcf'))}; P/E={multiple_label(valuation.get('pe'))}; EV/Sales={multiple_label(valuation.get('ev_sales'))}",
            "At least one valuation anchor is needed before investment action language.",
            "If earnings/FCF are negative, use an explicit asset, revenue, or turnaround framework rather than forcing P/E or P/FCF.",
        )
    )
    gates.append(
        ValidationGate(
            "S3-scenario-assumptions",
            "PASS" if scenario_status == "analyst_supplied" else ("PROVISIONAL" if scenario_status == "public_data_derived" else "BLOCKED"),
            "P1" if scenario_status == "public_data_derived" else "P0",
            f"Scenario status={scenario_status}; scenario rows={len(scenarios)}",
            "Public-data scenarios can support underwriting prioritization, but not final trade action without analyst review.",
            "Replace or confirm public-data assumptions with analyst-supplied drivers, normalized metrics, exit multiples, probabilities, and falsification triggers.",
        )
    )
    gates.append(
        ValidationGate(
            "S3-consensus-or-expectations",
            "PASS" if market_expectations.get("consensus_status") == "SOURCED" else "PROVISIONAL",
            "P1",
            f"Market expectation status={market_expectations.get('status')}; consensus={market_expectations.get('consensus_status')}; confidence={market_expectations.get('confidence')}",
            "Public market proxies help frame expectations, but paid/sourced consensus would improve variant perception.",
            "Add sourced consensus, management guidance, peer/historical multiples, or a clearly documented expectation proxy if available.",
        )
    )
    gates.append(
        ValidationGate(
            "S3-opportunity-cost",
            "PASS" if opportunity.get("status") == "PASS" else "MISSING",
            "P2",
            f"Stock 12m={percent_label(opportunity.get('stock_12m_return'))}; {SPY_TICKER} 12m={percent_label(opportunity.get('benchmark_12m_return'))}",
            "Opportunity cost helps decide whether this idea deserves capital versus public alternatives.",
            "If benchmark data is missing, supply a relevant index, sector ETF, cash hurdle, or comparable watchlist alternative.",
        )
    )
    gates.append(
        ValidationGate(
            "S3-portfolio-context",
            "BLOCKED",
            "P1",
            "No fund-specific exposure, risk limit, liquidity, concentration, or target-return constraint was provided.",
            "Position sizing cannot be reliable without portfolio context.",
            "Add target return hurdle, max loss, liquidity budget, sector exposure, concentration limits, and current holdings overlap.",
        )
    )
    gates.append(
        ValidationGate(
            "S3-action-gate",
            "PROVISIONAL" if scenario_status == "public_data_derived" and valuation_ok else "BLOCKED",
            "P1" if scenario_status == "public_data_derived" and valuation_ok else "P0",
            "Public-data valuation, market expectation proxy, and scenario shell are available; portfolio context remains incomplete.",
            "The output can support underwriting priority, not final buy/sell/hold or position sizing.",
            "Complete partner portfolio overlay before turning research-support action into portfolio action.",
        )
    )
    return gates


def final_action_view(gates: list[ValidationGate], scenarios: list[Scenario], scenario_status: str) -> tuple[str, str, str, str]:
    raise RuntimeError("Deprecated action path. Use determine_data_gate() and action_for_gate().")
    blocked_p0 = [g for g in gates if g.result == "BLOCKED" and g.severity == "P0"]
    if blocked_p0:
        return "Watch / Need More Work", "No position sizing", "Low", "P0 data gaps remain."
    if scenario_status != "public_data_derived" and scenario_status != "analyst_supplied":
        return "Watch / Need More Work", "No position sizing", "Low", "Scenario model is not usable."

    expected = legacy_weighted_price_change(scenarios)
    bear = next((s.total_return for s in scenarios if s.name == "Bear"), None)
    bull = next((s.total_return for s in scenarios if s.name == "Bull"), None)
    if expected is None or bear is None or bull is None:
        return "Watch / Need More Work", "No position sizing", "Low", "Risk/reward cannot be calculated."

    if expected >= 0.15 and bear >= -0.30 and bull >= 0.25:
        return (
            "Potential Long to Underwrite",
            "No position sizing until partner portfolio overlay is completed",
            "Medium",
            "Public-data scenario clears a preliminary return hurdle; still requires consensus, thesis, and portfolio review.",
        )
    if expected >= 0.08 and bear >= -0.35:
        return (
            "Watch / Need More Work",
            "No position sizing",
            "Medium",
            "Public-data scenario is not strong enough for action, but may be worth deeper underwriting.",
        )
    if expected < 0 or bear < -0.35:
        return (
            "Watch / Need More Work",
            "No position sizing",
            "Low",
            "Public-data scenario does not yet show attractive risk/reward.",
        )
    return (
        "Watch / Need More Work",
        "No position sizing",
        "Low",
        "Public-data scenario is inconclusive.",
    )


def build_committee_roles(
    valuation: dict[str, Any],
    scenarios: list[Scenario],
    opportunity: dict[str, Any],
    market_expectations: dict[str, Any],
    probability_validation: dict[str, Any],
    action_view: str,
    action_confidence: str,
    action_rationale: str,
) -> list[CommitteeRole]:
    weighted_price = (
        weighted_implied_price(scenarios)
        if probability_validation.get("status") == "VALIDATED"
        else None
    )
    bear = next((s.total_return for s in scenarios if s.name == "Bear"), None)
    bull_price = next((s.target_price for s in scenarios if s.name == "Bull"), None)
    bull_change = next((s.total_return for s in scenarios if s.name == "Bull"), None)

    return [
        CommitteeRole(
            role="Fundamental Analyst",
            view="Credit/liquidity data can inform underwriting, but the investment case is not complete.",
            evidence=(
                f"LTM revenue={fmt_usd(valuation.get('ltm_revenue'))}; "
                f"LTM FCF={fmt_usd(valuation.get('ltm_fcf'))}; "
                f"net debt before facility={fmt_usd(valuation.get('net_debt_before_facility'))}."
            ),
            decision_impact="Use the credit/liquidity work to identify binding constraints and downside risks before valuation work.",
            confidence="Medium" if valuation.get("ltm_revenue") is not None else "Low",
            falsification_trigger="New filing data, refinancing, covenant issues, or working-capital deterioration changes the liquidity path.",
        ),
        CommitteeRole(
            role="Market Expectations Analyst",
            view=market_expectations.get("summary_view", "Market expectations are available only through public proxies."),
            evidence=(
                f"Price={price_label(valuation.get('price'))}; "
                f"P/FCF={multiple_label(valuation.get('p_fcf'))}; "
                f"P/E={multiple_label(valuation.get('pe'))}; "
                f"EV/Sales={multiple_label(valuation.get('ev_sales'))}; "
                f"variant question={market_expectations.get('variant_question')}."
            ),
            decision_impact="Use this to decide what the market may already be pricing before writing a variant perception.",
            confidence=market_expectations.get("confidence", "Low"),
            falsification_trigger="Consensus/guidance or peer work shows the market is already pricing the same upside/downside view.",
        ),
        CommitteeRole(
            role="Bull Case",
            view="The upside case is a public-data hypothesis to underwrite, not a final conclusion.",
            evidence=(
                f"Bull implied-price sensitivity={price_label(bull_price)}; "
                f"price change vs current={percent_label(bull_change)}; "
                f"probability-weighted implied-price sensitivity={price_label(weighted_price)}; "
                f"probability status={probability_validation.get('status')}."
            ),
            decision_impact="Potential upside is useful only after confirming or replacing public-data assumptions with company-specific drivers and catalysts.",
            confidence="Low",
            falsification_trigger="Normalized FCF, margins, growth, or multiple support fails under sourced assumptions.",
        ),
        CommitteeRole(
            role="Bear Case",
            view="The downside case should focus on cash-flow durability, working-capital stress, liquidity uses, and valuation compression.",
            evidence=(
                f"Bear price change vs current={percent_label(bear)}; "
                f"net debt/FCF={multiple_label(valuation.get('net_debt_to_fcf'))}; "
                f"FCF yield={percent_label(valuation.get('fcf_yield'))}."
            ),
            decision_impact="Downside must be explicit before sizing; credit comfort alone is not enough.",
            confidence="Low" if scenarios else "Medium",
            falsification_trigger="Scenario downside, liquidity runway, or refinancing stress is worse than the draft model allows.",
        ),
        CommitteeRole(
            role="Risk Manager",
            view="Action language should remain constrained until public-data scenarios are reviewed and portfolio context is added.",
            evidence="Scenario assumptions are public-data derived; partner portfolio context is still a blocked validation gate.",
            decision_impact="Prevent false certainty and keep the memo in research-support mode.",
            confidence="High",
            falsification_trigger="All P0 gates clear with sourced valuation, scenario, consensus, and downside evidence.",
        ),
        CommitteeRole(
            role="Portfolio Manager",
            view=action_view,
            evidence=(
                f"Action confidence={action_confidence}; "
                f"relative 12m return vs {SPY_TICKER}={percent_label(opportunity.get('relative_12m_return'))}; "
                f"rationale={action_rationale}"
            ),
            decision_impact="No sizing until target return, downside, liquidity, and opportunity cost are portfolio-aware.",
            confidence=action_confidence,
            falsification_trigger="Sourced scenario return clears hurdle and beats alternatives after risk and portfolio constraints.",
        ),
    ]


def validation_report(company: dict[str, Any], gates: list[ValidationGate]) -> str:
    lines = [
        f"# {company['name']} ({company['ticker']}) Step 3 Validation Report",
        "",
        f"Generated: {utc_now()}",
        "",
        "| Gate | Result | Class | Severity | Evidence | Decision Impact | Remediation |",
        "|---|---|---|---|---|---|---|",
    ]
    for gate in gates:
        lines.append(
            f"| {gate.gate_id} | {gate.result} | {gate.issue_class} | {gate.severity} | {gate.evidence} | {gate.decision_impact} | {gate.remediation} |"
        )
    return "\n".join(lines) + "\n"


def valuation_rows(valuation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"metric": "Current price", "value": valuation.get("price"), "display": price_label(valuation.get("price")), "use": "Entry price"},
        {"metric": "Shares used", "value": valuation.get("shares"), "display": f"{valuation.get('shares') / 1_000_000:,.1f}m" if valuation.get("shares") else "n/a", "use": "Market cap denominator"},
        {"metric": "Market cap", "value": valuation.get("market_cap"), "display": fmt_usd(valuation.get("market_cap")), "use": "Equity value"},
        {"metric": "Enterprise value proxy", "value": valuation.get("enterprise_value_proxy"), "display": fmt_usd(valuation.get("enterprise_value_proxy")), "use": "Market cap + debt + leases - cash/STI; facility availability excluded"},
        {"metric": "Cash + short-term investments", "value": valuation.get("cash_and_short_term_investments"), "display": fmt_usd(valuation.get("cash_and_short_term_investments")), "use": "Liquid resources before facility note review"},
        {"metric": "Total debt", "value": valuation.get("total_debt"), "display": fmt_usd(valuation.get("total_debt")), "use": "Funded debt pressure"},
        {"metric": "Lease liabilities", "value": valuation.get("lease_liabilities"), "display": fmt_usd(valuation.get("lease_liabilities")), "use": "Debt-like fixed obligations"},
        {"metric": "Net debt before facility", "value": valuation.get("net_debt_before_facility"), "display": fmt_usd(valuation.get("net_debt_before_facility")), "use": "Leverage / downside context"},
        {"metric": "LTM revenue", "value": valuation.get("ltm_revenue"), "display": fmt_usd(valuation.get("ltm_revenue")), "use": "Scale and EV/Sales denominator"},
        {"metric": "LTM operating income", "value": valuation.get("ltm_operating_income"), "display": fmt_usd(valuation.get("ltm_operating_income")), "use": "Operating earnings denominator"},
        {"metric": "LTM net income", "value": valuation.get("ltm_net_income"), "display": fmt_usd(valuation.get("ltm_net_income")), "use": "P/E denominator when positive"},
        {"metric": "LTM CFO", "value": valuation.get("ltm_cfo"), "display": fmt_usd(valuation.get("ltm_cfo")), "use": "Cash generation"},
        {"metric": "LTM capex", "value": valuation.get("ltm_capex"), "display": fmt_usd(valuation.get("ltm_capex")), "use": "FCF bridge"},
        {"metric": "LTM FCF", "value": valuation.get("ltm_fcf"), "display": fmt_usd(valuation.get("ltm_fcf")), "use": "Cash-flow valuation denominator"},
        {"metric": "P/E", "value": valuation.get("pe"), "display": multiple_label(valuation.get("pe")), "use": "Market-implied earnings multiple"},
        {"metric": "P/FCF", "value": valuation.get("p_fcf"), "display": multiple_label(valuation.get("p_fcf")), "use": "Market-implied cash-flow multiple"},
        {"metric": "FCF yield", "value": valuation.get("fcf_yield"), "display": percent_label(valuation.get("fcf_yield")), "use": "Cash return before growth"},
        {"metric": "EV/Sales", "value": valuation.get("ev_sales"), "display": multiple_label(valuation.get("ev_sales")), "use": "Revenue valuation anchor"},
        {"metric": "EV/Operating income", "value": valuation.get("ev_operating_income"), "display": multiple_label(valuation.get("ev_operating_income")), "use": "Operating earnings valuation anchor"},
        {"metric": "Net debt/FCF", "value": valuation.get("net_debt_to_fcf"), "display": multiple_label(valuation.get("net_debt_to_fcf")), "use": "Balance-sheet pressure versus cash generation"},
    ]


def build_markdown(
    company: dict[str, Any],
    out_dir: Path,
    market_snapshot: dict[str, Any],
    benchmark_snapshot: dict[str, Any],
    valuation: dict[str, Any],
    drivers: dict[str, Any],
    market_expectations: dict[str, Any],
    scenarios: list[Scenario],
    scenario_status: str,
    gates: list[ValidationGate],
    committee: list[CommitteeRole],
    action_view: str,
    sizing_view: str,
    action_confidence: str,
    action_rationale: str,
    opportunity: dict[str, Any],
) -> str:
    raise RuntimeError("Deprecated renderer. Render the validated shared output contract instead.")
    expected = legacy_weighted_price_change(scenarios)
    bear = next((s.total_return for s in scenarios if s.name == "Bear"), None)
    bull = next((s.total_return for s in scenarios if s.name == "Bull"), None)

    valuation_table = [
        "| Metric | Value | Decision Use |",
        "|---|---:|---|",
    ]
    for row in valuation_rows(valuation):
        valuation_table.append(f"| {row['metric']} | {row['display']} | {row['use']} |")

    driver_table = [
        "| Driver | Value | Evidence | Decision Use |",
        "|---|---:|---|---|",
    ]
    for row in drivers.get("rows", []):
        driver_table.append(
            f"| {row.get('driver')} | {row.get('display')} | {row.get('evidence')} | {row.get('decision_use')} |"
        )

    expectation_table = [
        "| Indicator | Value | Interpretation | Evidence Type |",
        "|---|---:|---|---|",
    ]
    for indicator in market_expectations.get("indicators", []):
        expectation_table.append(
            f"| {indicator.get('indicator')} | {indicator.get('display')} | {indicator.get('interpretation')} | {indicator.get('evidence_type')} |"
        )

    scenario_table = [
        "| Scenario | Probability | Metric | Growth | Exit Multiple | Target Price | Return | Key Driver | Status |",
        "|---|---:|---|---:|---:|---:|---:|---|---|",
    ]
    if scenarios:
        for scenario in scenarios:
            scenario_table.append(
                "| "
                + " | ".join(
                    [
                        scenario.name,
                        percent_label(scenario.probability),
                        scenario.metric,
                        percent_label(scenario.growth_assumption),
                        multiple_label(scenario.exit_multiple),
                        price_label(scenario.target_price),
                        percent_label(scenario.total_return),
                        scenario.key_driver,
                        scenario.assumption_status,
                    ]
                )
                + " |"
            )
    else:
        scenario_table.append("| n/a | n/a | n/a | n/a | n/a | n/a | n/a | MISSING | Blocked: missing price, shares, or positive valuation metric |")

    committee_table = [
        "| Role | View | Evidence | Decision Impact | Confidence |",
        "|---|---|---|---|---|",
    ]
    for role in committee:
        committee_table.append(
            f"| {role.role} | {role.view} | {role.evidence} | {role.decision_impact} | {role.confidence} |"
        )

    gate_table = [
        "| Gate | Result | Severity | Evidence |",
        "|---|---|---|---|",
    ]
    for gate in gates:
        gate_table.append(f"| {gate.gate_id} | {gate.result} | {gate.severity} | {gate.evidence} |")

    blocked_gates = [gate.gate_id for gate in gates if gate.result == "BLOCKED"]

    lines = [
        f"# {company['name']} ({company['ticker']}) Step 3 Investment Decision-Support Layer",
        "",
        f"Generated: {utc_now()}",
        "Scope: Public SEC data plus public market data. This is decision support, not a formal trade instruction.",
        "",
        "## Decision Strip",
        "",
        f"- Action view: {action_view}",
        f"- Sizing view: {sizing_view}",
        f"- Confidence: {action_confidence}",
        "- Time horizon: 12-month investment view plus 2-3 year business-quality context.",
        f"- Current price: {price_label(valuation.get('price'))}",
        f"- Market cap: {fmt_usd(valuation.get('market_cap'))}",
        f"- Enterprise value proxy: {fmt_usd(valuation.get('enterprise_value_proxy'))}",
        f"- Probability-weighted return from public-data scenario: {percent_label(expected)}",
        f"- Bear downside / bull upside from public-data scenario: {percent_label(bear)} / {percent_label(bull)}",
        f"- Action rationale: {action_rationale}",
        f"- Blocked gates: {', '.join(blocked_gates) if blocked_gates else 'None'}",
        "",
        "## What This Supports Now",
        "",
        "- It supports investment research prioritization, public-data valuation framing, preliminary risk/reward diligence, and memo drafting.",
        "- It can indicate whether a company is worth underwriting further from public data.",
        "- It does not support final buy/sell/hold or position sizing until partner portfolio context and analyst-reviewed assumptions are added.",
        "",
        "## Market Expectations / Variant Perception",
        "",
        f"- Status: {market_expectations.get('status')} / consensus: {market_expectations.get('consensus_status')}.",
        f"- Summary view: {market_expectations.get('summary_view')}",
        f"- Variant question: {market_expectations.get('variant_question')}",
        "",
        *expectation_table,
        "",
        "## Valuation and Trailing Metrics",
        "",
        *valuation_table,
        "",
        "## Public-Data Drivers",
        "",
        *driver_table,
        "",
        "## Probability-Weighted Public-Data Scenario",
        "",
        f"Scenario status: {scenario_status}. These assumptions are derived from public data and must be reviewed before becoming a final investment case.",
        "",
        *scenario_table,
        "",
        "## Target Return and Action Gate",
        "",
        "- A potential long needs sourced variant perception, normalized earnings/FCF, downside case, catalyst path, and probability-weighted return above the fund's hurdle.",
        f"- Current action gate result: {action_view}.",
        "- The public-data model can support underwriting priority, but final action and sizing remain blocked until analyst review and partner portfolio overlay are complete.",
        "",
        "## Portfolio Opportunity Cost",
        "",
        f"- 12-month stock return: {percent_label(opportunity.get('stock_12m_return'))}.",
        f"- 12-month {SPY_TICKER} return: {percent_label(opportunity.get('benchmark_12m_return'))}.",
        f"- Relative 12-month return vs {SPY_TICKER}: {percent_label(opportunity.get('relative_12m_return'))}.",
        "- Opportunity-cost check: capital should go here only if expected return, downside protection, and catalyst quality beat cash, index exposure, and watchlist alternatives.",
        "",
        "## Investment Committee Snapshot",
        "",
        *committee_table,
        "",
        "## Step 3 Validation Gates",
        "",
        *gate_table,
        "",
        "## Partner Portfolio Overlay",
        "",
        "- Public-data mode can prioritize underwriting, but portfolio action needs fund-specific context.",
        "- Use `partner_overlay_template.csv` or `partner_overlay_template.md` in this folder to add target return, downside tolerance, existing exposure, sizing range, and opportunity-cost alternatives.",
        "- Until that overlay is completed, sizing remains blocked even if the public-data scenario looks attractive.",
        "",
        "## Required Inputs Before Stronger Action Language",
        "",
        "1. Analyst review of public-data scenario assumptions, including normalized earnings/FCF and exit multiple.",
        "2. Sourced consensus, management guidance, peer/historical multiples, or a stronger market-expectation proxy if available.",
        "3. Company-specific catalysts and thesis-break triggers.",
        "4. Peer/historical multiple context or a different valuation framework when earnings/FCF are not meaningful.",
        "5. Portfolio target return, max loss, liquidity, exposure, concentration, and opportunity-cost constraints.",
        "",
        "## Source Links",
        "",
        f"- Step 2 data pack: {out_dir / 'investment_data_pack.md'}",
        f"- SEC company ticker file: {TICKER_SOURCE}",
        f"- SEC companyfacts: https://data.sec.gov/api/xbrl/companyfacts/CIK{company['cik']}.json",
        f"- Market data provider: {market_snapshot.get('provider')} ({market_snapshot.get('source_url')})",
        f"- Benchmark data provider: {benchmark_snapshot.get('provider')} ({benchmark_snapshot.get('source_url')})",
        "",
    ]
    return "\n".join(lines)


def write_dict_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        fieldnames = keys or ["status"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def partner_overlay_rows() -> list[dict[str, Any]]:
    return [
        {
            "field": "overlay_mode",
            "example_or_default": "REAL_PARTNER_INPUT",
            "why_needed": "Illustrative inputs can demonstrate workflow but cannot unlock Gate 4.",
            "sensitivity": "Low",
            "partner_input": "",
        },
        {
            "field": "input_status",
            "example_or_default": "VALIDATED",
            "why_needed": "Confirms the fund-specific inputs were reviewed before use.",
            "sensitivity": "Low",
            "partner_input": "",
        },
        {
            "field": "reviewed_by",
            "example_or_default": "Human reviewer name or role",
            "why_needed": "Records ownership of portfolio assumptions.",
            "sensitivity": "Low/Medium",
            "partner_input": "",
        },
        {
            "field": "target_return_hurdle",
            "example_or_default": "15%-20% expected return",
            "why_needed": "Determines whether public-data scenario return is attractive enough.",
            "sensitivity": "Low if expressed as policy, higher if tied to live portfolio.",
            "partner_input": "",
        },
        {
            "field": "max_bear_case_downside",
            "example_or_default": "-20% to -30%",
            "why_needed": "Controls whether downside is tolerable before underwriting.",
            "sensitivity": "Low/Medium",
            "partner_input": "",
        },
        {
            "field": "intended_holding_period",
            "example_or_default": "6-12 months / 12-24 months / 3 years",
            "why_needed": "Matches scenario horizon to the fund's investment process.",
            "sensitivity": "Low",
            "partner_input": "",
        },
        {
            "field": "portfolio_role",
            "example_or_default": "core long / tactical long / hedge monitor / watchlist only",
            "why_needed": "Changes required conviction, catalyst, and risk tolerance.",
            "sensitivity": "Medium",
            "partner_input": "",
        },
        {
            "field": "existing_exposure",
            "example_or_default": "none / existing position / sector exposure",
            "why_needed": "Needed before any sizing or incremental-capital decision.",
            "sensitivity": "High if position-specific; can be anonymized.",
            "partner_input": "",
        },
        {
            "field": "max_position_size",
            "example_or_default": "0.5%-2% starter / 3%-5% core",
            "why_needed": "Prevents the memo from implying sizing outside risk limits.",
            "sensitivity": "Medium/High",
            "partner_input": "",
        },
        {
            "field": "opportunity_cost_alternatives",
            "example_or_default": "SPY, sector ETF, watchlist names, existing holdings",
            "why_needed": "Tests whether the idea beats real alternatives.",
            "sensitivity": "Medium/High if watchlist is proprietary.",
            "partner_input": "",
        },
        {
            "field": "internal_variant_view",
            "example_or_default": "What do we believe that market consensus may miss?",
            "why_needed": "Turns public-data analysis into an investable thesis.",
            "sensitivity": "High",
            "partner_input": "",
        },
        {
            "field": "internal_thesis_break",
            "example_or_default": "Revenue miss, margin compression, leverage trigger, catalyst failure",
            "why_needed": "Defines when to stop underwriting or reduce exposure.",
            "sensitivity": "Medium",
            "partner_input": "",
        },
        {
            "field": "human_approval",
            "example_or_default": "NOT_REVIEWED / APPROVED",
            "why_needed": "Portfolio action and position range remain hidden without explicit human approval.",
            "sensitivity": "Low",
            "partner_input": "",
        },
        {
            "field": "approved_by",
            "example_or_default": "Approver name or role",
            "why_needed": "Identifies the owner of the final portfolio decision.",
            "sensitivity": "Low/Medium",
            "partner_input": "",
        },
        {
            "field": "approved_portfolio_action",
            "example_or_default": "Leave blank until human-approved",
            "why_needed": "The system displays an approved action; it does not invent one.",
            "sensitivity": "High",
            "partner_input": "",
        },
        {
            "field": "approved_position_range",
            "example_or_default": "Leave blank until human-approved",
            "why_needed": "The system displays a human-approved range only after Gate 4.",
            "sensitivity": "High",
            "partner_input": "",
        },
    ]


def partner_overlay_markdown(company: dict[str, Any]) -> str:
    lines = [
        f"# {company['name']} ({company['ticker']}) Partner Portfolio Overlay Template",
        "",
        "Fill this only if the public-data memo should be converted into a portfolio-aware decision view.",
        "Do not paste sensitive holdings or client data into external tools unless explicitly authorized.",
        "",
        "| Field | Example / Default | Why Needed | Sensitivity | Partner Input |",
        "|---|---|---|---|---|",
    ]
    for row in partner_overlay_rows():
        lines.append(
            f"| {row['field']} | {row['example_or_default']} | {row['why_needed']} | {row['sensitivity']} |  |"
        )
    lines.extend(
        [
            "",
            "## How To Use",
            "",
            "1. Leave sensitive fields blank if they cannot be shared.",
            "2. Use ranges or anonymized labels when exact portfolio data is not appropriate.",
            "3. After completion, rerun the decision overlay or manually update the Portfolio Manager section.",
            "",
        ]
    )
    return "\n".join(lines)


def action_for_gate(gate: dict[str, Any]) -> tuple[str, str, str]:
    level = float(gate.get("level", 0))
    if level == 0:
        return (
            "Data Validation Failed",
            "Formal issuer and investment conclusions are blocked until the listed Hard Stops are resolved.",
            "No position sizing",
        )
    if level == 1:
        return (
            "Preliminary Screen / Need More Work",
            "Core data can support a preliminary description, but issuer underwriting is not complete.",
            "No position sizing",
        )
    if level == 2.5:
        return (
            "Continue Research / Valuation Incomplete",
            "Issuer underwriting is complete, but normalized FCF, market expectations, valuation, or scenarios remain unvalidated.",
            "No position sizing",
        )
    if level == 3:
        return (
            "Ready for Human Investment Review",
            "Valuation and scenario outputs are reproducible, but the system does not replace the analyst's investment decision and has no portfolio mandate.",
            "No position sizing until Gate 4",
        )
    return (
        "Ready for Human Portfolio Decision",
        "Validated portfolio inputs are available; a human owner must still approve any action.",
        "Use only the human-approved position range",
    )


def build_contract_markdown(contract: dict[str, Any]) -> str:
    company = contract["company"]
    question = contract["investment_question"]
    confidence = contract["decision_confidence"]
    gate = contract["data_gate"]
    lines = [
        f"# {company['name']} ({company['ticker']}) Public-Company Underwriting Output",
        "",
        f"Schema: {contract['schema_version']} | Report ID: {contract['report_id']}",
        f"Data Gate: **{gate['label']}**",
        f"Current action: **{contract['current_action']}**",
        f"Decision Confidence: **{confidence['level']}**",
        "",
        "## Investment Question / 投资问题",
        "",
        f"- {question['text']}",
        f"- Status: {question['status']}",
        "",
        "## What Can Be Concluded / 目前可以得出的结论",
        "",
    ]
    lines.extend(f"- {item}" for item in contract.get("what_can_be_concluded", []))
    lines.extend(["", "## What Cannot Be Concluded / 目前不能得出的结论", ""])
    lines.extend(f"- {item}" for item in contract.get("what_cannot_be_concluded", []))
    lines.extend(["", "## Key Debates / 核心争议", ""])
    for debate in contract.get("key_debates", []):
        lines.extend(
            [
                f"### {debate['title']}",
                f"- Market / conventional view: {debate['market_view']}",
                f"- Alternative view: {debate['alternative_view']}",
                f"- Missing evidence: {debate['missing_evidence']}",
                f"- Resolving KPI or event: {debate['resolution_kpi_or_event']}",
                f"- Decision impact: {debate['decision_impact']}",
                "",
            ]
        )
    lines.extend(["## Issuer Underwriting Status / 发行人分析状态", ""])
    lines.extend(["| Module | Status | Conclusion |", "|---|---|---|"])
    for name, module in contract.get("issuer_underwriting", {}).get("modules", {}).items():
        lines.append(f"| {name} | {module.get('status')} | {module.get('conclusion')} |")
    lines.extend(["", "## Validation / 验证", ""])
    lines.extend(
        [
            f"- Hard Stops: {len(contract.get('hard_stops', []))}",
            f"- Warnings: {len(contract.get('warnings', []))}",
            f"- Contract validation: {contract.get('contract_validation', {}).get('status', 'pending')}",
            "",
            "## Evidence Required Next / 下一步所需证据",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in contract.get("evidence_required_next", []))
    lines.extend(["", "## Portfolio Overlay / 组合叠加", ""])
    lines.append("- Portfolio Decision: Not Evaluated unless Gate 4 is complete and human approval is recorded.")
    return "\n".join(lines) + "\n"


def build_unsupported_investment_output(step2: dict[str, Any], out_dir: Path) -> Path:
    """Create a formal Gate 0 diagnostic without running an invalid overlay."""

    company = step2["company"]
    support = step2.get("supported_universe", {})
    hard_stops = list(step2.get("hard_stops", []))
    missing = [
        f"Specialized {support.get('overlay_required', 'issuer')} overlay.",
        *support.get("reasons", []),
    ]
    gate = {
        "level": 0,
        "label": "Gate 0 - Specialized overlay required",
        "allowed_outputs": ["diagnostic_validation_report", "missing_information", "source_status"],
        "prohibited_outputs": [
            "automatic_trade",
            "credit_constraint_conclusion",
            "expected_return",
            "final_investment_action",
            "issuer_risk_judgment",
            "portfolio_action",
            "position_sizing",
            "target_price",
        ],
        "hard_stop_ids": [item.get("check_id", item.get("id")) for item in hard_stops],
    }
    reason = " ".join(support.get("reasons", [])) or "The issuer is outside the supported public-company core."
    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_id": stable_id("RPT", company.get("cik"), "unsupported", SCHEMA_VERSION),
        "company": company,
        "build_date": utc_now(),
        "report_dates": {**step2.get("as_of_registry", {}), "analysis_generated_at": utc_now()},
        "supported_universe": support,
        "investment_question": {"text": "Not Defined", "status": "NOT_DEFINED", "evidence_class": "MISSING"},
        "key_debates": [],
        "data_gate": gate,
        "validation_status": "FAIL",
        "decision_confidence": {"level": "Low", "limitations": [reason]},
        "current_action": "Specialized Overlay Required",
        "current_action_rationale": reason,
        "core_investment_view": "No issuer or investment conclusion is permitted under the current accounting overlay.",
        "what_can_be_concluded": ["The issuer is outside the supported non-financial US GAAP 10-K/10-Q core workflow."],
        "what_cannot_be_concluded": ["Issuer risk, valuation, expected return, target price, or position size."],
        "evidence_required_next": missing,
        "issuer_underwriting": {"status": "BLOCKED", "required_modules": [], "modules": {}, "complete": False},
        "market_snapshot": {},
        "benchmark_snapshot": {},
        "valuation": {},
        "public_data_drivers": {"rows": []},
        "market_expectations": {"status": "NOT_SOURCED", "consensus_status": "NOT_SOURCED", "variant_status": "NOT_DEFINED"},
        "peer_valuation_context": {"status": "UNAVAILABLE", "rows": [], "metric_summaries": []},
        "fcf_quality_assessment": {
            "status": "NOT_VALIDATED",
            "rating": "Not Evaluated",
            "cash_conversion_confidence": "Low",
            "evidence_class": "MISSING",
        },
        "investment_decision_summary": {
            "status": "NOT_VALIDATED",
            "current_action": "Continue Research",
            "current_view": "No investment conclusion is permitted under the current accounting overlay.",
            "evidence_class": "MISSING",
        },
        "scenario_status": "blocked_supported_universe",
        "scenarios": [],
        "probability_validation": {
            "status": "NOT_PROVIDED",
            "weighted_return_allowed": False,
            "freshness_status": "NOT_APPLICABLE",
        },
        "probability_weighted_return": None,
        "target_price": None,
        "opportunity_cost": {"status": "NOT_EVALUATED"},
        "validation_gates": [],
        "validation_issues": list(step2.get("validation_tests", [])),
        "hard_stops": hard_stops,
        "warnings": list(step2.get("warnings", [])),
        "committee": [],
        "action_view": "Specialized Overlay Required",
        "sizing_view": "Not Evaluated",
        "action_confidence": "Low",
        "action_rationale": reason,
        "decision_rules": {"status": "MISSING", "upgrade_conditions": [], "downgrade_conditions": [], "thesis_invalidation_conditions": []},
        "catalysts": [],
        "thesis_breaks": [],
        "liquidity_status": {"status": "NOT_EVALUATED"},
        "credit_constraint_status": {"status": "NOT_EVALUATED"},
        "capital_allocation_status": {"status": "NOT_EVALUATED"},
        "management_guidance_status": {"status": "NOT_EVALUATED"},
        "normalized_fcf_status": {"status": "NOT_VALIDATED"},
        "valuation_status": {"status": "NOT_VALIDATED"},
        "position_sizing": None,
        "portfolio_action": "Not Evaluated",
        "portfolio_context": {"status": "DISABLED"},
        "source_registry": list(step2.get("source_registry", [])),
        "source_log_references": [],
        "evidence_records": list(step2.get("evidence_records", [])),
        "external_evidence_index": [],
        "cash_flow_ledger": list(step2.get("cash_flow_ledger", [])),
        "known_facts": [],
        "calculated_metrics": [],
        "inferences": [],
        "judgments": [],
        "missing_information": missing,
        "final_investment_action": "Not Evaluated",
        "limitations": [reason],
    }
    payload = apply_friday_v1_contract_semantics(payload, {})
    payload = finalize_output_contract(payload)
    step3_dir = out_dir / "step3"
    step3_dir.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    for name in ("step3_data.json", "investment_layer.json", "underwriting_output_contract.json"):
        (step3_dir / name).write_text(serialized, encoding="utf-8")
    (step3_dir / "analyst_input_template.json").write_text(
        json.dumps(analyst_input_template(company, payload["evidence_records"]), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (step3_dir / "step3_validation_report.md").write_text(
        f"# {company['name']} ({company['ticker']})\n\nGate 0: {reason}\n",
        encoding="utf-8",
    )
    (step3_dir / "investment_layer.md").write_text(build_contract_markdown(payload), encoding="utf-8")
    return step3_dir


def build_investment_layer(
    company_query: str,
    out_root: Path = DEFAULT_OUT_ROOT,
    research_input_path: Path | None = None,
) -> Path:
    out_dir = build_company_pack(company_query, out_root)
    step2 = read_step2_json(out_dir)
    company = step2["company"]
    research_input = load_research_input(research_input_path)
    if step2.get("supported_universe", {}).get("status") != "SUPPORTED_CORE":
        return build_unsupported_investment_output(step2, out_dir)

    companyfacts = fetch_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{company['cik']}.json")
    market_snapshot = get_price_snapshot(company["ticker"])
    benchmark_snapshot = get_price_snapshot(SPY_TICKER)
    market_approval = research_input.get("market_data_approval", {})
    if (
        market_approval.get("status") in APPROVED_MARKET_DATA_STATUSES
        and market_approval.get("provider") == market_snapshot.get("provider") == benchmark_snapshot.get("provider")
        and bool(market_approval.get("scope"))
        and bool(market_approval.get("reviewed_by"))
    ):
        approval_status = market_approval["status"]
        market_snapshot["provider_approval_status"] = approval_status
        benchmark_snapshot["provider_approval_status"] = approval_status
        market_snapshot["source_level"] = 3
        benchmark_snapshot["source_level"] = 3
        market_snapshot["provider_approval_reviewer"] = market_approval["reviewed_by"]
        benchmark_snapshot["provider_approval_reviewer"] = market_approval["reviewed_by"]
        market_snapshot["provider_approval_scope"] = market_approval["scope"]
        benchmark_snapshot["provider_approval_scope"] = market_approval["scope"]

    valuation = build_valuation(step2, companyfacts, market_snapshot)
    drivers = build_public_data_drivers(step2, companyfacts, valuation)
    opportunity = build_opportunity_cost(market_snapshot, benchmark_snapshot)
    external_records, external_sources, external_evidence_issues = build_external_evidence(company, research_input)
    foundational_records = list(step2.get("evidence_records", step2.get("data_points", []))) + external_records
    preliminary_market_expectations = build_market_expectations(
        valuation,
        market_snapshot,
        opportunity,
        research_input,
        foundational_records,
    )
    investment_question = build_investment_question(research_input)
    preliminary_share_basis = build_share_count_basis(
        {
            "valuation": valuation,
            "report_dates": {"market_price_date": valuation.get("price_date")},
            "evidence_records": foundational_records,
        },
        research_input,
    )
    scenarios, scenario_status = scenario_set(
        valuation,
        drivers,
        preliminary_market_expectations,
        research_input,
        preliminary_share_basis,
    )
    preliminary_probability_validation = build_probability_validation(
        research_input,
        scenarios,
        foundational_records,
        str(valuation.get("price_date") or datetime.now(UTC).date().isoformat()),
    )
    preliminary_analysis_records, _, _ = build_analysis_evidence(
        company,
        step2,
        market_snapshot,
        benchmark_snapshot,
        valuation,
        opportunity,
        preliminary_market_expectations,
        scenarios,
        preliminary_probability_validation,
        research_input,
        external_records,
    )
    resolution_records = foundational_records + preliminary_analysis_records
    market_expectations = build_market_expectations(
        valuation,
        market_snapshot,
        opportunity,
        research_input,
        resolution_records,
    )
    probability_validation = build_probability_validation(
        research_input,
        scenarios,
        resolution_records,
        str(valuation.get("price_date") or datetime.now(UTC).date().isoformat()),
    )
    analysis_records, analysis_sources, analysis_evidence_issues = build_analysis_evidence(
        company,
        step2,
        market_snapshot,
        benchmark_snapshot,
        valuation,
        opportunity,
        market_expectations,
        scenarios,
        probability_validation,
        research_input,
        external_records,
    )
    all_supplemental_records = external_records + analysis_records
    all_analysis_records = list(step2.get("evidence_records", step2.get("data_points", []))) + all_supplemental_records
    peer_valuation_context = build_peer_valuation_context(research_input, all_analysis_records)
    fcf_quality_assessment = build_fcf_quality_assessment(research_input, all_analysis_records)
    investment_decision_summary = build_investment_decision_summary(research_input, all_analysis_records)
    key_debates = build_key_debates(step2, research_input, all_supplemental_records)
    issuer_underwriting = build_issuer_underwriting(
        step2,
        valuation,
        drivers,
        research_input,
        all_supplemental_records,
    )
    gates = build_system_validation_gates(
        step2,
        market_snapshot,
        valuation,
        opportunity,
        investment_question,
        key_debates,
        issuer_underwriting,
        market_expectations,
        scenario_status,
        probability_validation,
        peer_valuation_context,
        fcf_quality_assessment,
        investment_decision_summary,
        research_input,
    )
    upstream_validation_tests = reconcile_upstream_validation_tests(
        step2,
        issuer_underwriting,
        market_expectations,
        scenario_status,
        research_input,
        external_records,
    )
    issues = (
        upstream_validation_tests
        + gates_to_issues(gates)
        + issuer_underwriting.get("validation_issues", [])
        + market_expectations.get("validation_issues", [])
        + probability_validation.get("validation_issues", [])
        + peer_valuation_context.get("validation_issues", [])
        + fcf_quality_assessment.get("validation_issues", [])
        + investment_decision_summary.get("validation_issues", [])
        + external_evidence_issues
        + analysis_evidence_issues
    )
    core_data_validated = not any(
        issue.get("issue_class") == "HARD_STOP" and issue.get("status", issue.get("result")) in {"FAIL", "BLOCKED"}
        for issue in issues
    )
    normalized_fcf_validated = research_input.get("normalized_fcf", {}).get("status") == "VALIDATED"
    valuation_input = research_input.get("valuation_framework", {})
    market_expectations_validated = (
        market_expectations.get("consensus_status") == "SOURCED"
        and market_expectations.get("variant_status") == "ANALYST_DEFINED"
        and market_expectations.get("variant_structure_status") == "COMPLETE"
    )
    market_provider_approved = market_data_is_approved(market_snapshot)
    question_defined = investment_question["status"] == "ANALYST_DEFINED"
    key_debates_validated = 2 <= len(key_debates) <= 3 and all(
        debate.get("status") == "ANALYST_DEFINED" for debate in key_debates
    )
    decision_rules = research_input.get("decision_rules", {})
    decision_rules_validated = (
        decision_rules.get("status") == "VALIDATED"
        and bool(decision_rules.get("reviewed_by"))
        and bool(decision_rules.get("upgrade_conditions"))
        and bool(decision_rules.get("downgrade_conditions"))
        and bool(decision_rules.get("thesis_invalidation_conditions"))
    )
    valuation_validated = (
        normalized_fcf_validated
        and valuation_input_is_structurally_complete(research_input)
        and market_expectations_validated
        and market_provider_approved
        and question_defined
        and key_debates_validated
        and decision_rules_validated
        and fcf_quality_assessment.get("status") == "VALIDATED"
        and investment_decision_summary.get("status") == "VALIDATED"
    )
    scenarios_validated = scenario_status == "scenario_assumptions_validated"
    probabilities_validated = probability_validation.get("status") == "VALIDATED"
    portfolio_inputs_validated = research_input.get("portfolio_context", {}).get("status") == "VALIDATED"
    human_approval = (
        research_input.get("human_approval", {}).get("status") == "APPROVED"
        and bool(research_input.get("human_approval", {}).get("reviewed_by"))
    )
    data_gate = determine_data_gate(
        issues=issues,
        core_data_validated=core_data_validated,
        issuer_underwriting_complete=issuer_underwriting["complete"],
        valuation_validated=valuation_validated,
        scenarios_validated=scenarios_validated,
        portfolio_inputs_validated=portfolio_inputs_validated,
        human_approval=human_approval,
        probabilities_validated=probabilities_validated,
    )
    confidence = determine_decision_confidence(
        gate_level=float(data_gate["level"]),
        issues=issues,
        investment_question_defined=investment_question["status"] == "ANALYST_DEFINED",
        critical_assumptions_transparent=valuation_validated and scenarios_validated,
        disconfirming_evidence_considered=decision_rules_validated and all(
            debate.get("status") == "ANALYST_DEFINED" for debate in key_debates
        ),
    )
    action_view, action_rationale, sizing_view = action_for_gate(data_gate)
    action_confidence = confidence["level"]
    if data_gate["level"] >= 3:
        committee = build_committee_roles(
            valuation,
            scenarios,
            opportunity,
            market_expectations,
            probability_validation,
            action_view,
            action_confidence,
            action_rationale,
        )
    else:
        committee = [
            CommitteeRole(
                role="Committee Layer",
                view="Disabled below Gate 3.",
                evidence=f"Current Data Gate={data_gate['level']}.",
                decision_impact="Prevents incomplete valuation or scenario work from becoming an investment-committee conclusion.",
                confidence="High",
                falsification_trigger="Enable only after Gate 3 validation passes.",
            )
        ]

    step3_dir = out_dir / "step3"
    step3_dir.mkdir(parents=True, exist_ok=True)

    write_dict_csv(step3_dir / "valuation_metrics.csv", valuation_rows(valuation), ["metric", "display", "value", "use"])
    write_dict_csv(
        step3_dir / "public_data_drivers.csv",
        drivers.get("rows", []),
        ["driver", "display", "value", "evidence", "decision_use"],
    )
    write_dict_csv(
        step3_dir / "market_expectations.csv",
        market_expectations.get("indicators", []),
        ["indicator", "display", "value", "interpretation", "evidence_type", "source"],
    )
    scenario_csv_rows = [asdict(scenario) for scenario in scenarios]
    for row in scenario_csv_rows:
        row["implied_price"] = row.pop("target_price", None)
        row["price_change_vs_current"] = row.pop("total_return", None)
        row["formula"] = (
            "implied_price = metric_value_total / share_count_basis * scenario_multiple; "
            "price_change_vs_current = implied_price / dated_market_price - 1"
        )
    if data_gate["level"] < 3:
        for row in scenario_csv_rows:
            row["implied_price"] = None
            row["price_change_vs_current"] = None
    write_dict_csv(
        step3_dir / "scenario_model.csv",
        scenario_csv_rows or [{"name": "blocked", "notes": scenario_status}],
        [
            "name",
            "probability",
            "metric",
            "metric_per_share",
            "growth_assumption",
            "exit_multiple_factor",
            "exit_multiple",
            "implied_price",
            "price_change_vs_current",
            "evidence_type",
            "assumption_status",
            "confidence",
            "key_driver",
            "falsification_trigger",
            "assumption_sources",
            "probability_rationale",
            "notes",
            "evidence_ids",
            "formula",
        ],
    )
    write_dict_csv(
        step3_dir / "committee_snapshot.csv",
        [asdict(role) for role in committee],
        ["role", "view", "evidence", "decision_impact", "confidence", "falsification_trigger"],
    )
    write_dict_csv(
        step3_dir / "partner_overlay_template.csv",
        partner_overlay_rows(),
        ["field", "example_or_default", "why_needed", "sensitivity", "partner_input"],
    )
    (step3_dir / "partner_overlay_template.md").write_text(partner_overlay_markdown(company), encoding="utf-8")

    hard_stops = [
        issue
        for issue in issues
        if issue.get("issue_class") == "HARD_STOP" and issue.get("status", issue.get("result")) in {"FAIL", "BLOCKED"}
    ]
    warnings = [
        issue
        for issue in issues
        if issue.get("issue_class") == "WARNING"
        and issue.get("status", issue.get("result")) in {"FAIL", "BLOCKED", "MISSING", "PROVISIONAL", "WARNING"}
    ]
    missing_information = [
        gate.remediation for gate in gates if gate.result in {"MISSING", "WARNING", "BLOCKED"}
    ]
    what_can_be_concluded = [
        "The report may show only the outputs allowed by the current Data Gate.",
        "Period-aware SEC facts and calculations that pass validation remain traceable to stable evidence IDs.",
    ]
    if data_gate["level"] >= 2.5:
        what_can_be_concluded.append("Issuer underwriting is complete enough to identify the unresolved valuation question.")
    if data_gate["level"] >= 3:
        what_can_be_concluded.append("Validated Bear, Base, and Bull scenario prices may be presented for human investment review.")
    if data_gate["level"] >= 3 and probabilities_validated:
        what_can_be_concluded.append("Probability-weighted expected return may be presented because method, freshness, sensitivity, and approval passed validation.")
    what_cannot_be_concluded = []
    if data_gate["level"] < 2.5:
        what_cannot_be_concluded.append("Whether the issuer-level investment case is complete.")
    if data_gate["level"] < 3:
        what_cannot_be_concluded.extend(
            [
                "A target price, probability-weighted expected return, or final investment action.",
                "That a trailing multiple or 52-week price position proves what the market has priced in.",
            ]
        )
    elif not probabilities_validated:
        what_cannot_be_concluded.append(
            "A formal probability-weighted expected return; scenario weights remain unapproved or methodologically incomplete."
        )
    if data_gate["level"] < 4:
        what_cannot_be_concluded.append("Fund-specific position size, portfolio action, or opportunity-cost ranking.")

    report_id = stable_id(
        "RPT",
        company.get("cik"),
        step2.get("report_id"),
        valuation.get("price_date"),
        SCHEMA_VERSION,
    )
    evidence_records = (
        list(step2.get("evidence_records", step2.get("data_points", [])))
        + external_records
        + analysis_records
    )
    if data_gate["level"] < 3:
        suppressed_metric_names = {
            "probability_weighted_expected_return",
            "probability_weighted_implied_price_sensitivity",
            *{
                f"scenario_{name}_{suffix}"
                for name in ("bear", "base", "bull")
                for suffix in ("target_price", "total_return")
            },
        }
        suppressed_evidence_ids = {
            str(row.get("evidence_id"))
            for row in evidence_records
            if row.get("metric_name") in suppressed_metric_names and row.get("evidence_id")
        }
        evidence_records = [
            row for row in evidence_records if row.get("metric_name") not in suppressed_metric_names
        ]
        for scenario in scenarios:
            scenario.evidence_ids = [
                value for value in scenario.evidence_ids if value not in suppressed_evidence_ids
            ]
    source_registry_by_id = {
        row.get("source_id"): row
        for row in list(step2.get("source_registry", [])) + external_sources + analysis_sources
        if row.get("source_id")
    }
    source_registry = sorted(source_registry_by_id.values(), key=lambda row: row["source_id"])
    validated_valuation_framework = {
        "status": "NOT_VALIDATED",
        "method": valuation_input.get("method"),
        "reverse_valuation": {"status": "NOT_VALIDATED"},
        "sensitivity_completed": False,
        "sensitivity_table": [],
        "reviewed_by": None,
    }
    if data_gate["level"] >= 3 and valuation_validated:
        validated_valuation_framework = {
            "status": "VALIDATED",
            "method": valuation_input.get("method"),
            "reverse_valuation": valuation_input.get("reverse_valuation", {}),
            "sensitivity_completed": bool(valuation_input.get("sensitivity_completed")),
            "sensitivity_table": valuation_input.get("sensitivity_table", []),
            "reviewed_by": valuation_input.get("reviewed_by"),
        }
    public_data_conclusion = None
    if data_gate["level"] >= 3 and investment_decision_summary.get("status") == "VALIDATED":
        public_data_conclusion = investment_decision_summary.get("current_view")
    elif data_gate["level"] >= 3 and market_expectations.get("variant_status") == "ANALYST_DEFINED":
        public_data_conclusion = market_expectations.get("variant_perception")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "company": company,
        "build_date": utc_now(),
        "report_dates": {
            **step2.get("as_of_registry", {}),
            "market_price_date": valuation.get("price_date"),
            "share_count_date": valuation.get("shares_as_of_date"),
            "analysis_generated_at": utc_now(),
        },
        "supported_universe": step2.get("supported_universe", {}),
        "data_control_version": step2.get("data_control_version"),
        "notes_and_events_control_version": step2.get(
            "notes_and_events_control_version"
        ),
        "notes_and_events_assessment": step2.get(
            "notes_and_events_assessment",
            {},
        ),
        "investment_question": investment_question,
        "key_debates": key_debates,
        "data_gate": data_gate,
        "validation_status": "FAIL" if hard_stops else "PASS_WITH_WARNINGS" if warnings else "PASS",
        "decision_confidence": confidence,
        "current_action": action_view,
        "current_action_rationale": action_rationale,
        "core_investment_view": public_data_conclusion or action_rationale,
        "public_data_conclusion": public_data_conclusion,
        "what_can_be_concluded": what_can_be_concluded,
        "what_cannot_be_concluded": what_cannot_be_concluded,
        "evidence_required_next": missing_information,
        "issuer_underwriting": issuer_underwriting,
        "market_snapshot": {k: v for k, v in market_snapshot.items() if k != "history"},
        "benchmark_snapshot": {k: v for k, v in benchmark_snapshot.items() if k != "history"},
        "valuation": valuation,
        "valuation_framework": validated_valuation_framework,
        "peer_valuation_context": peer_valuation_context,
        "public_data_drivers": drivers,
        "market_expectations": market_expectations,
        "fcf_quality_assessment": fcf_quality_assessment,
        "investment_decision_summary": investment_decision_summary,
        "scenario_status": scenario_status,
        "scenarios": [asdict(s) for s in scenarios],
        "probability_validation": probability_validation,
        "probability_weighted_return": None,
        "target_price": None,
        "opportunity_cost": opportunity,
        "validation_gates": [asdict(g) for g in gates],
        "validation_issues": issues,
        "hard_stops": hard_stops,
        "warnings": warnings,
        "committee": [asdict(role) for role in committee],
        "action_view": action_view,
        "sizing_view": sizing_view,
        "action_confidence": action_confidence,
        "action_rationale": action_rationale,
        "decision_rules": {
            "status": "VALIDATED" if decision_rules_validated else "MISSING",
            "upgrade_conditions": decision_rules.get("upgrade_conditions", []),
            "downgrade_conditions": decision_rules.get("downgrade_conditions", []),
            "thesis_invalidation_conditions": decision_rules.get("thesis_invalidation_conditions", []),
        },
        "catalysts": research_input.get("catalysts", []),
        "thesis_breaks": decision_rules.get("thesis_invalidation_conditions", []),
        "liquidity_status": issuer_underwriting["modules"]["liquidity_sources_and_uses"],
        "credit_constraint_status": research_input.get("credit_constraint_status", {"status": "NOT_EVALUATED"}),
        "capital_allocation_status": issuer_underwriting["modules"]["capital_allocation"],
        "management_guidance_status": issuer_underwriting["modules"]["management_guidance_and_subsequent_events"],
        "normalized_fcf_status": research_input.get("normalized_fcf", {"status": "NOT_VALIDATED"}),
        "valuation_status": {
            "status": "VALIDATED" if valuation_validated else "NOT_VALIDATED",
            "trailing_observations_available": any(valuation.get(key) is not None for key in ("p_fcf", "pe", "ev_sales")),
        },
        "position_sizing": research_input.get("position_sizing") if data_gate["level"] >= 4 else None,
        "portfolio_action": research_input.get("portfolio_action", "Not Evaluated") if data_gate["level"] >= 4 else "Not Evaluated",
        "portfolio_context": research_input.get("portfolio_context", {"status": "DISABLED"}),
        "source_registry": source_registry,
        "source_log_references": [row.get("source_id") for row in source_registry],
        "evidence_records": evidence_records,
        "external_evidence_index": [
            {"external_key": row.get("external_key"), "evidence_id": row.get("evidence_id")}
            for row in external_records
        ],
        "cash_flow_ledger": step2.get("cash_flow_ledger", []),
        "known_facts": [row.get("evidence_id") for row in evidence_records if row.get("evidence_class") == "FACT"],
        "calculated_metrics": [row.get("evidence_id") for row in evidence_records if row.get("evidence_class") == "CALC"],
        "inferences": [debate["debate_id"] for debate in key_debates if debate.get("evidence_class") == "INFERENCE"],
        "judgments": ["investment_question"] if investment_question["evidence_class"] == "JUDGMENT" else [],
        "missing_information": missing_information,
        "final_investment_action": (
            "Not Evaluated"
            if data_gate["level"] < 3
            else investment_decision_summary.get("current_action", "Continue Research")
        ),
        "limitations": confidence["limitations"],
    }
    payload = apply_friday_v1_contract_semantics(payload, research_input)
    payload = finalize_output_contract(payload)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    (step3_dir / "step3_data.json").write_text(serialized, encoding="utf-8")
    (step3_dir / "investment_layer.json").write_text(serialized, encoding="utf-8")
    (step3_dir / "underwriting_output_contract.json").write_text(serialized, encoding="utf-8")
    (step3_dir / "analyst_input_template.json").write_text(
        json.dumps(analyst_input_template(company, evidence_records), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (step3_dir / "step3_validation_report.md").write_text(validation_report(company, gates), encoding="utf-8")
    (step3_dir / "investment_layer.md").write_text(build_contract_markdown(payload), encoding="utf-8")
    return step3_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Step 3 investment decision-support layer for a public company.")
    parser.add_argument("company", help="Ticker or company name.")
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT), help="Output root directory.")
    parser.add_argument("--research-input", help="Optional analyst-owned JSON input for question, underwriting, valuation, scenarios, and decision rules.")
    args = parser.parse_args()
    out = build_investment_layer(
        args.company,
        Path(args.out_root),
        Path(args.research_input) if args.research_input else None,
    )
    print(out)
    for name in (
        "investment_layer.md",
        "step3_data.json",
        "step3_validation_report.md",
        "valuation_metrics.csv",
        "public_data_drivers.csv",
        "market_expectations.csv",
        "scenario_model.csv",
        "committee_snapshot.csv",
        "partner_overlay_template.csv",
        "partner_overlay_template.md",
        "underwriting_output_contract.json",
        "analyst_input_template.json",
    ):
        path = out / name
        if path.exists():
            print(path)


if __name__ == "__main__":
    main()
