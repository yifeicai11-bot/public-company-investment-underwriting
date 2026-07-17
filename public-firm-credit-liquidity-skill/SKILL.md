---
name: public-firm-credit-liquidity
description: Use this skill to build auditable public-company issuer underwriting from public data, including evidence normalization, receivables and credit-loss risk, cash conversion, working capital, liquidity, debt, leases, covenants, refinancing, decision debates, and gated valuation/scenario support. Use it for a listed-company credit/liquidity review, investment-underwriting memo, bilingual partner output, source log, validation report, or reusable public-company research workflow.
---

# Public Firm Credit & Liquidity Research Support

## Purpose

This skill builds a reusable issuer-level public-company underwriting system. Its partner-ready product name is `Public-Data Issuer Underwriting and IC Pre-Read System - Friday V1`. It separates data and evidence, issuer underwriting, valuation/scenarios, rendering, and portfolio decisions. It is not a credit rating, complete investment-decision system, fair-value engine, or automatic buy/sell tool.

The review should identify key highlights, red flags, positive signals, missing information, and follow-up questions using public sources only. When the user or partner wants investment usefulness, the output must shorten the path from information to decision: what is binding, what is not binding, what would change the view, and what must be monitored next.

Default output should be bilingual in English and Chinese for partner-ready use. Use English first for professional finance/accounting terminology, followed by concise Chinese explanation. Do not create two completely separate reports unless requested.

For company-specific reviews, write as a direct research support output. Do not describe the company as a "sample," "test case," "baseline," "stress case," or "useful for testing" in Executive Highlights or Detailed Analysis.

Company reviews should answer: "What is happening at this company, what matters most, what evidence supports it, what decision it supports, and what should be monitored next?" They should not answer: "Why did we choose this company for the skill."

## Core Scope

Every full issuer review must cover these shared modules:

1. Business Model and Industry Structure
2. Receivables Quality and Bad Debt / Credit Loss Risk
3. Earnings Quality and Normalized Cash Flow Conversion
4. Working Capital Pressure
5. Short-Term Liquidity Sources and Uses
6. Debt, Leases, Covenants, and Near-Term Refinancing Pressure
7. Capital Allocation
8. Management Guidance and Subsequent Events
9. Company-Specific Stress Test

Receivables, bad debt, short-term liquidity, cash conversion, working capital, and refinancing remain mandatory in every complete analysis. Do not omit one because another issue appears more prominent. State `not material` with evidence when appropriate.

## Source Rules

Use public sources only unless the user explicitly provides internal materials and confirms they may be used.

Preferred public sources include annual reports, 10-K/10-Q filings, HKEX filings, earnings releases, investor presentations, company websites, publicly available rating commentary, exchange announcements, and relevant public news.

Apply the formal source hierarchy: Level 1 regulatory filings, Level 2 official company investor materials, Level 3 partner-approved market/reference feeds, Level 4 institutional research/consensus, and Level 5 other public sources. Analyst-owned assumptions use Level 0 and require a named reviewer plus linked evidence where applicable.

For source handling, read `references/source_policy.md` when preparing an evidence-backed output. For partner-ready evidence tables, read `references/source_log_standard.md`.

## Investment Decision Upgrade Rules

When the requested output is meant to support an investment judgment, read `references/investment_decision_upgrade.md` before drafting. Treat it as binding for data integrity, validation gates, memo structure, and action-language limits.

Read `references/friday_v1_output_standard.md` before creating or changing any partner-facing One-Page, Full Report, Evidence Appendix, QA Summary, output contract, or renderer. Its horizon language, FCF naming, dual statuses, valuation status, share-count proxy, priced-in, confidence, evidence-display, and portfolio-boundary rules are binding.

Read `references/system_architecture_and_contract.md` before changing any script, schema, gate, or renderer. Its system-wide applicability, supported-universe, source hierarchy, output-contract, Hard Stop, and testing requirements are binding.

Read `references/probability_and_peer_governance.md` whenever scenarios, probability-weighted return, peer valuation, or historical valuation context is requested. Its method, freshness, approval, and forced-comparison rules are binding.

