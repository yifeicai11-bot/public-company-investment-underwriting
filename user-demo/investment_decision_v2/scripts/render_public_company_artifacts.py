#!/usr/bin/env python3
"""Render bilingual public-company artifacts from one validated contract.

This module is a presentation layer. It formats validated outputs but does not
fetch data, create company facts, recalculate valuation, choose scenarios, or
change analytical meaning.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from underwriting_contract import validate_output_contract


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_ROOT = ROOT / "user-demo" / "investment_decision_v2" / "final_delivery"


METRIC_LABELS = {
    "market_price_unadjusted_close": "Dated market price / 市场价格",
    "shares_outstanding_point_in_time": "Shares outstanding / 流通股数",
    "market_cap_point_in_time": "Market capitalization / 市值",
    "latest_quarter_revenue": "Latest-quarter revenue / 最新季度收入",
    "latest_quarter_cfo": "Latest-quarter CFO / 最新季度经营现金流",
    "latest_quarter_fcf": "Latest-quarter FCF / 最新季度自由现金流",
    "accounts_receivable_net": "Net receivables / 应收账款净额",
    "allowance_for_credit_losses_ar": "A/R loss allowance / 应收信用损失准备",
    "inventory_net": "Inventory / 存货",
    "accounts_payable": "Accounts payable / 应付账款",
    "dso_avg_ar": "DSO / 应收周转天数",
    "dio_avg_inventory": "DIO / 存货周转天数",
    "dpo_avg_ap": "DPO / 应付周转天数",
    "cash_conversion_cycle": "Cash conversion cycle / 现金转换周期",
    "unrestricted_cash": "Unrestricted cash / 非受限现金",
    "total_available_borrowings_reported": "Reported borrowing availability / 披露可用借款",
    "available_liquidity_including_reported_facility": "Gross reported liquidity / 报告总流动性",
    "current_debt": "Current debt carrying value / 流动债务账面值",
    "long_term_debt": "Long-term debt carrying value / 长期债务账面值",
    "operating_lease_current": "Current operating lease liability / 流动经营租赁负债",
    "operating_lease_noncurrent": "Non-current operating lease liability / 非流动经营租赁负债",
    "purchase_commitments": "Purchase commitments / 采购承诺",
    "variable_rate_interest_sensitivity": "+100bp annual interest impact / 加息100bp年度利息影响",
    "valuation_basis_revenue": "LTM revenue / 过去十二个月收入",
    "valuation_basis_cfo": "LTM CFO / 过去十二个月经营现金流",
    "valuation_basis_capex": "LTM capex / 过去十二个月资本开支",
    "reported_ltm_fcf": "Reported LTM FCF / 报告口径过去十二个月FCF",
    "public_data_fcf_underwriting_base": "Public-Data FCF Underwriting Base / 公开数据FCF分析基准",
    "trailing_p_fcf": "Trailing reported P/FCF / 报告口径P/FCF",
    "trailing_fcf_yield": "Trailing reported FCF yield / 报告口径FCF收益率",
    "relative_12m_total_return": "12-month relative return vs SPY / 相对SPY的12个月回报",
    "factset_median_price_target": "FactSet median target / FactSet目标价中位数",
    "reverse_valuation_selected_multiple": "Reverse valuation multiple / 反向估值倍数",
    "reverse_valuation_required_metric_value": "FCF required at selected multiple / 选定倍数所需FCF",
}

MODULE_LABELS = {
    "business_and_industry": "Business and Industry / 业务与行业",
    "earnings_quality": "Earnings Quality / 盈利质量",
    "working_capital_and_cash_conversion": "Working Capital and Cash Conversion / 营运资金与现金转化",
    "liquidity_sources_and_uses": "Liquidity Sources and Uses / 流动性来源与用途",
    "debt_leases_covenants_refinancing": "Debt, Leases, Covenants and Refinancing / 债务、租赁、契约与再融资",
    "capital_allocation": "Capital Allocation / 资本配置",
    "management_guidance_and_subsequent_events": "Guidance and Subsequent Events / 指引与后续事项",
    "stress_test": "Stress Test / 压力测试",
}

ACTION_LABELS = {
    "Data Review Required": "Data Review Required / 需要数据复核",
    "Underwriting In Progress": "Underwriting In Progress / 分析进行中",
    "Ready for Human Review": "Ready for Human Review / 可供人工审阅",
    "Ready for Human Investment Review": "Ready for Human Investment Review / 可供人工投资审阅",
    "Preliminary Screen / Need More Work": "Preliminary Screen / Need More Work / 初步筛选，仍需完善",
    "Specialized Overlay Required": "Specialized Overlay Required / 需要专门分析叠加层",
    "Continue Research": "Continue Research / 继续研究",
    "Watch": "Watch / 观察",
    "Stop Research": "Stop Research / 停止研究",
    "Investment Case Strengthening": "Investment Case Strengthening / 投资逻辑增强",
    "Investment Case Weakening": "Investment Case Weakening / 投资逻辑减弱",
}

CONFIDENCE_LABELS = {"High": "High / 高", "Medium": "Medium / 中", "Low": "Low / 低"}

IMPORTANT_EVIDENCE_METRICS = [
    "market_price_unadjusted_close",
    "shares_outstanding_point_in_time",
    "market_cap_point_in_time",
    "public_data_fcf_underwriting_base",
    "reverse_valuation_selected_multiple",
    "reverse_valuation_required_metric_value",
]


def esc(value: Any) -> str:
    text = "" if value is None else str(value)
    # Keep contract field names stable, while using neutral language in rendered text.
    text = re.sub(r"\bpartner-approved\b", "approved", text, flags=re.IGNORECASE)
    text = re.sub(r"\bpartner overlay\b", "portfolio overlay", text, flags=re.IGNORECASE)
    text = re.sub(r"\bpartner preference\b", "user preference", text, flags=re.IGNORECASE)
    text = re.sub(r"\bPartner\b", "User", text)
    text = re.sub(r"\bpartner\b", "user", text)
    return html.escape(text)


def safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_money(value: Any, *, decimals: int = 1) -> str:
    number = safe_float(value)
    if number is None:
        return "n/a"
    sign = "-" if number < 0 else ""
    absolute = abs(number)
    if absolute >= 1_000_000_000:
        return f"{sign}$" + f"{absolute / 1_000_000_000:,.{decimals}f}bn"
    if absolute >= 1_000_000:
        return f"{sign}$" + f"{absolute / 1_000_000:,.{decimals}f}m"
    if absolute >= 1_000:
        return f"{sign}$" + f"{absolute / 1_000:,.{decimals}f}k"
    return f"{sign}$" + f"{absolute:,.{decimals}f}"


def fmt_number(value: Any, *, decimals: int = 1) -> str:
    number = safe_float(value)
    return "n/a" if number is None else f"{number:,.{decimals}f}"


def fmt_price(value: Any) -> str:
    number = safe_float(value)
    return "n/a" if number is None else "$" + f"{number:,.2f}"


def fmt_percent(value: Any, *, decimals: int = 1) -> str:
    number = safe_float(value)
    return "n/a" if number is None else f"{number * 100:,.{decimals}f}%"


def fmt_multiple(value: Any, *, decimals: int = 1) -> str:
    number = safe_float(value)
    return "n/a" if number is None else f"{number:,.{decimals}f}x"


def fmt_period(row: dict[str, Any]) -> str:
    start = row.get("period_start")
    end = row.get("period_end") or row.get("as_of_date")
    return f"{start} to {end}" if start else str(end or "n/a")


def fmt_record(row: dict[str, Any] | None, *, exact: bool = False) -> str:
    if not row:
        return "n/a"
    value = row.get("value")
    unit = row.get("unit")
    name = str(row.get("metric_name") or "")
    number = safe_float(value)
    if number is None:
        return esc(value) if value not in (None, "") else "n/a"
    if unit == "USD":
        return "$" + f"{number:,.0f}" if exact else fmt_money(number)
    if unit == "USD/year":
        return f"{fmt_money(number)}/year"
    if unit == "USD/share":
        return fmt_price(number)
    if unit == "shares":
        return f"{number / 1_000_000:,.1f}m"
    if unit == "days":
        return f"{number:,.1f} days / 天"
    if unit == "pure":
        if any(token in name for token in ("return", "yield", "position", "growth", "probability")):
            return fmt_percent(number)
        return fmt_multiple(number)
    return f"{number:,.3f}" if exact else f"{number:,.1f}"


def shorten(value: Any, limit: int = 240) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def load_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_output_contract(payload)
    stored = payload.get("contract_validation", {})
    if stored.get("status") != "PASS":
        errors.extend(stored.get("errors", []))
    if errors:
        payload.setdefault("render_blockers", []).extend(sorted(set(errors)))
    return payload


def evidence_by_metric(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("metric_name")): row
        for row in contract.get("evidence_records", [])
        if row.get("metric_name")
    }


def evidence_badge(evidence_id: Any) -> str:
    value = str(evidence_id or "")
    if not value or value.startswith(("EV-", "SRC-")):
        return ""
    return f'<span class="evidence-id">{esc(value)}</span>'


def record_badge(row: dict[str, Any] | None) -> str:
    return evidence_badge(row.get("evidence_id")) if row else ""


def evidence_alias_map(contract: dict[str, Any]) -> dict[str, str]:
    return {
        str(row.get("evidence_id")): str(row.get("display_id"))
        for row in contract.get("evidence_display_index", [])
        if row.get("evidence_id") and row.get("display_id")
    }


def short_evidence_badges(contract: dict[str, Any], evidence_ids: Iterable[Any]) -> str:
    aliases = evidence_alias_map(contract)
    values = [aliases.get(str(value)) for value in evidence_ids if aliases.get(str(value))]
    return " ".join(evidence_badge(value) for value in dict.fromkeys(values))


def bundle_badge(contract: dict[str, Any], section_key: str) -> str:
    bundle = next(
        (row for row in contract.get("evidence_bundles", []) if row.get("section_key") == section_key),
        None,
    )
    if not bundle:
        return ""
    return (
        f'<span class="bundle-id">{esc(bundle.get("bundle_id"))} · '
        f'{esc(bundle.get("label"))} · {esc(bundle.get("record_count"))} records</span>'
    )


def list_html(items: Iterable[Any], empty: str = "None / 无", *, limit: int | None = None) -> str:
    values = list(items)
    if limit is not None:
        values = values[:limit]
    if not values:
        return f'<p class="muted">{esc(empty)}</p>'
    return "<ul>" + "".join(f"<li>{esc(value)}</li>" for value in values) + "</ul>"


def status_text(contract: dict[str, Any]) -> tuple[str, str, str]:
    action = str(contract.get("research_workflow_status") or "Data Review Required")
    gate = contract.get("data_gate", {})
    confidence = str(contract.get("decision_confidence", {}).get("level") or "Low")
    return (
        ACTION_LABELS.get(action, action),
        f"Gate {gate.get('level', 'n/a')} / 数据门禁 {gate.get('level', 'n/a')}",
        CONFIDENCE_LABELS.get(confidence, confidence),
    )


def html_page(title: str, body: str, *, one_page: bool = False) -> str:
    page_margin = "7mm 8mm 9mm" if one_page else "10mm 11mm 14mm"
    page_class = "one-page-root" if one_page else "full-report-root"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
@page {{ size: A4; margin: {page_margin}; }}
* {{ box-sizing: border-box; }}
:root {{ --ink:#172026; --muted:#637078; --line:#d8dee1; --soft:#f3f5f4; --teal:#176c72;
--teal-soft:#e8f2f1; --gold:#9a6a16; --gold-soft:#fbf4e6; --red:#9c3f3a; --red-soft:#faeeee;
--green:#2c6d4f; --green-soft:#edf6f0; }}
html,body {{ margin:0; background:#fff; color:var(--ink); }}
body {{ font-family:Arial,"PingFang SC","Microsoft YaHei",sans-serif; font-size:9.5px; line-height:1.42; letter-spacing:0; }}
main {{ width:100%; margin:0 auto; }}
h1,h2,h3,p {{ overflow-wrap:anywhere; }}
h1 {{ margin:0; font-size:22px; line-height:1.14; letter-spacing:0; }}
h2 {{ margin:17px 0 7px; padding-bottom:4px; border-bottom:1px solid var(--line); font-size:13.5px; line-height:1.25; letter-spacing:0; break-after:avoid; page-break-after:avoid; }}
h3 {{ margin:8px 0 4px; font-size:10.5px; line-height:1.3; letter-spacing:0; }}
p {{ margin:4px 0; }} ul {{ margin:4px 0 7px; padding-left:17px; }} li {{ margin:2px 0; }}
a {{ color:var(--teal); text-decoration:none; }}
table {{ width:100%; margin:5px 0 9px; border-collapse:collapse; table-layout:fixed; font-variant-numeric:tabular-nums; }}
th,td {{ padding:4px 5px; border-bottom:1px solid var(--line); vertical-align:top; overflow-wrap:anywhere; }}
tr {{ break-inside:avoid; page-break-inside:avoid; }}
th {{ background:var(--soft); color:#334047; text-align:left; font-size:8px; font-weight:700; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }} .muted {{ color:var(--muted); }} .small {{ font-size:8px; }}
.eyebrow {{ margin-bottom:2px; color:var(--teal); font-size:8px; font-weight:700; text-transform:uppercase; }}
.header {{ display:flex; align-items:flex-end; justify-content:space-between; gap:18px; padding-bottom:8px; border-bottom:3px solid var(--teal); }}
.header-meta {{ text-align:right; color:var(--muted); font-size:7.8px; line-height:1.45; }}
.decision-strip {{ display:grid; grid-template-columns:1.1fr .85fr .48fr .52fr .72fr; gap:1px; margin:8px 0; background:var(--line); border:1px solid var(--line); }}
.decision-cell {{ min-width:0; padding:6px 7px; background:#fff; }}
.decision-cell .kicker {{ display:block; color:var(--muted); font-size:7px; text-transform:uppercase; }}
.decision-cell strong {{ display:block; margin-top:1px; color:var(--teal); font-size:9.3px; line-height:1.25; }}
.workflow-disclosure {{ margin:2px 0 5px; color:var(--muted); font-size:7px; }}
.answer-box {{ margin:9px 0; padding:8px 10px; border-left:4px solid var(--teal); background:var(--teal-soft); }}
.answer-box.warning {{ border-color:var(--gold); background:var(--gold-soft); }}
.answer-box strong {{ color:var(--teal); }} .answer-box.warning strong {{ color:var(--gold); }}
.metric-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; margin:7px 0 9px; }}
.metric {{ min-height:52px; padding:6px 7px; border:1px solid var(--line); background:#fff; }}
.metric-label {{ color:var(--muted); font-size:7.3px; line-height:1.2; }}
.metric-value {{ margin-top:2px; font-size:14px; font-weight:700; line-height:1.05; }}
.metric-note {{ margin-top:3px; color:var(--muted); font-size:6.9px; }}
.evidence-id {{ display:inline-block; color:#5f6b72; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:6.6px; line-height:1.25; }}
.bundle-id {{ display:inline-block; margin:2px 0; padding:1px 4px; border:1px solid #a9c5c5; color:var(--teal); background:var(--teal-soft); font-size:6.5px; font-weight:700; line-height:1.25; }}
.bundle-tail {{ break-inside:avoid; page-break-inside:avoid; }}
.two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:11px; }}
.scenario-band {{ display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin:7px 0 9px; }}
.scenario-card {{ min-height:76px; padding:7px; border-top:3px solid var(--gold); background:var(--gold-soft); }}
.scenario-card.bear {{ border-color:var(--red); background:var(--red-soft); }}
.scenario-card.bull {{ border-color:var(--green); background:var(--green-soft); }}
.scenario-card h3 {{ margin-top:0; }} .scenario-price {{ font-size:16px; font-weight:700; }}
.scenario-return {{ font-size:10px; font-weight:700; }} .negative {{ color:var(--red); }} .positive {{ color:var(--green); }}
.module {{ margin:7px 0; padding:7px 9px; border-left:3px solid #aeb9bd; background:#fafbfa; break-inside:avoid; }}
.module-head {{ display:flex; justify-content:space-between; gap:10px; }} .module-head h3 {{ margin:0; }}
.status {{ color:var(--teal); font-size:7.5px; font-weight:700; }}
.debate {{ margin:8px 0; padding:7px 9px; border:1px solid var(--line); break-inside:avoid; }}
.debate h3 {{ margin-top:0; color:var(--teal); }}
.tag {{ display:inline-block; margin-right:4px; padding:1px 4px; border:1px solid var(--line); color:var(--muted); font-size:6.8px; font-weight:700; }}
.portfolio-disabled {{ margin:8px 0; padding:7px 9px; border:1px solid #d8b66c; background:var(--gold-soft); }}
.page-break {{ break-before:page; }} .keep {{ break-inside:avoid; }} .section-intro {{ margin-bottom:6px; color:#334047; }}
.formula {{ color:#4e5c63; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:7px; }}
.audit-table {{ font-size:7.2px; }} .audit-table th,.audit-table td {{ padding:3px 4px; }}
.selected-evidence {{ font-size:6.5px; }} .selected-evidence th,.selected-evidence td {{ padding:2px 3px; }}
.source-list {{ font-size:7.3px; }} .source-list td {{ padding:3px 4px; }} .source-level {{ width:7%; text-align:center; }}
.source-ids {{ color:#66727a; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:6px; }}
.contract-identity {{ display:none; }}
.running-footer {{ display:flex; justify-content:space-between; gap:10px; margin-top:8px; padding-top:3px; border-top:1px solid var(--line); color:#7a858b; font-size:6.5px; break-inside:avoid; }}
.one-page-root {{ font-size:8.5px; line-height:1.3; }} .one-page-root h1 {{ font-size:18px; }}
.one-page-root h2 {{ margin:7px 0 3px; padding-bottom:2px; font-size:10.4px; }}
.one-page-root h3 {{ margin:3px 0 2px; font-size:8.8px; }} .one-page-root .header {{ padding-bottom:5px; }}
.one-page-root .decision-strip {{ margin:5px 0; }} .one-page-root .decision-cell {{ padding:4px 5px; }}
.one-page-root .decision-cell strong {{ font-size:8.2px; }} .one-page-root .answer-box {{ margin:5px 0; padding:5px 7px; }}
.one-page-root .workflow-disclosure {{ margin:1px 0 4px; font-size:7.2px; }}
.one-page-root .metric-grid {{ grid-template-columns:repeat(6,minmax(0,1fr)); gap:3px; margin:4px 0 5px; }}
.one-page-root .metric {{ min-height:44px; padding:4px; }} .one-page-root .metric-label {{ font-size:6.7px; }}
.one-page-root .metric-value {{ font-size:11.2px; }} .one-page-root .metric-note {{ font-size:6.2px; }}
.one-page-root table {{ margin:3px 0 5px; }} .one-page-root th,.one-page-root td {{ padding:2.5px 3px; font-size:7.1px; line-height:1.2; }}
.one-page-root .small {{ font-size:7.5px; }}
.one-page-root .debate {{ margin:3px 0; padding:4px 5px; }} .one-page-root ul {{ margin:2px 0 3px; padding-left:13px; }}
.one-page-root li {{ margin:1px 0; }} .one-page-root .portfolio-disabled {{ margin:4px 0; padding:4px 6px; }}
</style></head><body><main class="{page_class}">{body}</main></body></html>"""


