# S11 Valuation Cross-Checks and Probability Governance

Use this reference for the shared `valuation_cross_check_contract`, scenario
probabilities, formal probability-weighted outcomes, peer valuation,
historical valuation, reverse valuation, and independent DCF. A formal return
also requires the complete S09 context in `shared_valuation_contract.md`.

Authoritative implementation:

`user-demo/investment_decision_v2/scripts/valuation_cross_checks.py`

Valuation cross-check contract version: `1.0.0`

Probability governance version: `1.0.0`

## S11 Status Boundary

Use:

- `NOT_PROVIDED`: no S11 input was supplied.
- `INVALID`: submitted inputs are contradictory, unsupported, or
  unreproducible.
- `PARTIALLY_VALIDATED`: at least one method validates, but the complete S11
  set does not.
- `MULTI_METHOD_VALIDATED`: controlled peer comparison, historical valuation,
  reverse valuation, and one independent DCF all validate.

`MULTI_METHOD_VALIDATED` means the methods are reproducible and governed. It
does not mean the methods agree, establish fair value, justify a target price,
or authorize an investment action.

These are S11 component-contract statuses. The report-level Valuation Status is
stricter: S11 partial support alone remains report-level `RANGE_ONLY`, and S11
multi-method support cannot become report-level `MULTI_METHOD_VALIDATED`
without a validated S10 forecast/share bridge and complete S09 horizon. Read
`valuation_cross_company_acceptance.md` for the combined status rules.

Below Gate 3, suppress S11 valuation values and S11 CALC evidence. Do not leak
analyst assumptions through the public output contract.

## Shared Evidence Rule

Every peer or historical observation must be recalculated from:

- a positive capital value;
- a positive fundamental denominator for the selected metric;
- exact, dated, PASS evidence for both values;
- FACT evidence from Source Levels 1 through 4, or a reproducible CALC from
  Source Levels 0 through 4;
- a publication or retrieval date no later than the observation as-of date;
- one currency;
- an explicit fiscal-period end and period basis;
- one accounting definition.

Every displayed peer median, historical statistic, reverse required metric,
DCF range point, and method-agreement result must receive a stable CALC
evidence ID. The renderer must not recreate any calculation.

## Scenario Price Versus Probability

Keep two validations separate:

1. Scenario-price validation proves that Bear/Base/Bull operating assumptions, metric values, multiples, share count, prices, formulas, sensitivity, and falsification triggers are reproducible.
2. Probability validation proves that scenario weights have a declared method, current evidence, sensitivity, and human approval.

Gate 3 may show scenario prices without probabilities. In that case:

- set each scenario probability to null;
- set probability status to `NOT_PROVIDED`, `ILLUSTRATIVE`, or `STALE` as applicable;
- set the formal probability-weighted output to null;
- do not describe the Base weight as the most likely case.

## Allowed Probability Methods

Every formal probability set must declare one method type:

- `HISTORICAL_FREQUENCY`
- `MANAGEMENT_GUIDANCE_CONFIDENCE`
- `SCENARIO_JUDGMENT`
- `MONTE_CARLO`
- `BASE_RATE_ANALYSIS`

`SCENARIO_JUDGMENT` is allowed only when the allocation rationale, evidence, scenario-specific rationales, and alternative weight sensitivities are explicit. The phrase `analyst judgment` alone is not a methodology.

## Required Probability Fields

Require all of the following before formal weighted return:

- method type and methodology;
- method-specific details;
- evidence IDs;
- a rationale for Bear, Base, and Bull;
- probabilities totaling 100%;
- probability as-of date;
- expiration/review date;
- review triggers, including new earnings or guidance;
- at least downside-heavy, central, and upside-heavy sensitivity sets;
- named reviewer;
- explicit independent research approval, approver, approval date, and approval
  scope `PROBABILITY_METHODOLOGY_AND_WEIGHTS`.

The approver must be different from the probability-model owner and
`independent_research_review` must be true. Approval must be dated no earlier
than the probability as-of date and no later than the analysis date.

`HISTORICAL_FREQUENCY` and `BASE_RATE_ANALYSIS` require at least ten
observations. `MONTE_CARLO` requires at least 1,000 iterations and disclosed
input distributions. Method evidence must be current PASS evidence from
Source Levels 1 through 4.

Set probability status to `STALE` when the expiration date has passed or a newer relevant earnings/guidance event supersedes the evidence. A stale or unapproved probability set cannot unlock a formal probability-weighted outcome. Even an approved set cannot create formal return language without the complete S09 valuation horizon, including forecast and metric periods, explicit dividend, forward share basis, and exit basis. Probability approval is not required for a separately validated Base-Case Return.

## Peer Comparability Gate

Never force a peer ranking. Validate each metric row separately.

Suppress automatic comparison or ranking when any of these applies:

- negative EBITDA for an EBITDA-based multiple;
- negative FCF for an FCF-based multiple;
- materially different fiscal periods without a controlled bridge;
- currency mismatch without an explicit dated conversion;
- accounting-definition mismatch, including reported versus adjusted denominators;
- unavailable source, denominator, or as-of date.

