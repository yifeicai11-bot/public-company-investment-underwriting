#!/usr/bin/env python3
"""Build Step 4 partner / portfolio overlay from Step 3 public data.

The overlay combines a public-data investment layer with partner-provided
portfolio constraints. Demo inputs must be explicitly marked as illustrative
and are not treated as real fund data.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[3]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_public_company_investment_layer import DEFAULT_OUT_ROOT, build_investment_layer  # noqa: E402


@dataclass
class OverlayGate:
    gate_id: str
    result: str
    severity: str
    evidence: str
    decision_impact: str
    remediation: str


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def fmt_num(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}x"


ACTION_ZH = {
    "Not Evaluated": "未评估",
    "Watch / Need More Work": "继续观察 / 需要补充研究",
    "Watch / Do Not Advance": "观察但暂不推进",
    "Potential Long to Underwrite": "可作为潜在多头继续尽调",
    "Portfolio Candidate, starter-size only": "可作为组合候选，仅限小仓位起步",
    "Hedge / Monitor Exposure": "用于对冲或持仓监控",
    "Avoid on Credit/Liquidity Grounds": "因信用或流动性原因回避",
}

CONFIDENCE_ZH = {
    "High": "高",
    "Medium": "中",
    "Low": "低",
    "Missing": "缺失",
}

BASIS_ZH = {
    "PUBLIC_DATA": "公开数据",
    "PARTNER_INPUT": "Partner/组合输入",
}

RESULT_ZH = {
    "PASS": "通过",
    "FAIL": "未通过",
    "BLOCKED": "阻断",
    "PROVISIONAL": "暂定 / 需复核",
    "CONSTRAINED": "受限制",
    "MISSING": "缺失",
}

FIELD_ZH = {
    "overlay_mode": "叠加模式",
    "target_return_hurdle": "目标回报门槛",
    "max_bear_case_downside": "最大可接受熊市下行",
    "intended_holding_period": "预期持有期",
    "portfolio_role": "组合中的角色",
    "existing_exposure": "已有风险敞口",
    "sector_concentration": "行业集中度",
    "max_position_size": "最大仓位上限",
    "opportunity_cost_alternatives": "机会成本对比对象",
    "opportunity_cost_view": "机会成本判断",
    "internal_variant_view": "内部差异化观点",
    "internal_expected_return": "内部预期回报",
    "internal_bear_case": "内部熊市情景",
    "internal_bull_case": "内部牛市情景",
    "internal_conviction": "内部信心等级",
    "catalyst_quality": "催化剂质量",
    "liquidity_constraint": "流动性约束",
    "internal_thesis_break": "投资逻辑失效条件",
}

GATE_ZH = {
    "O1-public-data-foundation": "公开数据基础是否可靠",
    "O2-overlay-mode": "叠加输入是真实数据还是演示假设",
    "O3-return-hurdle": "预期回报是否超过门槛",
    "O4-downside-tolerance": "熊市下行是否在可接受范围内",
    "O5-variant-view": "是否有差异化投资观点",
    "O6-catalyst-quality": "是否有足够清晰的催化剂",
    "O7-existing-exposure": "已有敞口是否限制仓位",
    "O8-opportunity-cost": "是否优于真实替代机会",
    "O9-sizing-input": "是否提供仓位上限",
    "O10-human-approval": "是否完成最终人工审批",
}

RATIONALE_ZH = {
    "Gate 4 prerequisites or human approval are incomplete.": "Gate 4 前置条件或人工审批尚未完成。",
    "Portfolio inputs are illustrative or not validated.": "组合输入仅为演示或尚未验证。",
    "Displaying the explicitly human-approved portfolio decision; the system did not choose it.": "仅展示已由人工明确批准的组合决策；系统并未自动作出该决定。",
    "Public-data scenario is inconclusive.": "公开数据情景结论不够明确。",
    "Public-data scenario does not yet show attractive risk/reward.": "公开数据情景还没有显示有吸引力的风险回报。",
    "Public-data scenario is not strong enough for action, but may be worth deeper underwriting.": "公开数据情景还不足以支持行动，但可能值得进一步尽调。",
    "Public-data foundation has P0 blocked gates.": "公开数据基础仍有 P0 阻断项。",
    "Return and downside pass, but exposure constraints cap action.": "回报和下行通过，但已有敞口限制行动空间。",
    "Partner overlay clears return, downside, variant, catalyst, and sizing gates.": "叠加输入通过回报、下行、差异化观点、催化剂和仓位约束检查。",
    "Expected return fails hurdle and bear case exceeds downside tolerance.": "预期回报低于门槛，且熊市情景下行超过可接受范围。",
    "Expected return does not clear partner hurdle.": "预期回报没有达到 partner 设定的门槛。",
    "Bear-case downside is outside partner tolerance.": "熊市情景下行超出 partner 可接受范围。",
    "Return/downside are acceptable, but variant, catalyst, opportunity cost, or sizing inputs need more work.": "回报和下行基本可接受，但差异化观点、催化剂、机会成本或仓位输入仍需补充。",
}


def zh_action(value: str | None) -> str:
    return ACTION_ZH.get(str(value or ""), "需人工判断")


def zh_confidence(value: str | None) -> str:
    return CONFIDENCE_ZH.get(str(value or ""), "需人工判断")


def zh_basis(value: str | None) -> str:
    return BASIS_ZH.get(str(value or ""), "需人工判断")


def zh_result(value: str | None) -> str:
    return RESULT_ZH.get(str(value or ""), "需人工判断")


def zh_rationale(value: str | None) -> str:
    return RATIONALE_ZH.get(str(value or ""), "需要结合具体输入人工解释。")


def parse_pct(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.endswith("%"):
        try:
            return float(text[:-1].strip()) / 100
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def scenario_return(data: dict[str, Any], name: str) -> float | None:
    for row in data.get("scenarios", []):
        if row.get("name") == name:
            return parse_pct(row.get("total_return"))
    return None


def load_step3(step3_dir: Path) -> dict[str, Any]:
    path = step3_dir / "step3_data.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing Step 3 data: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_overlay(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        out: dict[str, Any] = {}
        for row in rows:
            field = row.get("field")
            if field:
                out[field] = row.get("partner_input") or row.get("example_or_default") or ""
        return out
    raise ValueError(f"Unsupported overlay input format: {path}")


def clean_level(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low"}:
        return text.capitalize()
    return "Missing"


def return_pack(step3: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    public_expected = parse_pct(step3.get("probability_weighted_return"))
    public_bear = scenario_return(step3, "Bear")
    public_bull = scenario_return(step3, "Bull")

    internal_expected = parse_pct(overlay.get("internal_expected_return"))
    internal_bear = parse_pct(overlay.get("internal_bear_case"))
    internal_bull = parse_pct(overlay.get("internal_bull_case"))
    has_internal_return = internal_expected is not None and internal_bear is not None

    return {
        "basis": "PARTNER_INPUT" if has_internal_return else "PUBLIC_DATA",
        "expected_return": internal_expected if has_internal_return else public_expected,
        "bear_case": internal_bear if has_internal_return else public_bear,
        "bull_case": internal_bull if has_internal_return else public_bull,
        "public_expected_return": public_expected,
        "public_bear_case": public_bear,
        "public_bull_case": public_bull,
        "internal_expected_return": internal_expected,
        "internal_bear_case": internal_bear,
        "internal_bull_case": internal_bull,
    }


def overlay_gates(step3: dict[str, Any], overlay: dict[str, Any], returns: dict[str, Any]) -> list[OverlayGate]:
    gates: list[OverlayGate] = []
    mode = overlay.get("overlay_mode", "")
    target_hurdle = parse_pct(overlay.get("target_return_hurdle"))
    max_downside = parse_pct(overlay.get("max_bear_case_downside"))
    expected = returns.get("expected_return")
    bear = returns.get("bear_case")
    conviction = clean_level(overlay.get("internal_conviction"))
    catalyst = clean_level(overlay.get("catalyst_quality"))
    exposure = str(overlay.get("existing_exposure", "")).strip().lower()
    max_size = str(overlay.get("max_position_size", "")).strip()
    opportunity_view = str(overlay.get("opportunity_cost_view", "")).strip().lower()
    variant = str(overlay.get("internal_variant_view", "")).strip()

    public_gate = float(step3.get("data_gate", {}).get("level", 0))
    contract_valid = step3.get("contract_validation", {}).get("status") == "PASS"
    public_ready = public_gate >= 3 and contract_valid
    gates.append(
        OverlayGate(
            "O1-public-data-foundation",
            "PASS" if public_ready else "BLOCKED",
            "INFO" if public_ready else "P0",
            f"Public Data Gate={public_gate}; contract validation={step3.get('contract_validation', {}).get('status', 'missing')}",
            "Gate 4 cannot be reached until issuer underwriting, valuation, and scenarios have passed Gate 3.",
            "Complete and validate the shared public-company underwriting contract before portfolio overlay.",
        )
    )
    real_validated_mode = (
        mode == "REAL_PARTNER_INPUT"
        and overlay.get("input_status") == "VALIDATED"
        and bool(overlay.get("reviewed_by"))
    )
    gates.append(
        OverlayGate(
            "O2-overlay-mode",
            "PASS" if real_validated_mode else "BLOCKED",
            "P1",
            f"overlay_mode={mode or 'n/a'}; input_status={overlay.get('input_status', 'n/a')}; reviewer={overlay.get('reviewed_by', 'n/a')}",
            "Illustrative or unreviewed inputs may demonstrate workflow but cannot create Gate 4 outputs.",
            "Use REAL_PARTNER_INPUT, mark inputs VALIDATED, and record the human reviewer.",
        )
    )
    gates.append(
        OverlayGate(
            "O3-return-hurdle",
            "PASS" if expected is not None and target_hurdle is not None and expected >= target_hurdle else "FAIL",
            "P1",
            f"return basis={returns.get('basis')}; expected={fmt_pct(expected)}; hurdle={fmt_pct(target_hurdle)}",
            "Expected return must clear the partner's hurdle before portfolio action.",
            "Improve thesis/return case or keep on watchlist.",
        )
    )
    gates.append(
        OverlayGate(
            "O4-downside-tolerance",
            "PASS" if bear is not None and max_downside is not None and bear >= max_downside else "FAIL",
            "P1",
            f"bear case={fmt_pct(bear)}; max tolerated downside={fmt_pct(max_downside)}",
            "Bear-case downside must fit the fund's risk tolerance.",
            "Reduce size, improve downside protection, or keep as watchlist only.",
        )
    )
    gates.append(
        OverlayGate(
            "O5-variant-view",
            "PASS" if variant and conviction in {"Medium", "High"} else "PROVISIONAL",
            "P1",
            f"conviction={conviction}; variant view={'provided' if variant else 'missing'}",
            "A portfolio action needs a differentiated view, not only public-data math.",
            "Add the internal variant view and thesis-break triggers.",
        )
    )
    gates.append(
        OverlayGate(
            "O6-catalyst-quality",
            "PASS" if catalyst in {"Medium", "High"} else "PROVISIONAL",
            "P2",
            f"catalyst_quality={catalyst}",
            "Catalysts help turn an underwriteable idea into a time-bounded portfolio candidate.",
            "Identify earnings, guidance, refinancing, margin, capital allocation, or event catalysts.",
        )
    )
    gates.append(
        OverlayGate(
            "O7-existing-exposure",
            "CONSTRAINED" if "high" in exposure or "existing" in exposure else "PASS",
            "P2",
            f"existing_exposure={overlay.get('existing_exposure', 'n/a')}",
            "Existing exposure can cap sizing even if the idea clears return gates.",
            "Use incremental exposure limits and sector concentration rules.",
        )
    )
    gates.append(
        OverlayGate(
            "O8-opportunity-cost",
            "PASS"
            if opportunity_view in {"better", "acceptable", "compelling"}
            else ("FAIL" if opportunity_view == "worse" else "PROVISIONAL"),
            "P2",
            f"opportunity_cost_view={overlay.get('opportunity_cost_view', 'n/a')}; alternatives={overlay.get('opportunity_cost_alternatives', 'n/a')}",
            "The idea should beat realistic alternatives, not only SPY.",
            "Compare against cash, index, sector ETF, watchlist, and current holdings.",
        )
    )
    gates.append(
        OverlayGate(
            "O9-sizing-input",
            "PASS" if max_size else "BLOCKED",
            "P1",
            f"max_position_size={max_size or 'n/a'}",
            "Sizing cannot be suggested without a partner-provided size constraint.",
            "Provide max position size or leave action as no-sizing research support.",
        )
    )
    approved_action = str(overlay.get("approved_portfolio_action", "")).strip()
    approved_range = str(overlay.get("approved_position_range", "")).strip()
    human_approved = (
        overlay.get("human_approval") == "APPROVED"
        and bool(overlay.get("approved_by"))
        and bool(approved_action)
        and bool(approved_range)
    )
    gates.append(
        OverlayGate(
            "O10-human-approval",
            "PASS" if human_approved else "BLOCKED",
            "P0",
            f"human_approval={overlay.get('human_approval', 'NOT_REVIEWED')}; approved_by={overlay.get('approved_by', 'n/a')}",
            "The system may display a portfolio action or position range only after explicit human approval.",
            "Record the approved action, approved position range, approver, and approval status.",
        )
    )
    return gates


def choose_overlay_action(gates: list[OverlayGate], overlay: dict[str, Any], returns: dict[str, Any]) -> tuple[str, str, str, str]:
    gate_map = {g.gate_id: g for g in gates}
    p0_blocked = any(g.result == "BLOCKED" and g.severity == "P0" for g in gates)
    if p0_blocked:
        return "Not Evaluated", "No position sizing", "Low", "Gate 4 prerequisites or human approval are incomplete."

    if gate_map["O2-overlay-mode"].result != "PASS":
        return "Not Evaluated", "No position sizing", "Low", "Portfolio inputs are illustrative or not validated."

    return_pass = gate_map["O3-return-hurdle"].result == "PASS"
    downside_pass = gate_map["O4-downside-tolerance"].result == "PASS"
    variant_pass = gate_map["O5-variant-view"].result == "PASS"
    catalyst_pass = gate_map["O6-catalyst-quality"].result == "PASS"
    sizing_pass = gate_map["O9-sizing-input"].result == "PASS"
    exposure_constrained = gate_map["O7-existing-exposure"].result == "CONSTRAINED"

    max_size = overlay.get("max_position_size", "")
    approval_pass = gate_map["O10-human-approval"].result == "PASS"
    opportunity_pass = gate_map["O8-opportunity-cost"].result == "PASS"
    if return_pass and downside_pass and variant_pass and catalyst_pass and sizing_pass and opportunity_pass and approval_pass:
        return (
            str(overlay["approved_portfolio_action"]),
            str(overlay["approved_position_range"]),
            clean_level(overlay.get("internal_conviction")),
            "Displaying the explicitly human-approved portfolio decision; the system did not choose it.",
        )
    if not return_pass and not downside_pass:
        return (
            "Watch / Do Not Advance",
            "No position sizing",
            "Low",
            "Expected return fails hurdle and bear case exceeds downside tolerance.",
        )
    if not return_pass:
        return (
            "Watch / Need More Work",
            "No position sizing",
            "Low",
            "Expected return does not clear partner hurdle.",
        )
    if not downside_pass:
        return (
            "Watch / Need More Work",
            "No position sizing",
            "Low",
            "Bear-case downside is outside partner tolerance.",
        )
    return (
        "Potential Long to Underwrite",
        "No position sizing until provisional overlay gates are resolved",
        "Medium",
        "Return/downside are acceptable, but variant, catalyst, opportunity cost, or sizing inputs need more work.",
    )


def row_table(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return lines


def overlay_input_rows(overlay: dict[str, Any]) -> list[dict[str, str]]:
    fields = [
        "overlay_mode",
        "input_status",
        "reviewed_by",
        "target_return_hurdle",
        "max_bear_case_downside",
        "intended_holding_period",
        "portfolio_role",
        "existing_exposure",
        "sector_concentration",
        "max_position_size",
        "opportunity_cost_alternatives",
        "opportunity_cost_view",
        "internal_variant_view",
        "internal_expected_return",
        "internal_bear_case",
        "internal_bull_case",
        "internal_conviction",
        "catalyst_quality",
        "liquidity_constraint",
        "internal_thesis_break",
        "human_approval",
        "approved_by",
        "approved_portfolio_action",
        "approved_position_range",
    ]
    return [{"field": field, "中文字段": FIELD_ZH.get(field, ""), "value": overlay.get(field, "")} for field in fields]


def overlay_gate_rows(gates: list[OverlayGate]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for gate in gates:
        rows.append(
            {
                "gate_id": gate.gate_id,
                "中文含义": GATE_ZH.get(gate.gate_id, ""),
                "result": gate.result,
                "中文结果": zh_result(gate.result),
                "severity": gate.severity,
                "evidence": gate.evidence,
                "decision_impact": gate.decision_impact,
                "remediation": gate.remediation,
            }
        )
    return rows


def build_markdown(step3: dict[str, Any], overlay: dict[str, Any], returns: dict[str, Any], gates: list[OverlayGate], action: str, sizing: str, confidence: str, rationale: str) -> str:
    company = step3["company"]
    valuation = step3.get("valuation", {})
    public_gates = [g for g in step3.get("validation_gates", []) if g.get("result") in {"BLOCKED", "PROVISIONAL"}]
    gate_rows = overlay_gate_rows(gates)
    input_rows = overlay_input_rows(overlay)
    mode = overlay.get("overlay_mode", "n/a")

    lines = [
        f"# {company['name']} ({company['ticker']}) Public-Only and Partner Overlay Demo / 公开数据与 Partner 组合叠加演示",
        "",
        f"Generated: {utc_now()}",
        f"Overlay mode / 叠加模式: {mode}",
        "",
        "This output combines the public-data Step 3 memo with a partner/portfolio overlay. If `overlay_mode` is `ILLUSTRATIVE_DEMO_NOT_FUND_DATA`, the overlay inputs are examples for workflow demonstration, not real fund data.",
        "",
        "本文件把 Step 3 公开数据分析和 partner/组合约束叠加在一起。如果 `overlay_mode` 是 `ILLUSTRATIVE_DEMO_NOT_FUND_DATA`，说明这些 overlay 输入只是流程演示，不是真实基金数据或 partner 观点。",
        "",
        "## Public-Only Decision Strip / 公开数据结论",
        "",
        f"- Public action view: {step3.get('action_view')} / 中文：{zh_action(step3.get('action_view'))}",
        f"- Public expected return: {fmt_pct(returns.get('public_expected_return'))} / 公开数据预期回报：{fmt_pct(returns.get('public_expected_return'))}",
        f"- Public bear / bull: {fmt_pct(returns.get('public_bear_case'))} / {fmt_pct(returns.get('public_bull_case'))} / 公开数据熊市/牛市情景：{fmt_pct(returns.get('public_bear_case'))} / {fmt_pct(returns.get('public_bull_case'))}",
        f"- Public valuation: P/FCF={fmt_num(valuation.get('p_fcf'))}; P/E={fmt_num(valuation.get('pe'))}; EV/Sales={fmt_num(valuation.get('ev_sales'))} / 公开估值：P/FCF={fmt_num(valuation.get('p_fcf'))}; P/E={fmt_num(valuation.get('pe'))}; EV/Sales={fmt_num(valuation.get('ev_sales'))}",
        f"- Public action rationale: {step3.get('action_rationale')} / 中文：{zh_rationale(step3.get('action_rationale'))}",
        f"- Public provisional/blocked gates: {', '.join(g.get('gate_id', '') for g in public_gates) if public_gates else 'None'} / 公开数据中仍需复核或阻断的检查项：{', '.join(g.get('gate_id', '') for g in public_gates) if public_gates else '无'}",
        "",
        "## Partner Overlay Inputs / Partner 叠加输入",
        "",
        *row_table(input_rows, ["field", "中文字段", "value"]),
        "",
        "## Overlay Return Basis / 叠加后回报依据",
        "",
        f"- Return basis used: {returns.get('basis')} / 中文：{zh_basis(returns.get('basis'))}",
        f"- Overlay expected return: {fmt_pct(returns.get('expected_return'))} / 叠加后预期回报：{fmt_pct(returns.get('expected_return'))}",
        f"- Overlay bear / bull: {fmt_pct(returns.get('bear_case'))} / {fmt_pct(returns.get('bull_case'))} / 叠加后熊市/牛市情景：{fmt_pct(returns.get('bear_case'))} / {fmt_pct(returns.get('bull_case'))}",
        "",
        "## Overlay Decision Gates / 叠加后决策检查项",
        "",
        *row_table(
            gate_rows,
            ["gate_id", "中文含义", "result", "中文结果", "severity", "evidence", "decision_impact", "remediation"],
        ),
        "",
        "## Portfolio-Aware Action View / 组合视角行动结论",
        "",
        f"- Overlay action view: {action} / 中文：{zh_action(action)}",
        f"- Sizing view: {sizing} / 仓位判断：{sizing}",
        f"- Confidence: {confidence} / 信心等级：{zh_confidence(confidence)}",
        f"- Rationale: {rationale} / 中文：{zh_rationale(rationale)}",
        "",
        "## Delta Versus Public-Only / 相比公开数据结论的变化",
        "",
        f"- Public-only answer: {step3.get('action_view')} with no sizing because partner portfolio context was missing.",
        f"- 公开数据结论：{zh_action(step3.get('action_view'))}；由于缺少 partner/组合约束，不能给出仓位建议。",
        f"- Overlay answer: {action}; sizing remains controlled by partner input and is not a formal trade instruction.",
        f"- 叠加后结论：{zh_action(action)}；仓位仍由 partner 输入控制，不是正式交易指令。",
        "- The overlay can upgrade, downgrade, or cap the public-data view depending on return hurdle, downside tolerance, exposure, opportunity cost, and internal variant view.",
        "- Overlay 可能根据目标回报、下行容忍度、已有敞口、机会成本和内部差异化观点，对公开数据结论进行升级、降级或限制仓位。",
        "",
        "## Source Files / 来源文件",
        "",
        "- Public-only Step 3: `investment_layer.md` and `step3_data.json` in the same folder.",
        "- 公开数据 Step 3：同一文件夹下的 `investment_layer.md` 和 `step3_data.json`。",
        "- Overlay input: partner-provided or illustrative JSON/CSV.",
        "- Overlay 输入：partner 提供或用于演示的 JSON/CSV。",
        "",
    ]
    return "\n".join(lines)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_overlay(step3_dir: Path, overlay_path: Path) -> Path:
    step3 = load_step3(step3_dir)
    overlay = load_overlay(overlay_path)
    returns = return_pack(step3, overlay)
    gates = overlay_gates(step3, overlay, returns)
    action, sizing, confidence, rationale = choose_overlay_action(gates, overlay, returns)

    output = {
        "company": step3["company"],
        "build_date": utc_now(),
        "overlay_input_path": str(overlay_path),
        "overlay": overlay,
        "returns": returns,
        "overlay_gates": [asdict(g) for g in gates],
        "overlay_action_view": action,
        "overlay_action_view_zh": zh_action(action),
        "overlay_sizing_view": sizing,
        "overlay_confidence": confidence,
        "overlay_confidence_zh": zh_confidence(confidence),
        "overlay_rationale": rationale,
        "overlay_rationale_zh": zh_rationale(rationale),
        "public_action_view": step3.get("action_view"),
        "public_action_view_zh": zh_action(step3.get("action_view")),
        "public_expected_return": step3.get("probability_weighted_return"),
    }
    (step3_dir / "portfolio_overlay_demo.json").write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    write_csv(step3_dir / "portfolio_overlay_gates.csv", [asdict(g) for g in gates])
    (step3_dir / "public_only_and_partner_overlay_demo.md").write_text(
        build_markdown(step3, overlay, returns, gates, action, sizing, confidence, rationale),
        encoding="utf-8",
    )
    return step3_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Step 4 partner portfolio overlay from Step 3 data.")
    parser.add_argument("company_or_step3_dir", help="Ticker/company name or path to a step3 directory.")
    parser.add_argument("--overlay", required=True, help="Path to partner overlay JSON or CSV.")
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT), help="Output root when resolving a company.")
    args = parser.parse_args()

    target = Path(args.company_or_step3_dir)
    if target.exists() and target.is_dir():
        step3_dir = target
    else:
        step3_dir = build_investment_layer(args.company_or_step3_dir, Path(args.out_root))
    out = build_overlay(step3_dir, Path(args.overlay))
    print(out)
    print(out / "public_only_and_partner_overlay_demo.md")
    print(out / "portfolio_overlay_demo.json")
    print(out / "portfolio_overlay_gates.csv")


if __name__ == "__main__":
    main()
