# Gate 4 S13 Portfolio Constraint Engine

Read this reference whenever calculating or interpreting a portfolio constraint
ceiling from private Gate 4 inputs.

## Required Sequence

1. Load and validate the private manifest and every referenced document.
2. Load the exact Gate 3 `underwriting_output_contract.json`.
3. Run Gate 3 eligibility and freshness.
4. Reload the Gate 3 contract immediately before calculation.
5. Re-run eligibility and freshness.
6. Confirm the report ID, contract hash, SEC CIK, and equity ticker still match
   the candidate.
7. Calculate every applicable constraint from the shared engine.
8. Validate the shared S13 output contract.
9. Write the result only to the repo-external private output directory.

Any identity change between the two checks returns
`GATE_4_BLOCKED_GATE_3_CHANGED_DURING_RECHECK`. Stale or ineligible Gate 3
states suppress all private calculations.

## Required Private Input

The manifest must reference `portfolio_constraint_inputs.yaml`. It stores:

- the exact Gate 3 report ID and contract hash;
- candidate security, SEC CIK, sector, country, and correlation bucket;
- expected return with method, dates, horizon, source hash, and reviewer;
- downside return with method, dates, horizon, source hash, and reviewer;
- dated ADVT in portfolio base currency;
- proposed hedge terms, if any;
- current downside-loss risk-budget usage; and
- current policy-defined liquid portfolio weight.

`VALIDATED`, `PROVISIONAL`, and `MISSING` are explicit states.
`PROVISIONAL` and `MISSING` never become zero and cannot unlock a complete S13
ceiling.

Public Bear/Base/Bull price sensitivity is not a return. A public
probability-weighted return is accepted only when the Gate 3 valuation contract
itself marks that dated-horizon output `VALIDATED` and the value and dates
reconcile. A public Bear downside is accepted only from a validated formal
scenario-return object; an implied-price change is never substituted. A
Partner stress return must remain in the repo-external private input.

## Measurement Basis

Concentration is measured as `GROSS_LONG_WEIGHT`.

- Complete aggregated or full holdings may support a zero existing exposure
  when no matching long row exists.
- Exposure-only mode requires one explicit reviewed issuer, sector, country,
  and correlation-bucket row. Absence is `MISSING`, not zero.
- Exposure dimensions overlap and are never added to each other.

## Formulas

Single-name, sector, country, and correlated exposure:

```text
maximum incremental weight =
max(0, policy limit - current matching gross-long weight)
```

Candidate liquidity:

```text
maximum incremental weight =
ADVT * maximum daily volume participation * maximum days to exit
/ portfolio NAV
```

The candidate must also meet minimum ADVT. Exposure-only mode without NAV
cannot produce this ceiling. ADVT must be no older than the explicit policy
age limit.

Downside-loss risk budget:

```text
maximum incremental weight =
max(0, risk budget limit - current risk-budget usage)
/ abs(validated candidate downside return)
```

Target return, holding period, downside tolerance, current portfolio liquidity
floor, and opportunity cost are binary constraints. A validated failure gives
a zero ceiling; missing evidence gives a null ceiling.

Opportunity cost compares only active, validated alternatives with the same
security type and a holding-period difference within the reviewed policy:

```text
candidate return - highest comparable alternative return
>= minimum required excess return
```

Hedge terms are checked against permitted instruments, maximum ratio, and
effectiveness status. S13 never raises the unhedged ceiling for assumed hedge
relief.

## Binding Rule

When every required constraint has a numeric ceiling:

```text
maximum constraint-based incremental position =
minimum(all required constraint ceilings)
```

All constraints tied at that minimum are binding. Maximum total issuer weight
equals current issuer gross-long weight plus the incremental ceiling.

If any required constraint is `MISSING`, both final maximum fields remain null
and `binding_constraints` remains empty. `tightest_known_constraint` may be
shown, but it must say it is not final while inputs are missing.

## Status and Language

- `GATE_4_CONSTRAINTS_CALCULATED`: every required S13 ceiling is reproducible.
- `GATE_4_CONSTRAINTS_INCOMPLETE`: at least one required S13 input or ceiling
  is missing.
- `GATE_4_BLOCKED_STALE_GATE_3`: freshness failed.
- `GATE_4_BLOCKED_INELIGIBLE_GATE_3`: identity, validation, gate, valuation, or
  warning governance failed.
- `GATE_4_BLOCKED_GATE_3_CHANGED_DURING_RECHECK`: Gate 3 changed between checks.

S13 output is not an S14 system assessment. Keep:

- System Portfolio Assessment: `NOT_EVALUATED`
- Partner Decision: `PENDING`
- Approved Position Range: null
- Automatic Trade Execution: false

Always call the result a `constraint ceiling`, `maximum allowed by the tested
constraints`, or `maximum constraint-based position`. Never call it a
recommended, suggested, target, approved, or optimal position.

After S13 passes, read `gate4_assessment_and_approval.md` and run
`run_gate4_assessment.py`. S14 must consume the current shared S13 engine result;
it must not recreate S13 formulas in a renderer.
