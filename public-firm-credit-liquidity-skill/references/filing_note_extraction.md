# Filing Note Extraction Checklist

Use this file after the initial metric pack or financial-statement scan. The goal is to capture the note disclosures that explain whether a metric is benign timing noise or a real credit/liquidity issue.

## Table of Contents

- When Note Extraction Is Mandatory
- Filing Sections to Check
- Search Terms
- Module-Specific Checklist
- What to Capture
- Missing Disclosure Handling

## When Note Extraction Is Mandatory

Read filing notes, MD&A, and liquidity sections when any of these apply:

- AR is material, rising faster than revenue, or above roughly 35% of quarterly revenue.
- Allowance, write-offs, or provision data is missing while AR is material.
- Cash declines materially or cash coverage of current liabilities is weak.
- CFO is negative, materially below net income, or explained by working capital.
- Inventory, contract assets, or payables move materially.
- Current debt, long-term debt, interest expense, or refinancing risk is material.
- The company discloses restricted cash, factoring, securitization, revolving credit, covenant, default, waiver, going-concern, or subsequent-event language.
- The initial rating would otherwise be Medium or High.

If no note extraction is performed for a material module, mark confidence no higher than Medium and state what note still needs to be checked.

## Filing Sections to Check

For SEC issuers, prioritize:

- Consolidated balance sheet
- Consolidated statement of operations
- Consolidated cash flow statement
- Notes to financial statements
- MD&A, especially Liquidity and Capital Resources
- Revenue recognition and contract balances
- Accounts receivable / credit losses
- Inventory
- Debt / borrowings / credit facilities
- Leases
- Commitments and contingencies
- Concentration of credit risk
- Subsequent events
- Risk factors if liquidity, financing, customer, or supplier issues are material

For non-US public issuers, use the equivalent annual report, interim report, notes, management discussion, exchange announcements, and audited statements.

## Search Terms

Use targeted search terms in filings:

- Receivables: `accounts receivable`, `trade receivables`, `contract assets`, `unbilled`, `billed`, `days sales outstanding`, `DSO`, `past due`, `aging`, `customer concentration`, `credit risk`
- Bad debt: `allowance`, `doubtful`, `credit losses`, `expected credit loss`, `write-off`, `provision`, `impairment`, `CECL`
- Liquidity: `liquidity`, `working capital`, `cash requirements`, `restricted cash`, `available liquidity`, `capital resources`, `revolver`, `credit facility`
- Cash conversion: `operating cash flow`, `cash provided by operating activities`, `cash used in operating activities`, `changes in working capital`
- Working capital: `inventory`, `obsolete`, `slow-moving`, `markdown`, `accounts payable`, `supplier`, `contract liabilities`, `deferred revenue`
- Debt/refinancing: `maturity`, `principal payments`, `covenant`, `default`, `waiver`, `amendment`, `refinancing`, `convertible`, `notes payable`, `interest rate`, `SOFR`, `LIBOR`
- Severe stress: `going concern`, `substantial doubt`, `material uncertainty`, `unable to`, `breach`, `forbearance`, `restructuring`

## Module-Specific Checklist

### Receivables Quality

Extract:

- Gross AR and net AR when available.
- Allowance or ECL deducted from AR.
- AR aging or past-due buckets.
- Billed vs unbilled receivables or contract assets.
- Customer concentration and major customer exposure.
- Factoring, securitization, or sale of receivables.
- Any extended payment terms or collection issues.

Interpretation focus:

- Is AR growth explained by revenue growth, billing timing, seasonality, or customer mix?
- Is AR concentrated in a few customers?
- Are unbilled receivables or contract assets significant?

### Bad Debt / Credit Loss Risk

Extract:

- Beginning allowance, provisions, write-offs, recoveries, ending allowance.
- Bad debt expense or credit-loss expense.
- Methodology changes, macro assumptions, and customer-risk commentary.
- Any allowance release or reserve reduction.

Interpretation focus:

- Is allowance coverage direction consistent with AR quality?
- Are write-offs or provisions rising faster than revenue or AR?
- Is reserve release improving earnings while collection risk worsens?

### Short-Term Liquidity

Extract:

- Cash, restricted cash, short-term investments, and availability restrictions.
- Current assets, current liabilities, working capital.
- Current debt and short-term borrowings.
- Revolver availability and borrowing base limitations.
- MD&A liquidity commentary and expected cash needs.

Interpretation focus:

- Which liquidity sources are truly available?
- Does the company depend on refinancing, customer collections, or external capital?
- Are restrictions, covenants, or borrowing-base mechanics limiting access?

### Cash Flow Conversion

Extract:

- CFO, capex, and free cash flow.
- Working-capital adjustments in the cash flow statement.
- Management explanation for cash flow changes.
- One-time items or timing explanations.

Interpretation focus:

- Is weak CFO caused by AR, inventory, payables, or one-time items?
- Is the cash-flow gap temporary or recurring?
- Does cash conversion support debt service and operations?

### Working Capital Pressure

Extract:

- AR, inventory, contract assets, payables, accrued expenses, deferred revenue or contract liabilities.
- Inventory obsolescence, reserves, markdowns, or slow-moving inventory.
- Supplier financing, payables extension, or payment delay language.
- Working-capital discussion in MD&A.

Interpretation focus:

- Is growth being funded by working-capital build?
- Is cash preserved by stretching payables?
- Are inventory or contract assets at risk of delayed conversion?

### Near-Term Debt / Refinancing Pressure

Extract:

- Debt schedule by maturity year.
- Current portion of long-term debt and short-term borrowings.
- Revolver size, drawn amount, unused capacity, expiration date.
- Interest rates, floating-rate exposure, and interest expense.
- Covenant requirements and compliance/headroom.
- Defaults, waivers, amendments, refinancing plans, and subsequent debt events.

Interpretation focus:

- Are 12-24 month maturities covered by cash, CFO, and committed availability?
- Could covenant pressure restrict liquidity?
- Does the company need favorable market access to avoid stress?

## What to Capture

For every material note disclosure, capture:

- Filing name and form.
- Filing date and period end.
- Note or section title.
- Table name when applicable.
- Metric, amount, unit, and period.
- Short paraphrase of the disclosure.
- Why the disclosure changes or supports the risk view.
- Link to filing or source.

Avoid quoting long passages. Use concise paraphrase unless a short exact phrase is necessary.

## Missing Disclosure Handling

If a material detail is missing:

- Do not fill the gap with speculation.
- Mark the item as not disclosed or not found in reviewed public filings.
- Lower confidence if the missing detail affects the conclusion.
- Add a follow-up question that asks for the specific missing document or disclosure.

Examples:

- "AR aging was not located in the reviewed public filings; confidence on receivables quality is Medium."
- "Covenant headroom was not disclosed in the extracted data; refinancing pressure should be treated as provisional until the debt note is reviewed."

For executable classification, amendment/restatement handling, supplier-finance
silence, and subsequent-event Hard Stops, apply
`references/notes_and_events_controls.md`. This checklist identifies what to
read; that reference controls how the result is stored and gated.
