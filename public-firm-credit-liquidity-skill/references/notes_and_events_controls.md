# Notes and Events Controls

Read this reference before changing or independently reproducing debt, revolver,
lease, covenant, receivable, bad-debt, supplier-finance, acquisition,
amendment, restatement, or subsequent-event logic.

## Binding Statuses

Each module must return exactly one safe status:

- `VALIDATED`: required evidence was located and passed the module control.
- `MISSING`: required evidence was not located; absence is not zero.
- `NOT_APPLICABLE`: supported by an explicit disclosure or a completed event
  index review, not inferred from silence.
- `WARNING`: evidence is partial, unquantified, or requires a bridge.
- `HARD_STOP`: a known filing or event can contradict the displayed current
  state.

Warnings qualify the affected conclusion. Hard Stops block formal report
generation and produce diagnostics.

## Module Rules

### Debt

Keep carrying values, contractual principal maturities, and amendments or
waivers separate. A debt balance without a debt-note or maturity schedule is
incomplete.

### Revolver

Keep facility disclosure, commitment, borrowings, letters of credit, reserves,
reported availability, maturity, borrowing-base restrictions, and conditions
to borrowing separate. Reported availability is not covenant headroom. A
facility signal with incomplete capacity, maturity, or restriction evidence is
a `WARNING`; a completed filing scan with no facility signal may be
`NOT_APPLICABLE`.

### Leases

Keep lease-liability carrying values separate from undiscounted contractual
payments. Never use a carrying value as a liquidity use or maturity schedule.

### Covenants

Capture terms or triggers, compliance, and numerical headroom separately.
Compliance does not prove adequate headroom. Revolver availability is not
automatically covenant headroom.

### Receivables and Bad Debt

Keep net receivables, allowance, methodology, provision, write-offs, recoveries,
aging, concentration, and transfers separate. Missing allowance or activity is
never zero.

### Supplier Finance

Search both filing text and all available SEC taxonomy concepts containing
supplier-finance or supply-chain-finance semantics. Filing silence remains
`MISSING`. Use `NOT_APPLICABLE` only when the filing or a reviewer explicitly
supports it.

### Acquisitions

Reconcile the selected-period acquisition cash-flow or structured fact to the
transaction disclosure, consideration, purchase accounting, and pro forma
impact. A cash amount without a note bridge is a `WARNING`. Use
`NOT_APPLICABLE` only after both the selected filing and period-matched
structured-fact scan are complete. Keep post-period acquisitions in the
subsequent-event module until an explicit historical-to-current bridge exists.

### Amendments and Restatements

Index same-period 10-K/A and 10-Q/A filings. Administrative amendments may pass
only after their scope is reviewed. A financial restatement or non-reliance
signal blocks pre-amendment conclusions until corrected values and an old-to-new
evidence bridge are validated.

### Subsequent Events

Index every later 8-K and 8-K/A after the selected financial filing. Classify at
least debt issuance, refinancing, acquisition or disposition, repurchase,
guidance, covenant/default, bankruptcy, and non-reliance events.

Items 1.03, 2.04, and 4.02 are Hard Stop candidates because they can contradict
the displayed credit, liquidity, or financial-statement state. Other material
events remain Warnings until their effect is quantified. Never insert a
subsequent event into a historical balance without an explicit bridge.

## Evidence Contract

Every located disclosure or indexed filing must retain:

- Form, filing date, report date, accession, and source URL.
- A precise source locator and concise excerpt or event item code.
- Stable evidence ID after ingestion.
- Review status and decision impact.
- Missing information required to validate the module.

Material values at the same metric grain must pass the shared source-conflict
check. Conflicts create a Hard Stop until reconciled; source hierarchy cannot
silently override a contradictory value. A later amendment, earnings filing,
or material event makes the earlier current-state conclusion stale until the
required bridge or freshness review is complete.

The One-Page, Full Report, Evidence Appendix, and Validation Report must consume
the same validated object. Renderers must not reinterpret these statuses.
