# One-Page User Summary Template

Use this file when the user asks for a user-ready version, concise memo, first-page summary, or demo output. The one-page summary can stand alone or sit before the full review.

## Purpose

The v1.0.0 one-page summary should let a user understand the answer in approximately 30 seconds. Read `v1_0_0_output_standard.md` before using the legacy module template below.

- Overall risk view.
- Current Data Gate, Decision Confidence, and permitted decision language.
- Investment Question and two or three unresolved Key Debates.
- Top evidence-backed drivers.
- Key mitigants.
- What still needs to be checked.
- Where the evidence came from.

Do not include methodology explanation, sample-selection rationale, or long background.

## Writing Rules

- Lead with the company-specific conclusion.
- Use no more than three key risk drivers and three mitigants.
- Include a compact Firm Type Context section when the business model is clear.
- Include an Investment Committee Snapshot only at Gate 3 or above.
- Include numbers with period and unit, not vague language.
- Keep the source anchor compact; full source log belongs in the full memo.
- Use English first, then concise Chinese.
- Do not make a buy/sell/hold recommendation below Gate 3, a sizing recommendation below Gate 4, or a formal credit rating at any gate.
- Do not use "sample", "test case", "baseline", "stress case", or "useful for testing" in user-facing summaries.

## Template

```markdown
# [Company] ([Ticker]) One-Page Credit & Liquidity Summary / 一页信用与流动性摘要

Review date: [Date] \
Period reviewed: [Latest annual period] and [latest interim period] \
Primary public sources: [10-K / 10-Q / annual report / interim report] \
Scope: Public-data research support; not a formal credit rating or investment recommendation.

## Decision Strip / 决策栏

| Field | Status |
|---|---|
| Data Gate | Gate 0 / 1 / 2.5 / 3 / 4 |
| Research Workflow Status | Data Review Required / Underwriting In Progress / Ready for Human Review |
| Public-Data Investment View | Continue Research / Watch / Stop Research / Case Strengthening / Case Weakening |
| Decision Confidence | High / Medium / Low, with main limitation |
| Valuation Status | RANGE_ONLY / PARTIALLY_VALIDATED / MULTI_METHOD_VALIDATED |
| Validation | PASS / PASS WITH WARNINGS / FAIL |
| Portfolio Overlay | Disabled / Validated and human-approved |

## Investment Question / 投资问题

**Question:** [Decision uncertainty to resolve, or `Not Defined`.] \
**投资问题：** [中文。]

## Decision Boundary / 决策边界

**Can conclude:** [...] \
**目前可以判断：** [...]

**Cannot conclude:** [...] \
**目前不能判断：** [...]

## What Is Priced In / 市场隐含要求

[Conditional reverse-valuation conclusion tied to dated market data, the Public-Data FCF Underwriting Base, guidance, consensus where sourced, and operating evidence.]

## Scenario Price Sensitivity / 情景价格敏感性

Use `Implied Price` and `Price Change vs Current Price`. Disclose the share-count basis and `PROXY` status. Do not use formal return or target labels without a validated horizon.

## Key Debates / 核心争议

| Debate | Conventional View | Alternative View | Resolving KPI / Event | Decision Impact |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

## Overall View / 总体判断

**Overall Risk:** Low / Medium / High short-term credit and liquidity risk \
**总体风险：** 短期信用和流动性风险为低 / 中 / 高

**Core Message:** [One direct English sentence on what matters most.] \
**核心判断：** [一句中文解释。]

**Data Confidence:** High / Medium / Low \
**数据置信度：** 高 / 中 / 低

## Firm Type Context / 公司类型解释

**Firm Type:** [SaaS / Software, Retail, Wholesale / Distribution, Manufacturing / Industrial, Contractor / Government Services, Biotech / Pre-Revenue R&D, Energy / Commodity, Highly Levered, Consumer Durable / Auto, or unclear] \
**公司类型：** [中文公司类型]

**Overlay Applied:** [One sentence on how the business model changes interpretation of AR, liquidity, CFO, working capital, or debt.] \
**适用解释框架：** [一句中文说明。]

## Top Risk Drivers / 主要风险驱动

1. **[Risk driver]** - [Metric, period, and why it matters.] \
   **[中文]** [中文解释。]
2. **[Risk driver]** - [Metric, period, and why it matters.] \
   **[中文]** [中文解释。]
3. **[Risk driver]** - [Metric, period, and why it matters.] \
   **[中文]** [中文解释。]

## Mitigants / 风险缓释因素

1. **[Mitigant]** - [Metric or disclosure.] \
   **[中文]** [中文解释。]
2. **[Mitigant]** - [Metric or disclosure.] \
   **[中文]** [中文解释。]

## Investment Committee Snapshot / 投资委员会式判断

Show this section only at Gate 3 or above. Otherwise write `Disabled below Gate 3`.

| Role / 角色 | View / 判断 | Decision Impact / 对决策的影响 |
|---|---|---|
| Fundamental Analyst | ... | ... |
| Market Expectations Analyst | ... | ... |
| Bull Case | ... | ... |
| Bear Case | ... | ... |
| Risk Manager | ... | ... |
| Portfolio Manager | ... | ... |

## Risk Snapshot / 风险快照

| Module / 模块 | Risk | Confidence | Key Evidence |
|---|---:|---:|---|
| Receivables Quality | Low/Medium/High | High/Medium/Low | ... |
| Bad Debt / Credit Loss Risk | Low/Medium/High | High/Medium/Low | ... |
| Short-Term Liquidity | Low/Medium/High | High/Medium/Low | ... |
| Cash Flow Conversion | Low/Medium/High | High/Medium/Low | ... |
| Working Capital Pressure | Low/Medium/High | High/Medium/Low | ... |
| Near-Term Debt / Refinancing Pressure | Low/Medium/High | High/Medium/Low | ... |

## Evidence Anchors / 关键证据来源

- [Source 1]: [Filing date, period, key metric/disclosure, link or source reference.]
- [Source 2]: [Filing date, period, key metric/disclosure, link or source reference.]

## Follow-Up / 后续确认

- [Most important missing detail or diligence question.]
- [Second missing detail or diligence question.]
```

## Compression Guidance

If space is tight:

- Keep Overall View, Top Risk Drivers, Mitigants, Risk Snapshot, and Follow-Up.
- Move detailed source log, calculations, and module writeups to the full memo.
- Preserve the numbers that support the conclusion.