When the user or partner wants the memo to help make an investment decision, read `references/investment_committee_layer.md` after the investment decision upgrade rules. Use it to structure bull/bear debate, risk review, portfolio fit, and final action view without replacing validation or valuation evidence.

When using any third-party library, GitHub skill, MCP server, market-data source, or hosted API to support the review, read `references/external_tool_policy.md`. External tools may accelerate data extraction, market data retrieval, note reading, or portfolio analytics, but they must not bypass source logging, period validation, provider labeling, or investment-gate limits.

Do not directly wrap automated ratios as an investment report. Use the layered structure:

1. Data Integrity
2. Automated Screen
3. Analyst-Validated Credit Memo
4. Investment Decision Module
5. Investment Committee Synthesis, only when decision support is requested and enough valuation/scenario context exists

If valuation, consensus, the Public-Data FCF Underwriting Base, or scenario price sensitivity is incomplete, keep the Research Workflow Status and Public-Data Investment View separate and constrain the output through the Data Gate. Do not imply a complete buy/sell/hold recommendation.

## Workflow

1. Clarify the target company, ticker, exchange, period, and desired depth if not already provided.
2. Gather public source documents for the latest annual period and, when available, the latest interim/quarterly period.
3. Build a versioned evidence object for every material metric, including a stable evidence ID, value, unit, currency, period, as-of date, measurement basis, source level/type/locator, publication and retrieval dates, formula, upstream evidence IDs, confidence, validation status, and subsequent-event status.
4. Run data-integrity validation before writing analysis: period match, instant-vs-flow, quarter derivation, balance-sheet check, cash-flow check, debt reconciliation, facility check, lease check, covenant check, source freshness, and investment gate.
5. Extract metrics and disclosures relevant to all required issuer-underwriting modules.
6. Read `references/filing_note_extraction.md` when any module is material, Medium/High, or dependent on note-level disclosure. Debt, revolver/ABL, maturity, lease, covenant, acquisition, and refinancing conclusions require note-level reading.
7. Build evidence first, then assign risk ratings. Do not choose a rating and then search for confirming evidence.
8. Compare trends over at least two periods when data is available. For working-capital metrics, use average balances and same-period flow denominators where possible.
9. Apply relevant business-model guidance from `references/sector_overlays.md` when the company's firm type is clear. If the issuer is outside the validated SEC US-GAAP non-financial core, stop at Gate 0 and generate a diagnostic naming the required overlay.
10. Assign ratings using `references/rating_boundaries.md`.
11. Add a concise Firm Type Context section explaining which overlay was applied and how it changes interpretation of the six modules.
12. Define the Investment Question before producing an investment-support conclusion. If it is not analyst-defined, write `Not Defined` and lower Decision Confidence.
13. Identify two or three Key Debates. Do not fabricate a market view; use `Not Sourced` when consensus or conventional expectations are unavailable.
14. Produce executive highlights before detailed analysis.
15. Attach stable evidence IDs and source references to every material number and claim in the contract. Use compact evidence bundles on the One-Page, short references in the Full Report, and raw IDs only in the Evidence Audit Appendix.
16. State Data Gate and Decision Confidence separately. The gate controls which outputs are allowed; confidence describes reliability within those allowed outputs.
17. For investment-support memos, run the Investment Committee Layer only after valuation/scenario work and before a human-owned action view.
18. End with measurable upgrade, downgrade, and thesis-invalidation conditions. Mark them `MISSING` when the analyst has not defined them.

When working with SEC-reporting companies, use the generic decision-support builder when available:

`partner-demo/investment_decision_v2/scripts/build_public_company_decision_pack.py "<ticker or company name>"`

This creates a period-aware normalized data table, validation report, and investment-support data pack. Use `scripts/sec_metric_pack.py <ticker>` only as a lighter starting point or fallback. In both cases, read the relevant filing notes for debt maturity, facility availability, receivable aging, covenant, lease, acquisition, or disclosure nuance when those issues are material.

When the user wants Step 3 investment decision support, run the generic investment-layer builder after or instead of the Step 2 command:

