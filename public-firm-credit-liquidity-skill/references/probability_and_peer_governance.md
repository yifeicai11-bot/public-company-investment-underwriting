# Probability and Peer Governance

Use this reference for scenario probabilities, formal probability-weighted outcomes, peer valuation, and historical valuation context. A formal return also requires the complete return context in `friday_v1_output_standard.md`.

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
- explicit approval, approver, and approval date.

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

An unavailable or invalid peer set is an honest limitation, not a reason to manufacture comparability. The selected valuation multiple remains analyst-owned unless compatible peer or historical evidence supports it.
