# RPM INTERNATIONAL INC/DE/ (RPM) Public Company Decision-Support Data Pack

Review date: 2026-08-04
Exchange: NYSE
Scope: SEC public filings only. This is a data-integrity and credit/liquidity support pack, not a formal investment recommendation.

## Decision Strip

- Action view: Watch / Need More Work
- Confidence: Medium if core statements and validation pass; lower where facility, covenant, lease, valuation, or consensus data is missing.
- Latest quarterly filing: 10-Q filed 2026-04-08, period 2026-02-28.
- Latest annual filing: 10-K filed 2026-07-22, period 2026-05-31.
- Selected current filing: 10-K filed 2026-07-22, period 2026-05-31.
- Validation: 0 fail, 1 blocked, 5 missing/provisional checks.

## Core View

- The pack can support a preliminary credit/liquidity view only after data validation.
- Visible liquid resources including reported facility availability are $318.9m.
- Current lease obligations identified are $74.6m; current debt alone should not be treated as total near-term obligations.
- Current reported annual FCF is $675.2m; latest-quarter FCF is n/a where current and derivable.
- Formal investment action remains blocked until earnings drivers, normalized EBITDA/FCF, consensus, valuation, scenarios, catalysts, and risk/reward are sourced.

## Key Metrics

| Metric | Value | Period | Evidence | Decision Use |
|---|---:|---|---|---|
| Unrestricted cash | $315.2m | 2026-05-31 | FACT/instant | Immediate cash, before restricted-cash caveat |
| Cash + restricted cash | $315.2m | 2026-05-31 | FACT/instant | Cash-flow reconciliation, not fully available liquidity |
| Short-term investments | $3.2m | 2026-05-31 | FACT/instant | Adds to liquid resources if present |
| Cash + short-term investments | $318.4m | 2026-05-31 | CALC/instant | Liquidity before revolver/facility note review |
| Reported facility availability | $0.5m | 2026-05-31 | FACT/instant | Committed liquidity source if note parse is confirmed |
| Cash/STI + reported available borrowings | $318.9m | 2026-05-31 | CALC/instant | Preliminary liquidity source before downside haircut |
| Current debt | $407.8m | 2026-05-31 | FACT/instant | 12-month funded debt pressure |
| Current lease obligations | $74.6m | 2026-05-31 | CALC/instant | Mandatory uses not captured by current debt |
| Annual FCF | $675.2m | 2025-06-01 to 2026-05-31 | CALC/annual | Cash generation for the selected current annual period |

## Validation Report