`partner-demo/investment_decision_v2/scripts/build_public_company_investment_layer.py "<ticker or company name>"`

This rebuilds the data/evidence pack, adds dated public market observations, trailing valuation observations, issuer-underwriting status, Investment Question, Key Debates, Decision Confidence, partner input templates, and the shared versioned output contract.

In public-data-only mode, do not auto-create scenario probabilities, exit multiples, formal targets, or expected returns from historical growth, trailing multiples, leverage, price momentum, or 52-week range position. Without validated analyst inputs for the Public-Data FCF Underwriting Base, valuation, and scenarios, stop at Gate 1 or Gate 2.5. Validated scenario implied prices may reach Gate 3 without probabilities. Without a complete valuation horizon, label percentages `Price Change vs Current Price`; formal probability-weighted output remains null.

To supply analyst-owned assumptions, use:

`partner-demo/investment_decision_v2/scripts/build_public_company_investment_layer.py "<ticker>" --research-input "<validated input json>"`

Start from the generated `analyst_input_template.json`. Scenario implied prices are allowed only when the FCF underwriting base, valuation method, Bear/Base/Bull inputs, sensitivity, falsification triggers, and reviewer ownership pass Gate 3. Formal return language additionally requires a target date, holding period, metric period, dividend assumption, share-count basis, validated probability method, linked evidence, review dates, sensitivity, freshness, and explicit human approval.

Use `external_evidence` for public facts that are not already extracted from SEC XBRL, such as guidance, investor-presentation details, consensus, covenant terms, and industry evidence. Give each item a unique `external_key`, full source hierarchy metadata, as-of/publication/retrieval dates, source locator, and reviewer. Issuer modules and Key Debates may reference `evidence_keys`; the engine resolves them into stable evidence IDs.

When partner/fund-specific context is available, run the Step 4 portfolio overlay:

`partner-demo/investment_decision_v2/scripts/build_partner_portfolio_overlay.py "<ticker or company name>" --overlay "<overlay json or csv>"`

The overlay may run only after Gate 3. It combines validated underwriting with target return, downside tolerance, holding period, exposure, limits, opportunity cost, and partner-owned assumptions. Illustrative data can demonstrate the template but cannot unlock Gate 4. Portfolio action and position range may appear only when explicitly human-approved and must never trigger a trade.

Do not tune the Step 3 builder to a single regression company. PFGC may be used to catch regressions, but the rules must remain company-agnostic and usable for any SEC-reporting public company resolved from a ticker or company name.

If a company-specific regression script exists in `partner-demo/investment_decision_v2/scripts/`, run it before using that company as a partner demo. For PFGC, run `build_pfgc_step2_dataset.py` and inspect the validation report before drafting.

## Blind Review Mode

When the target company is not pre-classified by the user:

- Start neutral. Do not assume the company is low-risk, high-risk, receivables-driven, debt-driven, or a testing example.
- Identify the primary risk drivers from evidence across the six modules.
- If a module is not material, say so briefly and explain why.
- Do not force red flags into every module.
- Highlight the two or three most decision-relevant issues, not every metric extracted.
- Mention "sample" or "testing" only in separate validation notes, never in the partner-facing company review.
- If the company was selected through random screening or validation, keep that context outside the company review file. The company review itself should read as if the partner directly asked for that company.

## Company Review Voice

Use direct, decision-useful language:

- Good: "Near-term liquidity does not appear to be the base-case binding constraint after considering disclosed ABL excess availability, current lease obligations, and covenant compliance."
- Good: "Receivables require monitoring because AR increased faster than revenue and represented a high percentage of quarterly sales."
- Good: "This remains Watch / Need More Work because valuation, consensus, and downside scenario work are not yet complete."
- Avoid: "This is a good company for testing the receivables module."
- Avoid: "This sample shows how the framework handles refinancing risk."
- Avoid: "CFO/net income is strong" when the numerator and denominator use different periods.
- Avoid: "Current debt is zero, so near-term obligations are low" without checking leases, interest, and committed payments.

## Output Order

Always structure the output in this order unless the user requests another format:

1. Decision Strip: Research Workflow Status, Public-Data Investment View, Data Gate, Decision Confidence, and Valuation Status
2. Investment Question
3. What Can and Cannot Be Concluded
4. Key Debates
5. Firm Type Context
6. Issuer Underwriting by Module
7. What Is Priced In, valuation scope, share-count basis, and Scenario Price Sensitivity, only when allowed by the gate
8. Upgrade, Downgrade, and Thesis-Invalidation Rules
9. Source Log / Evidence Table
10. Missing Evidence and Limitations

For exact output templates, read `references/output_templates.md`.

For partner-ready concise outputs, create a one-page summary using `references/one_page_partner_summary.md`. If a full review is also requested, place the one-page summary before the full memo.

For sector or firm-type nuance, read `references/sector_overlays.md` after the core review is drafted. Use overlays to adjust interpretation and follow-up questions, not to override evidence. In partner-ready outputs, make the overlay visible through a short Firm Type Context section instead of leaving it implicit.

## Bilingual Output Guidance

For partner-ready outputs:

- Write section headings in English with Chinese in parentheses where helpful.
- Provide Executive Highlights in both English and Chinese.
- Provide Firm Type Context in both English and Chinese when the business model is clear.
- Provide Risk Rating Summary with English module names and concise Chinese explanations.
- In Detailed Analysis, use English labels and add a Chinese interpretation after each module.
- Keep Source Log source names and filing references in English, but include interpretation in English or bilingual form where space allows.
- Provide Follow-Up Questions in English and Chinese.

## Follow-Up Question Purpose

Follow-up questions are not extra work for the partner. They clarify what public data cannot prove and turn uncertainty into specific diligence actions. Use them to show which assumptions should be verified with management, internal data, broker materials, industry context, or later filings.

## Rating Guidance

Use Low / Medium / High ratings for each risk module. Do not imply a formal external credit rating.

For detailed indicators and red-flag logic, read `references/risk_framework.md`. For Low / Medium / High boundaries and confidence discipline, read `references/rating_boundaries.md`.

Use this sequence:

1. Evidence
2. Direction of change
3. Materiality
4. Possible benign explanations
5. Possible adverse explanations
6. Business-model interpretation
7. Risk level
8. Monitoring trigger

Use confidence levels:

- High: direct filing data supports the conclusion across multiple periods.
- Medium: data supports the direction, but some context or granularity is missing.
- Low: conclusion is based on limited disclosure, partial data, or indirect evidence.

## Guardrails

- Do not use non-public or confidential information unless explicitly authorized by the user.
- Do not upload sensitive client, fund, trading, or position data to external services.
- Do not fabricate metrics, page references, or source links.
- Do not let third-party tools, external skills, or hosted APIs become the unvalidated source of investment conclusions. Treat their outputs as inputs that must be reconciled, labeled, and source-checked.
- Do not make a buy/sell/hold recommendation from a credit screen. If the user explicitly requests a full investment memo, valuation, consensus, scenarios, catalysts, and risk/reward must be completed and clearly sourced before any action implication.
- Do not present the output as a complete credit rating model.
- If data is unavailable, say so and explain what should be requested or monitored.
- Do not mix quarter, YTD, annual, or LTM flow metrics in one ratio. If a ratio cannot pass period validation, block it and show the missing or mismatched fields.
- Do not relabel a YTD cash-flow fact as a standalone quarter when no quarter fact exists. Derive a quarter only from current YTD minus the prior same-fiscal-year YTD and retain both evidence IDs.
- Do not treat current lease liability carrying value as the contractual cash-payment schedule.
- Do not deduct cash interest, cash taxes, working-capital movements, or operating lease cash flows a second time from CFO-based FCF unless an explicit sourced reversal rebuilds CFO.
- Do not let a renderer contain company facts, investment assumptions, or calculations. One-Page and Full Report must render the same validated output contract.
- Do not use expected return, total return, annualized return, twelve-month return, or target price as formal labels without a complete validated return context.
- Do not show raw `EV-...` identifiers in the One-Page or Full Report. Preserve them in the machine-readable contract and Evidence Audit Appendix.
