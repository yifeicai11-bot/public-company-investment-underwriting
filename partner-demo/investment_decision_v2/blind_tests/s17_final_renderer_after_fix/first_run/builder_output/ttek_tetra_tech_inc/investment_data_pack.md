# TETRA TECH INC (TTEK) Public Company Decision-Support Data Pack

Review date: 2026-08-04
Exchange: Nasdaq
Scope: SEC public filings only. This is a data-integrity and credit/liquidity support pack, not a formal investment recommendation.

## Decision Strip

- Action view: Watch / Need More Work
- Confidence: Medium if core statements and validation pass; lower where facility, covenant, lease, valuation, or consensus data is missing.
- Latest quarterly filing: 10-Q filed 2026-07-31, period 2026-06-28.
- Latest annual filing: 10-K filed 2025-11-20, period 2025-09-28.
- Validation: 0 fail, 1 blocked, 5 missing/provisional checks.

## Core View

- The pack can support a preliminary credit/liquidity view only after data validation.
- Visible liquid resources before facility-note availability review are $230.8m.
- Current lease obligations identified are $74.7m; current debt alone should not be treated as total near-term obligations.
- YTD FCF is $452.6m; latest-quarter FCF is $225.1m where derivable.
- Formal investment action remains blocked until earnings drivers, normalized EBITDA/FCF, consensus, valuation, scenarios, catalysts, and risk/reward are sourced.

## Key Metrics

| Metric | Value | Period | Evidence | Decision Use |
|---|---:|---|---|---|
| Unrestricted cash | $230.8m | 2026-06-28 | FACT/instant | Immediate cash, before restricted-cash caveat |
| Cash + restricted cash | $230.8m | 2026-06-28 | FACT/instant | Cash-flow reconciliation, not fully available liquidity |
| Cash + short-term investments | $230.8m | 2026-06-28 | CALC/instant | Liquidity before revolver/facility note review |
| Current lease obligations | $74.7m | 2026-06-28 | CALC/instant | Mandatory uses not captured by current debt |
| YTD FCF | $452.6m | 2025-09-29 to 2026-06-28 | CALC/YTD | Cash generation, period-specific |
| Derived latest-quarter FCF | $225.1m | 2026-03-30 to 2026-06-28 | CALC/derived-quarter | Same-period cash conversion if derivable |
| DSO | 73.8 days | 2026-03-30 to 2026-06-28 | CALC/quarter | Receivables collection pressure |
| DPO | 96.8 days | 2026-03-30 to 2026-06-28 | CALC/quarter | Payables timing; check AP definition |

## Validation Report

