# Investment Committee Layer

Use this reference when the user or user wants the output to support an investment judgment, not only a credit/liquidity screen.

This layer adapts the useful multi-role decision structure from trading-agent frameworks, but keeps this skill's discipline: public sources, period-aware data, source logs, validation gates, valuation/scenario evidence, and explicit confidence limits.

## When to Use

Use the Investment Committee Layer only after:

1. Layer 0 data integrity checks are complete.
2. Layer 1 automated screen has identified material risk areas.
3. Layer 2 analyst-validated credit/liquidity memo has been drafted or summarized.
4. Gate 3 inputs are validated: dated market price, normalized valuation denominator, sourced expectations, reproducible scenarios, downside, and sensitivity.

If valuation, consensus, the Public-Data FCF Underwriting Base, or reproducible scenario prices are missing, the committee may produce a debate summary only. Keep formal price targets and probability-weighted outcomes suppressed. If Gate 3 scenario prices exist without a validated return context, show the Bear/Base/Bull range as `Scenario Price Sensitivity` and write `Formal probability-weighted outcome: Not Evaluated`.

## Role Structure

Run the roles in this order. Each role should produce evidence-backed output, not generic opinion.

| Role | Main Question | Required Inputs | Output |
|---|---|---|---|
| Fundamental Analyst | Is the business and balance sheet underwritable? | Validated filings, credit memo, earnings quality, cash conversion, liquidity, debt/covenants | Fundamental view, binding constraints, confidence |
| Market Expectations Analyst | What does the market appear to be pricing? | Current price/date, market cap/EV, consensus if available, peer/historical multiples, recent price move/news | Implied expectations, valuation gap, data limits |
| Bull Case | Why could the market be too pessimistic? | Fundamental positives, valuation upside, catalysts, mitigants | 2-3 strongest upside arguments with evidence |
| Bear Case | What breaks the thesis? | Liquidity risks, earnings downside, valuation downside, adverse working-capital signals, missing data | 2-3 strongest downside arguments with evidence |
| Risk Manager | What can go wrong, how bad can it be, and how would we know? | Bear case, stress tests, downside scenario, liquidity/refinancing risk, confidence gaps | Key risks, thesis-break triggers, confidence adjustment |
| Portfolio Manager | Is the risk-adjusted return worth capital versus alternatives? | Bull/base/bear returns, downside, hurdle return, sizing constraints, portfolio overlap/opportunity cost | Action view, sizing range, monitoring plan, next decision trigger |

## Role Output Requirements

Each role should include:

- `View`: one direct conclusion.
- `Evidence`: key facts/calculations with period and source.
- `Decision Impact`: why this matters for action.
- `Confidence`: High / Medium / Low.
- `Falsification Trigger`: what would change the view.

Do not allow any role to introduce unsupported claims. If evidence is missing, tag it as `MISSING` and explain whether it blocks action.

## Committee Synthesis

After the role outputs, synthesize into:

1. **Decision View**: use only the action language allowed by the current Data Gate.
2. **Variant Perception**: the clearest difference between the analyst view and apparent market expectation.
3. **Price Sensitivity / Risk**: base-case price change and bear-case downside versus the dated price; use formal return language only when the horizon, dividend, share-count, probability method, freshness, sensitivity, and approval are all validated.
4. **Position Sizing Logic**: proposed sizing range only if downside, liquidity, conviction, and portfolio context are sufficient.
5. **Opportunity Cost**: what this idea must beat: cash, index exposure, sector peer, existing portfolio name, or another identified alternative.
6. **Next Decision Trigger**: event or data point that should cause reassessment.

## Action View Rules

Use action language carefully:

- `Watch / Need More Work`: use when the company is interesting but valuation, consensus, scenario, or source evidence is incomplete.
- `Credit Screen Only`: use when the work supports only liquidity/credit assessment.
- `Ready for Human Investment Review`: use only at Gate 3 after valuation and scenario outputs are reproducible. It is not a buy instruction.
- `Avoid on Credit/Liquidity Grounds`: use when liquidity, refinancing, covenant, cash conversion, or accounting evidence creates a clear block.
- `Hedge / Monitor Exposure`: use when the analysis is more relevant to managing existing exposure than initiating a new one.

Do not use formal `Buy`, `Sell`, or `Hold` unless Gate 3 evidence is complete and a human analyst explicitly owns the action. Portfolio sizing additionally requires Gate 4.

## One-Page Committee Snapshot

For one-page outputs, compress the committee layer into this table:

```markdown
## Investment Committee Snapshot / 投资委员会式判断

| Role / 角色 | View / 判断 | Evidence / 证据 | Decision Impact / 对决策的影响 |
|---|---|---|---|
| Fundamental Analyst | ... | ... | ... |
| Market Expectations Analyst | ... | ... | ... |
| Bull Case | ... | ... | ... |
| Bear Case | ... | ... | ... |
| Risk Manager | ... | ... | ... |
| Portfolio Manager | ... | ... | ... |
```

Keep each cell short. Move detailed debate into the full memo.

## Full Memo Committee Section

For full investment memos, include:

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

## Guardrails

- Do not let the committee format create false certainty.
- Do not turn unsupported market sentiment into consensus.
- Do not use technical indicators as substitutes for valuation or scenario work.
- Do not let the bull/bear debate repeat the same evidence already stated elsewhere; each side must sharpen the decision.
- Do not present position sizing if portfolio context, downside, or confidence is missing.
- Always show what would change the conclusion.
