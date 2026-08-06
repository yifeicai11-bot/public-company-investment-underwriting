#!/usr/bin/env python3
"""Render S14 Gate 4 reports without recalculating assessment outputs."""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


SYNTHETIC_CLASSIFICATION = "SYNTHETIC_PUBLIC_EXAMPLE"
REPORT_FILENAMES = {
    "one_page": "Gate4_One_Page_Summary_Bilingual",
    "full_report": "Gate4_Full_Report_Bilingual",
    "evidence_appendix": "Gate4_Evidence_Appendix_Bilingual",
    "validation_report": "Gate4_Validation_Report_Bilingual",
}


def _esc(value: Any) -> str:
    text = "" if value is None else str(value)
    # Keep contract field names stable, while using neutral language in rendered text.
    text = re.sub(r"\bpartner-approved\b", "approved", text, flags=re.IGNORECASE)
    text = re.sub(r"\bpartner overlay\b", "portfolio overlay", text, flags=re.IGNORECASE)
    text = re.sub(r"\bpartner preference\b", "user preference", text, flags=re.IGNORECASE)
    text = re.sub(r"\bPartner\b", "User", text)
    text = re.sub(r"\bpartner\b", "user", text)
    return html.escape(text)


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _fmt_constraint_field(row: dict[str, Any], field: str) -> str:
    """Format constraint values from their contract-defined calculation semantics."""
    value = row.get(field)
    if value is None:
        return "n/a"

    constraint_id = str(row.get("constraint_id") or "")
    if constraint_id == "holding_period":
        return f"{float(value):.0f} days"
    if constraint_id == "liquidity_exit_capacity":
        if field == "limit_value":
            return f"{float(value):.0f} days"
        if field == "candidate_value":
            return f"{float(value):,.0f} (base currency)"
    return _fmt_pct(value)


def _company(contract: dict[str, Any]) -> tuple[str, str]:
    gate3 = contract.get("gate3_identity", {})
    company = gate3.get("company", {}) if isinstance(gate3, dict) else {}
    name = str(
        company.get("name")
        or contract.get("candidate_identity", {}).get("issuer_name")
        or "Unknown issuer"
    )
    ticker = str(
        company.get("ticker")
        or contract.get("candidate_identity", {}).get("security_identifier")
        or "N/A"
    )
    return name, ticker


def _decision_labels(contract: dict[str, Any]) -> tuple[str, str, str]:
    assessment = contract.get("system_portfolio_assessment", {})
    user = contract.get("partner_decision", {})
    return (
        str(assessment.get("assessment_label_en") or "Not Evaluated"),
        str(assessment.get("assessment_label_zh") or "未完成评估"),
        str(user.get("decision") or "PENDING"),
    )