| Check | Result | Evidence | Impact |
|---|---:|---|---|
| P0-supported-universe | PASS | SEC 10-K/10-Q, US GAAP, non-financial public-company core is supported. | The issuer is inside the current core accounting scope. |
| P0-current-financial-filing-selection | PASS | Selected 10-K period 2026-05-31, filed 2026-07-22; available candidates: 10-Q period 2026-02-28, filed 2026-04-08, 10-K period 2026-05-31, filed 2026-07-22. | Current balance-sheet, primary cash-flow, and subsequent-event anchors use the latest reported period rather than a fixed form preference. |
| P1-note-debt | PASS | Debt balance, note disclosure, and maturity language were located. | The control does not constrain the current output. |
| P1-note-revolver | WARNING | A revolver or credit-facility signal was located, but commitment, usage or availability, maturity, or restriction evidence is incomplete. | The affected underwriting conclusion must remain qualified. |
| P1-note-leases | WARNING | Lease evidence is partial; carrying values must not be presented as contractual cash payments. | The affected underwriting conclusion must remain qualified. |
| P1-note-covenants | WARNING | Covenant compliance language was located without complete numerical headroom; compliance is not treated as adequate headroom. | The affected underwriting conclusion must remain qualified. |
| P1-note-receivables | PASS | Receivable balance, note disclosure, and at least one risk-detail disclosure were located. | The control does not constrain the current output. |
| P1-note-bad-debt | PASS | Allowance balance, credit-loss methodology, and provision/write-off activity were located. | The control does not constrain the current output. |
| P1-note-supplier-finance | PASS | Supplier-finance disclosure and a period-matched structured fact were located. | The control does not constrain the current output. |
| P1-note-acquisitions | WARNING | An acquisition signal was located, but the period-matched amount, transaction consideration, purchase accounting, or pro forma impact is incomplete. | The affected underwriting conclusion must remain qualified. |
| P0-filing-amendment-review | NOT_APPLICABLE | No later amendment for the selected financial period was listed in SEC submissions. | The control does not constrain the current output. |
| P0-restatement-review | NOT_APPLICABLE | No high-confidence restatement, non-reliance, or prior-period revision signal was identified in the reviewed filing set. | The control does not constrain the current output. |
| P1-subsequent-event-review | PASS | No later 8-K or 8-K/A was listed after the selected financial filing as of the index review date. | The control does not constrain the current output. |
| P0-fiscal-calendar-control | PASS | Validated fiscal-year context: NON_CALENDAR_FISCAL_YEAR, DATE_BASED, 365 days. | Quarter, YTD, FY, and LTM controls use reported fiscal dates instead of assuming a December year-end or 365-day year. |
| P0-instant-flow-period-control | PASS | Every selected instant, quarter, YTD, derived-quarter, and FY row has a compatible XBRL context and duration. | Prevents instant/flow contamination and quarter/YTD/FY relabeling. |
| P0-unit-currency-control | PASS | All selected financial facts use validated semantic units and one reporting currency (USD); share count uses shares. | Prevents silent unit, currency, and share-count basis mixing. |
| P0-share-count-control | PASS | Point-in-time shares were selected as of 2026-07-21 from a filing published 2026-07-22. | The system separates point-in-time shares from weighted-average EPS shares and blocks future-publication leakage. |
| P0-cash-capex-component-coverage | PASS | latest_annual_capex uses a reported aggregate cash-capex concept; aggregate and component paths are mutually exclusive, and noncash incurred-but-unpaid capex is excluded. | CFO-based FCF uses an auditable cash-capex basis without known component omission or double counting. |
| P0-ltm-construction-control | MISSING | No key metric passed the complete shared LTM construction control; annual fallback or missing status is retained. | The system does not fabricate LTM values from non-comparable periods. |
| P0-missing-xbrl-safe-handling | PASS | Required shared selections were found and no missing XBRL fact was converted to zero. | Preserves the distinction between a reported zero and unavailable disclosure. |
| P0-negative-denominator-control | PASS | No calculated working-capital ratio used a zero, negative, missing, or non-finite denominator. | Prevents invalid DSO, DIO, or DPO outputs. |
| P0-instant-balance-semantic-check | PASS | No nonnegative balance-sheet metric uses a negative value or IncreaseDecrease cash-flow concept. | Protects point-in-time balances from cash-flow tag contamination. |
| P0-balance-sheet-check | PASS | Assets $8,344.6m; liabilities + equity $8,344.6m. | Confirms statement extraction integrity. |
| P0-period-mismatch-block | PASS | No quarter/YTD mixed-flow ratio was generated. | Flow ratios are period-gated. |
| P0-cash-definition-check | PASS | Cash $315.2m; cash + restricted cash $315.2m. | Prevents overstating usable cash. |
| P0-fcf-classification | PASS | Annual FCF tagged as annual. | Stops annual FCF from being mislabeled as YTD or standalone quarter. |
| P0-quarter-fcf-check | NOT_APPLICABLE | The selected current filing is a 10-K; no stale interim FCF is presented as the current-period cash-flow basis. | Annual CFO less annual cash capex is the primary reported FCF basis. |
| P0-working-capital-opening-balance-alignment | MISSING | Quarter start or opening working-capital balances are unavailable. | Average-balance working-capital days cannot be date-validated. |
| P0-working-capital-days | MISSING | Could not calculate average-balance DSO/DIO/DPO. | Working-capital pressure cannot be assessed fully. |
| P1-ap-definition-for-dpo | PASS | Current and opening accounts-payable balances use trade-compatible concepts. | DPO can be calculated without known accrued-liability contamination. |
| P0-current-debt-vs-lease-check | PASS | Current debt $407.8m; current leases $74.6m. | Near-term obligations are visible at high level. |
| P1-facility-note-check | PROVISIONAL | Reported facility availability parsed as $0.5m; full note still needs review. | Liquidity view can include a preliminary facility source, but restrictions and borrowing-base mechanics remain analyst-review items. |
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

- Latest 10-Q: https://www.sec.gov/Archives/edgar/data/110621/000119312526147191/rpm-20260228.htm
- Latest 10-K: https://www.sec.gov/Archives/edgar/data/110621/000119312526312142/rpm-20260531.htm
- SEC companyfacts: https://data.sec.gov/api/xbrl/companyfacts/CIK0000110621.json
