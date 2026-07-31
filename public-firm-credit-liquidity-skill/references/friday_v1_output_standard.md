# Friday V1 Output and Decision-Boundary Standard

Treat this reference as binding for every public-company One-Page, Full Report, contract, and renderer.

## Product Positioning

Use the name:

`Public-Data Issuer Underwriting and IC Pre-Read System - Friday V1`

The system helps a human investor decide whether an issuer deserves further research, what the public-data view is, what is conditionally priced in, what the key debates are, whether liquidity or credit constrains the case, and what evidence would change the view.

It is not a complete investment-decision system, trade recommendation, validated fair-value engine, portfolio-construction system, or position-sizing model.

## Return and Horizon Rule

Without all of the following validated fields, scenario percentages are only price sensitivities:

- `valuation_as_of_date`
- `target_date`
- `holding_period`
- `forecast_period`
- `metric_period`
- `dividend_assumption`
- `share_count_basis`
- `exit_basis`

Use `Scenario Price Sensitivity`, `Implied Price`, and `Price Change vs Current Price`. Do not use expected return, total return, annualized return, twelve-month return, or target price as formal output labels.

Under schema `5.1.0`, display four separate output classes from the shared valuation contract:

- `Price Sensitivity`
- `Base-Case Return`
- `Probability-Weighted Return`
- `Partner Internal Return`

Do not combine their values or validation statuses. Base-Case Return may validate without probabilities. Probability-Weighted Return requires the complete probability-governance gate. Partner Internal Return remains disabled in public issuer artifacts.

Formal-return periods must use the controlled horizon relationships in `shared_valuation_contract.md`; free-text labels are insufficient. Dividends must be cumulative through the target date, currency-matched, explicitly non-reinvested, and reviewer-owned. S09 supports the controlled scenario exit-multiple method only.

Do not use public Bear/Bull price sensitivities as portfolio downside/upside returns. Gate 4 may consume a validated public probability-weighted return as one return input, but downside-return tests require separately validated return inputs on the same dated horizon.

Display this disclosure:

> No target date or holding period is assigned. These figures are valuation sensitivities relative to the dated market price. They are not expected returns, total returns, annualized returns, or formal price targets.

## Public-Data FCF Underwriting Base

Do not use `Normalized FCF - Analyst Validated` as a generic headline. Use `Public-Data FCF Underwriting Base` and separately disclose:

- Source-data validation status.
- Calculation validation status.
- FCF Normalization Status.
- Normalization scope.
- Reproducible bridge lines.
- Unresolved economic-normalization items.

Allowed FCF Normalization Status values:

- `UNADJUSTED_PUBLIC_BASE`
- `PARTIALLY_NORMALIZED`
- `FULLY_NORMALIZED`

`PARTIALLY_NORMALIZED` requires at least one reproducible adjustment. `FULLY_NORMALIZED` cannot retain material unresolved items.

## Separate Workflow and Investment View

Display both:

- Research Workflow Status: `Data Review Required`, `Underwriting In Progress`, or `Ready for Human Review`.
- Public-Data Investment View: `Continue Research`, `Watch`, `Stop Research`, `Case Strengthening`, or `Case Weakening`.

Research readiness does not measure investment attractiveness and does not authorize a trade.

## Valuation Status

Allowed values:

- `RANGE_ONLY`: reproducible scenario price sensitivity may exist, but the
  driver forecast, forward share bridge, and independent cross-check are not
  all validated. A forward model alone or a cross-check alone cannot upgrade
  this status.
- `PARTIALLY_VALIDATED`: the driver-based forward forecast, target-date share
  bridge, and at least one independent valuation cross-check all validate.
- `MULTI_METHOD_VALIDATED`: the `PARTIALLY_VALIDATED` requirements plus the
  complete S09 horizon, reverse valuation, full S11 multi-method context, and
  named human review all validate.

Disclose the separate status of peer valuation, historical valuation, DCF cross-check, driver-based forward forecast, and forward share-count bridge. Scenario multiples are analyst-owned sensitivity references unless independently validated; never describe them as fair-value multiples merely because their calculations reproduce.

The aggregate Valuation Status is stricter than an individual S10 or S11
component status. In particular, S11 `PARTIALLY_VALIDATED` means at least one
S11 method validates; it does not by itself make the aggregate valuation
`PARTIALLY_VALIDATED`. A complete S11 contract without a validated S09 horizon
cannot produce aggregate `MULTI_METHOD_VALIDATED`.

## Share-Count Basis

Every per-share output must disclose:

- Value, date, type, and source.
- Point-in-time or forward basis.
- Forward bridge status.
- Known subsequent-event status and note.
- `CURRENT` or `PROXY` status.

If the share-count date differs from the market-price date and no validated forward bridge exists, label every per-share sensitivity `PROXY`.

## What Is Priced In

Include a conditional `What Is Priced In` section based on dated market capitalization, reverse valuation, the Public-Data FCF Underwriting Base, management guidance, consensus where sourced, and public operating evidence.

Do not infer priced-in expectations from price appreciation, a 52-week high, or historical range position alone. State that the result depends on the analyst-owned reference multiple and is not a fair-value claim.

## Decision Confidence

Every High, Medium, or Low label must include:

- Main supports.
- Main constraints.
- Evidence that would increase confidence.
- Events that would reduce confidence.

## Evidence Presentation

Preserve every raw stable evidence and source ID in the machine-readable contract and Evidence Audit Appendix.

- One-Page: no raw `EV-...` strings; use at most one compact evidence-bundle reference per section.
- Full Report: use evidence bundles and short `E###` references.
- Evidence Audit Appendix: show raw evidence/source IDs, exact values, periods, as-of dates, locators, formulas, and upstream IDs.
- One-Page and Full Report must use the same validated object and contract hash.

## One-Page Order

Keep it to one page and make the current view understandable in about 30 seconds:

1. Research Workflow Status.
2. Public-Data Investment View.
3. Data Gate.
4. Decision Confidence and constraints.
5. Valuation Status.
6. Investment Question.
7. Executive Investment Answer.
8. What Is Priced In.
9. Public-Data FCF Underwriting Base and Normalization Status.
10. Scenario Price Sensitivity.
11. Probability Status.
12. Key Debates.
13. Upgrade, downgrade, invalidation, and monitoring conditions.
14. What can and cannot be concluded.
15. Portfolio Overlay Disabled.

## Probability and Portfolio Boundaries

Scenario prices and price changes may appear without probabilities. A formal Base-Case Return requires the complete S09 horizon, forward share basis, and exit basis. A formal probability-weighted outcome additionally requires a validated method, evidence, fresh as-of and review dates, sensitivity, and named human approval.

Keep `Portfolio Decision: Not Evaluated` and `Portfolio Overlay: Disabled` until validated fund inputs and human approval reach Gate 4. Never place a trade.

## Required Artifacts and QA

For a partner-ready package generate:

- Bilingual One-Page Summary.
- Bilingual Full Report.
- Bilingual Evidence Audit Appendix.
- Bilingual QA Summary.
- Machine-readable shared contract.

Before delivery verify contract validation, Hard Stops, warnings, Data Gate, dual statuses, confidence rationale, FCF Normalization Status, Probability Status, Valuation Status, share-count proxy, portfolio status, period/date alignment, scenario reproduction, and absence of raw evidence IDs from the main reports. Any P0/Hard Stop blocks formal artifact generation.

Mark peer valuation, historical valuation, DCF, driver forecast, formal probabilities, multi-method fair value, portfolio overlay, or sizing as `NOT_COMPLETED` or `NEXT PHASE` when the required evidence and controls are not complete.
