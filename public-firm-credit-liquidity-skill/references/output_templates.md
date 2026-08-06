# Output Templates

For a concise user-ready front page, use `one_page_user_summary.md`.

When the output is intended to support investment judgment, also read `investment_decision_upgrade.md`. The one-page should lead with decision usefulness, not source mechanics.

When the output should help an investor decide what to do, also read `investment_committee_layer.md` and include a compressed committee snapshot if valuation/scenario evidence is available.

## Investment-Support One-Page / 投资判断支持版一页摘要

Use this template when the user asks whether the work helps investment judgment. Follow `v1_0_0_output_standard.md` and the Data Gate in `system_architecture_and_contract.md`. Below Gate 3, suppress scenario implied prices rather than filling them with provisional automated assumptions. At Gate 3, use `Scenario Price Sensitivity` and `Price Change vs Current Price` when no explicit horizon exists. Formal probability-weighted output remains `Not Evaluated / 未评估` unless both probability governance and return-context validation pass.

```markdown
## Header / Decision Strip / 判断栏

| Field | View |
|---|---|
| Company / Ticker | ... |
| Review Date | ... |
| Research Workflow Status | Data Review Required / Underwriting In Progress / Ready for Human Review |
| Public-Data Investment View | Continue Research / Watch / Stop Research / Case Strengthening / Case Weakening |
| Confidence | High / Medium / Low, with main reason |
| Time Horizon | ... |
| Next Decision Trigger | Next earnings / filing / valuation review / covenant update |
| Data Gate | Passed / Provisional / Blocked, with reason |

## Investment Question / 投资问题

[State the uncertainty and decision this research is intended to resolve. If not analyst-owned, write `Not Defined`.]

## Decision Boundary / 决策边界

- Can conclude now:
- Cannot conclude now:
- Evidence required next:

## Core Investment View / 核心投资判断

[3-4 sentences answering: what matters now, whether liquidity is binding, what the main variant view is, and what would change the view.]

中文解释：[简洁中文说明。]

## Key Debates / 核心争议

| Debate | Market / Conventional View | Alternative View | Missing Evidence | Resolving KPI / Event | Decision Impact |
|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... |

## Key Numbers / 关键数据

| Metric | Value | Period | Evidence Type | Decision Use |
|---|---:|---|---|---|
| Available liquidity | ... | ... | FACT/CALC | ... |
| 12m mandatory uses | ... | ... | FACT/CALC/MISSING | ... |
| Net / lease-adjusted obligations | ... | ... | CALC | ... |
| FCF | ... | ... | CALC | ... |
| DSO / DIO / DPO / CCC | ... | ... | CALC | ... |
| Valuation / price sensitivity | Missing or sourced value | ... | MISSING/FACT/CALC | ... |

## Thesis vs. Antithesis / 投资逻辑与反逻辑

| Thesis Support | Antithesis / Thesis Break |
|---|---|
| ... | ... |
| ... | ... |
| ... | ... |

## Investment Committee Snapshot / 投资委员会式判断

| Role / 角色 | View / 判断 | Evidence / 证据 | Decision Impact / 对决策的影响 |
|---|---|---|---|
| Fundamental Analyst | ... | ... | ... |
| Market Expectations Analyst | ... | ... | ... |
| Bull Case | ... | ... | ... |
| Bear Case | ... | ... | ... |
| Risk Manager | ... | ... | ... |
| Portfolio Manager | ... | ... | ... |

## Liquidity and Capital Structure / 流动性与资本结构

- Sources:
- Uses:
- Facility / covenant:
- Maturity / refinancing:
- Lease obligations:

## Working Capital and Cash Conversion / 营运资本与现金转化

- DSO:
- DIO:
- DPO:
- CCC:
- CFO / FCF bridge:
- Main caveat:

## Catalysts and Monitoring / 催化剂与监控

| KPI / Event | Why It Matters | Reassess Trigger |
|---|---|---|
| ... | ... | ... |

## Bottom Line / 最终判断

[Decision-useful conclusion. State what the memo can support now and what work is required before a formal investment action.]
```

## Data Integrity Appendix / 数据校验附录

For any user-ready memo, attach or reference a validation appendix:

```markdown
## Data Integrity Appendix

| Check | Result | Evidence | Impact |
|---|---:|---|---|
| Period Match | PASS/BLOCKED | ... | ... |
| Instant vs Flow | PASS/BLOCKED | ... | ... |
| Quarter Derivation | PASS/N/A | ... | ... |
| Balance Sheet Check | PASS/FAIL | ... | ... |
| Cash Flow Check | PASS/FAIL | ... | ... |
| Debt Reconciliation | PASS/FAIL | ... | ... |
| Facility Check | PASS/FAIL | ... | ... |
| Lease Check | PASS/FAIL | ... | ... |
| Covenant Check | PASS/FAIL | ... | ... |
| Investment Gate | PASS/BLOCKED | ... | ... |
```

## Executive Highlights / 执行摘要

```markdown
## Executive Highlights / 执行摘要

**Overall View:** Low / Medium / High short-term credit and liquidity risk
**总体判断：** 短期信用和流动性风险为低 / 中 / 高

**Data Confidence:** High / Medium / Low
**数据置信度：** 高 / 中 / 低

**Key Takeaways**
- [EN] [Most material company-specific conclusion supported by filing evidence.]
- [CN] [基于 filing evidence 的公司本身核心判断。]
- ...
- ...

**Red Flags / 风险信号**
- [EN] ...
- [CN] ...

**Positive Signals / 正面信号或风险缓释因素**
- [EN] ...
- [CN] ...

**Top Follow-Up Questions / 需要进一步确认的问题**
- [EN] ...
- [CN] ...
```

