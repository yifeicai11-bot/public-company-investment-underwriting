#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = TEST_DIR.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_public_company_decision_pack import (  # noqa: E402
    CALCULATION_FORMULAS,
    CALCULATION_INPUTS,
    DataPoint,
    Filing,
    build_ltm_metric,
    cash_capex_data_points,
    choose_cash_capex,
    choose_duration,
    choose_instant,
    comparable_ytd_periods,
    compatible_monetary_inputs,
    controlled_ratio,
    fact_context_kind,
    fiscal_calendar_profile,
    enrich_data_points,
    is_annual_flow,
    is_quarter_flow,
    is_ytd_flow,
    latest_share_count_fact,
    select_current_financial_filing,
    unit_profile,
)
from build_public_company_investment_layer import (  # noqa: E402
    latest_shares,
    ltm_metric,
)


REVENUE_TAG = "RevenueFromContractWithCustomerExcludingAssessedTax"


def companyfacts(
    taxonomy: str,
    tag: str,
    units: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    return {
        "facts": {
            taxonomy: {
                tag: {
                    "units": units,
                }
            }
        }
    }


def multi_companyfacts(
    values_by_tag: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    return {
        "facts": {
            "us-gaap": {
                tag: {"units": {"USD": values}}
                for tag, values in values_by_tag.items()
            }
        }
    }


def monetary_row(name: str, currency: str) -> DataPoint:
    return DataPoint(
        metric_name=name,
        value=1,
        unit=currency,
        currency=currency,
        period_start="",
        period_end="2026-03-31",
        period_type="instant",
        duration_days="",
        fiscal_period="",
        filing_type="10-Q",
        filing_date="2026-05-01",
        source_location="test",
        source_tag="us-gaap:test",
        source_url="https://www.sec.gov/test",
        evidence_type="FACT",
        reported_or_calculated="reported",
        confidence="High",
        validation_status="PASS",
    )


class S06PeriodContextTests(unittest.TestCase):
    @staticmethod
    def filing(form: str, period: str, filed: str, accession: str) -> Filing:
        return Filing(
            form=form,
            filed=filed,
            period=period,
            accession=accession,
            primary_doc=f"{accession}.htm",
            url=f"https://www.sec.gov/{accession}.htm",
        )

    def test_newer_annual_period_supersedes_stale_interim_current_state(self) -> None:
        interim = self.filing("10-Q", "2026-02-28", "2026-04-08", "q3")
        annual = self.filing("10-K", "2026-05-31", "2026-07-22", "fy")
        selected = select_current_financial_filing(interim, annual)
        self.assertEqual(selected, annual)

    def test_newer_interim_period_supersedes_annual_current_state(self) -> None:
        interim = self.filing("10-Q", "2026-06-30", "2026-08-01", "q2")
        annual = self.filing("10-K", "2025-12-31", "2026-02-15", "fy")
        selected = select_current_financial_filing(interim, annual)
        self.assertEqual(selected, interim)

    def test_same_period_uses_filing_date_and_accession_tiebreakers(self) -> None:
        earlier = self.filing("10-Q", "2026-03-31", "2026-05-01", "a")
        later = self.filing("10-K", "2026-03-31", "2026-05-02", "b")
        self.assertEqual(select_current_financial_filing(earlier, later), later)

    def test_standalone_98_day_quarter_is_accepted(self) -> None:
        point = {
            "start": "2026-01-04",
            "end": "2026-04-11",
            "form": "10-Q",
            "fp": "Q2",
        }
        self.assertEqual(fact_context_kind(point), "FLOW")
        self.assertTrue(is_quarter_flow(point))
        self.assertFalse(is_ytd_flow(point))

    def test_q2_cumulative_context_is_ytd(self) -> None:
        point = {
            "start": "2025-10-05",
            "end": "2026-04-11",
            "form": "10-Q",
            "fp": "Q2",
        }
        self.assertFalse(is_quarter_flow(point))
        self.assertTrue(is_ytd_flow(point))

    def test_multi_quarter_ytd_is_not_relabelled_as_quarter(self) -> None:
        facts = companyfacts(
            "us-gaap",
            REVENUE_TAG,
            {
                "USD": [
                    {
                        "start": "2025-10-05",
                        "end": "2026-04-11",
                        "val": 200,
                        "form": "10-Q",
                        "filed": "2026-05-01",
                        "accn": "q2",
                        "fp": "Q2",
                    }
                ]
            },
        )
        audit: list[dict[str, object]] = []
        quarter = choose_duration(
            facts,
            (REVENUE_TAG,),
            "2026-04-11",
            form="10-Q",
            accn="q2",
            prefer="quarter",
            metric_name="latest_quarter_revenue",
            audit_log=audit,
        )
        ytd = choose_duration(
            facts,
            (REVENUE_TAG,),
            "2026-04-11",
            form="10-Q",
            accn="q2",
            prefer="ytd",
        )
        self.assertIsNone(quarter)
        self.assertEqual(ytd["val"], 200)
        self.assertEqual(audit[-1]["status"], "INCOMPATIBLE_XBRL_CONTEXT")

    def test_53_week_fy_is_valid_but_short_fy_is_rejected(self) -> None:
        valid = {
            "start": "2024-09-29",
            "end": "2025-10-04",
            "form": "10-K",
            "fp": "FY",
        }
        invalid = {
            "start": "2025-01-26",
            "end": "2025-12-31",
            "form": "10-K",
            "fp": "FY",
        }
        self.assertTrue(is_annual_flow(valid))
        self.assertFalse(is_annual_flow(invalid))

    def test_instant_selector_rejects_flow_context(self) -> None:
        facts = companyfacts(
            "us-gaap",
            "Assets",
            {
                "USD": [
                    {
                        "start": "2026-01-01",
                        "end": "2026-03-31",
                        "val": 100,
                        "form": "10-Q",
                        "filed": "2026-05-01",
                        "accn": "q1",
                    }
                ]
            },
        )
        audit: list[dict[str, object]] = []
        selected = choose_instant(
            facts,
            ("Assets",),
            "2026-03-31",
            "q1",
            metric_name="total_assets",
            audit_log=audit,
        )
        self.assertIsNone(selected)
        self.assertEqual(audit[-1]["expected_context"], "INSTANT")
        self.assertFalse(audit[-1]["missing_value_assumed_zero"])


class S06FiscalCalendarAndLtmTests(unittest.TestCase):
    def test_non_calendar_52_week_profile_is_explicit(self) -> None:
        profile = fiscal_calendar_profile(
            {
                "start": "2024-09-29",
                "end": "2025-09-27",
                "form": "10-K",
                "fp": "FY",
                "tag": REVENUE_TAG,
                "unit": "USD",
            }
        )
        self.assertEqual(profile["status"], "PASS")
        self.assertTrue(profile["is_non_calendar_fiscal_year"])
        self.assertEqual(profile["week_structure"], "52_WEEK")

    def test_53_week_profile_is_explicit(self) -> None:
        profile = fiscal_calendar_profile(
            {
                "start": "2024-09-29",
                "end": "2025-10-04",
                "form": "10-K",
                "fp": "FY",
                "tag": REVENUE_TAG,
                "unit": "USD",
            }
        )
        self.assertEqual(profile["status"], "PASS")
        self.assertTrue(profile["is_53_week_fiscal_year"])
        self.assertEqual(profile["duration_days"], 371)

    def test_comparable_ytd_allows_one_week_53_week_shift(self) -> None:
        current = {
            "tag": REVENUE_TAG,
            "unit": "USD",
            "start": "2025-10-05",
            "end": "2026-04-04",
            "form": "10-Q",
            "fp": "Q2",
        }
        prior = {
            "tag": REVENUE_TAG,
            "unit": "USD",
            "start": "2024-09-29",
            "end": "2025-03-29",
            "form": "10-Q",
            "fp": "Q2",
        }
        comparable, reason = comparable_ytd_periods(current, prior)
        self.assertTrue(comparable, reason)

    def test_ltm_uses_one_concept_and_comparable_fiscal_periods(self) -> None:
        facts = companyfacts(
            "us-gaap",
            REVENUE_TAG,
            {
                "USD": [
                    {
                        "start": "2024-09-29",
                        "end": "2025-10-04",
                        "val": 100,
                        "form": "10-K",
                        "filed": "2025-11-01",
                        "accn": "k",
                        "fp": "FY",
                    },
                    {
                        "start": "2025-10-05",
                        "end": "2026-04-04",
                        "val": 60,
                        "form": "10-Q",
                        "filed": "2026-05-01",
                        "accn": "q",
                        "fp": "Q2",
                    },
                    {
                        "start": "2024-09-29",
                        "end": "2025-03-29",
                        "val": 50,
                        "form": "10-Q",
                        "filed": "2025-05-01",
                        "accn": "pq",
                        "fp": "Q2",
                    },
                ]
            },
        )
        result = build_ltm_metric(facts, "revenue", "2026-04-04", "2025-10-04")
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["period_type"], "LTM")
        self.assertEqual(result["value"], 110)
        self.assertEqual(result["currency"], "USD")

    def test_ltm_rejects_currency_mismatch_and_keeps_annual_fallback(self) -> None:
        facts = companyfacts(
            "us-gaap",
            REVENUE_TAG,
            {
                "USD": [
                    {
                        "start": "2025-01-01",
                        "end": "2025-12-31",
                        "val": 100,
                        "form": "10-K",
                        "filed": "2026-02-01",
                        "accn": "k",
                        "fp": "FY",
                    },
                    {
                        "start": "2026-01-01",
                        "end": "2026-06-30",
                        "val": 60,
                        "form": "10-Q",
                        "filed": "2026-08-01",
                        "accn": "q",
                        "fp": "Q2",
                    },
                ],
                "EUR": [
                    {
                        "start": "2025-01-01",
                        "end": "2025-06-30",
                        "val": 50,
                        "form": "10-Q",
                        "filed": "2025-08-01",
                        "accn": "pq",
                        "fp": "Q2",
                    }
                ],
            },
        )
        result = ltm_metric(facts, "revenue", "2026-06-30", "2025-12-31")
        self.assertEqual(result["period_type"], "annual")
        self.assertEqual(result["validation_status"], "LTM_NOT_AVAILABLE")


class S06UnitCurrencyAndShareCountTests(unittest.TestCase):
    def test_unit_profile_separates_money_per_share_and_shares(self) -> None:
        self.assertEqual(unit_profile("USD")["category"], "MONETARY")
        self.assertEqual(unit_profile("USD/shares")["category"], "MONETARY_PER_SHARE")
        self.assertEqual(unit_profile("shares")["category"], "SHARES")
        self.assertEqual(unit_profile("widgets")["category"], "UNKNOWN")

    def test_flow_selector_rejects_per_share_unit_for_revenue(self) -> None:
        facts = companyfacts(
            "us-gaap",
            REVENUE_TAG,
            {
                "USD/shares": [
                    {
                        "start": "2026-01-01",
                        "end": "2026-03-31",
                        "val": 2,
                        "form": "10-Q",
                        "filed": "2026-05-01",
                        "accn": "q1",
                    }
                ]
            },
        )
        self.assertIsNone(
            choose_duration(
                facts,
                (REVENUE_TAG,),
                "2026-03-31",
                form="10-Q",
                accn="q1",
                prefer="quarter",
            )
        )

    def test_monetary_calculation_rejects_mixed_currencies(self) -> None:
        result = compatible_monetary_inputs(
            monetary_row("cash", "USD"),
            monetary_row("investments", "EUR"),
        )
        self.assertEqual(result["status"], "INCOMPATIBLE")

    def test_share_count_requires_instant_shares_and_no_future_publication(self) -> None:
        facts = companyfacts(
            "dei",
            "EntityCommonStockSharesOutstanding",
            {
                "shares": [
                    {
                        "val": 100,
                        "end": "2026-03-31",
                        "filed": "2026-04-20",
                        "form": "10-Q",
                        "accn": "a",
                    },
                    {
                        "val": 95,
                        "end": "2026-04-17",
                        "filed": "2026-08-05",
                        "form": "10-Q",
                        "accn": "b",
                    },
                    {
                        "val": 90,
                        "start": "2026-01-01",
                        "end": "2026-03-31",
                        "filed": "2026-04-20",
                        "form": "10-Q",
                        "accn": "a",
                    },
                ]
            },
        )
        result = latest_share_count_fact(facts, "2026-07-15")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["value"], 100)
        self.assertEqual(result["share_count_date"], "2026-03-31")
        delegated_value, delegated_point = latest_shares(facts, "2026-07-15")
        self.assertEqual(delegated_value, 100)
        self.assertEqual(delegated_point["accn"], "a")

    def test_conflicting_latest_share_counts_are_blocked(self) -> None:
        facts = companyfacts(
            "dei",
            "EntityCommonStockSharesOutstanding",
            {
                "shares": [
                    {
                        "val": 100,
                        "end": "2026-04-17",
                        "filed": "2026-04-20",
                        "form": "10-Q",
                        "accn": "a",
                    },
                    {
                        "val": 110,
                        "end": "2026-04-17",
                        "filed": "2026-04-20",
                        "form": "10-Q",
                        "accn": "a",
                    },
                ]
            },
        )
        result = latest_share_count_fact(facts, "2026-07-15")
        self.assertEqual(result["status"], "CONFLICT")
        self.assertIsNone(result["value"])


