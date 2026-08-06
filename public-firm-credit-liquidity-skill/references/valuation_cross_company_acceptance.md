# S12 Valuation Cross-Company Acceptance

Use this reference before changing the aggregate Valuation Status, adding a
business-model driver, or claiming that S09-S11 valuation behavior generalizes
across companies.

Authoritative acceptance runner:

`user-demo/investment_decision_v2/scripts/run_s12_valuation_cross_company_acceptance.py`

Frozen scope:

`user-demo/investment_decision_v2/regression/s12_valuation_cross_company_acceptance_manifest.json`

## Aggregate Status Rules

The report-level Valuation Status is not the S10 status and is not the S11
status.

### RANGE_ONLY

Use when scenario price sensitivity is reproducible but all requirements for
the next status are not present.

The following are insufficient by themselves:

- a driver-based forward forecast;
- a forward share bridge;
- one independent DCF or other cross-check;
- an S11 partial status;
- an S11 multi-method status without a complete S09 horizon.

Price Sensitivity may remain available. Base-Case Return and
Probability-Weighted Return follow their separate S09 permissions and must not
be inferred from this status label.

### PARTIALLY_VALIDATED

Require all of:

- a `VALIDATED` S10 driver-based forward forecast;
- a completed target-date forward share-count bridge;
- at least one validated independent valuation cross-check.

The requirements use logical AND. One-sided evidence remains `RANGE_ONLY`.

### MULTI_METHOD_VALIDATED

Require all `PARTIALLY_VALIDATED` conditions plus:

- a validated S09 horizon and Base-Case Return contract;
- validated reverse valuation;
- S11 `MULTI_METHOD_VALIDATED`, including controlled peer, historical,
  reverse, and independent methods;
- named human review.

Probability governance remains separate. A formal Probability-Weighted Return
requires its own current method, evidence, sensitivity, expiration, and
independent approval.

## Required Acceptance Matrix

Exercise every controlled S10 business-model module:

- `RETAIL`
- `CONSUMER_BRAND`
- `SUBSCRIPTION_SOFTWARE`
- `INDUSTRIAL`
- `ACQUISITION_HEAVY`
- `DISTRIBUTION`

Exercise the three aggregate status paths on different models. Also exercise
negative guards for independent-only support, forward-only support, and
multi-method support without a complete S09 horizon.

Inspect preserved public-company contracts offline to confirm that absent
analyst inputs return safe states such as `DRIVER_MODEL_NOT_AVAILABLE`,
`NOT_PROVIDED`, or `RANGE_ONLY`. Never backfill a real company with synthetic
valuation assumptions.

## Synthetic Fixture Boundary

Controlled acceptance data must carry `SYNTHETIC_ACCEPTANCE_ONLY`. It exists to
exercise shared calculations and validation, not to represent a company,
market view, target price, or investment recommendation.

Keep synthetic assumptions out of public-company research inputs and rendered
user reports.

## Anti-Overfitting Rule

Freeze the manifest and pre-run commit before the first run. Preserve the first
failure output. Do not replace a difficult case after failure.

Fix failures only in the shared component that owns the rule. Do not add:

- ticker or company-name checks;
- fixture-ID branches;
- hard-coded company values;
- renderer-side analytical fixes;
- status overrides.

After any shared fix, rerun:

1. the complete S12 matrix;
2. the complete unit-test suite;
3. cross-industry anti-hardcoding governance;
4. skill validation;
5. the frozen v1.0.0 HTML, PDF page-count, and pixel baseline.

## Return-Language Boundary

- Price sensitivity is not a target price.
- Base-Case Return requires the complete S09 horizon.
- Probability-Weighted Return additionally requires validated probability
  governance.
- User Internal Return, position sizing, portfolio action, and trade
  execution remain disabled outside the private Gate 4 workflow.

Rounded presentation values are acceptable. The authoritative calculations,
dates, periods, units, currencies, share bases, and evidence links must remain
reproducible.
