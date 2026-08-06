# Modular Forward Operating Bridges

Use this reference for S10 forward FCF and forward share-count work.

## Architecture

Use:

`Shared Forward Valuation Contract + Business-Model Driver Module`

Business-model modules may change the revenue bridge only. Every module must
produce the same common operating, FCF, share-count, evidence, and validation
fields. Do not add a ticker, company-name, or renderer-specific calculation.

The authoritative implementation is:

`user-demo/investment_decision_v2/scripts/forward_operating_model.py`

Contract version: `1.0.0`

Driver registry version: `1.0.0`

## Initial Controlled Modules

- `RETAIL`: base revenue, comparable-sales growth, net-store growth, and other
  revenue growth.
- `CONSUMER_BRAND`: named brand or segment revenue bases and growth.
- `SUBSCRIPTION_SOFTWARE`: at least two named revenue streams, including the
  subscription and non-subscription economics relevant to the issuer.
- `INDUSTRIAL`: base revenue, volume, price/mix, acquisition revenue, and
  divestiture revenue.
- `ACQUISITION_HEAVY`: base revenue, organic growth, acquired revenue, and
  divested revenue.
- `DISTRIBUTION`: base revenue, volume, and price/mix.

Module selection is analyst-owned. It requires a rationale, linked public
evidence, and a named reviewer. Do not select a module from a ticker lookup.

If no controlled module fits, return:

`DRIVER_MODEL_NOT_AVAILABLE`

Do not substitute historical growth, consensus growth, a generic margin, or an
unsupported total FCF forecast.

`Forward FCF` is available only from a `VALIDATED` S10 driver model. When the
status is `DRIVER_MODEL_NOT_AVAILABLE`, do not route a manually entered
`Forward FCF` total through the legacy scenario path.

## Common Operating Bridge

Every Bear, Base, and Bull scenario must contain:

1. A module-specific forward revenue bridge.
2. Operating margin.
3. Cash interest.
4. Cash taxes.
5. Depreciation and amortization.
6. Stock-based compensation.
7. Other non-cash items.
8. Working-capital investment.
9. Capex.
10. Restructuring cash.
11. Acquisition or integration cash.
12. Other cash adjustments.

Every common cash-flow line uses a controlled `measurement_basis`. In
particular, operating margin must be:

`EBIT_MARGIN_BEFORE_SEPARATELY_MODELED_RESTRUCTURING_AND_INTEGRATION_CASH_ITEMS_INCLUDING_DA_AND_SBC`

This prevents adjusted operating margin from being combined with a second D&A
or SBC addback, and prevents separately modeled restructuring or integration
cash from being deducted after the same expense was already retained in the
margin. Use another model rather than changing this definition silently.

S10 revenue and FCF are flow metrics. The S10 `metric_period` must therefore be
an allowed `FORWARD_METRIC` period aligned with the dated S09 target. A
`POINT_IN_TIME_METRIC` is never valid for forward revenue or FCF.

Use the common basis:

`LEVERED_CFO_MINUS_CAPEX_BRIDGE`

Calculate:

`operating_income = forward_revenue * operating_margin`

`forward_fcf = operating_income - cash_interest - cash_taxes + D&A + SBC + other_non_cash_items - working_capital_investment - capex - restructuring_cash - acquisition_integration_cash + other_cash_adjustments`

This is an operating bridge to a levered CFO-minus-capex style metric. It
excludes dividends, repurchases, net borrowing, and acquisition purchase
consideration unless the controlled input definition explicitly includes an
operating cash item.

Do not input CFO, net income, or another embedded cash-flow subtotal into the
same bridge. The engine rejects unsupported fields so interest, tax, working
capital, leases, or other CFO items cannot be counted twice.

Use these signs:

- Cash interest, capex, restructuring cash, and acquisition/integration cash:
  positive use.
- Cash taxes: positive use; negative amount is a refund.
- Working-capital investment: positive use; negative amount is a release.
- Other cash adjustments: positive source; negative amount is a use.

Negative forward FCF may be a valid operating-model result. It is not eligible
for a positive FCF multiple. Do not force a price from it.

## Evidence Rules

Classify every input or bridge line as:

- `FACT`
- `CALC`
- `JUDGMENT`
- `MISSING`

For every non-missing input, require:

- finite value;
- stable evidence ID;
- evidence ID present in the shared evidence layer;
- named reviewer;
- rationale for `JUDGMENT`;
- formula for analyst-supplied `CALC`;
- matching currency and unit.