| Check | Result | Evidence | Impact |
|---|---:|---|---|
| P0-supported-universe | PASS | SEC 10-K/10-Q, US GAAP, non-financial public-company core is supported. | The issuer is inside the current core accounting scope. |
| P1-note-debt | WARNING | Debt is present, but maturity evidence is incomplete or an amendment, waiver, or forbearance signal requires agreement-level review. | The affected underwriting conclusion must remain qualified. |
| P1-note-revolver | WARNING | A revolver or credit-facility signal was located, but commitment, usage or availability, maturity, or restriction evidence is incomplete. | The affected underwriting conclusion must remain qualified. |
| P1-note-leases | WARNING | Lease evidence is partial; carrying values must not be presented as contractual cash payments. | The affected underwriting conclusion must remain qualified. |
| P1-note-covenants | WARNING | Covenant compliance language was located without complete numerical headroom; compliance is not treated as adequate headroom. | The affected underwriting conclusion must remain qualified. |
| P1-note-receivables | PASS | Receivable balance, note disclosure, and at least one risk-detail disclosure were located. | The control does not constrain the current output. |
| P1-note-bad-debt | WARNING | Bad-debt evidence is partial; allowance, methodology, and activity must remain separately identified. | The affected underwriting conclusion must remain qualified. |
| P1-note-supplier-finance | MISSING | No supplier-finance disclosure was located; silence is not treated as NOT_APPLICABLE. | The affected underwriting conclusion must remain qualified. |
| P1-note-acquisitions | PASS | Period-matched acquisition amount, transaction terms, and acquisition-accounting disclosure were located. | The control does not constrain the current output. |
| P0-filing-amendment-review | NOT_APPLICABLE | No later amendment for the selected financial period was listed in SEC submissions. | The control does not constrain the current output. |
| P0-restatement-review | NOT_APPLICABLE | No high-confidence restatement, non-reliance, or prior-period revision signal was identified in the reviewed filing set. | The control does not constrain the current output. |
| P1-subsequent-event-review | PASS | No later 8-K or 8-K/A was listed after the selected financial filing as of the index review date. | The control does not constrain the current output. |
| P0-fiscal-calendar-control | PASS | Validated fiscal-year context: NON_CALENDAR_FISCAL_YEAR, 52_WEEK, 364 days. | Quarter, YTD, FY, and LTM controls use reported fiscal dates instead of assuming a December year-end or 365-day year. |
| P0-instant-flow-period-control | PASS | Every selected instant, quarter, YTD, derived-quarter, and FY row has a compatible XBRL context and duration. | Prevents instant/flow contamination and quarter/YTD/FY relabeling. |
| P0-unit-currency-control | PASS | All selected financial facts use validated semantic units and one reporting currency (USD); share count uses shares. | Prevents silent unit, currency, and share-count basis mixing. |
| P0-share-count-control | PASS | Point-in-time shares were selected as of 2026-07-20 from a filing published 2026-07-31. | The system separates point-in-time shares from weighted-average EPS shares and blocks future-publication leakage. |
| P0-cash-capex-component-coverage | PASS | latest_ytd_capex uses compatible reported components: property_plant_equipment; aggregate and component paths are mutually exclusive, and noncash incurred-but-unpaid capex is excluded. | CFO-based FCF uses an auditable cash-capex basis without known component omission or double counting. |
| P0-ltm-construction-control | PASS | Validated LTM construction is available for: capex, cfo, net_income, revenue. | Each LTM value uses one concept, one unit/currency, a validated FY, and comparable current/prior YTD contexts. |
| P0-missing-xbrl-safe-handling | PASS | Required shared selections were found and no missing XBRL fact was converted to zero. | Preserves the distinction between a reported zero and unavailable disclosure. |
| P0-negative-denominator-control | PASS | No calculated working-capital ratio used a zero, negative, missing, or non-finite denominator. | Prevents invalid DSO, DIO, or DPO outputs. |
| P0-instant-balance-semantic-check | PASS | No nonnegative balance-sheet metric uses a negative value or IncreaseDecrease cash-flow concept. | Protects point-in-time balances from cash-flow tag contamination. |
| P0-balance-sheet-check | PASS | Assets $4,388.3m; liabilities + equity $4,388.3m. | Confirms statement extraction integrity. |
| P0-period-mismatch-block | PASS | Incompatible inputs were detected and not combined: quarter net income 2026-03-30 to 2026-06-28; YTD CFO 2025-09-29 to 2026-06-28. | The engine correctly prevents invalid CFO/net income or FCF/profit ratios. |
| P0-cash-definition-check | PASS | Cash $230.8m; cash + restricted cash $230.8m. | Prevents overstating usable cash. |
| P0-fcf-classification | PASS | YTD FCF tagged as YTD. | Stops YTD FCF from being mislabeled as standalone quarter. |
| P0-quarter-fcf-check | PASS | Latest-quarter FCF is tagged as derived-quarter. | Supports same-period cash conversion analysis. |
| P0-working-capital-opening-balance-alignment | PASS | Expected opening balance date 2026-03-29; extracted dates 2026-03-29. | Prevents DSO/DIO/DPO from averaging non-adjacent balance-sheet dates. |
| P0-working-capital-days | PASS | At least one average-balance working-capital day metric calculated. | Improves monitoring vs single-point ratios. |
| P1-working-capital-component-coverage | PROVISIONAL | Available components: DSO, DPO; missing pending classification: DIO, CCC. No absent component is assumed to be zero. | A partial cycle must not be presented as complete cash-conversion analysis. |
| P1-ap-definition-for-dpo | PASS | Current and opening accounts-payable balances use trade-compatible concepts. | DPO can be calculated without known accrued-liability contamination. |
| P0-current-debt-vs-lease-check | MISSING | A standardized current-debt value was not identified; absence of a tag is not treated as zero. | Near-term funded debt and total fixed obligations cannot be confirmed. |
| P1-facility-note-check | PROVISIONAL | Facility/credit agreement snippet found, but not fully parsed. | Availability/covenant conclusions require note-level review. |
| P1-covenant-check | PROVISIONAL | Covenant-related snippet found, but trigger/headroom not fully parsed. | Covenant risk cannot be rated high-confidence yet. |
| P2-investment-action-gate | BLOCKED | This generic data pack does not source consensus, peer valuation, target price, normalized EBITDA, or scenario return. | Prevents a credit screen from being presented as a complete investment recommendation. |
| P0-calculation-unit-currency-lineage | PASS | Every calculated metric preserves a consistent monetary currency across its linked input evidence. | Prevents a renderer or downstream module from hiding unit or currency mismatches. |
| P0-calculation-lineage | PASS | Every calculated row has an explicit formula and upstream evidence IDs. | All displayed calculations are structurally reproducible from the evidence registry. |
| P0-cash-flow-double-count-ledger | PASS | No line is both embedded in CFO and separately modeled without an explicit reversal. | CFO-based FCF and liquidity calculations pass the structural double-counting check. |

## Required Follow-Up Before Full Investment Memo

- Read debt/facility notes for commitment, availability, letters of credit, reserves, borrowing-base mechanics, maturity, and covenant trigger.
- Build 12/24-month sources and uses: cash, revolver availability, debt maturities, leases, cash interest, maintenance capex, committed payments, and working-capital stress.
- Build 8-quarter DSO/DIO/DPO/CCC trend where filings allow.
- Source LTM adjusted EBITDA and reconcile management adjustments before using leverage ratios.
- Add consensus, peer multiples, historical valuation range, base/bull/bear scenarios, catalysts, and thesis-break thresholds before any investment action.

## Sources

- Latest 10-Q: https://www.sec.gov/Archives/edgar/data/831641/000083164126000017/ttek-20260628.htm
- Latest 10-K: https://www.sec.gov/Archives/edgar/data/831641/000083164125000032/ttek-20250928.htm
- SEC companyfacts: https://data.sec.gov/api/xbrl/companyfacts/CIK0000831641.json
