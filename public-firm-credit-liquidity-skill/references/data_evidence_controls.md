# Shared Period, XBRL, and Accounting Controls

Read this reference before changing financial-fact selection, period construction, share count, working-capital ratios, or LTM calculations.

## Ownership

`build_public_company_decision_pack.py` is authoritative for these controls. Downstream modules may delegate to its functions but must not recreate the logic. Do not add ticker, company-name, industry-fixture, or renderer exceptions.

## Required Controls

| Area | Shared rule | Unsafe behavior |
|---|---|---|
| Quarter | A reported or derived standalone quarter must have a validated flow context and 70-105 days. | Relabel YTD as quarter. |
| YTD | Use a 10-Q flow context ending on the requested fiscal date. Select the longest valid context when both quarter and cumulative facts exist. | Mix YTD with quarter or FY in one ratio. |
| FY | Use a 10-K/10-K/A flow context of 350-380 days. | Assume every FY is a calendar year or exactly 365 days. |
| LTM | Use one concept and one unit/currency: validated FY + current YTD - prior comparable YTD. Current and prior YTD duration may differ by no more than seven days. | Splice concepts, currencies, or non-comparable fiscal periods. |
| Instant versus flow | Instant facts have an end date and no start date. Flow facts have both. | Use a cash-flow movement as a balance or a balance as a period flow. |
| Unit | Classify monetary, monetary-per-share, shares, pure, or unknown before selection. | Accept a per-share or unknown unit for a financial-statement amount. |
| Currency | Preserve the reported currency and require one compatible currency for arithmetic. | Assume USD or silently combine currencies. |
| Share count | Use published point-in-time shares on or before the market date; also require filing publication on or before that date. | Use weighted-average EPS shares, future-published facts, or unresolved class conflicts. |
| Non-calendar FY | Derive fiscal boundaries from reported start and end dates. | Map fiscal quarters to calendar quarters by month alone. |
| 53-week FY | Accept a validated annual duration of 368-374 days and allow a seven-day comparable-YTD shift. | Reject or silently compress the extra week. |
| Denominator | Zero, negative, missing, or non-finite denominators produce structured suppression. | Calculate DSO, DIO, DPO, or another positive-denominator ratio anyway. |
| Missing XBRL | Record attempted tags, context, unit, rejection reason, and `missing_value_assumed_zero: false`. | Convert missing disclosure to zero or force a lower-quality fact into the metric. |

## Data Object

The shared data pack must expose:

- `data_control_version`
- `fiscal_calendar_profile`
- `xbrl_selection_log`
- `ltm_control_results`
- `share_count_control`
- `denominator_control_log`

Material failures must appear in `validation_tests`, `hard_stops`, or `warnings`. A selected value must never bypass the evidence registry.

## Validation IDs

- `P0-fiscal-calendar-control`
- `P0-instant-flow-period-control`
- `P0-unit-currency-control`
- `P0-share-count-control`
- `P0-ltm-construction-control`
- `P0-missing-xbrl-safe-handling`
- `P0-negative-denominator-control`
- `P0-calculation-unit-currency-lineage`

Missing disclosure normally constrains research through a Warning. A selected or calculated value with a wrong context, unresolved material unit/currency conflict, conflicting share count, or inconsistent calculation lineage is a Hard Stop.

## Acceptance

Completion requires:

1. Dedicated positive and negative tests for every control above.
2. Existing unit and v1.0.0 regressions passing.
3. Cross-company runs covering calendar, non-calendar, 52-week, 53-week, and missing/non-comparable XBRL patterns.
4. No company-specific analytical branch.
