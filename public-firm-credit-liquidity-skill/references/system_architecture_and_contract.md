# System Architecture and Output Contract

Treat this reference as binding whenever changing the public-company skill, scripts, schemas, tests, or report outputs.

## System-Wide Rule

Fix every defect in the shared component that owns it. Do not add ticker checks, company-name branches, hard-coded financial values, hard-coded conclusions, or renderer workarounds.

CROX, AAPL, PFGC, and other named companies are regression fixtures only. A change is complete only when:

1. The shared cause is corrected.
2. Regression fixtures pass.
3. An unseen-company forward test passes.
4. No company-specific workaround is present.

## Supported Universe

The initial core supports SEC-reporting, US GAAP, non-financial issuers using 10-K and 10-Q filings.

Return `SPECIALIZED_OVERLAY_REQUIRED` for:

- Banks, insurers, brokers, and other financial institutions.
- Foreign private issuers using 20-F/6-K or non-US-GAAP taxonomies.
- Any issuer whose accounting model is outside the validated core.

Do not force an unsupported issuer through the core rules. Generate diagnostics and identify the required overlay.

## Component Boundaries

### Data and Evidence Engine

`build_public_company_decision_pack.py` owns:

- SEC ingestion and company resolution.
- Period, unit, currency, taxonomy, and as-of-date normalization.
- Stable evidence and source IDs.
- Source hierarchy and conflict logging.
- Subsequent-event index review.
- The shared notes-and-events control object for debt, revolvers, leases,
  covenants, receivables, bad debt, supplier finance, acquisitions, amendments,
  restatements, and subsequent events.
- Calculation formulas and input evidence IDs.
- CFO double-counting ledger.
- Data-integrity validations and Data Gate foundation.

It must not create unsupported investment opinions.

`notes_events_controls.py` is a shared Data and Evidence Engine component. It
must remain issuer-agnostic. It may classify evidence and safe failure states,
but it must not contain ticker branches, company values, or investment views.

### Investment Analysis Engine

`build_public_company_investment_layer.py` owns:

- Investment Question.
- Key Debates.
- Decision Confidence.
- Business, earnings-quality, working-capital, liquidity, debt, lease, covenant, refinancing, and stress-test modules.
- Capital-allocation and management-guidance/subsequent-event modules.
- Public-Data FCF Underwriting Base, source/calculation validation, and FCF Normalization Status.
- Market-expectation status.
- Reverse valuation and scenario status.
- Upgrade, downgrade, and thesis-invalidation rules.
- Data Gate determination and output suppression.

It may consume only validated facts or explicitly qualified inputs.

### Rendering Engine

`render_public_company_artifacts.py` owns formatting only.

It must:

- Render One-Page and Full Report from the identical output contract.
- Display report ID, contract hash, Research Workflow Status, Public-Data Investment View, Data Gate, Decision Confidence, Valuation Status, and warnings.
- Use evidence bundles and short references in main reports; keep raw IDs in the separate Evidence Audit Appendix.
- Generate a diagnostic report instead of formal artifacts when Gate 0 or a contract failure is active.

It must not fetch data, hard-code facts, calculate ratios, select scenarios, or change a conclusion.

`build_crox_partner_ready_artifacts.py` is only a thin regression wrapper.

## Evidence Record

Every material number must store:

- `evidence_id`
- `metric_name`, value, unit, currency, scale
- period start, period end, period type, duration
- as-of date and measurement basis
- filing type and fiscal period
- source ID, level, type, name, locator, tag, and URL
- publication and retrieval dates
- FACT, CALC, INFERENCE, JUDGMENT, or MISSING
- reported/calculated status
- formula and input evidence IDs
- confidence and validation status
- subsequent-event status

Calculated values must be reproducible from their linked input IDs.

## Source Hierarchy