def report_header(contract: dict[str, Any], subtitle: str) -> str:
    company = contract.get("company", {})
    dates = contract.get("report_dates", {})
    # Render a stable public product name rather than replaying legacy contract
    # metadata from frozen fixtures.
    product_name = "Public-Data Issuer Underwriting and IC Pre-Read System - v1.0.0"
    return f"""
<header class="header"><div><div class="eyebrow">{esc(product_name)}</div>
<h1>{esc(company.get('name'))} ({esc(company.get('ticker'))})</h1></div>
<div class="header-meta">{esc(subtitle)}<br>Report ID: {esc(contract.get('report_id'))}<br>
Financials: {esc(dates.get('financial_statement_date') or 'n/a')} | Market: {esc(dates.get('market_price_date') or 'n/a')}<br>
Subsequent-event review: {esc(dates.get('subsequent_event_index_review_through') or 'n/a')}</div></header>"""


def running_footer(contract: dict[str, Any]) -> str:
    contract_hash = str(contract.get("contract_hash") or "n/a")
    return (
        '<div class="running-footer">'
        f"<span>{esc(contract.get('company', {}).get('ticker'))} | Public-data underwriting | "
        f"{esc(contract.get('report_id'))} | Hash {esc(contract_hash[:12])}</span>"
        f'<span class="contract-identity">Contract hash: {esc(contract_hash)}</span>'
        '<span>Validated contract identity / 已验证合同标识</span></div>'
    )


def decision_strip(contract: dict[str, Any]) -> str:
    workflow, gate, confidence = status_text(contract)
    public_view = str(contract.get("public_data_investment_view") or "Continue Research")
    valuation_status = str(contract.get("valuation_status", {}).get("status") or "NOT_EVALUATED")
    return f"""
<div class="decision-strip">
<div class="decision-cell"><span class="kicker">Research workflow / 研究流程</span><strong>{esc(workflow)}</strong></div>
<div class="decision-cell"><span class="kicker">Public-data view / 公开数据观点</span><strong>{esc(public_view)}</strong></div>
<div class="decision-cell"><span class="kicker">Data Gate / 数据门禁</span><strong>{esc(gate)}</strong></div>
<div class="decision-cell"><span class="kicker">Confidence / 可信度</span><strong>{esc(confidence)}</strong></div>
<div class="decision-cell"><span class="kicker">Valuation status / 估值状态</span><strong>{esc(valuation_status)}</strong></div>
</div><p class="workflow-disclosure">Research readiness measures whether issuer-level analysis is ready for human review; it does not measure investment attractiveness or authorize a trade. / 研究就绪仅表示发行人层面分析可供人工审阅，不代表投资吸引力，也不授权交易。</p>"""


def metric_card(label: str, value: str, note: str = "") -> str:
    note_html = f'<div class="metric-note">{esc(note)}</div>' if note else ""
    return (
        '<div class="metric">'
        f'<div class="metric-label">{esc(label)}</div><div class="metric-value">{esc(value)}</div>'
        f"{note_html}</div>"
    )


def headline_metrics(contract: dict[str, Any]) -> str:
    by_metric = evidence_by_metric(contract)
    price = by_metric.get("market_price_unadjusted_close")
    fcf_base_record = by_metric.get("public_data_fcf_underwriting_base")
    fcf_base = contract.get("fcf_underwriting_base", {})
    required = by_metric.get("reverse_valuation_required_metric_value")
    gross_liquidity = by_metric.get("available_liquidity_including_reported_facility")
    cash_liquidity = by_metric.get("available_liquidity_before_facility_notes")
    liquidity = gross_liquidity or cash_liquidity
    p_fcf = by_metric.get("trailing_p_fcf")
    selected_multiple = contract.get("valuation_framework", {}).get("reverse_valuation", {}).get("selected_multiple")
    multiple_label = fmt_multiple(selected_multiple)
    required_label = (
        f"FCF required at {multiple_label} / {multiple_label.removesuffix('x')}倍所需FCF"
        if selected_multiple is not None
        else "FCF required at selected multiple / 选定倍数所需FCF"
    )
    liquidity_label = (
        "Gross reported liquidity / 报告总流动性"
        if gross_liquidity
        else "Cash + current marketable securities / 现金及流动市场化证券"
    )
    liquidity_note = (
        "Includes reported facility availability / 包含已披露授信可用额"
        if gross_liquidity
        else "Excludes unstructured facility availability / 不含未结构化授信可用额"
    )
    cards = [
        metric_card(
            "Dated price / 时点股价",
            fmt_price(price.get("value") if price else contract.get("valuation", {}).get("price")),
            contract.get("report_dates", {}).get("market_price_date") or "",
        ),
        metric_card(
            "Public-Data FCF Base / 公开数据FCF基准",
            fmt_money(fcf_base_record.get("value") if fcf_base_record else fcf_base.get("value")),
            str(fcf_base.get("period_end") or "n/a"),
        ),
        metric_card(
            required_label,
            fmt_money(required.get("value") if required else None),
            "Conditional reverse valuation / 条件性反向估值",
        ),
        metric_card(
            "FCF normalization / FCF标准化",
            str(fcf_base.get("normalization_status") or "NOT_EVALUATED").replace("_", " "),
            "Economic normalization status / 经济标准化状态",
        ),
        metric_card(liquidity_label, fmt_record(liquidity), liquidity_note),
        metric_card("Reported P/FCF / 报告P/FCF", fmt_record(p_fcf), "Trailing observation / 历史观察"),
    ]
    return '<div class="metric-grid">' + "".join(cards) + "</div>"