def _binding_names(contract: dict[str, Any]) -> str:
    rows = contract.get("constraint_snapshot", {}).get("binding_constraints", [])
    values = [str(row.get("constraint_id")) for row in rows if isinstance(row, dict)]
    return ", ".join(values) if values else "None / 无"


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        values = [str(value).replace("|", "\\|").replace("\n", " ") for value in row]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def markdown_reports(contract: dict[str, Any]) -> dict[str, str]:
    name, ticker = _company(contract)
    assessment = contract["system_portfolio_assessment"]
    user = contract["partner_decision"]
    ceiling = assessment["maximum_constraint_ceiling"]
    assessment_en, assessment_zh, decision = _decision_labels(contract)
    banner = (
        "SYNTHETIC DATA ONLY / 仅使用合成数据"
        if contract.get("data_classification") == SYNTHETIC_CLASSIFICATION
        else "PRIVATE LOCAL OUTPUT / 私有本地输出"
    )
    snapshot_rows = [
        ["System Assessment / 系统评估", f"{assessment_en} / {assessment_zh}"],
        ["User Decision / User 决策", decision],
        ["Constraint ceiling, incremental / 约束上限（新增）", _fmt_pct(ceiling.get("incremental_weight"))],
        ["Constraint ceiling, total issuer / 约束上限（发行人总仓位）", _fmt_pct(ceiling.get("total_issuer_weight"))],
        ["Binding constraint / 约束项", _binding_names(contract)],
        ["Assessment hash / 评估哈希", contract.get("assessment_hash") or "n/a"],
    ]
    one_page = "\n".join(
        [
            f"# {name} ({ticker}) Gate 4 One-Page Summary / Gate 4 一页摘要",
            f"**{banner}**",
            "",
            _markdown_table(["Decision field / 决策字段", "Validated output / 已验证输出"], snapshot_rows),
            "",
            "## Decision Rationale / 决策依据",
            *[f"- {value}" for value in assessment.get("rationale_en", [])],
            *[f"- {value}" for value in assessment.get("rationale_zh", [])],
            "",
            "## Active Escalations / 有效升级项",
            *([f"- `{value}`" for value in assessment.get("escalation_ids", [])] or ["- None / 无"]),
            "",
            "## Boundary / 边界",
            f"- {ceiling.get('disclosure_en')}",
            f"- {ceiling.get('disclosure_zh')}",
            f"- {contract.get('next_action_en')}",
            f"- {contract.get('next_action_zh')}",
        ]
    )

    constraint_rows = []
    for row in contract.get("constraint_snapshot", {}).get("constraints", []):
        constraint_rows.append(
            [
                row.get("label_en"),
                row.get("label_zh"),
                row.get("status"),
                _fmt_constraint_field(row, "limit_value"),
                _fmt_constraint_field(row, "current_value"),
                _fmt_constraint_field(row, "candidate_value"),
                _fmt_pct(row.get("maximum_incremental_position_weight")),
                "Yes" if row.get("binding") else "No",
                "Yes" if row.get("escalation_triggered") else "No",
            ]
        )
    approved_range = user.get("approved_position_range")
    approval_lines = [
        f"- Submitted decision / 提交决定: {user.get('submitted_decision')}",
        f"- Effective decision / 生效决定: {user.get('decision')}",
        f"- Validation / 验证: {user.get('validation_status')}",
        f"- Approved range / 已批准区间: {(_fmt_pct(approved_range.get('minimum')) + ' to ' + _fmt_pct(approved_range.get('maximum'))) if isinstance(approved_range, dict) else 'n/a'}",
        "- Automatic trade execution / 自动交易执行: Disabled / 已禁用",
    ]
    full_report = "\n".join(
        [
            f"# {name} ({ticker}) Gate 4 Full Report / Gate 4 完整报告",
            f"**{banner}**",
            "",
            "## Executive Decision / 核心决策",
            _markdown_table(["Field / 字段", "Output / 输出"], snapshot_rows),
            "",
            "## System Assessment / 系统评估",
            *[f"- {value}" for value in assessment.get("rationale_en", [])],
            *[f"- {value}" for value in assessment.get("rationale_zh", [])],
            f"- Can support User approval / 可支持 User 审批: {assessment.get('can_support_partner_approval')}",
            "",
            "## Constraint Matrix / 约束矩阵",
            _markdown_table(
                ["Constraint", "中文", "Status", "Limit", "Current", "Candidate", "Incremental ceiling", "Binding", "Escalation"],
                constraint_rows,
            ),
            "",
            "## User Decision / User 决策",
            *approval_lines,
            "",
            "## Decision Boundaries / 决策边界",
            f"- {ceiling.get('disclosure_en')}",
            f"- {ceiling.get('disclosure_zh')}",
            "- System position range / 系统仓位区间: null",
            "- External transmission / 对外传输: DENIED",
            "- Automatic trade execution / 自动交易执行: false",
        ]
    )

    evidence_rows = []
    for row in contract.get("evidence_ledger", []):
        evidence_rows.append(
            [
                row.get("evidence_id"),
                row.get("evidence_class"),
                row.get("label_en"),
                row.get("label_zh"),
                row.get("source_object"),
                ", ".join(row.get("source_fields", [])),
                _fmt_value(row.get("value")),
            ]
        )
    evidence_appendix = "\n".join(
        [
            f"# {name} ({ticker}) Gate 4 Evidence Appendix / Gate 4 证据附录",
            f"**{banner}**",
            "",
            f"- S13 result hash: `{contract.get('s13_result_hash')}`",
            f"- Assessment hash: `{contract.get('assessment_hash') or 'n/a'}`",
            f"- Assessment input fingerprint: `{contract.get('assessment_input_fingerprint') or 'n/a'}`",
            "",
            _markdown_table(
                ["Evidence ID", "Class", "Label", "中文", "Source object", "Source fields", "Exact value"],
                evidence_rows,
            ),
        ]
    )

    validation_rows = []
    for row in contract.get("validation", {}).get("checks", []):
        validation_rows.append(
            [
                row.get("check_id"),
                row.get("status"),
                row.get("severity"),
                row.get("message_en"),
                row.get("message_zh"),
                ", ".join(row.get("evidence_ids", [])),
            ]
        )
    validation_report = "\n".join(
        [
            f"# {name} ({ticker}) Gate 4 Validation Report / Gate 4 验证报告",
            f"**{banner}**",
            "",
            f"- Output contract: {contract.get('contract_validation', {}).get('status')}",
            f"- Analytical validation: {contract.get('validation', {}).get('status')}",
            f"- Hard Stops: {contract.get('validation', {}).get('hard_stop_count')}",
            f"- Warnings: {contract.get('validation', {}).get('warning_count')}",
            f"- Renderer recalculation: {contract.get('report_controls', {}).get('renderer_may_recalculate')}",
            "",
            _markdown_table(
                ["Check", "Status", "Severity", "Message", "中文", "Evidence"],
                validation_rows,
            ),
        ]
    )
    return {
        "one_page": one_page + "\n",
        "full_report": full_report + "\n",
        "evidence_appendix": evidence_appendix + "\n",
        "validation_report": validation_report + "\n",
    }


