# OLD DOMINION FREIGHT LINE, INC. (ODFL) Public Company Decision-Support Data Pack

Review date: 2026-07-28
Exchange: Nasdaq
Scope: SEC public filings only. This is a data-integrity and credit/liquidity support pack, not a formal investment recommendation.

## Decision Strip

- Action view: Watch / Need More Work
- Confidence: Medium if core statements and validation pass; lower where facility, covenant, lease, valuation, or consensus data is missing.
- Latest quarterly filing: 10-Q filed 2026-05-06, period 2026-03-31.
- Latest annual filing: 10-K filed 2026-02-24, period 2025-12-31.
- Validation: 0 fail, 1 blocked, 4 missing/provisional checks.

## Core View

- The pack can support a preliminary credit/liquidity view only after data validation.
- Visible liquid resources including reported facility availability are $656.3m.
- Current lease obligations are missing or not standardized; near-term obligations need note review.
- YTD FCF is n/a; latest-quarter FCF is $311.1m where derivable.
- Formal investment action remains blocked until earnings drivers, normalized EBITDA/FCF, consensus, valuation, scenarios, catalysts, and risk/reward are sourced.

## Key Metrics

| Metric | Value | Period | Evidence | Decision Use |
|---|---:|---|---|---|
| Unrestricted cash | $288.1m | 2026-03-31 | FACT/instant | Immediate cash, before restricted-cash caveat |
| Cash + restricted cash | $288.1m | 2026-03-31 | FACT/instant | Cash-flow reconciliation, not fully available liquidity |
| Cash + short-term investments | $288.1m | 2026-03-31 | CALC/instant | Liquidity before revolver/facility note review |
| Reported facility availability | $368.2m | 2026-03-31 | FACT/instant | Committed liquidity source if note parse is confirmed |
| Cash/STI + reported available borrowings | $656.3m | 2026-03-31 | CALC/instant | Preliminary liquidity source before downside haircut |
| Current debt | $20.0m | 2026-03-31 | FACT/instant | 12-month funded debt pressure |
| DSO | 34.2 days | 2026-01-01 to 2026-03-31 | CALC/quarter | Receivables collection pressure |

## Validation Report

| Check | Result | Evidence | Impact |
|---|---:|---|---|
| P0-supported-universe | PASS | SEC 10-K/10-Q, US GAAP, non-financial public-company core is supported. | The issuer is inside the current core accounting scope. |
| P0-instant-balance-semantic-check | PASS | No nonnegative balance-sheet metric uses a negative value or IncreaseDecrease cash-flow concept. | Protects point-in-time balances from cash-flow tag contamination. |
| P0-balance-sheet-check | PASS | Assets $5,656.9m; liabilities + equity $5,656.9m. | Confirms statement extraction integrity. |
| P0-period-mismatch-block | PASS | No quarter/YTD mixed-flow ratio was generated. | Flow ratios are period-gated. |
| P0-cash-definition-check | PASS | Cash $288.1m; cash + restricted cash $288.1m. | Prevents overstating usable cash. |
| P0-quarter-fcf-check | PASS | Latest-quarter FCF is tagged as quarter. | Supports same-period cash conversion analysis. |
| P0-working-capital-opening-balance-alignment | PASS | Expected opening balance date 2025-12-31; extracted dates 2025-12-31. | Prevents DSO/DIO/DPO from averaging non-adjacent balance-sheet dates. |
| P0-working-capital-days | PASS | At least one average-balance working-capital day metric calculated. | Improves monitoring vs single-point ratios. |
| P1-ap-definition-for-dpo | PASS | Current and opening accounts-payable balances use trade-compatible concepts. | DPO can be calculated without known accrued-liability contamination. |
| P0-current-debt-vs-lease-check | MISSING | Current debt is $20.0m, but standardized current lease tags were not found. | Near-term obligations may be understated if leases are material. |
| P0-facility-reconciliation | PASS | Facility commitment $400.0m reconciles to availability and known reductions within $1.0m. | The extracted facility amounts pass the internal arithmetic consistency check. |
| P1-facility-note-check | PROVISIONAL | Reported facility availability parsed as $368.2m; full note still needs review. | Liquidity view can include a preliminary facility source, but restrictions and borrowing-base mechanics remain analyst-review items. |
| P1-covenant-check | PROVISIONAL | Covenant-related snippet found, but trigger/headroom not fully parsed. | Covenant risk cannot be rated high-confidence yet. |
| P2-investment-action-gate | BLOCKED | This generic data pack does not source consensus, peer valuation, target price, normalized EBITDA, or scenario return. | Prevents a credit screen from being presented as a complete investment recommendation. |
| P1-subsequent-event-review | PROVISIONAL | 3 Form 8-K/8-K/A filing(s) were filed after the latest financial filing; content review remains required. | A later event may change debt, liquidity, shares, guidance, or the displayed current state. |
| P0-calculation-lineage | PASS | Every calculated row has an explicit formula and upstream evidence IDs. | All displayed calculations are structurally reproducible from the evidence registry. |
| P0-cash-flow-double-count-ledger | PASS | No line is both embedded in CFO and separately modeled without an explicit reversal. | CFO-based FCF and liquidity calculations pass the structural double-counting check. |

## Required Follow-Up Before Full Investment Memo

- Read debt/facility notes for commitment, availability, letters of credit, reserves, borrowing-base mechanics, maturity, and covenant trigger.
- Build 12/24-month sources and uses: cash, revolver availability, debt maturities, leases, cash interest, maintenance capex, committed payments, and working-capital stress.
- Build 8-quarter DSO/DIO/DPO/CCC trend where filings allow.
- Source LTM adjusted EBITDA and reconcile management adjustments before using leverage ratios.
- Add consensus, peer multiples, historical valuation range, base/bull/bear scenarios, catalysts, and thesis-break thresholds before any investment action.

## Sources

- Latest 10-Q: https://www.sec.gov/Archives/edgar/data/878927/000087892726000011/odfl-20260331.htm
- Latest 10-K: https://www.sec.gov/Archives/edgar/data/878927/000119312526067161/odfl-20251231.htm
- SEC companyfacts: https://data.sec.gov/api/xbrl/companyfacts/CIK0000878927.json