All monetary inputs use unscaled atomic units equal to the market-price
currency, for example `USD` with `amount_scale = 1.0`. Do not enter
`USD_MILLIONS`, values in millions with a `USD` label, or any other implicit
scale. Every assumption line must state its own unit and, for monetary values,
currency; the engine does not infer them from the top-level contract. Share
values and share changes use unscaled `SHARES`.

A `FACT` or `CALC` input is valid only when at least one linked evidence record
has:

- the same evidence class;
- `PASS` validation;
- the same canonical value after applying the evidence record's explicit
  scale;
- the same currency and unit;
- a dated period, as-of date, or publication date.

An existing but unrelated evidence ID is not sufficient. `JUDGMENT` lines may
use contextual evidence, but require an explicit rationale and named reviewer.

Historical base-revenue lines must be `FACT` or reproducible `CALC`; do not
classify a historical base as analyst judgment. Scenario growth, margin, and
cash-flow assumptions may be `JUDGMENT` when their rationale and supporting
evidence are explicit.

An explicit zero is allowed only when it is entered, linked, and reviewed. A
missing line is not zero.

Calculated forward revenue, forward FCF, and forward shares must become CALC
evidence records with formulas and upstream evidence IDs. Renderers must not
recalculate them. Persisted scenario evidence IDs, calculation evidence IDs,
the reported-share input, and the forward-share calculation evidence are
revalidated against the shared evidence layer.

## Forward Share-Count Bridge

Start from the authoritative latest reported point-in-time share count and
bridge to the S09 target date using:

- repurchases, entered as a positive share reduction;
- stock-based-compensation issuance;
- employee-plan issuance;
- convertible dilution;
- acquisition share issuance;
- other net share change, using a signed amount.

Calculate:

`forward_diluted_shares = latest_reported_shares - repurchases + SBC_issuance + employee_plan_issuance + convertible_dilution + acquisition_share_issuance + other_net_change`

Require:

- target date equal to the shared valuation target date;
- a stable evidence ID for the reported share base;
- explicit values for every change line;
- reviewed subsequent events;
- named reviewer;
- positive forward diluted shares.

If the manual S09 share input and the S10 bridge both claim completion but
disagree, return `FORWARD_SHARE_INPUT_CONFLICT`. Do not choose one silently.

## Statuses

- `DRIVER_MODEL_NOT_AVAILABLE`: no supported module; no forecast generated.
- `INVALID`: the operating model is incomplete, contradictory, or
  unreproducible.
- `PARTIALLY_VALIDATED`: the operating model is valid but the forward
  share-count bridge is incomplete.
- `VALIDATED`: all three operating scenarios and the target-date share bridge
  validate.

Only `VALIDATED` may project generated scenario FCF and forward shares into the
shared S09 valuation contract.

Renderers suppress all forward numeric values when the operating model is
`INVALID`. Persisted contracts are revalidated and recalculated even if their
status has been downgraded, so changing a status label cannot bypass numerical,
evidence, period, unit, or governance checks.

A persisted S09 scenario using `Forward FCF` is invalid unless S10 remains
`VALIDATED`. When S10 is validated, every S09 Bear/Base/Bull per-share Forward
FCF and target-date share denominator must reconcile back to the S10 output.
Malformed dates, lists, or nested objects must return validation errors rather
than raising an exception.

Even a `VALIDATED` S10 model does not by itself establish:

- an appropriate exit multiple;
- peer or historical comparability;
- probability weights;
- a formal expected return;
- a target price;
- a portfolio action.

Those remain governed by S09, S11, and Gate 4.

## Input Workflow

1. Run the generic investment-layer builder without a research input.
2. Open the generated `analyst_input_template.json`.
3. Select one controlled `driver_module`.
4. Complete `module_selection`, all three scenario revenue and cash-flow
   drivers, and `share_count_bridge`.
5. Keep the S09 forecast period, metric period, and target date aligned.
6. Complete the separate `scenario_model` exit-multiple, key-driver, and
   falsification fields.
7. Rerun with `--research-input`.
8. Inspect `forward_valuation_contract.validation_issues`, the Evidence
   Appendix, and contract validation before using any scenario price.

Do not mark the S10 session complete from template generation alone. Run the
dedicated S10 tests, the full regression suite, skill validation, and an
independent review.