def _base_css(*, one_page: bool = False) -> str:
    compact = "font-size:8.5px; line-height:1.25;" if one_page else "font-size:9.5px; line-height:1.38;"
    return f"""
    @page {{ size: A4; margin: 11mm 11mm 13mm; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; color: #18212b; font-family: Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif; {compact} }}
    h1 {{ font-size: 19px; line-height: 1.14; margin: 0 0 5px; color: #0e3a4a; letter-spacing: 0; }}
    h2 {{ font-size: 12px; margin: 10px 0 5px; padding-bottom: 3px; border-bottom: 1px solid #9db1b8; color: #0e3a4a; letter-spacing: 0; }}
    h3 {{ font-size: 10px; margin: 7px 0 3px; letter-spacing: 0; }}
    p {{ margin: 3px 0; }}
    ul {{ margin: 3px 0 5px 16px; padding: 0; }}
    li {{ margin: 2px 0; }}
    .banner {{ background: #fff2bf; border: 1px solid #d6b94f; padding: 5px 7px; font-weight: 700; margin: 6px 0; }}
    .decision {{ background: #eaf3f0; border-left: 4px solid #1f796b; padding: 7px 9px; margin: 6px 0; }}
    .boundary {{ background: #f4f6f7; border-left: 4px solid #66757d; padding: 6px 8px; margin: 6px 0; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }}
    .panel {{ border: 1px solid #c8d2d6; padding: 6px 7px; break-inside: avoid; }}
    .metric {{ font-size: 17px; font-weight: 700; color: #0e3a4a; }}
    .muted {{ color: #64727a; }}
    .hash {{ font-family: Menlo, Consolas, monospace; font-size: 7px; overflow-wrap: anywhere; }}
    table {{ width: 100%; border-collapse: collapse; margin: 4px 0 8px; table-layout: fixed; }}
    th {{ background: #e7edef; color: #24343c; text-align: left; font-weight: 700; }}
    th, td {{ border: 1px solid #bdc9ce; padding: 3px 4px; vertical-align: top; overflow-wrap: anywhere; }}
    .compact-table {{ font-size: 7.6px; line-height: 1.22; }}
    .compact-table th, .compact-table td {{ padding: 2px 3px; }}
    .audit-card {{ border: 1px solid #bdc9ce; margin: 0 0 6px; padding: 6px 7px; break-inside: avoid; }}
    .audit-card h3 {{ color: #0e3a4a; margin-top: 0; border-bottom: 1px solid #d5dde0; padding-bottom: 3px; }}
    .audit-metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 4px; margin: 4px 0; }}
    .audit-metric {{ background: #f3f6f7; padding: 4px; min-height: 31px; }}
    .audit-metric b {{ display: block; font-size: 7px; color: #64727a; }}
    .audit-line {{ display: grid; grid-template-columns: 26mm 1fr; gap: 5px; margin-top: 3px; }}
    .audit-line b {{ color: #34454d; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .status {{ font-weight: 700; }}
    .pass {{ color: #176b4a; }}
    .warning {{ color: #8a5a00; }}
    .fail {{ color: #a12626; }}
    .page-break {{ break-before: page; }}
    .avoid {{ break-inside: avoid; }}
    footer {{ position: fixed; left: 0; right: 0; bottom: -8mm; border-top: 1px solid #bac5c9; padding-top: 2px; font-size: 7px; color: #66757d; display: flex; justify-content: space-between; }}
    .inline-footer {{ margin-top: 8px; border-top: 1px solid #bac5c9; padding-top: 2px; font-size: 7px; color: #66757d; display: flex; justify-content: space-between; }}
    """


