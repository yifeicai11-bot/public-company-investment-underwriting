# Source Log Standard

Use this file when preparing the evidence table / source log for a public-company credit and liquidity review.

The source log is the audit trail. It should let a partner understand which public evidence supports each material conclusion and where the evidence came from.

## Table of Contents

- Minimum Coverage
- Evidence Hierarchy
- Source Log Columns
- Evidence Types
- Derived Metrics
- Confidence Standard
- Common Failures to Avoid

## Minimum Coverage

Every full review should include:

- Latest annual filing or annual report.
- Latest interim or quarterly filing when available.
- Evidence rows for each material Executive Highlight.
- Evidence rows for each Medium or High module rating.
- Evidence rows for important positive mitigants, such as cash, unused revolver, positive CFO, or no current debt.
- Missing-data rows for material information that could not be found.

For SEC companies, the source log should normally include both filing links:

- Latest 10-K / 20-F annual filing.
- Latest 10-Q / 6-K interim filing, when applicable.

## Evidence Hierarchy

Use the five external source levels in `source_policy.md`; reserve Level 0 for reviewer-owned assumptions and judgments. Source priority applies only after definition, basis, period, as-of date, unit, currency, filing version, and amendment status are reconciled. Material unresolved conflicts must appear in the validation log.

Do not rely on scraped finance websites for primary filing metrics when official filings are available.

## Source Log Columns

Use this structure unless the user requests a different table:

| Evidence ID | Source ID | Module | Metric / Claim | Class | Value / Disclosure | Unit | Period / As-of | Source Level | Publication / Retrieval | Locator | Formula / Inputs | Confidence | Validation | Link |
|---|---|---|---|---|---|---|---|---:|---|---|---|---|---|---|

Column guidance:

- Evidence ID: stable system-generated ID used by calculations and renderers.
- Source ID: stable source-registry ID.
- Module: one of the required issuer-underwriting modules or `Overall`.
- Claim / Metric: the conclusion being supported.
- Class: FACT, CALC, INFERENCE, JUDGMENT, or MISSING.
- Source: filing/report name, e.g. `FY2025 Form 10-K`.
- Period / As-of: include period start/end/type for flows and exact as-of date for point-in-time values.
- Publication / Retrieval: preserve both dates.
- Locator: note title, MD&A section, statement name, table, XBRL concept, or verified page.
- Value / Disclosure: amount, percentage, ratio, or concise paraphrase.
- Interpretation: why this evidence matters for the risk view.
- Confidence: High / Medium / Low.
- Formula / Inputs: required for CALC; include upstream evidence IDs.
- Validation: PASS, PROVISIONAL, WARNING, MISSING, or FAIL.
- Link: official filing or source URL.

## Evidence Types

Metric:

- A directly reported value such as cash, AR, current liabilities, CFO, current debt, allowance, or inventory.

Trend:

- A comparison across periods, such as AR rising from one period to another.

Disclosure:

- A filing-note or MD&A statement about liquidity, covenant compliance, customer concentration, restricted cash, or credit-loss methodology.

Derived Metric:

- A ratio or calculation made from reported numbers, such as current ratio, AR / quarterly revenue, CFO / net income, or total debt / cash.

Missing Data:

- A material item that was searched for but not located, such as AR aging or covenant headroom.

External Event:

- Public news, rating commentary, restructuring announcement, covenant waiver, debt issuance, default notice, or similar event.

## Derived Metrics

When using a derived metric:

- Show the formula or source inputs in the Value / Disclosure field.
- Use consistent units.
- Do not overstate precision.
- Explain whether the ratio is a screening indicator or a formal covenant/credit metric.

Examples:

- Current ratio = current assets / current liabilities.
- DSO = average net AR / same-period revenue x period days.
- Reported FCF = CFO - cash capex. Do not call it normalized FCF without a sourced bridge.
- Liquidity coverage = cash + short-term investments + disclosed available revolver, if revolver availability is confirmed.

## Confidence Standard

High:

- Official filing evidence directly supports the claim.
- Values are traceable to filing statements, notes, or standardized XBRL.
- The period and units are clear.

Medium:

- Evidence supports the direction, but note-level detail is missing.
- The metric is derived from public data but requires interpretation.
- The source is official, but the disclosure is not granular enough.

Low:

- Evidence is indirect, incomplete, or based on public context rather than direct financial disclosure.
- Key data is missing or inconsistent.
- The conclusion is provisional.

## Common Failures to Avoid

- Do not cite a conclusion without a source row.
- Do not cite a source row that only repeats the conclusion without evidence.
- Do not use page numbers unless they were actually verified.
- Do not mix periods without labeling them clearly.
- Do not relabel YTD as a standalone quarter.
- Do not use lease carrying values as contractual lease cash payments.
- Do not resolve material source conflicts silently.
- Do not treat missing disclosure as proof that risk is low.
- Do not imply a formal credit rating.
- Do not upload or include non-public information unless the user explicitly authorizes it.
