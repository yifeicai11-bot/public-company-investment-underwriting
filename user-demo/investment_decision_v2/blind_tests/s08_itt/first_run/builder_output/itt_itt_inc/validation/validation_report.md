# ITT INC. (ITT) Validation Report

Data Gate: **Gate 1 - Core financial data validated**

| ID | Result | Class | Severity | Evidence | Remediation |
|---|---:|---:|---:|---|---|
| P0-supported-universe | PASS | INFO | Critical | SEC 10-K/10-Q, US GAAP, non-financial public-company core is supported. | Apply specialized overlays if the issuer's reporting model changes. |
| P1-note-debt | PASS | INFO | Info | Debt balance, note disclosure, and maturity language were located. | Preserve the source and rerun after the next filing. |
| P1-note-leases | WARNING | WARNING | High | Lease evidence is partial; carrying values must not be presented as contractual cash payments. | Undiscounted contractual payment schedule |
| P1-note-covenants | WARNING | WARNING | High | Covenant compliance language was located without complete numerical headroom; compliance is not treated as adequate headroom. | Compliance statement; Numerical headroom or availability |
| P1-note-receivables | PASS | INFO | Info | Receivable balance, note disclosure, and at least one risk-detail disclosure were located. | Preserve the source and rerun after the next filing. |
| P1-note-bad-debt | PASS | INFO | Info | Allowance balance, credit-loss methodology, and provision/write-off activity were located. | Preserve the source and rerun after the next filing. |
| P1-note-supplier-finance | MISSING | WARNING | High | No supplier-finance disclosure was located; silence is not treated as NOT_APPLICABLE. | Supplier-finance program disclosure; Period-matched supplier-finance obligation |
| P0-filing-amendment-review | NOT_APPLICABLE | INFO | Info | No later amendment for the selected financial period was listed in SEC submissions. | Preserve the source and rerun after the next filing. |
| P0-restatement-review | NOT_APPLICABLE | INFO | Info | No high-confidence restatement, non-reliance, or prior-period revision signal was identified in the reviewed filing set. | Preserve the source and rerun after the next filing. |
| P1-subsequent-event-review | WARNING | WARNING | High | Later filings may change debt, liquidity, acquisition, repurchase, guidance, or other current-state conclusions and require an explicit bridge. | Quantified bridge from historical balances to each material subsequent event |
| P0-fiscal-calendar-control | PASS | INFO | Critical | Validated fiscal-year context: CALENDAR_YEAR, DATE_BASED, 365 days. | Re-evaluate the profile after every annual filing or restatement. |
| P0-instant-flow-period-control | PASS | INFO | Critical | Every selected instant, quarter, YTD, derived-quarter, and FY row has a compatible XBRL context and duration. | Keep the shared selector as the only financial-fact ingestion path. |
| P0-unit-currency-control | PASS | INFO | Critical | All selected financial facts use validated semantic units and one reporting currency (USD); share count uses shares. | Require explicit conversion evidence before combining another currency. |
| P0-share-count-control | PASS | INFO | Critical | Point-in-time shares were selected as of 2026-05-04 from a filing published 2026-05-06. | Re-select shares against the exact market-price date before valuation. |
| P0-ltm-construction-control | PASS | INFO | Critical | Validated LTM construction is available for: capex, cfo, net_income, revenue. | Keep annual fallback clearly labeled for metrics that do not pass LTM construction. |
| P0-missing-xbrl-safe-handling | PASS | INFO | High | Required shared selections were found and no missing XBRL fact was converted to zero. | Retain explicit MISSING status for optional or future metrics. |
| P0-negative-denominator-control | PASS | INFO | High | No calculated working-capital ratio used a zero, negative, missing, or non-finite denominator. | Apply the same shared ratio control to every future denominator-based metric. |
| P0-instant-balance-semantic-check | PASS | INFO | Critical | No nonnegative balance-sheet metric uses a negative value or IncreaseDecrease cash-flow concept. | Keep this validation active for every supported issuer. |
| P0-balance-sheet-check | PASS | INFO | Critical | Assets $11,131.6m; liabilities + equity $11,123.9m. | Investigate tag selection or noncontrolling-interest equity if fail. |
| P0-period-mismatch-block | PASS | INFO | Critical | No quarter/YTD mixed-flow ratio was generated. | Keep validation before memo drafting. |
| P0-cash-definition-check | PASS | INFO | High | Cash $600.8m; cash + restricted cash $602.2m. | Use unrestricted cash for liquidity unless restricted cash is verified usable. |
| P0-quarter-fcf-check | PASS | INFO | High | Latest-quarter FCF is tagged as quarter. | Do not annualize mechanically. |
| P0-working-capital-opening-balance-alignment | PASS | INFO | Critical | Expected opening balance date 2025-12-31; extracted dates 2025-12-31. | Use the balance sheet dated one day before the quarter starts before calculating working-capital days. |
| P0-working-capital-days | PASS | INFO | Medium | At least one average-balance working-capital day metric calculated. | Add 8-quarter trend before final memo. |
| P1-working-capital-component-coverage | PASS | INFO | High | DSO, DIO, DPO, and CCC are all available; no absent component was assumed to be zero. | Retain business-model and note-definition review before peer comparison. |
| P1-ap-definition-for-dpo | PASS | INFO | High | Current and opening accounts-payable balances use trade-compatible concepts. | Retain note-level definition review for material peer comparisons. |
| P0-current-debt-vs-lease-check | PASS | INFO | Medium | Current debt $477.3m; current leases $34.9m. | Still include cash interest and capex. |
| P1-facility-note-check | PROVISIONAL | WARNING | High | Facility/credit agreement snippet found, but not fully parsed. | Read debt note and extract commitment, availability, LC, reserves, maturity, borrowing base. |
| P1-covenant-check | PROVISIONAL | WARNING | High | Covenant-related snippet found, but trigger/headroom not fully parsed. | Extract trigger, headroom, compliance, and springing conditions. |
| P2-investment-action-gate | BLOCKED | WARNING | High | This generic data pack does not source consensus, peer valuation, target price, normalized EBITDA, or scenario return. | Add valuation, earnings quality, scenario, catalyst, and risk/reward layers before Buy/Sell/Hold. |
| P0-calculation-unit-currency-lineage | PASS | INFO | Critical | Every calculated metric preserves a consistent monetary currency across its linked input evidence. | Retain linked input evidence for every future calculation. |
| P0-calculation-lineage | PASS | INFO | Critical | Every calculated row has an explicit formula and upstream evidence IDs. | Retain this check for every new calculation module. |
| P0-cash-flow-double-count-ledger | PASS | INFO | Critical | No line is both embedded in CFO and separately modeled without an explicit reversal. | Keep every future source/use line in the shared cash-flow ledger. |