def _html_page(title: str, body: str, footer: str, *, one_page: bool = False) -> str:
    footer_tag = f"<div class='inline-footer'>{footer}</div>"
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_esc(title)}</title><style>{_base_css(one_page=one_page)}</style>"
        f"</head><body>{body}{footer_tag}</body></html>"
    )


def _header(contract: dict[str, Any], subtitle: str) -> str:
    name, ticker = _company(contract)
    classification = contract.get("data_classification")
    banner = (
        "SYNTHETIC DATA ONLY / 仅使用合成数据"
        if classification == SYNTHETIC_CLASSIFICATION
        else "PRIVATE LOCAL OUTPUT / 私有本地输出"
    )
    return (
        f"<h1>{_esc(name)} ({_esc(ticker)})</h1>"
        f"<div class='muted'>{_esc(subtitle)}</div>"
        f"<div class='banner'>{_esc(banner)}</div>"
    )


def _footer(contract: dict[str, Any]) -> str:
    _, ticker = _company(contract)
    assessment_hash = str(contract.get("assessment_hash") or "not-evaluated")
    return (
        f"<span>{_esc(ticker)} | Gate 4 S14</span>"
        f"<span>Assessment hash: {_esc(assessment_hash[:16])}</span>"
        "<span>No automatic trade / 不自动交易</span>"
    )


def _snapshot_table(contract: dict[str, Any]) -> str:
    assessment = contract["system_portfolio_assessment"]
    user = contract["partner_decision"]
    ceiling = assessment["maximum_constraint_ceiling"]
    assessment_en, assessment_zh, decision = _decision_labels(contract)
    rows = [
        ("System Assessment / 系统评估", f"{assessment_en}<br>{assessment_zh}"),
        ("User Decision / User 决策", decision),
        ("Constraint ceiling, incremental / 约束上限（新增）", _fmt_pct(ceiling.get("incremental_weight"))),
        ("Constraint ceiling, total issuer / 约束上限（发行人总仓位）", _fmt_pct(ceiling.get("total_issuer_weight"))),
        ("Binding constraint / 约束项", _binding_names(contract)),
        ("Input mode / 输入模式", contract.get("input_mode")),
    ]
    return "<table><tbody>" + "".join(
        f"<tr><th>{_esc(label)}</th><td>{value if '<br>' in str(value) else _esc(value)}</td></tr>"
        for label, value in rows
    ) + "</tbody></table>"


def one_page_html(contract: dict[str, Any]) -> str:
    assessment = contract["system_portfolio_assessment"]
    user = contract["partner_decision"]
    ceiling = assessment["maximum_constraint_ceiling"]
    rationale = "".join(
        f"<li>{_esc(value)}</li>" for value in assessment.get("rationale_en", []) + assessment.get("rationale_zh", [])
    )
    escalations = assessment.get("escalation_ids", [])
    escalation_html = "".join(f"<li>{_esc(value)}</li>" for value in escalations) or "<li>None / 无</li>"
    body = _header(contract, "Gate 4 One-Page Summary / Gate 4 一页摘要")
    body += "<div class='decision'>" + _snapshot_table(contract) + "</div>"
    body += (
        "<div class='grid'><section class='panel'><h2>Decision Rationale / 决策依据</h2>"
        f"<ul>{rationale}</ul></section>"
        "<section class='panel'><h2>Escalations / 升级项</h2>"
        f"<ul>{escalation_html}</ul>"
        f"<p><b>Approval capable / 可支持审批:</b> {_esc(assessment.get('can_support_partner_approval'))}</p>"
        "</section></div>"
    )
    body += (
        "<section class='panel'><h2>User Decision / User 决策</h2>"
        f"<p><b>Submitted / 提交:</b> {_esc(user.get('submitted_decision'))} &nbsp; "
        f"<b>Effective / 生效:</b> {_esc(user.get('decision'))} &nbsp; "
        f"<b>Validation / 验证:</b> {_esc(user.get('validation_status'))}</p>"
        "</section>"
    )
    body += (
        "<div class='boundary'><b>Decision boundary / 决策边界</b>"
        f"<p>{_esc(ceiling.get('disclosure_en'))}</p>"
        f"<p>{_esc(ceiling.get('disclosure_zh'))}</p>"
        f"<p><b>Next / 下一步:</b> {_esc(contract.get('next_action_en'))}<br>{_esc(contract.get('next_action_zh'))}</p>"
        "</div>"
        f"<p class='hash'><b>Assessment hash:</b> {_esc(contract.get('assessment_hash') or 'n/a')}</p>"
    )
    return _html_page(
        "Gate 4 One-Page Summary",
        body,
        _footer(contract),
        one_page=True,
    )