def portfolio_notice(contract: dict[str, Any], *, compact: bool = False) -> str:
    if compact:
        return (
            '<div class="portfolio-disabled"><b>Portfolio Decision: Not Evaluated / 组合决策：未评估。 '
            'Portfolio Overlay: Disabled / 组合叠加层：未启用。</b> '
            'Fund-specific inputs were not provided; no sizing or trade authorization is shown. / '
            '未提供基金特定参数；不展示仓位，也不授权交易。</div>'
        )
    note = contract.get("portfolio_context", {}).get("note") or (
        "Portfolio Overlay: Disabled - fund-specific target return, downside tolerance, horizon, exposure, "
        "liquidity, concentration and opportunity cost were not provided. / 组合叠加层未启用：尚未提供基金特定参数。"
    )
    return (
        '<div class="portfolio-disabled"><b>Portfolio Decision: Not Evaluated / 组合决策：未评估。</b> '
        f"{esc(note)} No position sizing is shown and no trade is authorized. / 不展示仓位，也不授权交易。</div>"
    )


def scenario_evidence(contract: dict[str, Any], scenario_name: str, suffix: str) -> dict[str, Any] | None:
    return evidence_by_metric(contract).get(f"scenario_{scenario_name.lower()}_{suffix}")


def display_scenarios(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Read scenario numbers from S09, with a 5.0 rendering fallback."""

    valuation_contract = contract.get("valuation_contract")
    if not isinstance(valuation_contract, dict):
        return list(contract.get("scenarios", []))
    price_output = valuation_contract.get("outputs", {}).get("price_sensitivity", {})
    if price_output.get("status") != "VALIDATED":
        return []
    narrative_by_name = {
        str(row.get("name") or ""): row for row in contract.get("scenarios", [])
    }
    rows: list[dict[str, Any]] = []
    for numeric in price_output.get("scenarios", []):
        merged = dict(narrative_by_name.get(str(numeric.get("name") or ""), {}))
        merged.update(numeric)
        rows.append(merged)
    return rows


def scenario_table(contract: dict[str, Any], *, compact: bool = False) -> str:
    scenarios = display_scenarios(contract)
    if not scenarios or float(contract.get("data_gate", {}).get("level", 0)) < 3:
        return '<div class="answer-box warning">Scenario price sensitivities are suppressed until Gate 3. / Gate 3之前不展示情景价格敏感性。</div>'
    probability = contract.get("probability_validation", {})
    probability_status = str(probability.get("status") or "NOT_PROVIDED")
    probability_header = "Validated probability / 已验证概率" if probability_status == "VALIDATED" else "Probability input / 概率输入"
    rows = []
    for scenario in scenarios:
        name = str(scenario.get("name") or "")
        metric_record = scenario_evidence(contract, name, "metric_value")
        probability_value = fmt_percent(scenario.get("probability"), decimals=0) if scenario.get("probability") is not None else "n/a"
        rows.append(
            "<tr>"
            f"<td><b>{esc(name)}</b></td><td class=\"num\">{probability_value}</td>"
            f"<td class=\"num\">{fmt_money(metric_record.get('value') if metric_record else None)}</td>"
            f"<td class=\"num\">{fmt_percent(scenario.get('growth_assumption'))}</td>"
            f"<td class=\"num\">{fmt_multiple(scenario.get('exit_multiple'))}</td>"
            f"<td class=\"num\">{fmt_price(scenario.get('implied_price'))}</td>"
            f"<td class=\"num\">{fmt_percent(scenario.get('price_change_vs_current'))}</td>"
            + ("" if compact else f"<td>{esc(scenario.get('key_driver'))}</td>")
            + "</tr>"
        )
    driver_header = "" if compact else "<th>Key driver / 核心驱动</th>"
    share_basis = contract.get("share_count_basis", {})
    if compact:
        share_note = (
            f'<p class="small muted"><b>Per-share basis / 每股口径:</b> '
            f'{esc(share_basis.get("proxy_status"))}; {esc(share_basis.get("share_count_type"))} '
            f'as of {esc(share_basis.get("share_count_date"))}; forward bridge '
            f'{esc(share_basis.get("forward_share_count_bridge_status"))}; subsequent-event status '
            f'{esc(share_basis.get("known_subsequent_event_status"))}. / 前瞻股数桥及后续事项状态如上。</p>'
        )
    else:
        share_note = (
            f'<p class="small muted"><b>Per-share basis / 每股口径:</b> '
            f'{esc(share_basis.get("per_share_output_label"))}; '
            f'{esc(share_basis.get("share_count_type"))} as of {esc(share_basis.get("share_count_date"))}. '
            f'{esc(share_basis.get("known_subsequent_event_note"))}</p>'
        )
    return (
        f"<table><thead><tr><th>Scenario / 情景</th><th class=\"num\">{esc(probability_header)}</th>"
        "<th class=\"num\">FCF base / FCF基准</th><th class=\"num\">Change / 变化</th>"
        "<th class=\"num\">Multiple / 倍数</th><th class=\"num\">Implied price / 隐含价格</th>"
        f"<th class=\"num\">Price change vs current / 较现价变化</th>{driver_header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f'<p class="small muted">{esc(contract.get("return_context", {}).get("disclosure"))}</p>'
        f'{share_note}'
    )


def scenario_band(contract: dict[str, Any]) -> str:
    cards = []
    translations = {"Bear": "悲观", "Base": "基准", "Bull": "乐观"}
    probability_status = str(contract.get("probability_validation", {}).get("status") or "NOT_PROVIDED")
    probability_prefix = {
        "VALIDATED": "validated p / 已验证概率",
        "ILLUSTRATIVE": "illustrative p / 示意概率",
    }.get(probability_status, "p / 概率")
    for scenario in display_scenarios(contract):
        name = str(scenario.get("name") or "")
        tone = name.lower() if name.lower() in {"bear", "bull"} else "base"
        return_value = safe_float(scenario.get("price_change_vs_current"))
        return_tone = "negative" if return_value is not None and return_value < 0 else "positive"
        probability_value = fmt_percent(scenario.get("probability"), decimals=0) if scenario.get("probability") is not None else "n/a"
        cards.append(
            f'<div class="scenario-card {tone}"><h3>{esc(name)} / {esc(translations.get(name, name))}</h3>'
            f'<div class="scenario-price">{fmt_price(scenario.get("implied_price"))}</div>'
            f'<div class="scenario-return {return_tone}">vs current {fmt_percent(scenario.get("price_change_vs_current"))}</div>'
            f'<div class="small muted">{esc(probability_prefix)}={probability_value} | {fmt_multiple(scenario.get("exit_multiple"))}</div></div>'
        )
    return '<div class="scenario-band">' + "".join(cards) + "</div>" if cards else ""


def valuation_return_outputs_html(contract: dict[str, Any], *, compact: bool = False) -> str:
    valuation_contract = contract.get("valuation_contract")
    if not isinstance(valuation_contract, dict):
        return ""
    outputs = valuation_contract.get("outputs", {})
    price = outputs.get("price_sensitivity", {})
    base = outputs.get("base_case_return", {})
    weighted = outputs.get("probability_weighted_return", {})
    user = outputs.get("partner_internal_return", {})

    def result_text(output: dict[str, Any], *, price_only: bool = False) -> str:
        if output.get("status") != "VALIDATED":
            return "Not evaluated / 未评估"
        if price_only:
            return "See Bear/Base/Bull range above / 见上方三情景区间"
        total = fmt_percent(output.get("total_return"))
        annualized = fmt_percent(output.get("annualized_return"))
        return f"Total {total}; annualized {annualized} / 总回报{total}；年化{annualized}"

    rows = [
        (
            "Price Sensitivity / 价格敏感性",
            price.get("status"),
            result_text(price, price_only=True),
        ),
        (
            "Base-Case Return / 基准情景回报",
            base.get("status"),
            result_text(base),
        ),
        (
            "Probability-Weighted Return / 概率加权回报",
            weighted.get("status"),
            result_text(weighted),
        ),
        (
            "User Internal Return / User内部回报",
            user.get("status"),
            "Private Gate 4 only / 仅限私有Gate 4",
        ),
    ]
    table = (
        "<table><thead><tr><th>Output class / 输出类别</th><th>Status / 状态</th>"
        "<th>Result / 结果</th></tr></thead><tbody>"
        + "".join(
            f"<tr><td><b>{esc(label)}</b></td><td>{esc(status)}</td><td>{esc(result)}</td></tr>"
            for label, status, result in rows
        )
        + "</tbody></table>"
    )
    if compact:
        return table
    return (
        table
        + f'<p class="small muted"><b>Valuation as-of / 估值时点:</b> '
        f'{esc(valuation_contract.get("valuation_as_of_date"))}; '
        f'<b>Target / 目标日期:</b> {esc(valuation_contract.get("target_date"))}; '
        f'<b>Horizon status / 时间口径状态:</b> {esc(valuation_contract.get("status"))}. '
        f'{esc(contract.get("return_context", {}).get("disclosure"))}</p>'
    )


def investment_decision_summary_html(contract: dict[str, Any], *, compact: bool = False) -> str:
    summary = contract.get("investment_decision_summary", {})
    action = summary.get("current_action") or "Continue Research"
    view = summary.get("current_view") or contract.get("public_data_conclusion") or "Not Evaluated"
    evidence = ""
    if compact:
        return (
            '<div class="answer-box"><strong>Public-data action / 公开数据动作: '
            f"{esc(action)}</strong><br>{esc(view)}<div>{evidence}</div></div>"
        )
    return (
        '<div class="answer-box"><strong>Public-data action / 公开数据动作: '
        f"{esc(action)}</strong><p>{esc(view)}</p>{evidence}</div>"
        '<div class="two-col"><section><h3>What would make it attractive / 提升吸引力的条件</h3>'
        f'{list_html(summary.get("what_would_make_attractive", []))}</section>'
        '<section><h3>What would invalidate the view / 推翻判断的条件</h3>'
        f'{list_html(summary.get("what_would_invalidate", []))}</section></div>'
        '<h3>What to monitor next / 下一步监控</h3>'
        f'{list_html(summary.get("what_to_monitor_next", []))}'
    )


def probability_governance_html(contract: dict[str, Any], *, compact: bool = False) -> str:
    probability = contract.get("probability_validation", {})
    status = str(probability.get("status") or "NOT_PROVIDED")
    approval = probability.get("approval", {})
    formal_status = probability.get(
        "formal_probability_weighted_expected_return_status"
    )
    formal_allowed = (
        formal_status == "VALIDATED"
        if formal_status is not None
        else bool(probability.get("weighted_return_allowed"))
    )
    tone = "" if formal_allowed else " warning"
    result = "VALIDATED" if formal_allowed else "NOT_EVALUATED"
    details = (
        f"Method / 方法: {valuation_governance_label(probability.get('method_type') or 'NOT_PROVIDED')}; "
        f"Freshness / 时效: {valuation_governance_label(probability.get('freshness_status') or 'NOT_APPLICABLE')}; "
        f"Approval / 审批: {valuation_governance_label(approval.get('status') or 'NOT_APPROVED')}; "
        f"Independent review / 独立复核: "
        f"{'Yes' if approval.get('independent_research_review') else 'No'}; "
        f"Formal probability-weighted outcome / 正式概率加权结果: {result}."
    )
    if compact:
        return f'<div class="answer-box{tone}"><strong>Probability governance / 概率治理: {esc(valuation_governance_label(status))}</strong> {esc(details)}</div>'
    methodology = probability.get("methodology") or "No controlled methodology provided. / 未提供受控方法。"
    limitations = probability.get("limitations", [])
    sensitivity = probability.get("sensitivity_table", [])
    sensitivity_rows = "".join(
        "<tr>"
        f"<td>{esc(row.get('label'))}</td>"
        f"<td class=\"num\">{fmt_percent(row.get('probabilities', {}).get('Bear'), decimals=0)}</td>"
        f"<td class=\"num\">{fmt_percent(row.get('probabilities', {}).get('Base'), decimals=0)}</td>"
        f"<td class=\"num\">{fmt_percent(row.get('probabilities', {}).get('Bull'), decimals=0)}</td></tr>"
        for row in sensitivity
    )
    sensitivity_html = ""
    if sensitivity_rows:
        sensitivity_html = (
            '<h3>Probability sensitivity / 概率敏感性</h3><table><thead><tr><th>Case / 情形</th>'
            '<th class="num">Bear</th><th class="num">Base</th><th class="num">Bull</th>'
            f'</tr></thead><tbody>{sensitivity_rows}</tbody></table>'
        )
    return (
        f'<div class="answer-box{tone}"><strong>Probability governance / 概率治理: {esc(valuation_governance_label(status))}</strong>'
        f"<p>{esc(details)}</p><p><b>Methodology / 方法说明:</b> {esc(methodology)}</p>"
        f"<p><b>As of / 截止:</b> {esc(probability.get('as_of_date') or 'n/a')} | "
        f"<b>Review by / 复核期限:</b> {esc(probability.get('expiration_review_date') or 'n/a')} | "
        f"<b>Owner / 模型负责人:</b> {esc(probability.get('reviewed_by') or 'n/a')} | "
        f"<b>Independent approver / 独立审批人:</b> {esc(approval.get('approved_by') or 'n/a')}</p>"
        f"{bundle_badge(contract, 'scenario_sensitivity')}</div>"
        f"{sensitivity_html}"
        f'<div class="keep"><h3>Probability limitations / 概率限制</h3>{list_html(limitations)}</div>'
    )


def fcf_quality_html(contract: dict[str, Any]) -> str:
    quality = contract.get("fcf_quality_assessment", {})
    dimensions = quality.get("dimensions", [])
    dimension_rows = "".join(
        "<tr>"
        f"<td>{esc(row.get('dimension') or row.get('name'))}</td>"
        f"<td>{esc(row.get('assessment') or row.get('status'))}</td>"
        f"<td>{esc(row.get('implication') or row.get('rationale'))}</td></tr>"
        for row in dimensions
        if isinstance(row, dict)
    )
    table = (
        '<table><thead><tr><th>Dimension / 维度</th><th>Assessment / 评价</th>'
        f'<th>Investment implication / 投资含义</th></tr></thead><tbody>{dimension_rows}</tbody></table>'
        if dimension_rows
        else ""
    )
    return (
        '<div class="module"><div class="module-head"><h3>FCF Quality / FCF质量</h3>'
        f'<span class="status">{esc(quality.get("status"))} | {esc(quality.get("rating"))}</span></div>'
        f'<p>{esc(quality.get("conclusion"))}</p>'
        f'<p><b>Source of FCF / FCF来源:</b> {esc(" | ".join(quality.get("source_of_fcf", [])))}</p>'
        f'<p><b>Sustainability / 可持续性:</b> {esc(quality.get("sustainability_assessment"))}</p>'
        f'<p><b>Cash-conversion confidence / 现金转化可信度:</b> {esc(quality.get("cash_conversion_confidence"))}</p>'
        f'{table}</div>'
    )


def variant_perception_html(contract: dict[str, Any]) -> str:
    expectations = contract.get("market_expectations", {})
    rows = [
        ("Market expectation / 市场预期", expectations.get("market_expectation"), expectations.get("market_evidence_ids", [])),
        ("Current public evidence / 当前公开证据", expectations.get("current_public_evidence"), expectations.get("public_evidence_ids", [])),
        ("Potential variant / 潜在差异化观点", expectations.get("potential_variant"), expectations.get("variant_evidence_ids", [])),
        ("Disconfirming evidence / 反证", expectations.get("disconfirming_evidence"), expectations.get("disconfirming_evidence_ids", [])),
    ]
    return "".join(
        '<div class="module"><h3>' + esc(label) + '</h3><p>' + esc(value) + '</p></div>'
        for label, value, _evidence_ids in rows
    )


def valuation_governance_label(value: Any) -> str:
    code = str(value or "NOT_PROVIDED")
    labels = {
        "NOT_PROVIDED": "Not provided / 未提供",
        "NOT_APPLICABLE": "Not applicable / 不适用",
        "INVALID": "Not validated / 未通过验证",
        "SUPPRESSED_INCOMPARABLE": "Suppressed as incomparable / 因不可比已抑制",
        "PARTIALLY_VALIDATED": "Partially validated / 部分通过验证",
        "MULTI_METHOD_VALIDATED": "Multi-method validated / 多方法已验证",
        "VALIDATED": "Validated / 已验证",
        "AVAILABLE": "Available / 可用",
        "SUPPRESSED_INSUFFICIENT_COMPARABLE_PEERS": "Insufficient comparable peers / 可比公司不足",
        "SUPPRESSED_INSUFFICIENT_OR_INCOMPARABLE_HISTORY": "Insufficient comparable history / 可比历史不足",
        "WITHIN_TOLERANCE": "Within tolerance / 差异在容许范围内",
        "DIVERGENT": "Methods diverge / 方法结果存在分歧",
        "NOT_EVALUATED": "Not evaluated / 未评估",
        "ILLUSTRATIVE": "Illustrative only / 仅作示意",
        "STALE": "Stale; review required / 已过期，需复核",
        "CURRENT": "Current / 当前有效",
        "EXPIRING_SOON": "Review due soon / 即将到期复核",
        "SUPERSEDED": "Superseded by new evidence / 已被新证据取代",
        "APPROVED": "Approved / 已审批",
        "NOT_APPROVED": "Not approved / 未审批",
        "SUPPORTED": "Supported by controlled context / 有受控背景支持",
        "NOT_SUPPORTED": "Not supported by controlled context / 缺少受控背景支持",
        "COMPARABLE": "Comparable / 可比",
        "LIMITED": "Limited comparability / 可比性有限",
        "NOT_COMPARABLE": "Not comparable / 不可比",
        "HISTORICAL_FREQUENCY": "Historical frequency / 历史频率",
        "MANAGEMENT_GUIDANCE_CONFIDENCE": "Management-guidance confidence / 管理层指引可信度",
        "SCENARIO_JUDGMENT": "Scenario judgment / 情景判断",
        "MONTE_CARLO": "Monte Carlo / 蒙特卡洛模拟",
        "BASE_RATE_ANALYSIS": "Base-rate analysis / 基准率分析",
        "EQUITY_FCF_MULTIPLE": "Equity FCF multiple / 股权FCF倍数",
        "EQUITY_EARNINGS_MULTIPLE": "Equity earnings multiple / 股权盈利倍数",
        "ENTERPRISE_VALUE_EBITDA_MULTIPLE": "Enterprise-value EBITDA multiple / 企业价值EBITDA倍数",
        "ENTERPRISE_VALUE_REVENUE_MULTIPLE": "Enterprise-value revenue multiple / 企业价值收入倍数",
        "EQUITY_FCF_YIELD": "Equity FCF yield / 股权FCF收益率",
        "UNLEVERED_FCFF": "Unlevered FCFF / 无杠杆企业自由现金流",
        "WACC": "WACC / 加权平均资本成本",
        "POINT_IN_TIME_OUTSTANDING": "Point-in-time outstanding shares / 时点流通股数",
        "POINT_IN_TIME_DILUTED": "Point-in-time diluted shares / 时点摊薄股数",
        "FORWARD_DILUTED": "Forward diluted shares / 前瞻摊薄股数",
    }
    return labels.get(code, code.replace("_", " ").title())


def comparability_flag_label(value: Any) -> str:
    code = str(value or "")
    labels = {
        "negative_ebitda": "Negative EBITDA / EBITDA为负",
        "negative_fcf": "Negative FCF / FCF为负",
        "negative_earnings": "Negative earnings / 盈利为负",
        "negative_revenue": "Non-positive revenue / 收入非正",
        "different_fiscal_period": "Fiscal-period mismatch / 财务期间不一致",
        "different_fiscal_period_basis": "Period-basis mismatch / 期间口径不一致",
        "currency_mismatch": "Currency mismatch / 币种不一致",
        "accounting_definition_mismatch": "Accounting-definition mismatch / 会计定义不一致",
        "missing_or_mismatched_evidence": "Missing or mismatched evidence / 证据缺失或不匹配",
        "value_formula_mismatch": "Formula mismatch / 公式不一致",
        "limited_business_model_fit": "Limited business-model fit / 商业模式可比性有限",
        "business_model_fit_missing_or_invalid": "Business-model fit not validated / 商业模式可比性未验证",
        "duplicate_peer_metric": "Duplicate peer metric / 同业指标重复",
        "missing_peer_identity": "Peer identity missing / 同业身份缺失",
        "controlled_period_bridge": "Controlled period bridge / 已验证期间桥接",
        "controlled_currency_normalization": "Controlled currency normalization / 已验证币种转换",
    }
    return labels.get(code, code.replace("_", " ").title())


def peer_valuation_html(contract: dict[str, Any]) -> str:
    s11 = contract.get("valuation_cross_check_contract", {})
    context = (
        s11.get("peer_comparison", {})
        if isinstance(s11, dict) and s11.get("contract_version")
        else contract.get("peer_valuation_context", {})
    )
    rows = []
    for row in context.get("rows", []):
        metric = str(row.get("metric") or "")
        value = (
            "Suppressed / 已抑制"
            if row.get("comparability_status") != "COMPARABLE"
            else fmt_percent(row.get("value"))
            if metric == "FCF_YIELD"
            else fmt_multiple(row.get("value"))
        )
        rows.append(
            "<tr>"
            f"<td>{esc(row.get('ticker'))}</td><td>{esc(metric)}</td><td class=\"num\">{value}</td>"
            f"<td>{esc(valuation_governance_label(row.get('comparability_status')))}</td>"
            f"<td>{esc('; '.join(comparability_flag_label(flag) for flag in row.get('comparability_flags', [])) or 'None / 无')}</td>"
            f"<td>{esc('Yes' if row.get('auto_rank_allowed') else 'No')}</td></tr>"
        )
    if not rows:
        return '<div class="answer-box warning"><strong>Peer valuation / 同业估值:</strong> Unavailable. No peer-derived ranking or fair-value conclusion is permitted. / 不可用；不得生成同业排名或公允价值结论。</div>'
    return (
        f'<p><b>Status / 状态:</b> {esc(valuation_governance_label(context.get("status")))}. '
        f'{esc(context.get("interpretation") or context.get("selection_rationale"))}</p>'
        '<table><thead><tr><th>Peer</th><th>Metric</th><th class="num">Value</th>'
        '<th>Comparability / 可比性</th><th>Flags / 标记</th><th>Auto rank</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        '<p class="small muted">Rows with negative EBITDA/FCF, period mismatch, currency mismatch or accounting-definition mismatch '
        'are display-only and cannot enter automatic rankings. / EBITDA或FCF为负、期间、币种或会计定义不一致的行仅供展示，不得参与自动排名。</p>'
    )


def valuation_cross_checks_html(
    contract: dict[str, Any],
    *,
    compact: bool = False,
) -> str:
    cross_checks = contract.get("valuation_cross_check_contract", {})
    if not isinstance(cross_checks, dict) or not cross_checks.get("contract_version"):
        return (
            '<div class="answer-box warning"><strong>Valuation cross-checks / '
            "估值交叉验证: Not provided / 未提供</strong></div>"
        )
    status = str(cross_checks.get("status") or "NOT_PROVIDED")
    components = cross_checks.get("components", {})
    agreement = cross_checks.get("method_agreement", {})
    if compact:
        return (
            f'<p><b>Valuation cross-checks / 估值交叉验证:</b> '
            f'{esc(valuation_governance_label(status))}; '
            f'<b>method agreement / 方法一致性:</b> '
            f'{esc(valuation_governance_label(agreement.get("status") or "NOT_EVALUATED"))}.</p>'
        )
    component_rows = "".join(
        f"<tr><td>{esc(name.replace('_', ' ').title())}</td>"
        f"<td>{esc(valuation_governance_label(component_status))}</td></tr>"
        for name, component_status in components.items()
    )
    historical = cross_checks.get("historical_valuation", {})
    historical_summary = historical.get("summary", {})
    reverse = cross_checks.get("reverse_valuation", {})
    independent = cross_checks.get("independent_cross_check", {})
    independent_share_basis = independent.get("share_basis", {})
    price_range = independent.get("implied_price_range", {})
    peer_summaries = cross_checks.get("peer_comparison", {}).get(
        "metric_summaries",
        [],
    )
    peer_rows = "".join(
        "<tr>"
        f"<td>{esc(row.get('metric'))}</td>"
        f"<td class=\"num\">{esc(row.get('comparable_peer_count'))}</td>"
        f"<td class=\"num\">"
        f"{fmt_percent(row.get('median')) if row.get('metric') == 'FCF_YIELD' else fmt_multiple(row.get('median'))}</td>"
        f"<td>{esc(valuation_governance_label(row.get('ranking_status')))}</td></tr>"
        for row in peer_summaries
    )
    peer_table = (
        '<h3>Controlled peer summary / 受控同业摘要</h3>'
        '<table><thead><tr><th>Metric</th><th class="num">Comparable peers</th>'
        '<th class="num">Median</th><th>Status</th></tr></thead>'
        f"<tbody>{peer_rows}</tbody></table>"
        if peer_rows
        else ""
    )
    return (
        f'<div class="answer-box"><strong>Valuation Cross-Checks / '
        f'估值交叉验证: {esc(valuation_governance_label(status))}</strong>'
        f'<p><b>Method agreement / 方法一致性:</b> '
        f'{esc(valuation_governance_label(agreement.get("status") or "NOT_EVALUATED"))}. '
        f'{esc(agreement.get("interpretation"))}</p></div>'
        '<table><thead><tr><th>Component / 组件</th><th>Status / 状态</th>'
        f'</tr></thead><tbody>{component_rows}</tbody></table>'
        f"{peer_table}"
        '<div class="two-col"><section><h3>Historical valuation / 历史估值</h3>'
        f'<p>Status: {esc(valuation_governance_label(historical.get("status")))}; metric: '
        f'{esc(historical.get("metric"))}; median: '
        f'{fmt_percent(historical_summary.get("median")) if historical.get("metric") == "FCF_YIELD" else fmt_multiple(historical_summary.get("median"))}; current percentile: '
        f'{fmt_percent(historical_summary.get("current_percentile"))}.</p></section>'
        '<section><h3>Reverse valuation / 反向估值</h3>'
        f'<p>Status: {esc(valuation_governance_label(reverse.get("status")))}; method: '
        f'{esc(valuation_governance_label(reverse.get("method")))}; required metric: '
        f'{fmt_money(reverse.get("required_metric_value"))}; reference support: '
        f'{esc(valuation_governance_label(reverse.get("reference_support", {}).get("status")))}.</p></section></div>'
        '<h3>Independent DCF range / 独立DCF区间</h3>'
        f'<p>Status: {esc(valuation_governance_label(independent.get("status")))}; '
        f'basis: {esc(valuation_governance_label(independent.get("cash_flow_basis")))}; '
        f'discount rate: {esc(valuation_governance_label(independent.get("discount_rate_basis")))}; '
        f'shares: {esc(valuation_governance_label(independent_share_basis.get("basis_type")))} '
        f'as of {esc(independent_share_basis.get("basis_date"))}; '
        f'minimum {fmt_price(price_range.get("minimum"))}, '
        f'central {fmt_price(price_range.get("central"))}, '
        f'maximum {fmt_price(price_range.get("maximum"))}. '
        "This is a cross-check range, not a target price. / "
        "这是交叉验证区间，不是目标价。</p>"
        f'{list_html(cross_checks.get("limitations", []), limit=2)}'
    )


def debate_html(debate: dict[str, Any], *, compact: bool = False) -> str:
    evidence_ids = debate.get("market_evidence_ids", []) + debate.get("alternative_evidence_ids", [])
    if compact:
        return (
            '<div class="debate">'
            f"<h3>{esc(debate.get('title'))}</h3>"
            f"<p><b>Resolve with / 解决指标:</b> {esc(debate.get('resolution_kpi_or_event'))}</p></div>"
        )
    return (
        '<div class="debate">'
        f"<h3>{esc(debate.get('title'))}</h3>"
        f"<p><span class=\"tag\">MARKET VIEW / 市场观点</span>{esc(debate.get('market_view'))}</p>"
        f"<p><span class=\"tag\">ALTERNATIVE / 替代观点</span>{esc(debate.get('alternative_view'))}</p>"
        f"<p><b>Missing evidence / 缺失证据:</b> {esc(debate.get('missing_evidence'))}</p>"
        f"<p><b>Resolution KPI or event / 解决指标或事件:</b> {esc(debate.get('resolution_kpi_or_event'))}</p>"
        f"<p><b>Decision impact / 决策影响:</b> {esc(debate.get('decision_impact'))}</p></div>"
    )


def key_metric_table(contract: dict[str, Any], names: list[str]) -> str:
    by_metric = evidence_by_metric(contract)
    rows = []
    for name in names:
        record = by_metric.get(name)
        if not record:
            continue
        rows.append(
            "<tr>"
            f"<td>{esc(METRIC_LABELS.get(name, name.replace('_', ' ').title()))}</td>"
            f"<td class=\"num\">{fmt_record(record)}</td><td>{esc(fmt_period(record))}</td>"
            f"<td>{esc(record.get('evidence_class'))}</td></tr>"
        )
    if not rows:
        return '<p class="muted">No validated metrics available / 暂无已验证指标</p>'
    return (
        "<table><thead><tr><th>Metric / 指标</th><th class=\"num\">Value / 数值</th>"
        "<th>Period / 期间</th><th>Class / 分类</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def normalized_fcf_bridge(contract: dict[str, Any]) -> str:
    by_metric = evidence_by_metric(contract)
    reported = by_metric.get("reported_ltm_fcf")
    base_record = by_metric.get("public_data_fcf_underwriting_base")
    status = contract.get("fcf_underwriting_base", {})
    rows = []
    if reported:
        rows.append(
            f"<tr><td>Reported LTM FCF / 报告口径LTM FCF</td><td class=\"num\">{fmt_record(reported)}</td>"
            f"<td>CALC</td></tr>"
        )
    for line in status.get("bridge_lines", []):
        rows.append(
            f"<tr><td>{esc(line.get('label'))}</td><td class=\"num\">{fmt_money(line.get('amount'))}</td>"
            f"<td>{esc(line.get('evidence_class'))}</td></tr>"
        )
    if base_record or status.get("value") is not None:
        rows.append(
            f"<tr><td><b>Public-Data FCF Underwriting Base / 公开数据FCF分析基准</b></td>"
            f"<td class=\"num\"><b>{fmt_money(base_record.get('value') if base_record else status.get('value'))}</b></td>"
            f"<td>JUDGMENT</td></tr>"
        )
    rationale = " ".join(str(line.get("rationale") or "") for line in status.get("bridge_lines", []))
    return (
        "<table><thead><tr><th>Bridge line / 桥接项目</th><th class=\"num\">Amount / 金额</th>"
        f"<th>Class / 分类</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f'<p><b>Source data / 源数据:</b> {esc(status.get("source_data_validation_status"))}; '
        f'<b>Calculation / 计算:</b> {esc(status.get("calculation_validation_status"))}; '
        f'<b>FCF Normalization Status / FCF标准化状态:</b> {esc(status.get("normalization_status"))}.</p>'
        f'<p class="small muted"><b>Scope / 范围:</b> {esc(status.get("normalization_scope"))}</p>'
        f'<p class="small muted"><b>Unresolved / 未解决:</b> {esc(" | ".join(status.get("unresolved_items", [])) or "None")}</p>'
        f'<p class="small muted"><b>Accounting control / 会计控制:</b> {esc(rationale)}</p>'
        f'{bundle_badge(contract, "fcf_underwriting_base")}'
    )


def sensitivity_table(contract: dict[str, Any]) -> str:
    framework = contract.get("valuation_framework", {})
    values = framework.get("sensitivity_table", [])
    if framework.get("status") != "VALIDATED" or not values:
        return '<div class="answer-box warning">Sensitivity output is unavailable or suppressed below Gate 3. / 敏感性结果不可得或在Gate 3之前被隐藏。</div>'
    metric_values: list[float] = []
    multiples: list[float] = []
    lookup: dict[tuple[float, float], Any] = {}
    for row in values:
        metric = safe_float(row.get("metric_value"))
        multiple = safe_float(row.get("multiple"))
        if metric is None or multiple is None:
            continue
        if metric not in metric_values:
            metric_values.append(metric)
        if multiple not in multiples:
            multiples.append(multiple)
        lookup[(metric, multiple)] = row.get("implied_price")
    headers = "".join(f'<th class="num">{fmt_multiple(value)}</th>' for value in multiples)
    rows = []
    for metric in metric_values:
        cells = "".join(
            f'<td class="num">{fmt_price(lookup.get((metric, multiple)))}</td>' for multiple in multiples
        )
        rows.append(f"<tr><td>{fmt_money(metric)} FCF</td>{cells}</tr>")
    return (
        "<table><thead><tr><th>Public-Data FCF Base / 公开数据FCF基准</th>"
        f"{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def issuer_modules_html(contract: dict[str, Any], names: list[str] | None = None) -> str:
    modules = contract.get("issuer_underwriting", {}).get("modules", {})
    chunks = []
    for name in names or list(modules):
        module = modules.get(name)
        if not module:
            continue
        chunks.append(
            '<div class="module">'
            f'<div class="module-head"><h3>{esc(MODULE_LABELS.get(name, name))}</h3>'
            f'<span class="status">{esc(module.get("status"))}</span></div>'
            f"<p>{esc(module.get('conclusion'))}</p>"
            f"<p class=\"small muted\"><b>Limitations / 限制:</b> "
            f"{esc(' | '.join(module.get('limitations', [])) or 'None')}</p>"
            f"</div>"
        )
    return "".join(chunks)


def source_groups(contract: dict[str, Any]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for source in contract.get("source_registry", []):
        url = str(source.get("source_url") or "")
        source_type = str(source.get("source_type") or "unspecified")
        key = (url, source_type) if url else ("", source_type)
        group = groups.setdefault(
            key,
            {
                "source_level": source.get("source_level"),
                "source_types": set(),
                "source_names": set(),
                "source_url": url,
                "source_ids": [],
                "locators": [],
            },
        )
        group["source_types"].add(source_type)
        if source.get("source_name"):
            group["source_names"].add(str(source.get("source_name")))
        if source.get("source_id"):
            group["source_ids"].append(str(source.get("source_id")))
        if source.get("source_locator"):
            group["locators"].append(str(source.get("source_locator")))
    output = []
    for group in groups.values():
        output.append(
            {
                **group,
                "source_types": sorted(group["source_types"]),
                "source_names": sorted(group["source_names"]),
                "source_ids": sorted(set(group["source_ids"])),
                "locators": list(dict.fromkeys(group["locators"])),
            }
        )
    return sorted(
        output,
        key=lambda row: (
            safe_float(row.get("source_level")) if safe_float(row.get("source_level")) is not None else 99,
            ",".join(row["source_types"]),
        ),
    )


def source_register(contract: dict[str, Any]) -> str:
    rows = []
    for source in source_groups(contract):
        name = ", ".join(source.get("source_names", [])) or ", ".join(source.get("source_types", []))
        url = source.get("source_url")
        link = (
            f'<a href="{esc(url)}">{esc(shorten(url, 75))}</a>'
            if url
            else "Internal analyst-owned input or calculation / 内部分析输入或计算"
        )
        rows.append(
            "<tr>"
            f'<td class="source-level">{esc(source.get("source_level"))}</td>'
            f"<td>{esc(name)}<br><span class=\"muted\">"
            f"{esc(shorten(' | '.join(source.get('locators', [])[:3]), 180))}</span></td>"
            f"<td>{link}</td></tr>"
        )
    return (
        '<table class="source-list"><thead><tr><th class="source-level">Level</th>'
        f"<th>Source / 来源</th><th>Link / 链接</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def evidence_register(contract: dict[str, Any]) -> str:
    wanted = set(IMPORTANT_EVIDENCE_METRICS)
    records = [
        row
        for row in contract.get("evidence_records", [])
        if row.get("metric_name") in wanted
    ]
    aliases = evidence_alias_map(contract)
    rows = []
    for record in records:
        value = fmt_record(record, exact=True)
        if record.get("unit") in {"text", "filing"}:
            value = esc(shorten(record.get("value"), 180))
        formula = record.get("formula") or record.get("measurement_basis") or ""
        rows.append(
            "<tr>"
            f"<td>{evidence_badge(aliases.get(str(record.get('evidence_id'))))}</td><td>{esc(record.get('evidence_class'))}</td>"
            f"<td>{esc(METRIC_LABELS.get(record.get('metric_name'), record.get('metric_name')))}</td>"
            f"<td>{value}</td><td>{esc(fmt_period(record))}</td>"
            f"<td><span class=\"formula\">{esc(shorten(formula, 110))}</span></td></tr>"
        )
    return (
        '<table class="audit-table selected-evidence"><thead><tr><th>Short ref / 短引用</th><th>Class</th>'
        "<th>Metric / 指标</th><th>Exact value / 原始值</th><th>Period / 期间</th>"
        f"<th>Source / formula</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def what_is_priced_in_html(contract: dict[str, Any], *, compact: bool = False) -> str:
    priced = contract.get("what_is_priced_in", {})
    if priced.get("status") != "VALIDATED":
        return '<div class="answer-box warning"><strong>What Is Priced In / 市场隐含要求:</strong> Not validated / 尚未验证。</div>'
    risk_detail = "" if compact else (
        f'<p class="small"><b>Risk interpretation / 风险解读:</b> {esc(priced.get("risk_interpretation"))}</p>'
    )
    body = (
        '<div class="answer-box"><strong>What Is Priced In / 市场隐含要求</strong>'
        f'<p>{esc(priced.get("conditional_conclusion"))}</p>'
        f'{risk_detail}'
        f'{bundle_badge(contract, "executive_view")}</div>'
    )
    if compact:
        return body
    return body + f'<p class="formula">{esc(priced.get("formula"))}</p>'


def valuation_status_html(contract: dict[str, Any], *, compact: bool = False) -> str:
    valuation_status = contract.get("valuation_status", {})
    components = valuation_status.get("components", {})
    forward_contract = contract.get("forward_valuation_contract", {})
    forward_status = forward_contract.get(
        "status",
        valuation_status.get(
            "forward_valuation_contract_status",
            "DRIVER_MODEL_NOT_AVAILABLE",
        ),
    )
    forward_module = forward_contract.get("driver_module") or "Not selected"
    if compact:
        incomplete = [name for name, status in components.items() if status != "COMPLETED"]
        return (
            f'<p><b>Valuation Status / 估值状态:</b> {esc(valuation_status.get("status"))}; '
            f'<b>forward model / 前瞻模型:</b> {esc(forward_status)} '
            f'({esc(forward_module)}); '
            f'<b>not completed / 未完成:</b> {esc(", ".join(incomplete) or "None")}.</p>'
        )
    rows = "".join(
        f'<tr><td>{esc(name.replace("_", " ").title())}</td><td>{esc(status)}</td></tr>'
        for name, status in components.items()
    )
    return (
        f'<div class="answer-box warning"><strong>Valuation Status / 估值状态: {esc(valuation_status.get("status"))}</strong>'
        f'<p>{esc(valuation_status.get("disclosure"))}</p></div>'
        '<table><thead><tr><th>Component / 组件</th><th>Status / 状态</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        f'{list_html(valuation_status.get("limitations", []))}'
    )


def forward_operating_bridge_html(contract: dict[str, Any]) -> str:
    forward = contract.get("forward_valuation_contract", {})
    status = forward.get("status") or "DRIVER_MODEL_NOT_AVAILABLE"
    module = forward.get("driver_module") or "Not selected"
    if status == "DRIVER_MODEL_NOT_AVAILABLE":
        return (
            '<div class="answer-box warning"><strong>Forward Operating Model / '
            "前瞻经营模型: DRIVER_MODEL_NOT_AVAILABLE</strong>"
            "<p>No controlled business-model driver was validated, so no unsupported "
            "forward FCF forecast was generated. / 尚无适配且通过验证的业务驱动模块，"
            "因此未生成缺乏支持的前瞻FCF预测。</p></div>"
        )
    if (
        status not in {"PARTIALLY_VALIDATED", "VALIDATED"}
        or forward.get("driver_model_status") != "VALIDATED"
    ):
        return (
            '<div class="answer-box warning"><strong>Forward Operating Model / '
            f'前瞻经营模型: {esc(status)}</strong>'
            "<p>Unvalidated forward revenue, FCF, share-count, and per-share values "
            "are suppressed. Review the Validation Report before further valuation work. / "
            "未验证的前瞻收入、FCF、股数及每股数值均已抑制；继续估值前请先复核Validation Report。"
            "</p></div>"
        )
    unit = str(forward.get("unit") or forward.get("currency") or "")
    def forward_amount(value: Any) -> str:
        formatted = fmt_number(value)
        return formatted if formatted == "n/a" or not unit else f"{formatted} {esc(unit)}"

    rows = "".join(
        "<tr>"
        f"<td>{esc(row.get('name'))}</td>"
        f"<td>{esc(row.get('status'))}</td>"
        f'<td class="num">{forward_amount(row.get("revenue_bridge", {}).get("forward_revenue", {}).get("value"))}</td>'
        f'<td class="num">{forward_amount(row.get("forward_fcf"))}</td>'
        "</tr>"
        for row in forward.get("scenarios", [])
    )
    share = forward.get("forward_share_count_bridge", {})
    share_value = (
        fmt_number(share.get("forward_diluted_shares"))
        if share.get("status") == "VALIDATED"
        else "n/a"
    )
    return (
        f'<div class="answer-box"><strong>Forward Operating Model / 前瞻经营模型: '
        f'{esc(status)}</strong><p><b>Module / 模块:</b> {esc(module)}; '
        f'<b>FCF basis / FCF口径:</b> {esc(forward.get("fcf_basis"))}; '
        f'<b>Forward shares / 前瞻股数:</b> '
        f'{share_value} '
        f'as of {esc(share.get("target_date"))} ({esc(share.get("status"))}).</p></div>'
        '<table><thead><tr><th>Scenario / 情景</th><th>Status / 状态</th>'
        '<th class="num">Forward revenue / 前瞻收入</th>'
        '<th class="num">Forward FCF / 前瞻FCF</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def decision_confidence_html(contract: dict[str, Any], *, compact: bool = False) -> str:
    confidence = contract.get("decision_confidence", {})
    if compact:
        return (
            f'<div class="answer-box warning"><strong>Decision Confidence / 决策可信度: {esc(confidence.get("level"))}</strong>'
            f'{list_html(confidence.get("constraints", []), limit=2)}</div>'
        )
    return (
        f'<div class="answer-box"><strong>Decision Confidence / 决策可信度: {esc(confidence.get("level"))}</strong></div>'
        '<div class="two-col"><section><h3>Supports / 支持因素</h3>'
        f'{list_html(confidence.get("supports", []))}</section>'
        '<section><h3>Constraints / 限制因素</h3>'
        f'{list_html(confidence.get("constraints", []))}</section></div>'
        '<div class="two-col"><section><h3>Evidence to increase confidence / 提升可信度所需证据</h3>'
        f'{list_html(confidence.get("evidence_to_increase", []))}</section>'
        '<section><h3>Events that reduce confidence / 降低可信度事件</h3>'
        f'{list_html(confidence.get("events_to_reduce", []))}</section></div>'
    )


def evidence_bundle_index_html(contract: dict[str, Any]) -> str:
    rows = "".join(
        '<tr>'
        f'<td>{evidence_badge(bundle.get("bundle_id"))}</td>'
        f'<td>{esc(bundle.get("label"))}</td>'
        f'<td class="num">{esc(bundle.get("record_count"))}</td>'
        f'<td>{esc(", ".join(bundle.get("display_ids", [])))}</td></tr>'
        for bundle in contract.get("evidence_bundles", [])
    )
    return (
        '<table class="audit-table"><thead><tr><th>Bundle</th><th>Decision section / 决策部分</th>'
        '<th class="num">Records</th><th>Short refs / 短引用</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def one_page_html(contract: dict[str, Any]) -> str:
    question = contract.get("investment_question", {})
    decision = contract.get("investment_decision_summary", {})
    body = report_header(contract, "IC Pre-Read One-Page / 投委会预读一页摘要")
    body += decision_strip(contract)
    body += "<h2>Investment Question / 投资问题</h2>"
    body += f"<p><b>{esc(question.get('text'))}</b></p>"
    body += investment_decision_summary_html(contract, compact=True)
    body += what_is_priced_in_html(contract, compact=True)
    body += headline_metrics(contract)
    body += "<h2>Scenario Price Sensitivity / 情景价格敏感性</h2>" + scenario_table(contract, compact=True)
    body += valuation_return_outputs_html(contract, compact=True)
    body += bundle_badge(contract, "scenario_sensitivity")
    body += '<div class="two-col"><section><h2>Key Debates / 核心争议</h2>'
    body += "".join(debate_html(debate, compact=True) for debate in contract.get("key_debates", []))
    body += f'{bundle_badge(contract, "key_debates")}</section><section><h2>Decision Boundaries / 决策边界</h2>'
    body += valuation_status_html(contract, compact=True)
    body += valuation_cross_checks_html(contract, compact=True)
    weighted_status = (
        contract.get("valuation_contract", {})
        .get("outputs", {})
        .get("probability_weighted_return", {})
        .get("status", "NOT_EVALUATED")
    )
    body += (
        f'<p><b>Probability / 概率:</b> {esc(contract.get("probability_validation", {}).get("status"))}; '
        f'formal weighted outcome {esc(weighted_status)}.</p>'
    )
    body += "<h3>More attractive / 提升吸引力</h3>" + list_html(
        decision.get("what_would_make_attractive", []), limit=1
    )
    body += "<h3>Invalidation / 推翻条件</h3>" + list_html(
        decision.get("what_would_invalidate", []), limit=1
    )
    body += "<h3>Monitor next / 下一步监控</h3>" + list_html(decision.get("what_to_monitor_next", []), limit=1)
    body += decision_confidence_html(contract, compact=True)
    body += '<div class="two-col"><section><h3>Can conclude / 可以得出</h3>'
    body += list_html(contract.get("what_can_be_concluded", []), limit=1)
    body += '</section><section><h3>Cannot conclude / 不能得出</h3>'
    body += list_html(contract.get("what_cannot_be_concluded", []), limit=1) + '</section></div>'
    body += "</section></div>" + portfolio_notice(contract, compact=True)
    body += running_footer(contract)
    return html_page(
        f"{contract.get('company', {}).get('ticker')} One-Page Summary / 一页摘要",
        body,
        one_page=True,
    )


def full_report_html(contract: dict[str, Any]) -> str:
    by_metric = evidence_by_metric(contract)
    question = contract.get("investment_question", {})
    expectations = contract.get("market_expectations", {})
    framework = contract.get("valuation_framework", {})
    s11_contract = contract.get("valuation_cross_check_contract", {})
    reverse = (
        s11_contract.get("reverse_valuation", {})
        if isinstance(s11_contract, dict)
        and s11_contract.get("contract_version")
        else framework.get("reverse_valuation", {})
    )
    rules = contract.get("decision_rules", {})
    body = report_header(contract, "IC Pre-Read Full Report / 投委会预读完整报告")
    body += decision_strip(contract)
    body += "<h2>Executive Investment Answer / 核心投资结论</h2>"
    body += investment_decision_summary_html(contract, compact=True)
    body += what_is_priced_in_html(contract, compact=True)
    body += headline_metrics(contract)
    body += scenario_band(contract)
    body += probability_governance_html(contract, compact=True)
    body += valuation_status_html(contract, compact=True)
    body += decision_confidence_html(contract, compact=True)
    body += '<div class="two-col"><section><h3>What can be concluded / 当前可以得出</h3>'
    body += list_html(contract.get("what_can_be_concluded", []), limit=1)
    body += '</section><section><h3>What cannot be concluded / 当前不能得出</h3>'
    body += list_html(contract.get("what_cannot_be_concluded", []), limit=1)
    body += "</section></div>" + portfolio_notice(contract, compact=True)

    body += '<section class="page-break"><h2>1. Investment Question and Key Debates / 投资问题与核心争议</h2>'
    body += f"<p><b>{esc(question.get('text'))}</b></p>"
    body += (
        f'<p class="muted">Decision supported / 支持的决策：'
        f'{esc(question.get("decision_supported"))}</p>'
    )
    body += "".join(debate_html(debate) for debate in contract.get("key_debates", []))
    body += bundle_badge(contract, "key_debates")
    body += "</section>"

    body += '<section class="page-break"><h2>2. Issuer Underwriting / 发行人基本面分析</h2>'
    body += (
        '<p class="section-intro">Each module is analyst-reviewed and evidence-linked. '
        "A VALIDATED label does not remove the stated limitations. / 每个模块均经过分析复核并链接证据；"
        "“已验证”不代表相关限制已经消失。</p>"
    )
    body += issuer_modules_html(
        contract,
        [
            "business_and_industry",
            "earnings_quality",
            "working_capital_and_cash_conversion",
            "capital_allocation",
        ],
    )
    body += "<h3>Selected operating and cash-conversion metrics / 关键经营与现金转化指标</h3>"
    body += key_metric_table(
        contract,
        [
            "latest_quarter_revenue",
            "latest_quarter_cfo",
            "latest_quarter_fcf",
            "accounts_receivable_net",
            "inventory_net",
            "accounts_payable",
            "dso_avg_ar",
            "dio_avg_inventory",
            "dpo_avg_ap",
            "cash_conversion_cycle",
        ],
    )
    body += "</section>"

    body += '<section class="page-break"><h2>3. Earnings Quality and Public-Data FCF Base / 盈利质量与公开数据FCF基准</h2>'
    earnings = contract.get("issuer_underwriting", {}).get("modules", {}).get("earnings_quality", {})
    body += f"<p>{esc(earnings.get('conclusion'))}</p>"
    body += normalized_fcf_bridge(contract)
    body += fcf_quality_html(contract)
    body += (
        '<div class="answer-box warning"><strong>Double-counting rule / 防重复计算规则:</strong> '
        "CFO already includes cash interest, cash taxes, working-capital movements and operating lease cash "
        "flows under the applicable presentation. They are not deducted again. Any non-cash item already added "
        "back within reported CFO is not added back a second time in a CFO-based FCF bridge. / 在适用列报口径下，"
        "CFO 已包含现金利息、现金税、营运资金变动及经营租赁现金流，因此不再重复扣除；任何已在报告CFO中"
        "加回的非现金项目，也不得在基于CFO的FCF桥接中再次加回。</div>"
    )
    body += "<h3>LTM construction / LTM构建</h3>"
    body += key_metric_table(
        contract,
        ["valuation_basis_revenue", "valuation_basis_cfo", "valuation_basis_capex", "reported_ltm_fcf"],
    )
    body += "</section>"

    body += '<section class="page-break"><h2>4. Liquidity, Debt and Refinancing / 流动性、债务与再融资</h2>'
    body += issuer_modules_html(
        contract,
        ["liquidity_sources_and_uses", "debt_leases_covenants_refinancing", "stress_test"],
    )
    body += "<h3>Validated balance-sheet and obligation facts / 已验证资产负债表与义务</h3>"
    body += key_metric_table(
        contract,
        [
            "unrestricted_cash",
            "total_available_borrowings_reported",
            "available_liquidity_including_reported_facility",
            "current_debt",
            "long_term_debt",
            "operating_lease_current",
            "operating_lease_noncurrent",
            "purchase_commitments",
            "variable_rate_interest_sensitivity",
        ],
    )
    credit = contract.get("credit_constraint_status", {})
    body += (
        f'<div class="answer-box"><strong>Credit constraint status / 信用约束状态:</strong> '
        f'{esc(credit.get("status"))}. {esc(credit.get("basis"))}</div>'
    )
    ledger_rows = []
    for line in contract.get("cash_flow_ledger", []):
        ledger_rows.append(
            "<tr>"
            f"<td>{esc(line.get('label'))}</td><td class=\"num\">{fmt_money(line.get('amount'))}</td>"
            f"<td>{esc(line.get('treatment'))}</td><td>{esc(line.get('embedded_in_cfo'))}</td>"
            f"<td>{esc(line.get('separately_modeled'))}</td><td>{esc(line.get('double_count_status'))}</td></tr>"
        )
    body += "<h3>Cash-flow treatment ledger / 现金流处理台账</h3>"
    body += (
        "<table><thead><tr><th>Line / 项目</th><th class=\"num\">Amount / 金额</th>"
        "<th>Treatment</th><th>In CFO</th><th>Separate</th><th>Double count</th></tr>"
        f"</thead><tbody>{''.join(ledger_rows)}</tbody></table>"
    )
    body += bundle_badge(contract, "liquidity_credit")
    body += "</section>"

    body += '<section class="page-break"><h2>5. Guidance, Consensus and Variant Perception / 指引、一致预期与差异化观点</h2>'
    body += issuer_modules_html(contract, ["management_guidance_and_subsequent_events"])
    body += f"<h3>Consensus / 一致预期</h3><p>{esc(expectations.get('summary_view'))}</p>"
    body += f"<h3>Variant question / 差异化问题</h3><p>{esc(expectations.get('variant_question'))}</p>"
    body += variant_perception_html(contract)
    indicator_rows = []
    for indicator in expectations.get("indicators", []):
        indicator_rows.append(
            f"<tr><td>{esc(indicator.get('indicator'))}</td>"
            f"<td class=\"num\">{esc(indicator.get('display'))}</td>"
            f"<td>{esc(indicator.get('interpretation'))}</td>"
            f"<td>{esc(indicator.get('evidence_type'))}</td></tr>"
        )
    body += (
        "<table class=\"audit-table\"><thead><tr><th>Indicator / 指标</th><th class=\"num\">Observation / 观察值</th>"
        "<th>Interpretation boundary / 解读边界</th><th>Class</th></tr></thead>"
        f"<tbody>{''.join(indicator_rows)}</tbody></table>{bundle_badge(contract, 'valuation_market')}</section>"
    )

    body += '<section class="page-break"><h2>6. What Is Priced In and Valuation Scope / 市场隐含要求与估值范围</h2>'
    body += valuation_status_html(contract)
    body += valuation_cross_checks_html(contract)
    body += forward_operating_bridge_html(contract)
    body += what_is_priced_in_html(contract)
    body += (
        '<p class="section-intro">A selected multiple or yield remains a controlled sensitivity reference. '
        "Peer and historical support can contextualize it but cannot turn it into a fair-value fact. / "
        "选定倍数或收益率仍是受控敏感性参考；同业和历史支持可以提供背景，但不能将其变成公允价值事实。</p>"
    )
    selected_reference = (
        reverse.get("selected_reference", {}).get("value")
        if isinstance(reverse.get("selected_reference"), dict)
        else reverse.get("selected_multiple")
    )
    required_metric = (
        reverse.get("required_metric_value")
        if reverse.get("required_metric_value") is not None
        else reverse.get("required_fcf")
    )
    reverse_rows = [
        (
            "Dated market price / 市场价格",
            fmt_price(contract.get("valuation", {}).get("price")),
            record_badge(by_metric.get("market_price_unadjusted_close")),
        ),
        (
            "Market capitalization / 市值",
            fmt_money(contract.get("valuation", {}).get("market_cap")),
            record_badge(by_metric.get("market_cap_point_in_time")),
        ),
        (
            "Selected multiple / 选定倍数",
            fmt_multiple(selected_reference),
            record_badge(by_metric.get("reverse_valuation_selected_multiple")),
        ),
        (
            "Required metric at selected reference / 选定参考所需指标",
            fmt_money(required_metric),
            record_badge(by_metric.get("reverse_valuation_required_metric_value")),
        ),
        (
            "Public-Data FCF Underwriting Base / 公开数据FCF分析基准",
            fmt_money(contract.get("fcf_underwriting_base", {}).get("value")),
            "",
        ),
        (
            "FactSet median target / FactSet目标价中位数",
            fmt_record(by_metric.get("factset_median_price_target")),
            record_badge(by_metric.get("factset_median_price_target")),
        ),
    ]
    body += (
        "<table><thead><tr><th>Input or output / 输入或输出</th>"
        "<th class=\"num\">Value / 数值</th></tr></thead><tbody>"
        + "".join(
            f"<tr><td>{esc(label)}</td><td class=\"num\">{value}</td></tr>"
            for label, value, _evidence in reverse_rows
        )
        + "</tbody></table>"
    )
    body += "<h3>Implied share-price sensitivity / 隐含股价敏感性</h3>" + sensitivity_table(contract)
    body += "<h3>Reverse-valuation limitations / 反向估值限制</h3>" + list_html(
        reverse.get("limitations", reverse.get("assumptions", []))
    )
    body += '<div class="bundle-tail"><h3>Peer valuation context / 同业估值背景</h3>'
    body += peer_valuation_html(contract)
    body += bundle_badge(contract, "valuation_market") + "</div>"
    body += "</section>"

    body += '<section><h2>7. Scenario Price Sensitivity: Bear, Base and Bull / 情景价格敏感性：悲观、基准与乐观</h2>'
    body += scenario_table(contract, compact=True)
    body += "<h3>Separated valuation outputs / 分离估值输出</h3>"
    body += valuation_return_outputs_html(contract)
    scenario_zh = {"Bear": "悲观", "Base": "基准", "Bull": "乐观"}
    for scenario in display_scenarios(contract):
        body += (
            '<div class="module">'
            f"<h3>{esc(scenario.get('name'))} scenario / "
            f"{esc(scenario_zh.get(scenario.get('name'), '情景'))}</h3>"
            f"<p><b>Key driver / 核心驱动:</b> {esc(scenario.get('key_driver'))}</p>"
            f"<p><b>Falsification / 推翻条件:</b> {esc(scenario.get('falsification_trigger'))}</p>"
            f"<p><b>Notes / 说明:</b> {esc(scenario.get('notes'))}</p>"
            f'<p class="formula">{esc(scenario.get("formula"))}</p></div>'
        )
    body += probability_governance_html(contract)
    body += "</section>"

    body += '<section><h2>8. Decision Rules and Monitoring / 决策规则与监控</h2>'
    body += '<div class="two-col"><section><h3>Upgrade conditions / 上调条件</h3>'
    body += list_html(rules.get("upgrade_conditions", []))
    body += '</section><section><h3>Downgrade conditions / 下调条件</h3>'
    body += list_html(rules.get("downgrade_conditions", []))
    body += "</section></div>"
    body += "<h3>Thesis invalidation / 投资逻辑失效条件</h3>" + list_html(
        rules.get("thesis_invalidation_conditions", [])
    )
    body += "<h3>Catalysts / 催化剂</h3>" + list_html(contract.get("catalysts", []))
    body += "<h3>Evidence required next / 下一步所需证据</h3>" + list_html(
        contract.get("evidence_required_next", [])
    )
    body += "<h3>Investment Decision Summary / 投资决策摘要</h3>"
    body += investment_decision_summary_html(contract)
    body += "<h3>Decision Confidence / 决策可信度</h3>" + decision_confidence_html(contract)
    body += portfolio_notice(contract) + "</section>"

    body += '<section><h2>9. Validation, Evidence and Audit Trail / 验证、证据与审计轨迹</h2>'
    body += (
        f"<p><b>Contract validation:</b> {esc(contract.get('contract_validation', {}).get('status'))}; "
        f"<b>Hard Stops:</b> {len(contract.get('hard_stops', []))}; "
        f"<b>Warnings:</b> {len(contract.get('warnings', []))}; "
        f"<b>Evidence records:</b> {len(contract.get('evidence_records', []))}; "
        f"<b>Source records:</b> {len(contract.get('source_registry', []))}.</p>"
    )
    body += (
        '<p class="small muted">Classification rule / 分类规则: FACT is directly sourced; CALC is reproducible '
        "from cited inputs; INFERENCE is an evidence-based interpretation; JUDGMENT is analyst-owned; "
        "MISSING is explicitly unavailable. The renderer performs no analytical recalculation. / "
        "渲染器不进行分析性重算。</p>"
    )
    if contract.get("warnings"):
        body += "<h3>Active warnings / 当前警告</h3>" + list_html(
            [
                f"{row.get('check_id')}: {row.get('message')} Impact: {row.get('decision_impact')}"
                for row in contract.get("warnings", [])
            ]
        )
    body += "<h3>Evidence bundles / 证据包</h3>" + evidence_bundle_index_html(contract)
    body += "<h3>Selected short evidence references / 关键短证据引用</h3>" + evidence_register(contract)
    body += "</section>"

    body += '<section><h2>10. Source Register / 来源记录</h2>'
    body += (
        '<p class="section-intro">Source hierarchy: Level 1 regulatory/company filings; Level 2 official '
        "company materials; Level 3 approved research market data; Level 4 institutional third-party research; "
        "Level 5 other external sources. Level 0 denotes analyst-owned assumptions or calculations and is never "
        "presented as an external fact. / 来源层级依次为监管文件、公司官方材料、获准研究市场数据、机构第三方研究"
        "及其他外部来源；Level 0 为分析师假设或计算，不作为外部事实呈现。</p>"
    )
    body += source_register(contract)
    body += (
        f'<p class="small muted">Full machine-readable ledger: contract {esc(contract.get("report_id"))}, '
        f'hash {esc(contract.get("contract_hash"))}. One-Page and Full Report use this same object. '
        "No report output authorizes a trade.</p></section>"
    )
    body += running_footer(contract)
    return html_page(
        f"{contract.get('company', {}).get('ticker')} Full Investment Underwriting Report / 完整投资分析报告",
        body,
    )


def evidence_audit_html(contract: dict[str, Any]) -> str:
    aliases = evidence_alias_map(contract)
    records = []
    for row in contract.get("evidence_records", []):
        value = fmt_record(row, exact=True)
        if row.get("unit") in {"text", "filing"}:
            value = esc(shorten(row.get("value"), 220))
        records.append(
            "<tr>"
            f'<td class="source-ids">{esc(row.get("evidence_id"))}</td>'
            f'<td>{evidence_badge(aliases.get(str(row.get("evidence_id"))))}</td>'
            f'<td>{esc(row.get("evidence_class"))}</td>'
            f'<td>{esc(row.get("metric_name"))}</td>'
            f'<td>{value}</td>'
            f'<td>{esc(fmt_period(row))}<br><span class="muted">as of {esc(row.get("as_of_date"))}</span></td>'
            f'<td>L{esc(row.get("source_level"))}<br><span class="source-ids">{esc(row.get("source_id"))}</span></td>'
            f'<td>{esc(shorten(row.get("source_locator"), 150))}<br>'
            f'<span class="formula">{esc(shorten(row.get("formula") or row.get("measurement_basis"), 160))}</span></td>'
            f'<td class="source-ids">{esc(" ".join(row.get("input_evidence_ids", [])))}</td></tr>'
        )
    sources = []
    for row in contract.get("source_registry", []):
        link = f'<a href="{esc(row.get("source_url"))}">{esc(shorten(row.get("source_url"), 85))}</a>' if row.get("source_url") else "n/a"
        sources.append(
            "<tr>"
            f'<td class="source-ids">{esc(row.get("source_id"))}</td>'
            f'<td>L{esc(row.get("source_level"))}</td>'
            f'<td>{esc(row.get("source_name"))}<br><span class="muted">{esc(row.get("source_type"))}</span></td>'
            f'<td>{esc(row.get("publication_date"))}</td><td>{esc(row.get("retrieval_date"))}</td>'
            f'<td>{esc(shorten(row.get("source_locator"), 180))}</td><td>{link}</td></tr>'
        )
    body = report_header(contract, "Evidence Audit Appendix / 证据审计附录")
    body += (
        '<div class="answer-box"><strong>Purpose / 用途</strong><p>This appendix preserves the raw machine-audit trail. '
        'The One-Page and Full Report use evidence bundles and short references from the same validated contract; no analytical meaning is changed. / '
        '本附录保留完整机器审计轨迹；一页摘要与完整报告使用同一已验证合同中的证据包及短引用，不改变分析含义。</p></div>'
    )
    body += "<h2>Evidence Bundle Map / 证据包映射</h2>" + evidence_bundle_index_html(contract)
    body += '<section class="page-break"><h2>Raw Evidence Ledger / 原始证据台账</h2>'
    body += (
        '<table class="audit-table"><thead><tr><th>Raw evidence ID</th><th>Short</th><th>Class</th>'
        '<th>Metric</th><th>Exact value</th><th>Period / as-of</th><th>Source</th><th>Locator / formula</th><th>Inputs</th></tr></thead>'
        f'<tbody>{"".join(records)}</tbody></table></section>'
    )
    body += '<section class="page-break"><h2>Raw Source Registry / 原始来源记录</h2>'
    body += (
        '<table class="audit-table"><thead><tr><th>Source ID</th><th>Level</th><th>Name / type</th>'
        '<th>Published</th><th>Retrieved</th><th>Locator</th><th>Link</th></tr></thead>'
        f'<tbody>{"".join(sources)}</tbody></table></section>'
    )
    body += running_footer(contract)
    return html_page(
        f"{contract.get('company', {}).get('ticker')} Evidence Audit Appendix / 证据审计附录",
        body,
    )


def qa_summary_html(contract: dict[str, Any]) -> str:
    dates = contract.get("report_dates", {})
    fcf = contract.get("fcf_underwriting_base", {})
    share = contract.get("share_count_basis", {})
    probability = contract.get("probability_validation", {})
    valuation = contract.get("valuation_status", {})
    valuation_outputs = contract.get("valuation_contract", {}).get("outputs", {})
    checks = [
        ("Contract validation / 合同验证", contract.get("contract_validation", {}).get("status")),
        ("Data validation / 数据验证", contract.get("validation_status")),
        ("Hard Stops / 强制停止", len(contract.get("hard_stops", []))),
        ("Warnings / 警告", len(contract.get("warnings", []))),
        ("FCF source data / FCF源数据", fcf.get("source_data_validation_status")),
        ("FCF calculation / FCF计算", fcf.get("calculation_validation_status")),
        ("FCF normalization / FCF标准化", fcf.get("normalization_status")),
        ("Share-count basis / 股数口径", share.get("proxy_status")),
        ("Forward share bridge / 前瞻股数桥", share.get("forward_share_count_bridge_status")),
        ("Valuation scope / 估值范围", valuation.get("status")),
        ("Probability governance / 概率治理", probability.get("status")),
        ("Formal weighted outcome / 正式概率加权结果", probability.get("formal_probability_weighted_expected_return_status")),
        ("Return context / 回报语境", contract.get("return_context", {}).get("status")),
        ("Price sensitivity / 价格敏感性", valuation_outputs.get("price_sensitivity", {}).get("status")),
        ("Base-case return / 基准情景回报", valuation_outputs.get("base_case_return", {}).get("status")),
        (
            "Probability-weighted return / 概率加权回报",
            valuation_outputs.get("probability_weighted_return", {}).get("status"),
        ),
        ("User internal return / User内部回报", valuation_outputs.get("partner_internal_return", {}).get("status")),
        ("Portfolio overlay / 组合叠加", contract.get("portfolio_context", {}).get("status")),
    ]
    rows = "".join(f'<tr><td>{esc(label)}</td><td><b>{esc(value)}</b></td></tr>' for label, value in checks)
    warning_items = [
        f"{row.get('check_id')}: {row.get('message')}"
        for row in contract.get("warnings", [])
    ]
    body = report_header(contract, "v1.0.0 QA Summary / v1.0.0质量检查摘要")
    body += decision_strip(contract)
    body += (
        '<div class="answer-box"><strong>QA conclusion / 质量检查结论</strong>'
        f'<p>Schema {esc(contract.get("schema_version"))}; contract hash {esc(str(contract.get("contract_hash"))[:16])}; '
        'One-Page, Full Report, and Evidence Appendix are rendered from this same validated object. / '
        '一页摘要、完整报告及证据附录均由同一个已验证对象生成。</p></div>'
    )
    body += '<div class="two-col"><section><h2>Date and Period Boundary / 日期与期间边界</h2>'
    body += (
        f'<p><b>Financial statement date:</b> {esc(dates.get("financial_statement_date"))}<br>'
        f'<b>Market price date:</b> {esc(dates.get("market_price_date"))}<br>'
        f'<b>Share-count date:</b> {esc(dates.get("share_count_date"))}<br>'
        f'<b>Subsequent-event review through:</b> {esc(dates.get("subsequent_event_index_review_through"))}</p>'
        f'<p>{esc(share.get("known_subsequent_event_note"))}</p></section>'
    )
    body += '<section><h2>Control Status / 控制状态</h2>'
    body += f'<table><tbody>{rows}</tbody></table></section></div>'
    body += '<div class="two-col"><section><h2>Decision Boundaries / 决策边界</h2>'
    body += list_html(contract.get("what_cannot_be_concluded", []))
    body += '</section><section><h2>Active Warnings / 当前警告</h2>' + list_html(warning_items) + '</section></div>'
    body += (
        '<div class="portfolio-disabled"><b>Renderer integrity / 渲染完整性:</b> Formatting only; no independent '
        'valuation, financial-period construction, share bridge, or investment conclusion is recalculated in the renderer. / '
        '渲染器仅负责格式，不独立重算估值、财务期间、股数桥或投资结论。</div>'
    )
    body += running_footer(contract)
    return html_page(
        f"{contract.get('company', {}).get('ticker')} v1.0.0 QA Summary / 质量检查摘要",
        body,
        one_page=True,
    )


def diagnostic_html(contract: dict[str, Any]) -> str:
    body = report_header(contract, "Diagnostic Validation Report / 诊断验证报告")
    body += decision_strip(contract)
    body += (
        '<div class="answer-box warning"><strong>'
        "Formal report generation blocked / 正式报告已阻止</strong></div>"
    )
    body += "<h2>Contract blockers / Contract阻断项</h2>" + list_html(
        contract.get("render_blockers", [])
    )
    body += "<h2>Hard Stops / 强制停止</h2>" + list_html(
        [
            f"{row.get('check_id')}: {row.get('message', row.get('evidence'))}"
            for row in contract.get("hard_stops", [])
        ]
    )
    body += "<h2>Remediation / 修复要求</h2>" + list_html(
        [
            row.get("remediation")
            for row in contract.get("hard_stops", [])
            if row.get("remediation")
        ]
    )
    body += running_footer(contract)
    return html_page("Diagnostic Validation Report / 诊断验证报告", body)


def chrome_binary() -> str | None:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ]
    return next((str(path) for path in candidates if path and Path(path).exists()), None)


def print_pdf(html_path: Path, pdf_path: Path) -> None:
    binary = chrome_binary()
    if not binary:
        raise RuntimeError("Google Chrome or Chromium is required for PDF output.")
    subprocess.run(
        [
            binary,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        raise RuntimeError(f"PDF generation produced no file: {pdf_path}")


def render(contract_path: Path, out_dir: Path, *, pdf: bool = False) -> dict[str, Any]:
    contract = load_contract(contract_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    formal_blocked = (
        bool(contract.get("render_blockers"))
        or bool(contract.get("hard_stops"))
        or float(contract.get("data_gate", {}).get("level", 0)) == 0
    )
    outputs: dict[str, str] = {}
    ticker = str(contract.get("company", {}).get("ticker") or "Company").upper()
    if formal_blocked:
        diagnostic = out_dir / f"{ticker}_Diagnostic_Validation_Report.html"
        diagnostic.write_text(diagnostic_html(contract), encoding="utf-8")
        outputs["diagnostic_html"] = str(diagnostic)
        if pdf:
            diagnostic_pdf = out_dir / f"{ticker}_Diagnostic_Validation_Report.pdf"
            print_pdf(diagnostic, diagnostic_pdf)
            outputs["diagnostic_pdf"] = str(diagnostic_pdf)
    else:
        one_page = out_dir / f"{ticker}_One_Page_Summary_Bilingual.html"
        full_report = out_dir / f"{ticker}_Full_Report_Bilingual.html"
        evidence_appendix = out_dir / f"{ticker}_Evidence_Audit_Appendix_Bilingual.html"
        qa_summary = out_dir / f"{ticker}_V1_0_0_QA_Summary_Bilingual.html"
        one_page.write_text(one_page_html(contract), encoding="utf-8")
        full_report.write_text(full_report_html(contract), encoding="utf-8")
        evidence_appendix.write_text(evidence_audit_html(contract), encoding="utf-8")
        qa_summary.write_text(qa_summary_html(contract), encoding="utf-8")
        outputs.update(
            {
                "one_page_html": str(one_page),
                "full_report_html": str(full_report),
                "evidence_appendix_html": str(evidence_appendix),
                "qa_summary_html": str(qa_summary),
            }
        )
        if pdf:
            one_pdf = out_dir / f"{ticker}_One_Page_Summary_Bilingual.pdf"
            full_pdf = out_dir / f"{ticker}_Full_Report_Bilingual.pdf"
            evidence_pdf = out_dir / f"{ticker}_Evidence_Audit_Appendix_Bilingual.pdf"
            qa_pdf = out_dir / f"{ticker}_V1_0_0_QA_Summary_Bilingual.pdf"
            print_pdf(one_page, one_pdf)
            print_pdf(full_report, full_pdf)
            print_pdf(evidence_appendix, evidence_pdf)
            print_pdf(qa_summary, qa_pdf)
            outputs.update(
                {
                    "one_page_pdf": str(one_pdf),
                    "full_report_pdf": str(full_pdf),
                    "evidence_appendix_pdf": str(evidence_pdf),
                    "qa_summary_pdf": str(qa_pdf),
                }
            )

    manifest = {
        "report_id": contract.get("report_id"),
        "contract_hash": contract.get("contract_hash"),
        "contract_path": str(contract_path),
        "formal_report_blocked": formal_blocked,
        "outputs": outputs,
        "renderer_rule": "Formatting only; no analytical recalculation.",
        "contract_validation": contract.get("contract_validation", {}).get("status"),
        "data_gate": contract.get("data_gate", {}).get("level"),
        "hard_stop_count": len(contract.get("hard_stops", [])),
        "warning_count": len(contract.get("warnings", [])),
    }
    manifest_path = out_dir / "render_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render bilingual one-page and full-report artifacts from a shared underwriting contract."
    )
    parser.add_argument("contract", help="Path to underwriting_output_contract.json")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument("--pdf", action="store_true", help="Also print PDFs with local Chrome or Chromium")
    args = parser.parse_args()
    manifest = render(Path(args.contract), Path(args.out_dir), pdf=args.pdf)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