| Level | Source |
|---|---|
| 0 | Analyst-owned assumption or judgment; not external evidence and always requires reviewer ownership |
| 1 | Regulatory and filed company materials, including 10-K, 10-Q, filed debt agreements, and official regulatory filings |
| 2 | Official company investor materials, releases, presentations, guidance, and official transcripts |
| 3 | Partner-approved market and reference-data feeds |
| 4 | Institutional research, consensus, ratings, and specialist databases |
| 5 | Other public websites, news, summaries, and unapproved aggregators |

Do not apply priority mechanically. First reconcile definition, measurement basis, period, as-of date, unit, currency, filing version, and amendment status. Comparable conflicts must be logged. Material unresolved conflicts are Hard Stops.

An unapproved Level 5 price may support a clearly labeled demonstration observation. It cannot support an unqualified final valuation.

Public evidence entered outside the automated SEC pipeline must use the shared `external_evidence` schema. Each row needs a unique `external_key`, source level/type/name/locator, publication/retrieval/as-of dates, explicit unit and measurement basis, evidence class, and named reviewer. Downstream modules may resolve `evidence_keys` into stable IDs; they must not cite free text that bypasses the evidence registry.

## Data Gates

### Gate 0: Data Not Validated

Allow only diagnostics, missing information, and source status. Block formal conclusions, ratings, expected return, target price, and sizing.

### Gate 1: Core Data Validated

Allow preliminary screen, basic financial description, and major missing information. Block issuer-risk conclusions, valuation conclusions, expected return, and sizing.

### Gate 2: Issuer Underwriting Complete

Require business, earnings quality, working capital, cash conversion, liquidity, debt, leases, covenants, refinancing, capital allocation, management guidance/subsequent events, and initial stress work. Allow Continue Research, Watch, Stop Research, or a qualified credit-constraint conclusion.

### Gate 2.5: Valuation or Scenarios Incomplete

Issuer underwriting is complete, but the Public-Data FCF Underwriting Base, market expectations, reverse valuation, exit multiple, or implied scenario price remains unvalidated. Allow only research continuation and the unresolved valuation question. Missing probabilities alone do not block scenario-price validation; they block a formal probability-weighted outcome.

### Gate 3: Valuation and Scenarios Validated

Require a calculation-validated Public-Data FCF Underwriting Base with a separate normalization status, sourced market expectations, an analyst-owned variant perception, reverse valuation, Bear/Base/Bull assumptions, reproducible implied prices, falsification triggers, decision rules, and sensitivity analysis. Allow scenario price sensitivity, valuation range, and a public-data view for human review. Formal probability-weighted output remains null unless probability governance and the return context both pass.

Formal probability validation requires a declared method type, method-specific details, linked evidence, a rationale for each scenario weight, probabilities totaling 100%, an as-of date, an expiration/review date, review triggers, sensitivity cases, freshness review, a named reviewer, and explicit human approval. An illustrative or analyst-judgment allocation may be displayed only as non-formal context and cannot unlock expected return.

### Gate 4: Portfolio Inputs and Human Review Complete

Require target return, downside tolerance, horizon, liquidity, limits, existing exposure, opportunity cost, partner-owned assumptions, and explicit human approval. Display only the approved position range and portfolio action. Never place a trade.

#### Gate 4 Entry Contract and Freshness

Gate 4 must consume the exact shared `underwriting_output_contract.json` produced at Gate 3. It must not accept ticker-only input, rebuild issuer analysis, read legacy `step3_data.json`, change issuer conclusions, or overwrite the Gate 3 contract.

Before reading private portfolio inputs, the shared eligibility engine must verify:

- supported Gate 3 schema version
- canonical contract hash and contract-validation status
- Data Gate 3 or above
- no active Data Integrity Hard Stop
- report, financial-statement, market-price, and latest-filing dates
- explicit maximum ages for report, financial, market, and public-source checks
- a dated reviewer-owned attestation that no newer earnings filing or unreviewed material subsequent event is known
- valuation status against an explicit list of eligible statuses
- probability status, as-of date, expiration review date, freshness, and approval when formal probabilities are required
- every active issuer-level Warning is resolved or covered by an allowed, dated, reviewer-owned escalation