class S06DenominatorAndMissingTagTests(unittest.TestCase):
    def test_positive_denominator_calculates(self) -> None:
        result = controlled_ratio(50, 100, multiplier=90)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["value"], 45)

    def test_zero_negative_and_nonfinite_denominators_are_suppressed(self) -> None:
        self.assertEqual(controlled_ratio(50, 0)["status"], "SUPPRESSED")
        self.assertEqual(controlled_ratio(50, -10)["status"], "SUPPRESSED")
        self.assertEqual(controlled_ratio(50, float("inf"))["status"], "SUPPRESSED")

    def test_missing_xbrl_tag_is_logged_and_never_assumed_zero(self) -> None:
        audit: list[dict[str, object]] = []
        selected = choose_instant(
            {"facts": {"us-gaap": {}}},
            ("Assets",),
            "2026-03-31",
            metric_name="total_assets",
            audit_log=audit,
        )
        self.assertIsNone(selected)
        self.assertEqual(audit[-1]["status"], "MISSING_XBRL_TAG")
        self.assertFalse(audit[-1]["missing_value_assumed_zero"])


class S06CashCapexCompositionTests(unittest.TestCase):
    def test_annual_fcf_has_shared_formula_and_input_lineage(self) -> None:
        self.assertEqual(
            CALCULATION_INPUTS["latest_annual_fcf"],
            ("latest_annual_cfo", "latest_annual_capex"),
        )
        self.assertEqual(
            CALCULATION_FORMULAS["latest_annual_fcf"],
            "latest_annual_cfo - latest_annual_capex",
        )

    @staticmethod
    def point(value: float, *, start: str = "2026-01-01") -> dict[str, object]:
        return {
            "start": start,
            "end": "2026-06-30",
            "val": value,
            "form": "10-Q",
            "filed": "2026-07-31",
            "accn": "q2",
            "fy": 2026,
            "fp": "Q2",
        }

    def test_period_matched_ppe_and_software_are_summed_with_lineage(self) -> None:
        facts = multi_companyfacts(
            {
                "PaymentsToAcquirePropertyPlantAndEquipment": [self.point(7_610_000)],
                "PaymentsForSoftware": [self.point(25_642_000)],
                "CapitalExpendituresIncurredButNotYetPaid": [self.point(99_000_000)],
            }
        )
        audit: list[dict[str, object]] = []
        selection = choose_cash_capex(
            facts,
            "2026-06-30",
            form="10-Q",
            accn="q2",
            prefer="ytd",
            metric_name="latest_ytd_capex",
            audit_log=audit,
        )
        self.assertEqual(selection["status"], "PASS")
        self.assertEqual(selection["basis"], "COMPONENT_SUM")
        self.assertEqual(selection["fact"]["val"], 33_252_000)
        self.assertEqual(
            set(selection["components"]),
            {"property_plant_equipment", "software"},
        )
        self.assertEqual(audit[-1]["status"], "SELECTED_COMPOSITE")

        rows = cash_capex_data_points(
            "latest_ytd_capex",
            selection,
            "https://www.sec.gov/test",
            "YTD",
        )
        enrich_data_points(
            {"ticker": "TEST", "name": "Test", "cik": "0000000001"},
            rows,
        )
        parent = next(row for row in rows if row.metric_name == "latest_ytd_capex")
        self.assertEqual(parent.reported_or_calculated, "calculated")
        self.assertEqual(len(parent.input_evidence_ids or []), 2)
        self.assertNotIn("CapitalExpendituresIncurredButNotYetPaid", parent.formula)

    def test_reported_aggregate_prevents_component_double_counting(self) -> None:
        facts = multi_companyfacts(
            {
                "PaymentsToAcquireProductiveAssets": [self.point(40_000_000)],
                "PaymentsToAcquirePropertyPlantAndEquipment": [self.point(15_000_000)],
                "PaymentsForSoftware": [self.point(25_000_000)],
            }
        )
        selection = choose_cash_capex(
            facts,
            "2026-06-30",
            form="10-Q",
            accn="q2",
            prefer="ytd",
            metric_name="latest_ytd_capex",
        )
        self.assertEqual(selection["basis"], "REPORTED_AGGREGATE")
        self.assertEqual(selection["fact"]["val"], 40_000_000)
        self.assertEqual(selection["components"], {})

    def test_non_cash_capex_signal_is_never_used_as_cash_capex(self) -> None:
        facts = multi_companyfacts(
            {"CapitalExpendituresIncurredButNotYetPaid": [self.point(12_000_000)]}
        )
        selection = choose_cash_capex(
            facts,
            "2026-06-30",
            form="10-Q",
            accn="q2",
            prefer="ytd",
            metric_name="latest_ytd_capex",
        )
        self.assertEqual(selection["status"], "MISSING_XBRL_TAG")
        self.assertIsNone(selection["fact"])

    def test_incompatible_component_period_blocks_composite_capex(self) -> None:
        facts = multi_companyfacts(
            {
                "PaymentsToAcquirePropertyPlantAndEquipment": [self.point(7_610_000)],
                "PaymentsForSoftware": [self.point(20_000_000, start="2026-04-01")],
            }
        )
        selection = choose_cash_capex(
            facts,
            "2026-06-30",
            form="10-Q",
            accn="q2",
            prefer="ytd",
            metric_name="latest_ytd_capex",
        )
        self.assertEqual(selection["status"], "INCOMPATIBLE_COMPONENT_CONTEXT")
        self.assertIsNone(selection["fact"])
        self.assertIn("software", selection["unresolved_component_groups"])

    def test_ltm_capex_sums_each_components_validated_period_chain(self) -> None:
        def chain(annual: float, current: float, prior: float) -> list[dict[str, object]]:
            return [
                {
                    "start": "2025-01-01",
                    "end": "2025-12-31",
                    "val": annual,
                    "form": "10-K",
                    "filed": "2026-02-15",
                    "accn": "k",
                    "fy": 2025,
                    "fp": "FY",
                },
                {
                    "start": "2026-01-01",
                    "end": "2026-06-30",
                    "val": current,
                    "form": "10-Q",
                    "filed": "2026-07-31",
                    "accn": "q2",
                    "fy": 2026,
                    "fp": "Q2",
                },
                {
                    "start": "2025-01-01",
                    "end": "2025-06-30",
                    "val": prior,
                    "form": "10-Q",
                    "filed": "2025-07-31",
                    "accn": "prior-q2",
                    "fy": 2025,
                    "fp": "Q2",
                },
            ]

        facts = multi_companyfacts(
            {
                "PaymentsToAcquirePropertyPlantAndEquipment": chain(100, 30, 40),
                "PaymentsForSoftware": chain(50, 20, 10),
            }
        )
        result = build_ltm_metric(facts, "capex", "2026-06-30", "2025-12-31")
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["period_type"], "LTM")
        self.assertEqual(result["value"], 150)
        self.assertEqual(result["period_end"], "2026-06-30")
        self.assertEqual(len(result["components"]), 6)
        self.assertNotIn("CapitalExpendituresIncurredButNotYetPaid", result["formula"])


class S06CrossFiscalPatternTests(unittest.TestCase):
    def test_calendar_noncalendar_and_53_week_patterns_are_all_classified(self) -> None:
        points = [
            {
                "start": "2025-01-01",
                "end": "2025-12-31",
                "form": "10-K",
                "fp": "FY",
                "tag": REVENUE_TAG,
                "unit": "USD",
            },
            {
                "start": "2024-09-29",
                "end": "2025-09-27",
                "form": "10-K",
                "fp": "FY",
                "tag": REVENUE_TAG,
                "unit": "USD",
            },
            {
                "start": "2024-09-29",
                "end": "2025-10-04",
                "form": "10-K",
                "fp": "FY",
                "tag": REVENUE_TAG,
                "unit": "USD",
            },
        ]
        profiles = [fiscal_calendar_profile(point) for point in points]
        self.assertEqual([profile["status"] for profile in profiles], ["PASS", "PASS", "PASS"])
        self.assertEqual(profiles[0]["calendar_basis"], "CALENDAR_YEAR")
        self.assertEqual(profiles[1]["week_structure"], "52_WEEK")
        self.assertEqual(profiles[2]["week_structure"], "53_WEEK")


if __name__ == "__main__":
    unittest.main()