def _constraint_table(contract: dict[str, Any], *, include_formula: bool) -> str:
    headers = ["Constraint / 约束", "Status", "Limit", "Current", "Candidate", "Incremental ceiling", "Binding", "Escalation"]
    if include_formula:
        headers.extend(["Formula", "Source fields"])
    head = "".join(f"<th>{_esc(value)}</th>" for value in headers)
    rows = []
    for row in contract.get("constraint_snapshot", {}).get("constraints", []):
        values = [
            f"{_esc(row.get('label_en'))}<br><span class='muted'>{_esc(row.get('label_zh'))}</span>",
            _esc(row.get("status")),
            _esc(_fmt_constraint_field(row, "limit_value")),
            _esc(_fmt_constraint_field(row, "current_value")),
            _esc(_fmt_constraint_field(row, "candidate_value")),
            _esc(_fmt_pct(row.get("maximum_incremental_position_weight"))),
            "Yes" if row.get("binding") else "No",
            "Yes" if row.get("escalation_triggered") else "No",
        ]
        if include_formula:
            values.extend(
                [
                    _esc(row.get("formula")),
                    _esc(", ".join(row.get("source_fields", []))),
                ]
            )
        rows.append("<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>")
    css_class = "" if include_formula else " class='compact-table'"
    return f"<table{css_class}><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _constraint_audit_cards(contract: dict[str, Any]) -> str:
    cards = []
    for row in contract.get("constraint_snapshot", {}).get("constraints", []):
        metrics = [
            ("Status / 状态", row.get("status")),
            ("Limit / 上限", _fmt_constraint_field(row, "limit_value")),
            ("Current / 当前", _fmt_constraint_field(row, "current_value")),
            ("Candidate / 候选", _fmt_constraint_field(row, "candidate_value")),
            ("Incremental ceiling / 新增上限", _fmt_pct(row.get("maximum_incremental_position_weight"))),
            ("Binding / 约束项", "Yes" if row.get("binding") else "No"),
            ("Escalation / 升级", "Yes" if row.get("escalation_triggered") else "No"),
            ("Constraint ID / 约束编号", row.get("constraint_id")),
        ]
        metric_html = "".join(
            f"<div class='audit-metric'><b>{_esc(label)}</b>{_esc(value)}</div>"
            for label, value in metrics
        )
        cards.append(
            "<section class='audit-card'>"
            f"<h3>{_esc(row.get('label_en'))} / {_esc(row.get('label_zh'))}</h3>"
            f"<div class='audit-metrics'>{metric_html}</div>"
            f"<div class='audit-line'><b>Formula / 公式</b><span class='hash'>{_esc(row.get('formula'))}</span></div>"
            f"<div class='audit-line'><b>Source fields / 来源字段</b><span class='hash'>{_esc(', '.join(row.get('source_fields', [])))}</span></div>"
            "</section>"
        )
    return "".join(cards)