The eligibility policy must explicitly provide age thresholds, eligible valuation statuses, whether validated probabilities are required, and whether Warning escalation is allowed. The engine must not supply hidden defaults. A `RANGE_ONLY` valuation is eligible only when the policy explicitly permits it.

Use:

- `GATE_4_PRIVATE_INPUTS_REQUIRED` when Gate 3 is eligible but private inputs are not yet available.
- `GATE_4_BLOCKED_STALE_GATE_3` when dates, filings, subsequent events, or probability freshness require a Gate 3 update.
- `GATE_4_BLOCKED_INELIGIBLE_GATE_3` when the contract version/hash, validation, Data Gate, valuation policy, Hard Stops, or Warning governance fails.

When Gate 3 is stale or ineligible, suppress Gate 4 return, risk, sizing, and action calculations. A diagnostic may identify the contract and blocking checks, but it must not silently reuse stale scenario values. Hard Stops can never be escalated.

#### Gate 4 Private Input Boundary

Real fund policy, holdings, opportunity-set, approval, and sizing data must stay
in a local workspace outside every Git worktree. Use the schemas and empty
templates under `partner-demo/investment_decision_v2/gate4/`, initialize
`~/investment_private` with `initialize_gate4_private_workspace.py`, and run the
entry check with `run_gate4_local_entry.py`. Do not paste real portfolio data
into chat or send it to an external model/API.

The private manifest must select `EXPOSURE_ONLY`, `AGGREGATED_PORTFOLIO`, or
`FULL_HOLDINGS`. The first mode prohibits holdings; the second requires both
aggregate exposure and issuer-level position files; the third requires complete
security-level holdings and permits an optional independent exposure
reconciliation. Never infer security-level liquidity from a lower-granularity
mode. Apply the shared four-class field-governance contract and require a dated,
row-specific reviewer record for every permitted not-applicable field.

Private-input validation may return `GATE_4_INPUTS_VALIDATED`, but this means
only that the dated local bundle is complete and reconciled. Until the shared
constraint engine is implemented and run, keep System Portfolio Assessment
`NOT_EVALUATED`, Partner Decision `PENDING`, and every sizing/action field null.
The legacy `build_partner_portfolio_overlay.py` path is restricted to
`SYNTHETIC_PUBLIC_EXAMPLE` demos and must reject real inputs.

Direct private PDF writes are prohibited. A private PDF may be written only by
the local sanitizer after fixed metadata, XMP removal, attachment/action checks,
page-count preservation, secure output permissions, and post-write reopening
all pass.

## Decision Confidence

Keep Decision Confidence separate from Data Gate.

Confidence reflects:

- Data completeness and source quality.
- Validation and reproducibility.
- Assumption transparency.
- Disconfirming evidence.
- Sensitivity to uncertain inputs.

A favorable view with Low Confidence cannot use strong action language.

## Hard Stops and Warnings

Hard Stops block formal report generation but must still produce diagnostics. Examples:

- Wrong financial period or quarter/YTD mixing.
- Broken market or benchmark date alignment.
- Missing source for a material displayed number.
- Broken share-count calculation.
- Material unit mismatch.
- Unreproducible scenario price, or probabilities represented as formally validated when they do not total 100% or lack the required method controls.
- Known subsequent event contradicting the displayed current state.
- Output and validated data object disagreement.
- CFO, FCF, or liquidity double counting.

Warnings allow research to continue with prominent limitations. Examples:

- Consensus unavailable.
- Numerical covenant headroom unavailable.
- Guidance, industry, channel, peer, commitment, or legal data incomplete.
- Some subsequent-event effects remain unquantified.

## CFO and Liquidity Double Counting

