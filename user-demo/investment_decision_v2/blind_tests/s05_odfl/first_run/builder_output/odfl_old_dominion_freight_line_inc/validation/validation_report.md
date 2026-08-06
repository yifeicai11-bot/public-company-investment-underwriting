# OLD DOMINION FREIGHT LINE, INC. (ODFL) Validation Report

Data Gate: **Gate 1 - Core financial data validated**

| ID | Result | Class | Severity | Evidence | Remediation |
|---|---:|---:|---:|---|---|
| P0-supported-universe | PASS | INFO | Critical | SEC 10-K/10-Q, US GAAP, non-financial public-company core is supported. | Apply specialized overlays if the issuer's reporting model changes. |
| P0-instant-balance-semantic-check | PASS | INFO | Critical | No nonnegative balance-sheet metric uses a negative value or IncreaseDecrease cash-flow concept. | Keep this validation active for every supported issuer. |
| P0-balance-sheet-check | PASS | INFO | Critical | Assets $5,656.9m; liabilities + equity $5,656.9m. | Investigate tag selection or noncontrolling-interest equity if fail. |
| P0-period-mismatch-block | PASS | INFO | Critical | No quarter/YTD mixed-flow ratio was generated. | Keep validation before memo drafting. |
| P0-cash-definition-check | PASS | INFO | High | Cash $288.1m; cash + restricted cash $288.1m. | Use unrestricted cash for liquidity unless restricted cash is verified usable. |
| P0-quarter-fcf-check | PASS | INFO | High | Latest-quarter FCF is tagged as quarter. | Do not annualize mechanically. |
| P0-working-capital-opening-balance-alignment | PASS | INFO | Critical | Expected opening balance date 2025-12-31; extracted dates 2025-12-31. | Use the balance sheet dated one day before the quarter starts before calculating working-capital days. |
| P0-working-capital-days | PASS | INFO | Medium | At least one average-balance working-capital day metric calculated. | Add 8-quarter trend before final memo. |
| P1-ap-definition-for-dpo | PASS | INFO | High | Current and opening accounts-payable balances use trade-compatible concepts. | Retain note-level definition review for material peer comparisons. |
| P0-current-debt-vs-lease-check | MISSING | WARNING | Medium | Current debt is $20.0m, but standardized current lease tags were not found. | Inspect lease note and commitments before final memo. |
| P1-facility-note-check | PROVISIONAL | WARNING | High | Facility/credit agreement snippet found, but not fully parsed. | Read debt note and extract commitment, availability, LC, reserves, maturity, borrowing base. |
| P1-covenant-check | PROVISIONAL | WARNING | High | Covenant-related snippet found, but trigger/headroom not fully parsed. | Extract trigger, headroom, compliance, and springing conditions. |
| P2-investment-action-gate | BLOCKED | WARNING | High | This generic data pack does not source consensus, peer valuation, target price, normalized EBITDA, or scenario return. | Add valuation, earnings quality, scenario, catalyst, and risk/reward layers before Buy/Sell/Hold. |
| P1-subsequent-event-review | PROVISIONAL | WARNING | High | 3 Form 8-K/8-K/A filing(s) were filed after the latest financial filing; content review remains required. | Review each listed subsequent filing and link any effect to a new evidence record before a partner-ready memo. |
| P0-calculation-lineage | PASS | INFO | Critical | Every calculated row has an explicit formula and upstream evidence IDs. | Retain this check for every new calculation module. |
| P0-cash-flow-double-count-ledger | PASS | INFO | Critical | No line is both embedded in CFO and separately modeled without an explicit reversal. | Keep every future source/use line in the shared cash-flow ledger. |