def full_report_html(contract: dict[str, Any]) -> str:
    assessment = contract["system_portfolio_assessment"]
    user = contract["partner_decision"]
    ceiling = assessment["maximum_constraint_ceiling"]
    body = _header(contract, "Gate 4 Full Report / Gate 4 完整报告")
    body += "<h2>Executive Decision / 核心决策</h2>" + _snapshot_table(contract)
    body += "<div class='grid'><section class='panel'><h2>System Assessment / 系统评估</h2><ul>"
    body += "".join(f"<li>{_esc(value)}</li>" for value in assessment.get("rationale_en", []) + assessment.get("rationale_zh", []))
    body += "</ul></section><section class='panel'><h2>State Separation / 状态分离</h2>"
    body += (
        f"<p><b>System:</b> {_esc(assessment.get('assessment_label_en'))} / {_esc(assessment.get('assessment_label_zh'))}</p>"
        f"<p><b>User:</b> {_esc(user.get('decision'))} ({_esc(user.get('validation_status'))})</p>"
        "<p>The system does not own the User decision. / 系统不拥有 User 的最终决定。</p></section></div>"
    )
    body += "<h2>Constraint Matrix / 约束矩阵</h2>" + _constraint_table(contract, include_formula=False)
    body += "<div class='page-break'></div><h2>Constraint Detail and Formula Audit / 约束明细与公式审计</h2>"
    body += _constraint_audit_cards(contract)
    body += "<h2>User Decision Record / User 决策记录</h2>"
    approved_range = user.get("approved_position_range")
    body += (
        "<table><tbody>"
        f"<tr><th>Submitted / 提交</th><td>{_esc(user.get('submitted_decision'))}</td></tr>"
        f"<tr><th>Effective / 生效</th><td>{_esc(user.get('decision'))}</td></tr>"
        f"<tr><th>Validation / 验证</th><td>{_esc(user.get('validation_status'))}</td></tr>"
        f"<tr><th>Approved range / 已批准区间</th><td>{_esc((_fmt_pct(approved_range.get('minimum')) + ' to ' + _fmt_pct(approved_range.get('maximum'))) if isinstance(approved_range, dict) else 'n/a')}</td></tr>"
        f"<tr><th>Blocking reasons / 阻断原因</th><td>{_esc(', '.join(user.get('blocking_reason_codes', [])) or 'None / 无')}</td></tr>"
        "</tbody></table>"
    )
    body += (
        "<div class='boundary'><b>Decision Boundaries / 决策边界</b>"
        f"<p>{_esc(ceiling.get('disclosure_en'))}</p>"
        f"<p>{_esc(ceiling.get('disclosure_zh'))}</p>"
        "<p>System position range: null. External transmission: DENIED. Automatic trade execution: false.</p>"
        "<p>系统仓位区间：null。对外传输：DENIED。自动交易执行：false。</p></div>"
    )
    body += f"<p class='hash'><b>S13 result hash:</b> {_esc(contract.get('s13_result_hash'))}<br><b>Assessment hash:</b> {_esc(contract.get('assessment_hash') or 'n/a')}</p>"
    return _html_page("Gate 4 Full Report", body, _footer(contract))


def evidence_appendix_html(contract: dict[str, Any]) -> str:
    body = _header(contract, "Gate 4 Evidence Appendix / Gate 4 证据附录")
    body += (
        f"<p class='hash'><b>S13 result hash:</b> {_esc(contract.get('s13_result_hash'))}<br>"
        f"<b>Assessment hash:</b> {_esc(contract.get('assessment_hash') or 'n/a')}<br>"
        f"<b>Assessment input fingerprint:</b> {_esc(contract.get('assessment_input_fingerprint') or 'n/a')}</p>"
    )
    body += "<table><thead><tr><th>Evidence ID</th><th>Class</th><th>Label / 中文</th><th>Source object</th><th>Source fields</th><th>Exact value</th></tr></thead><tbody>"
    for row in contract.get("evidence_ledger", []):
        body += (
            "<tr>"
            f"<td class='hash'>{_esc(row.get('evidence_id'))}</td>"
            f"<td>{_esc(row.get('evidence_class'))}</td>"
            f"<td>{_esc(row.get('label_en'))}<br><span class='muted'>{_esc(row.get('label_zh'))}</span></td>"
            f"<td>{_esc(row.get('source_object'))}</td>"
            f"<td class='hash'>{_esc(', '.join(row.get('source_fields', [])))}</td>"
            f"<td class='hash'>{_esc(_fmt_value(row.get('value')))}</td>"
            "</tr>"
        )
    body += "</tbody></table>"
    return _html_page("Gate 4 Evidence Appendix", body, _footer(contract))


