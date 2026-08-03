# Monitoring and Update Mode

Treat this reference as binding whenever comparing issuer reports across time.

## Purpose

S15 answers: what changed since the prior validated issuer contract, which
reviewer-approved conditions were triggered, how scenario sensitivities moved,
and whether probability assumptions require review.

It does not answer the formal thesis question by itself. The system may output
`STRENGTHENING`, `UNCHANGED`, `WEAKENING`, `MIXED`,
`POTENTIALLY_BROKEN`, or `NOT_EVALUATED` as a provisional assessment. The
formal thesis status must remain `PENDING_HUMAN_REVIEW` until a named person
reviews the update.

## Input Contract

Both inputs must be immutable shared issuer contracts that:

- pass the current shared contract validator;
- retain valid canonical hashes;
- represent the same SEC CIK;
- use non-regressing financial, filing, market, and subsequent-event dates; and
- preserve unique evidence class/metric identities.

Do not compare ticker-only inputs, rendered PDFs, or independently recreated
spreadsheets. A changed company name or ticker does not override CIK identity.

## Change Classes

Record separately:

1. `FACT` changes, with values, periods, units, currencies, sources, and IDs.
2. `CALC` changes, with formula and upstream evidence changes.
3. `INFERENCE` and `JUDGMENT` changes, including Investment Question, Key
   Debates, decision rules, thesis breaks, valuation status, and current view.
4. Evidence and source-registry changes.
5. Warning and Hard Stop additions, resolutions, and modifications.

Do not calculate a percentage change when units or currencies differ, either
value is nonnumeric, or the prior denominator is zero or negative.

## KPI Governance

KPI evaluation requires a machine-readable monitoring policy with:

- exact metric name and evidence class;
- current-value, absolute-change, or percent-change basis;
- operator, threshold, unit, and currency;
- upgrade, downgrade, thesis-break, or monitor trigger type;
- effective and expiration dates;
- rationale, named reviewer, and approval status.

The engine must not extract numerical thresholds from narrative decision rules.
Missing, expired, or dimensionally inconsistent rules return `MISSING`,
`EXPIRED`, or `NOT_COMPARABLE` rather than an inferred result.

## Scenario and Probability Rules

Scenario impact compares disclosed Bear, Base, and Bull sensitivities. It does
not silently convert price sensitivity into expected return. Scenario changes
may influence the provisional system assessment only when an approved policy
explicitly enables that use and defines a materiality threshold.

Evaluate probability expiration against an explicit monitoring date and policy
warning window. A new earnings/guidance event, material capital-allocation
change, or covenant/refinancing change must trigger review when the probability
method declares that trigger. Expired or review-required probabilities cannot
support a formal probability-weighted output.

## Decision Boundary

- A current Hard Stop makes the system thesis assessment `NOT_EVALUATED`.
- A triggered thesis-break KPI may produce `POTENTIALLY_BROKEN`.
- Conflicting approved upgrade and downgrade signals produce `MIXED`.
- No formal thesis status may be selected automatically.
- No monitoring output may recommend a position or execute a trade.
