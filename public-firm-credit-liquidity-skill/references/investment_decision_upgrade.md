# Investment Decision Upgrade Rules

Use this reference when the work is intended to support an investment judgment. Read `system_architecture_and_contract.md` first; it is the authoritative system specification.

## Objective

Move from a descriptive financial report to an auditable issuer-level underwriting memo that answers a defined Investment Question and clearly states what the current evidence can and cannot support.

Do not equate a complete set of sections with a complete investment case.

## Required Evidence Classes

| Class | Meaning |
|---|---|
| FACT | Direct source evidence with period, as-of date, and locator |
| CALC | Reproducible calculation with formula and input evidence IDs |
| INFERENCE | Interpretation based on identified facts and stated assumptions |
| JUDGMENT | Analyst-owned view, threshold, override, or decision |
| MISSING | Decision-relevant evidence not available or not validated |

Every material number and conclusion must use one of these classes.

## Mandatory Front Matter

Every investment-support output must begin with:

1. Data Gate.
2. Current allowed action.
3. Decision Confidence.
4. Investment Question.
5. What can be concluded.
6. What cannot be concluded.
7. Two or three Key Debates.

If no analyst-defined Investment Question exists, write `Not Defined`, reduce confidence, and avoid strong action language.

Each Key Debate must show:

- Market or conventional view, or `Not Sourced`.
- Alternative or internal view, or `Not Formed`.
- Supporting evidence IDs for each side.
- Missing evidence.
- KPI or event that resolves the debate.
- Decision impact.

## Issuer Underwriting Requirements

Complete these shared modules before Gate 2:

- Business and industry.
- Earnings quality.
- Working capital and cash conversion.
- Liquidity sources and uses.
- Debt, leases, covenants, and refinancing.
- Initial downside stress test.
- Capital allocation where material.
- Management guidance and subsequent events where available.

Use note-level evidence for debt, revolver/ABL, maturity, leases, covenants, acquisitions, impairments, credit losses, commitments, and refinancing.

## Period and Accounting Rules

- Match period start, period end, period type, and duration for flow ratios.
- Use instant balances with flows only through an explicit average-balance formula.
- A missing standalone cash-flow quarter remains missing. Do not relabel YTD as quarter.
- Derive a quarter only from current YTD minus prior same-fiscal-year YTD, retaining both sources.
- Build LTM as latest annual plus current YTD minus prior comparable YTD using one concept and compatible fiscal periods.
- Label CFO minus total cash capex as reported FCF, not normalized FCF.
- Separate maintenance capex from growth capex only with sourced evidence.
- Separate unrestricted cash, restricted cash, and cash plus restricted cash.
- Separate lease carrying values from contractual lease cash payments.
- Reconcile debt carrying value, contractual principal, discounts, current/noncurrent classification, and tranche schedule.
- Compliance does not prove covenant headroom. Show trigger, test definition, and numerical headroom when available.

## Public-Data FCF Underwriting Base and Normalization

Do not imply complete economic normalization merely because source data and arithmetic validate. Display a Public-Data FCF Underwriting Base plus `UNADJUSTED_PUBLIC_BASE`, `PARTIALLY_NORMALIZED`, or `FULLY_NORMALIZED`. Any adjustment requires a transparent bridge showing:

- Reported CFO and period.
- Cash capex and whether it is total or maintenance.
- Each normalization line.
- FACT, CALC, or JUDGMENT classification.
- Source or analyst owner.
- Formula and sign convention.
- Recurring versus non-recurring rationale.
- No CFO double counting.

CFO already includes cash interest, cash taxes, working capital, and operating lease cash flows under the applicable US-GAAP presentation. Deducting these again requires an explicit sourced reversal and rebuild.

## Liquidity Sources and Uses

A forward liquidity model must not treat historical CFO as a forecast.

Distinguish:

- Point-in-time liquidity: unrestricted cash, eligible investments, confirmed facility availability.
- Contractual uses: debt maturities, lease cash payments, interest, commitments, and other fixed uses.
- Forecast uses: maintenance capex and company-specific operating needs.
- Forecast operating cash generation under explicit assumptions.

Every line must declare whether it is embedded in CFO and separately modeled. A duplicate without a reversal is a Hard Stop.

## Market Expectations and Variant Perception

Do not infer consensus from a trailing multiple, price momentum, or a 52-week range position.

Use:

- Sourced consensus and date.
- Official management guidance and date.
- Historical and peer valuation with compatible definitions.
- Reverse valuation that states what growth, margin, or cash flow is required by the current price.
- An explicitly labeled internal expectation when consensus is unavailable.

If expectations are unavailable, write `Not Sourced`. Do not substitute an automated narrative.

## Valuation and Scenarios

Below Gate 3, scenario implied prices and price changes must remain null. At Gate 3, percentages are `Price Change vs Current Price` unless the complete return context is validated. Formal probability-weighted output remains null unless probability governance and return-context validation separately pass.

Gate 3 requires:

- A calculation-validated Public-Data FCF Underwriting Base or another justified valuation denominator, with separate economic-normalization status.
- Selected valuation method and reason.
- Reverse valuation.
- Bear, Base, and Bull company-specific assumptions.
- Reproducible implied prices.
- Sensitivity analysis.
- Falsification trigger for each scenario.
- Named human reviewer.

Do not automatically convert historical growth, trailing multiples, leverage, cash-flow margin, or price performance into scenario probabilities or exit multiples.

Probabilities are optional for scenario-price construction. When a formal probability-weighted outcome is requested, apply `probability_and_peer_governance.md`: declare the method, link evidence, explain every scenario weight, set as-of and expiration-review dates, run probability sensitivity, confirm freshness, obtain explicit human approval, and validate the target date, holding period, metric period, dividend assumption, and share-count basis.

## Decision Rules

Every report must state:

- What can currently be concluded.
- What cannot currently be concluded.
- What evidence is required next.
- Measurable upgrade conditions.
- Measurable downgrade conditions.
- Thesis-invalidation conditions.

Thresholds must be sourced or analyst-owned. Do not invent them. Use `MISSING` when absent.

## Portfolio Boundary

Keep the portfolio overlay disabled until Gate 4.

Gate 4 requires validated fund-specific inputs and explicit human approval. Illustrative overlay data cannot unlock Gate 4.

The system may display a human-approved portfolio action and position range. It must not choose them independently and must never place a trade.

## One-Page Structure

1. Decision Strip.
2. Investment Question.
3. What is and is not supported.
4. Key Debates.
5. Evidence-linked key numbers.
6. Current issuer-underwriting status.
7. Next evidence and decision triggers.
8. Portfolio overlay status.

## Full Report Structure

1. Executive decision boundary.
2. Investment Question and Key Debates.
3. Business and industry.
4. Earnings quality and Public-Data FCF Underwriting Base, including FCF Normalization Status.
5. Working capital and cash conversion.
6. Liquidity sources and uses.
7. Debt, leases, covenants, and refinancing.
8. Stress tests and capital allocation.
9. Management guidance and subsequent events.
10. Market expectations, reverse valuation, and scenarios when allowed.
11. Upgrade, downgrade, and thesis-invalidation rules.
12. Evidence, sources, formulas, validation, and missing information.

One-Page and Full Report must render the same versioned output contract and display the same report ID and contract hash.
