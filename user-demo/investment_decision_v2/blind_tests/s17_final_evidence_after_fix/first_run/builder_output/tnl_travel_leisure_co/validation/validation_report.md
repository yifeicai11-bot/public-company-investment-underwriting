# Travel & Leisure Co. (TNL) Validation Report

Data Gate: **Gate 1 - Core financial data validated**

| ID | Result | Class | Severity | Evidence | Remediation |
|---|---:|---:|---:|---|---|
| P0-supported-universe | PASS | INFO | Critical | SEC 10-K/10-Q, US GAAP, non-financial public-company core is supported. | Apply specialized overlays if the issuer's reporting model changes. |
| P0-current-financial-filing-selection | PASS | INFO | Critical | Selected 10-Q period 2026-06-30, filed 2026-07-22; available candidates: 10-Q period 2026-06-30, filed 2026-07-22, 10-K period 2025-12-31, filed 2026-02-18. | Re-run the selector after each new 10-Q or 10-K and investigate same-period amended filings separately. |
| P1-note-debt | MISSING | WARNING | High | A complete debt balance and note package was not located; absence is not treated as zero debt. | Debt carrying value; Contractual maturity schedule |
| P1-note-revolver | WARNING | WARNING | High | A revolver or credit-facility signal was located, but commitment, usage or availability, maturity, or restriction evidence is incomplete. | Borrowing-base, reserve, or borrowing-condition detail |
| P1-note-leases | WARNING | WARNING | High | Lease evidence is partial; carrying values must not be presented as contractual cash payments. | Lease carrying value |
| P1-note-covenants | WARNING | WARNING | High | Covenant compliance language was located without complete numerical headroom; compliance is not treated as adequate headroom. | Numerical headroom or availability |
| P1-note-receivables | MISSING | WARNING | High | Receivable balance or note evidence was not established; the module remains missing. | Net receivable balance |
| P1-note-bad-debt | WARNING | WARNING | High | Bad-debt evidence is partial; allowance, methodology, and activity must remain separately identified. | Allowance balance |
| P1-note-supplier-finance | MISSING | WARNING | High | No supplier-finance disclosure was located; silence is not treated as NOT_APPLICABLE. | Supplier-finance program disclosure; Period-matched supplier-finance obligation |
| P1-note-acquisitions | PASS | INFO | Info | Period-matched acquisition amount, transaction terms, and acquisition-accounting disclosure were located. | Preserve the source and rerun after the next filing. |
| P0-filing-amendment-review | NOT_APPLICABLE | INFO | Info | No later amendment for the selected financial period was listed in SEC submissions. | Preserve the source and rerun after the next filing. |
| P0-restatement-review | NOT_APPLICABLE | INFO | Info | No high-confidence restatement, non-reliance, or prior-period revision signal was identified in the reviewed filing set. | Preserve the source and rerun after the next filing. |
| P1-subsequent-event-review | PASS | INFO | Info | No later 8-K or 8-K/A was listed after the selected financial filing as of the index review date. | Preserve the source and rerun after the next filing. |
| P0-fiscal-calendar-control | PASS | INFO | Critical | Validated fiscal-year context: CALENDAR_YEAR, DATE_BASED, 365 days. | Re-evaluate the profile after every annual filing or restatement. |
| P0-instant-flow-period-control | PASS | INFO | Critical | Every selected instant, quarter, YTD, derived-quarter, and FY row has a compatible XBRL context and duration. | Keep the shared selector as the only financial-fact ingestion path. |
| P0-unit-currency-control | PASS | INFO | Critical | All selected financial facts use validated semantic units and one reporting currency (USD); share count uses shares. | Require explicit conversion evidence before combining another currency. |
| P0-share-count-control | PASS | INFO | Critical | Point-in-time shares were selected as of 2026-06-30 from a filing published 2026-07-22. | Re-select shares against the exact market-price date before valuation. |
| P0-cash-capex-component-coverage | PASS | INFO | Critical | latest_ytd_capex uses compatible reported components: property_plant_equipment; aggregate and component paths are mutually exclusive, and noncash incurred-but-unpaid capex is excluded. | Re-run component selection after every new filing and preserve every selected component as evidence. |
| P0-ltm-construction-control | PASS | INFO | Critical | Validated LTM construction is available for: capex, cfo, net_income, revenue. | Keep annual fallback clearly labeled for metrics that do not pass LTM construction. |
| P0-missing-xbrl-safe-handling | MISSING | WARNING | High | Required selections remain missing or incompatible: accounts_receivable_net, current_assets, current_liabilities; none was assumed to be zero. | Inspect the filing taxonomy, statement table, and company-specific extension tags before analyst validation. |
| P0-negative-denominator-control | PASS | INFO | High | No calculated working-capital ratio used a zero, negative, missing, or non-finite denominator. | Apply the same shared ratio control to every future denominator-based metric. |
| P0-instant-balance-semantic-check | PASS | INFO | Critical | No nonnegative balance-sheet metric uses a negative value or IncreaseDecrease cash-flow concept. | Keep this validation active for every supported issuer. |
| P0-balance-sheet-check | PASS | INFO | Critical | Assets $6,896.0m; liabilities + equity $6,897.0m. | Investigate tag selection or noncontrolling-interest equity if fail. |
| P0-period-mismatch-block | PASS | INFO | Critical | Incompatible inputs were detected and not combined: quarter net income 2026-04-01 to 2026-06-30; YTD CFO 2026-01-01 to 2026-06-30. | Continue to use YTD/YTD, quarter/quarter, or validated derived-quarter metrics only. |
| P0-cash-definition-check | PASS | INFO | High | Cash $282.0m; cash + restricted cash $471.0m. | Use unrestricted cash for liquidity unless restricted cash is verified usable. |
| P0-fcf-classification | PASS | INFO | High | YTD FCF tagged as YTD. | Show period type in memo. |
| P0-quarter-fcf-check | PASS | INFO | High | Latest-quarter FCF is tagged as derived-quarter. | Do not annualize mechanically. |
| P0-working-capital-opening-balance-alignment | PASS | INFO | Critical | Expected opening balance date 2026-03-31; extracted dates 2026-03-31. | Use the balance sheet dated one day before the quarter starts before calculating working-capital days. |
| P0-working-capital-days | PASS | INFO | Medium | At least one average-balance working-capital day metric calculated. | Add 8-quarter trend before final memo. |
| P1-working-capital-component-coverage | PROVISIONAL | WARNING | High | Available components: DIO; missing pending classification: DSO, DPO, CCC. No absent component is assumed to be zero. | Review the business model and filing definitions, then classify each unavailable component as NOT_APPLICABLE or MISSING before final underwriting. |
| P1-ap-definition-for-dpo | PROVISIONAL | WARNING | High | Accounts payable is disclosed through a composite payable/accrual concept; DPO and CCC are suppressed. | Source a trade-payables-only balance before calculating DPO or CCC. |
| P0-current-debt-vs-lease-check | MISSING | WARNING | High | A standardized current-debt value was not identified; absence of a tag is not treated as zero. | Inspect the balance sheet and debt note before stating that current debt is zero. |
| P1-facility-note-check | PROVISIONAL | WARNING | High | Facility/credit agreement snippet found, but not fully parsed. | Read debt note and extract commitment, availability, LC, reserves, maturity, borrowing base. |
| P1-covenant-check | PROVISIONAL | WARNING | High | Covenant-related snippet found, but trigger/headroom not fully parsed. | Extract trigger, headroom, compliance, and springing conditions. |
| P2-investment-action-gate | BLOCKED | WARNING | High | This generic data pack does not source consensus, peer valuation, target price, normalized EBITDA, or scenario return. | Add valuation, earnings quality, scenario, catalyst, and risk/reward layers before Buy/Sell/Hold. |
| P0-calculation-unit-currency-lineage | PASS | INFO | Critical | Every calculated metric preserves a consistent monetary currency across its linked input evidence. | Retain linked input evidence for every future calculation. |
| P0-calculation-lineage | PASS | INFO | Critical | Every calculated row has an explicit formula and upstream evidence IDs. | Retain this check for every new calculation module. |
| P0-cash-flow-double-count-ledger | PASS | INFO | Critical | No line is both embedded in CFO and separately modeled without an explicit reversal. | Keep every future source/use line in the shared cash-flow ledger. |
