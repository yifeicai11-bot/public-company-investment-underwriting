#!/usr/bin/env python3
"""Run S15 monitoring against two immutable issuer contracts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml

from monitoring_engine import build_monitoring_update


def _read_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected an object in {path}")
    return payload


def _write_private_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)


def _summary_markdown(result: dict[str, Any]) -> str:
    company = result.get("issuer_identity", {})
    thesis = result.get("system_thesis_assessment", {})
    probability = result.get("probability_expiration", {})
    breaches = result.get("kpi_breach_summary", {})
    scenario = result.get("scenario_impact", {})
    changes = result.get("change_summary", {})
    validation = result.get("input_validation", {})
    reasons = "\n".join(
        f"- {row.get('message_en')} / {row.get('message_zh')}"
        for row in thesis.get("reasons", [])
    ) or "- None / 无"
    kpi_rows = "\n".join(
        (
            f"- `{row.get('kpi_id')}`: `{row.get('status')}`; "
            f"{row.get('comparison_basis')}={row.get('evaluated_value')}; "
            f"trigger={row.get('trigger_type')}"
        )
        for row in result.get("kpi_assessments", [])
    ) or "- Not evaluated / 未评估"
    return f"""# Monitoring Update / 持续监控更新

## Decision Snapshot / 决策快照

- Company / 公司: {company.get('name')} ({company.get('ticker')})
- Monitoring date / 监控日期: {result.get('monitoring_as_of_date')}
- Monitoring status / 监控状态: `{result.get('status')}`
- System thesis assessment / 系统 thesis 评估: `{thesis.get('assessment')}` ({thesis.get('label_zh')})
- Formal thesis status / 正式 thesis 状态: `PENDING_HUMAN_REVIEW`
- Probability review / 概率复核: `{probability.get('status')}`
- Scenario impact / 情景影响: `{scenario.get('overall_impact')}`
- KPI breaches / KPI 违约或下调触发: {breaches.get('triggered_breach_count')}
- Automatic trade execution / 自动交易执行: `false`

## System Reasons / 系统依据

{reasons}

## KPI Assessments / KPI 评估

{kpi_rows}

## Change Counts / 变化数量

- Fact changes / 事实变化: {changes.get('fact_metrics', {}).get('changed', 0)} changed, {changes.get('fact_metrics', {}).get('added', 0)} added, {changes.get('fact_metrics', {}).get('removed', 0)} removed
- Calculation changes / 计算变化: {changes.get('calculation_metrics', {}).get('changed', 0)} changed, {changes.get('calculation_metrics', {}).get('added', 0)} added, {changes.get('calculation_metrics', {}).get('removed', 0)} removed
- Judgment changes / 判断变化: {changes.get('judgment_change_count', 0)}
- Warning changes / Warning 变化: {changes.get('warning_change_count', 0)}
- Hard Stop changes / Hard Stop 变化: {changes.get('hard_stop_change_count', 0)}

## Control Boundary / 控制边界

This output compares two validated contracts. It does not replace issuer underwriting, approve a formal thesis status, recommend a position, or place a trade. / 本输出比较两个已验证 contract；不会替代发行人分析、审批正式 thesis 状态、建议仓位或执行交易。

Input validation / 输入验证: `{validation.get('status')}`

Monitoring hash / 监控哈希: `{result.get('monitoring_hash')}`
"""


def run_monitoring_update(
    previous_path: Path,
    current_path: Path,
    policy_path: Path,
    monitoring_as_of_date: str,
    output_dir: Path,
) -> tuple[dict[str, Any], dict[str, Path]]:
    previous = _read_mapping(previous_path)
    current = _read_mapping(current_path)
    policy = _read_mapping(policy_path)
    result = build_monitoring_update(
        previous,
        current,
        policy,
        monitoring_as_of_date,
    )
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_dir, 0o700)
    paths = {
        "contract": output_dir / "monitoring_update_contract.json",
        "summary": output_dir / "monitoring_update_summary_bilingual.md",
    }
    _write_private_text(
        paths["contract"],
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    )
    _write_private_text(paths["summary"], _summary_markdown(result))
    return result, paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two validated public-company underwriting contracts."
    )
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result, paths = run_monitoring_update(
        args.previous,
        args.current,
        args.policy,
        args.as_of_date,
        args.output_dir,
    )
    print(f"status={result.get('status')}")
    print(
        "system_thesis_assessment="
        f"{result.get('system_thesis_assessment', {}).get('assessment')}"
    )
    print("formal_thesis_status=PENDING_HUMAN_REVIEW")
    print("automatic_trade_execution=false")
    for label, path in paths.items():
        print(f"{label}={path}")
    return 0 if result.get("contract_validation", {}).get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
