# Shared Equity Valuation Contract

Use this reference for every public-company equity valuation created under schema `5.1.0` or later.

## Required Horizon

Store the following once in `valuation_contract`:

- valuation as-of date;
- target date;
- holding period derived from the two dated endpoints using ACT/365.25;
- forecast period;
- valuation metric period;
- explicit dividend assumption, including an explicitly validated zero;
- forward share-count basis dated to the target date, reconciled to every scenario price, and supported by a completed subsequent-event review;
- exit or terminal basis;
- named reviewer.

Do not silently use the market-price date, zero dividends, a point-in-time share count, or an exit multiple as a validated formal-return assumption. A supplied as-of date must equal the dated market-price input. Conflicting holding-period days fail validation.

Every formal scenario must carry the same forecast period, metric period, and target-date share basis as the top-level valuation contract. Merely filling the top-level fields does not validate a scenario built on a different period or denominator.

For S09, use these fail-closed semantic values:

- forecast `period_type`: `FORECAST`;
- forecast `basis`: `HOLDING_PERIOD_FORECAST`, beginning on the valuation date or the next day and ending on the target date;
- metric `period_type`: `FORWARD_METRIC` or `POINT_IN_TIME_METRIC`;
- metric `basis`: `FORWARD_PERIOD_ENDING_AT_TARGET`, `FORWARD_PERIOD_STARTING_AT_TARGET`, or `POINT_IN_TIME_AT_TARGET`, with dates that reproduce the selected relationship;
- dividend `basis`: `CUMULATIVE_CASH_DIVIDENDS_THROUGH_TARGET_DATE`;
- dividend `payment_timing`: `DURING_HOLDING_PERIOD` or `AT_TARGET_DATE`;
- dividend `reinvestment`: explicitly `false`;
- exit `method`: `SCENARIO_EXIT_MULTIPLE`;
- exit timing: `EXIT`.

Labels and syntactically valid dates do not establish economic-period validity. Unsupported period, dividend, or exit semantics keep formal returns `NOT_EVALUATED`; S10 may add additional controlled methods.

## Four Separate Outputs

The shared object must contain exactly:

1. `price_sensitivity`
2. `base_case_return`
3. `probability_weighted_return`
4. `partner_internal_return`

### Price Sensitivity

Allow at Gate 3 when Bear, Base, and Bull implied prices reproduce from the validated scenario model.

Use:

`price_change_vs_current = implied_price / dated_market_price - 1`

This output has no holding-period claim and is never a formal return.

### Base-Case Return

Require the complete validated horizon, a completed forward share-count bridge, reviewed subsequent events, and an explicit exit basis.

Use:

`price_return = base_exit_price / current_price - 1`

`dividend_return = cumulative_dividend_per_share / current_price`

`total_return = (base_exit_price + cumulative_dividend_per_share) / current_price - 1`

`annualized_return = (1 + total_return) ^ (365.25 / holding_days) - 1`

Base-Case Return does not require scenario probabilities.

Validation must bind the displayed current price to the authoritative dated market-price object, the displayed exit price to the authoritative Base scenario, and dividends, currency, target date, holding period, forecast period, metric period, and forward share basis to the shared contract. A self-consistent edited output is invalid if it no longer agrees with those authoritative inputs.

### Probability-Weighted Return

Require everything needed for Base-Case Return plus:

- a controlled probability method;
- linked evidence and scenario rationales;
- current as-of and expiration-review dates;
- completed sensitivity analysis;
- named reviewer and independent human approval;
- Bear, Base, and Bull probabilities in `[0,1]` totaling exactly 100%.

Use probability-weighted scenario proceeds, including the same explicit dividend assumption. Do not weight price-change percentages that use inconsistent horizons or dividend bases.

Probability sensitivity without a complete horizon is a weighted implied-price sensitivity, not a return. Gate 4 must not use Bear/Bull price sensitivities as downside/upside return inputs.

### Partner Internal Return

Keep this output `DISABLED_PRIVATE_GATE_4_ONLY` in every public issuer contract. Do not store partner hurdle rates, internal expected returns, portfolio weights, or sizing in the public repository or issuer artifact.

Gate 4 may consume the public return outputs, but partner internal return must be calculated only from repo-external validated private inputs.

## Status and Suppression

- Below Gate 3, suppress price-sensitivity values and both public return outputs.
- An incomplete horizon leaves Price Sensitivity available at Gate 3 and keeps Base-Case Return `NOT_EVALUATED`.
- Incomplete, stale, or unapproved probability governance keeps Probability-Weighted Return `NOT_EVALUATED` without suppressing a valid Base-Case Return.
- A missing dividend is not zero.
- A point-in-time or proxy share count cannot unlock a formal return. A `COMPLETED` label without a positive forward value, date, source, reviewer, and scenario-price reconciliation is treated as incomplete.
- Renderers must read the four outputs and must not independently calculate them.

Current market capitalization must continue to use the latest reported point-in-time shares available on the market-price date. Scenario per-share values may use a separately validated target-date forward share bridge. Validation must never substitute the forward denominator into the current market-cap calculation.

The scenario engine is metric-agnostic at the shared-contract level. `Normalized FCF` may use the validated FCF bridge. Another positive multiple-based metric, such as earnings or EBITDA, requires its own positive, dated, currency-matched, evidence-linked, reviewer-owned `metric_basis`. Missing or negative denominators must not be forced through a multiple valuation. Business-model driver generation remains S10 scope.

## Compatibility

`return_context` is a read-only compatibility projection of `valuation_contract`; it is not a second source of calculations.

Gate 4 may continue to validate frozen schema `5.0.0` contracts. New outputs must use schema `5.1.0` and the S09 valuation contract.