Require at least three comparable peers before calculating a median, quartile,
percentile, or ranking. Preserve excluded rows and their flags in the audit
contract, but suppress their numerical value in user-facing reports.
The minimum means three distinct tickers for the metric. Duplicate ticker and
metric rows, missing ticker identity, or a missing/invalid business-model-fit
classification cannot increase the peer count.

A controlled period bridge or currency conversion is valid only when the row
also provides dated PASS evidence IDs, a rationale, and a named reviewer.
Writing `VALIDATED_BRIDGE` or `VALIDATED` without those controls does not
override a mismatch.

An unavailable or invalid peer set is an honest limitation, not a reason to
manufacture comparability. The selected valuation multiple remains
analyst-owned even when compatible peer evidence provides validated context.

## Historical Valuation

Require:

- the same metric and accounting definition as the current observation;
- the same currency and period basis;
- no observation dated after the valuation as-of date;
- at least five distinct observations;
- at least 365 days between the earliest and latest usable observations;
- exact evidence for each capital value and denominator;
- a comparability rationale and named reviewer.

Suppress the median, quartiles, and current percentile when the series fails
any requirement. Do not fill missing history with current values, interpolate
unsupported observations, or combine reported and adjusted definitions.

## Reverse Valuation

Supported methods are:

- `EQUITY_FCF_MULTIPLE`
- `EQUITY_EARNINGS_MULTIPLE`
- `ENTERPRISE_VALUE_EBITDA_MULTIPLE`
- `ENTERPRISE_VALUE_REVENUE_MULTIPLE`
- `EQUITY_FCF_YIELD`

Use the authoritative dated market capitalization for equity methods and the
authoritative dated enterprise value for enterprise methods. Ignore a
user-supplied replacement capital value.
The capital evidence must match the correct metric name, exact value,
currency, and valuation as-of date. A same-valued cash, debt, or stale market
record cannot be substituted. The selected-reference context must link to
current Source Level 1 through 4 evidence.
The reverse-valuation reference basis must state the valuation metric,
currency, forward period basis (`NTM` or `FY1`), and accounting definition.
A peer or historical range supports the selected reference only when all four
fields match. A shared `P/FCF` label cannot bridge reported LTM FCF to forward
normalized FCF.

Calculate:

`required_metric = capital_value / selected_multiple`

or, for FCF yield:

`required_fcf = market_cap * selected_fcf_yield`

The selected reference is always analyst-owned JUDGMENT with linked evidence,
rationale, and reviewer. Mark it supported only when it lies within at least
one validated peer or historical range for the same metric. A reproducible but
unsupported reference is `PARTIALLY_VALIDATED`.

Reverse valuation answers what the dated market capital basis requires under
one selected reference. It does not prove that the reference is fair.

## Independent Cross-Check

S11 V1 supports:

`DISCOUNTED_CASH_FLOW_GORDON_GROWTH`

This V1 method is an enterprise-value DCF. It accepts only
`cash_flow_basis = UNLEVERED_FCFF` and
`discount_rate_basis = WACC`. Do not feed CFO-minus-capex or another levered
FCF into this method and then subtract net debt; doing so would mix cash-flow
bases and can double count financing effects.

Require three to ten explicit annual cash-flow periods, discount rate,
terminal growth, net debt, non-operating assets, minority interest, shares,
an explicit share basis, named reviewers, linked evidence, and explicit zero
values where applicable. A missing value is never zero. Every FACT/CALC input
must bind to evidence that was available by the valuation as-of date; an
unknown or later-published evidence ID invalidates the line rather than being
silently ignored.
The share basis must be one of `POINT_IN_TIME_OUTSTANDING`,
`POINT_IN_TIME_DILUTED`, or `FORWARD_DILUTED`. Its basis date must match the
exact share evidence. A point-in-time basis cannot be dated after valuation;
a forward basis must be dated after valuation. This independent cross-check
does not relabel one share basis as another.
Each modeled period must be forward from the valuation date and span 300 to
430 days, which permits a 53-week fiscal year while preventing quarterly or
stub periods from being discounted as full years.

Calculate:

`enterprise_value = PV(forecast FCF) + PV(terminal value)`

`terminal_value = final_FCF * (1 + g) / (discount_rate - g)`

`equity_value = enterprise_value - net_debt + non_operating_assets - minority_interest`

`implied_price = equity_value / shares`

Require discount rate greater than terminal growth. Require explicit reviewed
discount-rate and terminal-growth sensitivity steps and produce a 3x3 price
range. The sensitivity steps are analyst-owned JUDGMENT and require dated
context evidence, a rationale, and a reviewer. The range is an independent
cross-check, not a target price.

## Method Agreement

Compare the validated S09 Base implied price with the independent DCF central
price only when an explicit, evidenced, reviewer-owned tolerance is supplied.
The S09 Base price must resolve to its exact dated CALC evidence record; the
scenario label alone is not sufficient evidence.
Use:

- `WITHIN_TOLERANCE`
- `DIVERGENT`
- `NOT_EVALUATED`

Divergence does not make either method disappear. Preserve both outputs,
identify the assumptions causing the difference, and do not average them
mechanically.
