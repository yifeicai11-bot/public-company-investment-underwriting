# Source Policy

## Public Sources

Use public information such as:

- Annual reports and audited financial statements
- 10-K, 10-Q, 20-F, 6-K, and other exchange filings
- HKEX filings and announcements
- Earnings releases and investor presentations
- Company website disclosures
- Public prospectuses or offering documents
- Publicly available rating agency commentary
- Public news from credible sources

## Evidence Standard

For each material conclusion or number, record:

- Source name
- Source type
- Filing/report date
- Reporting period
- Section, note, table, or page if available
- Extracted metric or paraphrased disclosure
- Interpretation
- Confidence level
- URL or file reference
- Stable source and evidence IDs
- Publication, retrieval, and as-of dates
- Evidence class: FACT, CALC, INFERENCE, JUDGMENT, or MISSING
- Formula and input evidence IDs for calculations

For user-ready evidence tables, follow the detailed structure in `source_log_standard.md`.

## Source Hierarchy

Use these levels:

0. Analyst-owned assumption or judgment. This is not an external source and requires reviewer ownership plus linked evidence where applicable.
1. Primary regulatory and filed company materials.
2. Official company investor materials.
3. User-approved market and reference-data feeds.
4. Institutional third-party research, consensus, and ratings.
5. Other public websites, news, summaries, and unapproved aggregators.

Do not let a higher-priority source mechanically override a lower-priority value until metric definition, measurement basis, period, as-of date, unit, currency, filing version, and amendment status are comparable. Log material conflicts instead of silently resolving them.

Use presentations for management framing and adjusted measures, but reconcile filing-defined financial values to Level 1 sources. Use a dated Level 3 feed for final market-price work. An unapproved Level 5 feed may support a labeled demonstration observation only.

For manually entered public evidence, use the shared `external_evidence` object with a unique `external_key`. Include metric/value/unit, measurement basis, period or as-of date, source level/type/name/locator/URL, publication and retrieval dates, evidence class, confidence, and reviewer. A downstream conclusion must resolve the key into a stable evidence ID before it is treated as validated.

Use news as supporting context, not as the sole basis for a financial-risk conclusion, unless the news itself reports a specific event such as a default, restatement, covenant breach, restructuring, fraud allegation, bankruptcy filing, or rating downgrade.

## Missing Data

If a metric is not disclosed, do not estimate it unless the formula is straightforward and required inputs are available. Mark it as unavailable and add a follow-up question.

## Confidentiality

If the user provides internal materials, ask whether the material may be used and whether it must be anonymized. Use the minimum necessary information. Do not mix internal data into a reusable public example unless the user explicitly authorizes it.