def validation_report_html(contract: dict[str, Any]) -> str:
    validation = contract.get("validation", {})
    body = _header(contract, "Gate 4 Validation Report / Gate 4 验证报告")
    body += (
        "<div class='grid'>"
        f"<section class='panel'><h2>Contract / 合同</h2><div class='metric'>{_esc(contract.get('contract_validation', {}).get('status'))}</div></section>"
        f"<section class='panel'><h2>Analytical validation / 分析验证</h2><div class='metric'>{_esc(validation.get('status'))}</div></section>"
        f"<section class='panel'><h2>Hard Stops / 强制停止</h2><div class='metric'>{_esc(validation.get('hard_stop_count'))}</div></section>"
        f"<section class='panel'><h2>Warnings / 警告</h2><div class='metric'>{_esc(validation.get('warning_count'))}</div></section>"
        "</div>"
    )
    body += "<h2>Validation Checks / 验证检查</h2><table class='compact-table'><thead><tr><th>Check</th><th>Status</th><th>Severity</th><th>Message / 中文</th><th>Evidence</th></tr></thead><tbody>"
    for row in validation.get("checks", []):
        css = "pass" if row.get("status") == "PASS" else ("warning" if row.get("status") == "WARNING" else "fail")
        body += (
            "<tr>"
            f"<td class='hash'>{_esc(row.get('check_id'))}</td>"
            f"<td class='status {css}'>{_esc(row.get('status'))}</td>"
            f"<td>{_esc(row.get('severity'))}</td>"
            f"<td>{_esc(row.get('message_en'))}<br><span class='muted'>{_esc(row.get('message_zh'))}</span></td>"
            f"<td class='hash'>{_esc(', '.join(row.get('evidence_ids', [])))}</td>"
            "</tr>"
        )
    body += "</tbody></table>"
    body += (
        "<div class='boundary'><b>Renderer Control / 渲染控制</b>"
        "<p>Formatting only. Assessment, ceiling, approval, and validation are read from the shared contract without independent recalculation.</p>"
        "<p>仅负责格式化。评估、约束上限、审批和验证均直接读取共享合同，不在渲染器中独立重算。</p></div>"
    )
    return _html_page("Gate 4 Validation Report", body, _footer(contract))


def html_reports(contract: dict[str, Any]) -> dict[str, str]:
    return {
        "one_page": one_page_html(contract),
        "full_report": full_report_html(contract),
        "evidence_appendix": evidence_appendix_html(contract),
        "validation_report": validation_report_html(contract),
    }


def chrome_binary() -> str | None:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ]
    return next((str(value) for value in candidates if value and Path(value).exists()), None)


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
        raise RuntimeError("PDF generation produced no output file.")


def render_synthetic_delivery(
    contract: dict[str, Any],
    output_dir: Path,
    *,
    pdf: bool,
) -> dict[str, Any]:
    if contract.get("data_classification") != SYNTHETIC_CLASSIFICATION:
        raise ValueError("Public report rendering accepts synthetic input only.")
    if contract.get("contract_validation", {}).get("status") != "PASS":
        raise ValueError("An invalid S14 contract cannot be rendered.")
    output_dir.mkdir(parents=True, exist_ok=True)
    name, ticker = _company(contract)
    prefix = f"{ticker}_SYNTHETIC"
    contract_path = output_dir / f"{prefix}_Gate4_Assessment_Contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    outputs: dict[str, Any] = {"contract": str(contract_path)}
    html_payloads = html_reports(contract)
    for key, payload in html_payloads.items():
        stem = f"{prefix}_{REPORT_FILENAMES[key]}"
        html_path = output_dir / f"{stem}.html"
        html_path.write_text(payload, encoding="utf-8")
        outputs[f"{key}_html"] = str(html_path)
        if pdf:
            pdf_path = output_dir / f"{stem}.pdf"
            print_pdf(html_path, pdf_path)
            outputs[f"{key}_pdf"] = str(pdf_path)
    file_hashes = {
        Path(path).name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for path in outputs.values()
        if isinstance(path, str) and Path(path).is_file()
    }
    manifest_path = output_dir / f"{prefix}_Gate4_Delivery_Manifest.json"
    manifest_payload = {
        "schema_version": "1.0.0",
        "document_type": "gate4_synthetic_delivery_manifest",
        "data_classification": SYNTHETIC_CLASSIFICATION,
        "company": name,
        "ticker": ticker,
        "assessment_hash": contract.get("assessment_hash"),
        "public_files": sorted(file_hashes),
        "file_hashes": file_hashes,
        "automatic_trade_execution": False,
    }
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    outputs["company"] = name
    outputs["ticker"] = ticker
    outputs["assessment_hash"] = contract.get("assessment_hash")
    outputs["file_hashes"] = file_hashes
    outputs["delivery_manifest"] = str(manifest_path)
    return outputs