CFO already includes cash interest, cash taxes, working-capital movements, and US-GAAP operating lease cash flows. Do not deduct them again in CFO-based FCF unless a sourced reversal explicitly rebuilds CFO.

If CFO is used as a source in a period model, do not list embedded items again as period uses.

Every cash-flow line must store:

- treatment
- whether embedded in CFO
- whether separately modeled
- evidence IDs
- reversal ID, when applicable
- double-count status

Historical CFO is not automatically a future liquidity source. Lease carrying values are not contractual cash-payment schedules.

## Mandatory Decision Fields

Every investment-support output must contain:

- Investment Question
- two or three Key Debates
- Data Gate
- Decision Confidence
- what is known and unknown
- what can and cannot be concluded
- evidence required next
- measurable upgrade, downgrade, and thesis-invalidation conditions, or MISSING
- Research Workflow Status and a separate Public-Data Investment View
- Public-Data FCF Underwriting Base and FCF Normalization Status
- Valuation Status and component completion statuses
- share-count basis and `CURRENT` or `PROXY` status for every per-share output
- conditional What Is Priced In
- Decision Confidence supports, constraints, evidence to increase, and events to reduce

If a system proposes a question or debate, label it `SYSTEM_PROPOSED_ANALYST_REVIEW_REQUIRED`. Never fabricate consensus; use `Not Sourced`.

## Shared Output Contract

One-Page and Full Report must consume the same versioned object. Required fields include:

- company identity and report dates
- report ID and contract hash
- Investment Question, Key Debates, gate, validation, and confidence
- Research Workflow Status, Public-Data Investment View, and conclusion boundaries
- issuer-underwriting modules
- facts, calculations, inferences, judgments, and missing information
- liquidity, credit constraint, FCF underwriting base/normalization, valuation scope, share-count basis, probability, and scenario status
- catalysts, thesis breaks, decision rules
- evidence records, source registry, Hard Stops, and Warnings

Below Gate 3, scenario implied prices and price changes must be null. At Gate 3, scenario outputs are `Implied Price` and `Price Change vs Current Price` unless all return-context fields are validated. Formal probability-weighted output remains null unless probability governance and the return context both pass. Below Gate 4, position sizing must be null and portfolio action must be Not Evaluated. A stale or ineligible Gate 3 contract must also suppress all Gate 4 calculations.

## Required Testing

Test data integrity, accounting logic, investment logic, rendering, and cross-company behavior.

Minimum company set:

- CROX regression fixture.
- AAPL for cash, buybacks, share count, and capital allocation.
- PFGC for working capital, low cash, revolver dependence, leases, and refinancing.
- At least one unseen non-financial issuer selected without matching an existing fixture.
- Forward tests should include materially different business models, such as a supplier-financed retailer and a subscription software issuer.

Tests must prove:

- No YTD fact is mislabeled as a quarter.
- LTM uses annual plus current YTD minus prior comparable YTD with one concept.
- Exact common dates and adjusted closes are used for relative return.
- No FCF or liquidity double counting.
- Unsafe outputs are suppressed by gate.
- Every displayed number resolves to a raw evidence ID through the shared contract; main reports use bundles or short aliases and the audit appendix preserves raw IDs.
- One-Page and Full Report contain no raw `EV-...` strings.
- Every per-share sensitivity discloses the share-count date, source, basis, subsequent-event status, and proxy status.
- Scenario price and priced-in FCF calculations reproduce from dated price, point-in-time market cap, share count, FCF, and analyst-owned multiple.
- One-Page and Full Report share report ID and contract hash.
- English and Chinese outputs do not contradict each other.
- No renderer or shared engine contains ticker-specific facts or conclusions.
- A foreign private issuer or financial institution produces a Gate 0 diagnostic instead of being forced through the core.
- Validated external evidence is traceable by both `external_key` and stable evidence ID; malformed rows marked validated create a Hard Stop.