## Firm Type Context / 公司类型解释

Use this section to show how the sector or firm-type overlay changes interpretation. Keep it concise. Do not use it to excuse weak evidence or override the required shared issuer review.

```markdown
## Firm Type Context / 公司类型解释

**Firm Type:** [SaaS / Software, Retail, Wholesale / Distribution, Manufacturing / Industrial, Contractor / Government Services, Biotech / Pre-Revenue R&D, Energy / Commodity, Highly Levered, Consumer Durable / Auto, or unclear]
**公司类型：** [...]

**Overlay Applied:** [One English sentence explaining the business-model lens used in the review.]
**适用解释框架：** [一句中文说明。]

**Why It Matters:** [Explain which modules need business-model-specific interpretation, such as deferred revenue, inventory, contract assets, burn rate, commodity exposure, or maturity wall.]
**为什么重要：** [中文解释哪些模块需要按公司类型理解。]
```

## Risk Rating Summary / 风险评级摘要

```markdown
## Risk Rating Summary / 风险评级摘要

| Module / 模块 | Risk Level / 风险等级 | Confidence / 置信度 | Key Evidence / 关键证据 | Why It Matters / 为什么重要 |
|---|---:|---:|---|---|
| Receivables Quality | Low/Medium/High | High/Medium/Low | ... | ... |
| Bad Debt / Credit Loss Risk | Low/Medium/High | High/Medium/Low | ... | ... |
| Short-Term Liquidity | Low/Medium/High | High/Medium/Low | ... | ... |
| Cash Flow Conversion | Low/Medium/High | High/Medium/Low | ... | ... |
| Working Capital Pressure | Low/Medium/High | High/Medium/Low | ... | ... |
| Near-Term Debt / Refinancing Pressure | Low/Medium/High | High/Medium/Low | ... | ... |
```

## Detailed Analysis / 详细分析

```markdown
## Detailed Analysis / 详细分析

### Receivables Quality
Observation:
Evidence:
Interpretation:
中文解释：
Risk Level:
Confidence:

### Bad Debt / Credit Loss Risk
Observation:
Evidence:
Interpretation:
中文解释：
Risk Level:
Confidence:

### Short-Term Liquidity
Observation:
Evidence:
Interpretation:
中文解释：
Risk Level:
Confidence:

### Cash Flow Conversion
Observation:
Evidence:
Interpretation:
中文解释：
Risk Level:
Confidence:

### Working Capital Pressure
Observation:
Evidence:
Interpretation:
中文解释：
Risk Level:
Confidence:

### Near-Term Debt / Refinancing Pressure
Observation:
Evidence:
Interpretation:
中文解释：
Risk Level:
Confidence:

### Capital Allocation
Observation:
Evidence:
Interpretation:
中文解释：
Status:
Confidence:

### Management Guidance and Subsequent Events
Observation:
Evidence:
Interpretation:
中文解释：
Status:
Confidence:

### Company-Specific Stress Test
Assumptions:
Sources and Uses / Operating Impact:
Evidence IDs:
Result:
中文解释：
Confidence:
```

## Investment Committee Synthesis / 投资委员会式综合判断

Use this section only for investment-support memos. If valuation/scenario inputs are missing, state that the committee layer is limited and avoid definitive action language.

```markdown
## Investment Committee Synthesis / 投资委员会式综合判断

### Fundamental Analyst
View:
Evidence:
Decision Impact:
Confidence:
Falsification Trigger:

### Market Expectations Analyst
View:
Evidence:
Decision Impact:
Confidence:
Falsification Trigger:

### Bull Case
1.
2.
3.

### Bear Case
1.
2.
3.

### Risk Manager
Key Risks:
Stress / Downside:
Thesis-Break Triggers:
Confidence Adjustment:

### Portfolio Manager
Action View:
Sizing Range:
Target Return / Downside:
Opportunity Cost:
Next Decision Trigger:
```

## Source Log / 证据来源表

```markdown
## Source Log / Evidence Table / 证据来源表

| Claim ID | Module / 模块 | Claim / Metric / 判断或指标 | Evidence Type | Source | Filing Date / Period | Section / Note | Value / Disclosure | Interpretation / 解释 | Confidence | Link |
|---|---|---|---|---|---|---|---|---|---|---|
| AR-1 | Receivables Quality | ... | Metric / Trend / Disclosure / Derived Metric / Missing Data | ... | ... | ... | ... | ... | ... | ... |
```

## Follow-Up Questions / 需要进一步确认的问题

Follow-up questions should explain what cannot be fully confirmed from public data and what the analyst or user may want to verify next.

```markdown
## Follow-Up Questions / 需要进一步确认的问题

- [EN] ...
  [CN] ...
- [EN] ...
  [CN] ...
```

## Limitations / 局限性

```markdown
## Limitations / 局限性

- This output is based only on public information available at the time of review.
- 本报告仅基于 review 时可获得的公开资料。
- It is a research support output, not a formal credit rating or investment recommendation.
- 这是 research support output，不是正式信用评级或投资建议。
- Some metrics may be unavailable due to disclosure limitations.
- 由于公开披露限制，部分指标可能无法获得。
- Further confirmation may be needed from management, filings, or internal data.
- 部分判断可能需要通过 management、后续 filings 或内部资料进一步确认。
```
