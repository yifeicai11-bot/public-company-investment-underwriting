# Gate 4 S14 Assessment, Approval, and Reports

Read this reference whenever converting a validated S13 constraint result into
a portfolio assessment, recording a Partner decision, or rendering Gate 4
reports.

## Required Sequence

1. Load the repo-external manifest and hash every assessment input.
2. Run S13 again through the shared constraint engine with the current files.
3. Confirm neither the private input bundle nor Gate 3 identity changed during
   the run.
4. Validate the S13 schema, S13 output validation, Gate 3 eligibility, final
   ceiling, and binding-constraint reproducibility.
5. Produce the System Portfolio Assessment.
6. Compute a deterministic assessment hash that excludes the mutable Partner
   decision record.
7. Validate the separately owned Partner decision against that hash and the
   total-issuer constraint ceiling.
8. Render the One-Page, Full Report, Evidence Appendix, and Validation Report
   from the same S14 contract without recalculation.

Run locally:

```bash
python3 partner-demo/investment_decision_v2/scripts/run_gate4_assessment.py \
  path/to/step3/underwriting_output_contract.json \
  --manifest ~/investment_private/gate4_private_workspace_manifest.json
```

The runner writes the S14 JSON contract and four bilingual Markdown reports
only to the private output directory. It prints no portfolio values.

## System Assessment State Machine

Apply this priority order:

1. `NOT_EVALUATED`: S13 is incomplete, stale, changed, invalid, or not
   reproducible.
2. `NOT_ELIGIBLE`: a required constraint is breached or no positive
   incremental capacity remains.
3. `REVIEW_REQUIRED`: an unresolved non-required but decision-relevant Warning
   or Missing item remains.
4. `ELIGIBLE_WITH_ESCALATION`: all required constraints pass, but a reviewed
   threshold or Gate 3 warning escalation remains active.
5. `ELIGIBLE`: all required constraints pass with positive incremental
   capacity and no unresolved review or escalation item.

`ELIGIBLE` and `ELIGIBLE_WITH_ESCALATION` mean only that the candidate can
proceed to a Partner decision under the tested policy. They are not buy/sell
instructions and do not create a system-owned position range.

## Partner Decision State Machine

The allowed Partner decisions are:

- `PENDING`
- `APPROVED`
- `MODIFIED`
- `REJECTED`
- `DEFERRED`

Keep the submitted decision and effective decision separate. An invalid
completed record is displayed as submitted but its effective decision remains
`PENDING` with `PARTNER_DECISION_BLOCKED`.

`APPROVED` and `MODIFIED` require:

- a current `ELIGIBLE` or `ELIGIBLE_WITH_ESCALATION` assessment;
- the exact current assessment hash;
- the designated Partner's name, dated timestamp, and rationale;
- a total-issuer gross-long position basis;
- a minimum and maximum range no greater than the total-issuer constraint
  ceiling; and
- exact acknowledgement of every active escalation ID.

`REJECTED` and `DEFERRED` never carry a position range. The system never
creates, modifies, or executes the Partner decision.

## Hash Boundary

The assessment-input fingerprint includes the manifest, policy, exposure or
holdings data, opportunity set, constraint inputs, freshness attestation, and
approval-policy configuration. It excludes `partner_decision` so the Partner
can bind a later decision to a stable assessment hash.

Any change to an assessment input produces a new assessment hash. A completed
decision carrying the old hash is blocked.

## Report Contract

All four reports consume one `gate4_assessment_output` object.

- One-Page: System Assessment, Partner Decision, constraint ceiling, binding
  constraint, escalations, and next action.
- Full Report: the complete constraint matrix, formula audit, assessment logic,
  approval record, and decision boundaries.
- Evidence Appendix: exact S13 hash, assessment-input fingerprint, stable Gate
  4 evidence IDs, source fields, formulas, and exact values.
- Validation Report: contract checks, reproducibility checks, Hard Stops,
  Warnings, and renderer controls.

The renderer may format and round for display but may not calculate an
assessment, ceiling, approval, or decision.

## Language and Privacy Controls

Call the S13 maximum only:

- `constraint ceiling`;
- `maximum allowed by the tested constraints`; or
- `maximum constraint-based position`.

Never call it a suggested, recommended, target, approved, or optimal position.
Only a validated Partner record may display an approved range.

Real reports remain local. Direct private PDF writes are prohibited; use the
tested sanitizer. Public HTML and PDF demos must use only
`SYNTHETIC_PUBLIC_EXAMPLE`, must say so prominently, and must keep automatic
trade execution disabled.

Build and validate the public synthetic report package with:

```bash
python3 partner-demo/investment_decision_v2/scripts/build_gate4_synthetic_demo.py
python3 partner-demo/investment_decision_v2/scripts/validate_gate4_synthetic_delivery.py \
  examples/gate4-synthetic
```

The delivery validator checks the manifest hashes, assessment contract,
automatic-trade boundary, A4 page geometry, exact one-page summary length,
bilingual content, rendered System/Partner states, and prohibited position
recommendation terms.
