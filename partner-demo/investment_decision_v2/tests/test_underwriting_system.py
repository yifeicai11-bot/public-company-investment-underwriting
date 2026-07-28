#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = TEST_DIR.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_public_company_decision_pack import (  # noqa: E402
    INSTANT_TAGS,
    ap_balance_is_trade_compatible,
    assess_facility_reconciliation,
    choose_duration,
    derive_total_liabilities,
    extract_facility_values,
    extract_inline_row_value,
)
from build_public_company_investment_layer import (  # noqa: E402
    aligned_return_pair,
    build_analysis_evidence,
    build_external_evidence,
    build_issuer_underwriting,
    build_market_expectations,
    build_peer_valuation_context,
    build_probability_validation,
    build_unsupported_investment_output,
    latest_shares,
    ltm_metric,
    market_data_is_approved,
    reconcile_upstream_validation_tests,
    resolve_evidence_references,
    scenario_set,
)
from build_partner_portfolio_overlay import (  # noqa: E402
    build_overlay,
    choose_overlay_action,
    load_gate3_contract,
    overlay_gates,
    return_pack,
)
from render_public_company_artifacts import headline_metrics, render, status_text  # noqa: E402
from underwriting_contract import (  # noqa: E402
    CashFlowLedgerLine,
    assess_gate3_for_gate4,
    assess_supported_universe,
    canonical_json,
    detect_material_conflicts,
    determine_data_gate,
    finalize_output_contract,
    validate_cash_flow_ledger,
)


class PeriodSelectionTests(unittest.TestCase):
    def test_ytd_fact_is_not_relabelled_as_quarter(self) -> None:
        facts = {
            "facts": {
                "us-gaap": {
                    "NetCashProvidedByUsedInOperatingActivities": {
                        "units": {
                            "USD": [
                                {
                                    "start": "2025-09-28",
                                    "end": "2026-03-28",
                                    "val": 100,
                                    "form": "10-Q",
                                    "filed": "2026-05-01",
                                    "accn": "x",
                                }
                            ]
                        }
                    }
                }
            }
        }
        tags = ("NetCashProvidedByUsedInOperatingActivities",)
        quarter = choose_duration(facts, tags, "2026-03-28", form="10-Q", accn="x", prefer="quarter")
        ytd = choose_duration(facts, tags, "2026-03-28", form="10-Q", accn="x", prefer="ytd")
        self.assertIsNone(quarter)
        self.assertEqual(ytd["val"], 100)

    def test_ltm_requires_comparable_prior_year_ytd(self) -> None:
        tag = "RevenueFromContractWithCustomerExcludingAssessedTax"
        base_points = [
            {"start": "2025-01-01", "end": "2025-12-31", "val": 100, "form": "10-K", "filed": "2026-02-01", "accn": "k", "fp": "FY"},
            {"start": "2026-01-01", "end": "2026-06-30", "val": 60, "form": "10-Q", "filed": "2026-08-01", "accn": "q", "fp": "Q2"},
            {"start": "2025-01-01", "end": "2025-06-30", "val": 50, "form": "10-Q", "filed": "2025-08-01", "accn": "pq", "fp": "Q2"},
        ]
        facts = {"facts": {"us-gaap": {tag: {"units": {"USD": base_points}}}}}
        result = ltm_metric(facts, "revenue", "2026-06-30", "2025-12-31")
        self.assertEqual(result["period_type"], "LTM")
        self.assertEqual(result["value"], 110)

        stale_points = [base_points[0], base_points[1], {**base_points[2], "start": "2024-01-01", "end": "2024-06-30"}]
        stale_facts = {"facts": {"us-gaap": {tag: {"units": {"USD": stale_points}}}}}
        stale_result = ltm_metric(stale_facts, "revenue", "2026-06-30", "2025-12-31")
        self.assertEqual(stale_result["period_type"], "annual")
        self.assertEqual(stale_result["value"], 100)


class MarketDataTests(unittest.TestCase):
    def test_research_approval_is_distinct_from_partner_approval(self) -> None:
        self.assertTrue(market_data_is_approved({"provider_approval_status": "APPROVED_FOR_RESEARCH"}))
        self.assertTrue(market_data_is_approved({"provider_approval_status": "APPROVED_BY_PARTNER"}))
        self.assertFalse(market_data_is_approved({"provider_approval_status": "NOT_APPROVED_BY_PARTNER"}))

    def test_returns_use_exact_common_dates_and_adjusted_close(self) -> None:
        stock = [
            {"date": "2025-01-02", "close": 90, "adjusted_close": 100},
            {"date": "2026-01-02", "close": 110, "adjusted_close": 120},
        ]
        benchmark = [
            {"date": "2025-01-02", "close": 190, "adjusted_close": 200},
            {"date": "2026-01-02", "close": 210, "adjusted_close": 220},
        ]
        result = aligned_return_pair(stock, benchmark, lookback_days=365)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["start_date"], "2025-01-02")
        self.assertEqual(result["end_date"], "2026-01-02")
        self.assertAlmostEqual(result["stock_return"], 0.20)
        self.assertAlmostEqual(result["benchmark_return"], 0.10)

    def test_latest_share_count_uses_cover_date_before_price(self) -> None:
        companyfacts = {
            "facts": {
                "dei": {
                    "EntityCommonStockSharesOutstanding": {
                        "units": {
                            "shares": [
                                {"val": 100, "end": "2026-03-31", "filed": "2026-04-20", "form": "10-Q", "accn": "a"},
                                {"val": 95, "end": "2026-04-17", "filed": "2026-04-20", "form": "10-Q", "accn": "a"},
                                {"val": 90, "end": "2026-08-01", "filed": "2026-08-05", "form": "10-Q", "accn": "b"},
                            ]
                        }
                    }
                }
            }
        }
        value, point = latest_shares(companyfacts, "2026-07-15")
        self.assertEqual(value, 95)
        self.assertEqual(point["end"], "2026-04-17")
        missing_value, missing_point = latest_shares(companyfacts, "2025-12-31")
        self.assertIsNone(missing_value)
        self.assertIsNone(missing_point)


class AccountingControlTests(unittest.TestCase):
    def test_total_liabilities_can_be_derived_with_negative_equity(self) -> None:
        self.assertEqual(derive_total_liabilities(20_916_463, -2_784_552), 23_701_015)
        self.assertIsNone(derive_total_liabilities(None, 10))

    def test_current_available_for_sale_debt_securities_are_liquid_resources(self) -> None:
        self.assertIn(
            "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
            INSTANT_TAGS["short_term_investments"],
        )

    def test_composite_payable_concept_is_not_dpo_compatible(self) -> None:
        self.assertTrue(ap_balance_is_trade_compatible("us-gaap:AccountsPayableTradeCurrent"))
        self.assertFalse(
            ap_balance_is_trade_compatible("us-gaap:AccountsPayableAndOtherAccruedLiabilitiesCurrent")
        )

    def test_ap_html_fallback_rejects_cash_flow_change_fact(self) -> None:
        raw = """
        <tr><td>Accounts payable and accrued expenses</td>
        <td><ix:nonFraction name="us-gaap:IncreaseDecreaseInAccountsPayableAndAccruedLiabilities"
        sign="-" scale="6">1,897</ix:nonFraction></td></tr>
        <tr><td>Accounts payable, accrued expenses and other liabilities</td>
        <td><ix:nonFraction name="us-gaap:AccountsPayableAndOtherAccruedLiabilitiesCurrent"
        scale="6">6,582</ix:nonFraction></td></tr>
        """
        value = extract_inline_row_value(raw, "Accounts payable")
        self.assertEqual(value, (6_582_000_000.0, "us-gaap:AccountsPayableAndOtherAccruedLiabilitiesCurrent"))

    def test_exact_scaled_liquidity_table_overrides_rounded_narrative(self) -> None:
        text = """
        Liquidity March 31, 2026 (in thousands)
        Cash and cash equivalents $130,881
        Available borrowings 849,865
        We had up to $849.9 million of available borrowings.
        """
        values = extract_facility_values(text)
        self.assertEqual(values["total_available_borrowings_reported"][0], 849_865_000)
        self.assertEqual(values["total_available_borrowings_reported"][1], "parsed from scaled liquidity table")

    def test_facility_parser_links_respectively_amounts_to_reporting_dates(self) -> None:
        text = """
        The Note Agreement provided for senior notes of up to $350.0 million.
        The Credit Agreement provides for a $400.0 million revolving credit facility.
        There were $31.8 million and $37.5 million of outstanding letters of credit
        at March 31, 2026 and December 31, 2025, respectively.
        As of March 31, 2026, we had $368.2 million of borrowing availability
        under the Credit Agreement after taking into account outstanding letters of credit.
        """
        values = extract_facility_values(text, as_of_date="2026-03-31")
        self.assertEqual(values["facility_commitment"][0], 400_000_000)
        self.assertEqual(values["facility_availability_reported"][0], 368_200_000)
        self.assertEqual(values["facility_letters_of_credit"][0], 31_800_000)
        self.assertNotEqual(values["facility_commitment"][0], 350_000_000)
        reconciliation = assess_facility_reconciliation(values)
        self.assertEqual(reconciliation["status"], "PASS")
        self.assertAlmostEqual(reconciliation["gap"], 0)

    def test_facility_parser_does_not_use_prior_date_when_current_date_is_absent(self) -> None:
        text = """
        There were $31.8 million and $37.5 million of outstanding letters of credit
        at March 31, 2026 and December 31, 2025, respectively.
        """
        values = extract_facility_values(text, as_of_date="2026-06-30")
        self.assertNotIn("facility_letters_of_credit", values)

    def test_scaled_credit_agreement_limit_overrides_other_debt_instruments(self) -> None:
        text = """
        The Note Agreement provided for notes of up to $350.0 million.
        The amounts outstanding and available borrowing capacity under the Credit
        Agreement are presented below:
        March 31, December 31, (In thousands) 2026 2025
        Credit Agreement limit $400,000 $400,000
        Credit Agreement borrowings — —
        Outstanding letters of credit (31,845) (37,533)
        Credit Agreement availability $368,155 $362,467
        """
        values = extract_facility_values(text, as_of_date="2026-03-31")
        self.assertEqual(values["facility_commitment"][0], 400_000_000)
        self.assertEqual(
            values["facility_commitment"][1],
            "parsed from the explicitly scaled Credit Agreement limit table",
        )

    def test_facility_reconciliation_blocks_impossible_commitment(self) -> None:
        result = assess_facility_reconciliation(
            {
                "facility_commitment": (350_000_000, "direct commitment"),
                "facility_availability_reported": (368_200_000, "dated availability"),
                "facility_letters_of_credit": (31_800_000, "dated letters of credit"),
            }
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["known_component_total"], 400_000_000)
        self.assertEqual(result["gap"], -50_000_000)

    def test_cfo_embedded_line_cannot_be_separately_modelled(self) -> None:
        line = CashFlowLedgerLine(
            line_id="CFL-1",
            label="Cash interest",
            amount=10,
            period_start="2026-01-01",
            period_end="2026-03-31",
            treatment="USE",
            embedded_in_cfo=True,
            separately_modeled=True,
        )
        issues = validate_cash_flow_ledger([line])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_class, "HARD_STOP")
        self.assertEqual(line.double_count_status, "FAIL")


class EvidenceInputTests(unittest.TestCase):
    def test_normalized_fcf_base_can_use_shared_metric_name(self) -> None:
        ltm_result = {
            "value": 100.0,
            "period_type": "LTM",
            "method": "annual + latest YTD - prior-year YTD using one XBRL concept",
            "confidence": "High",
            "components": {"current_ytd": {"end": "2026-03-31"}},
        }
        research = {
            "normalized_fcf": {
                "status": "VALIDATED",
                "value": 100.0,
                "period_end": "2026-03-31",
                "base_evidence_metric": "reported_ltm_fcf",
                "bridge_lines": [],
                "no_adjustments_rationale": "Reported FCF is retained without adjustment.",
                "reviewed_by": "Analyst",
            }
        }
        records, _, issues = build_analysis_evidence(
            {"cik": "0000000000", "ticker": "TEST"},
            {"evidence_records": []},
            {},
            {},
            {
                "price": None,
                "price_currency": "USD",
                "price_date": "",
                "shares": None,
                "shares_as_of_date": "",
                "shares_source": {},
                "market_cap": None,
                "ltm": {"cfo": ltm_result, "capex": {**ltm_result, "value": 0.0}},
                "ltm_fcf": 100.0,
            },
            {},
            {},
            [],
            {"status": "NOT_PROVIDED"},
            research,
        )
        self.assertFalse(any(row.get("check_id") == "G2.5-normalized-fcf-bridge-integrity" for row in issues))
        normalized = next(row for row in records if row.get("metric_name") == "public_data_fcf_underwriting_base")
        reported = next(row for row in records if row.get("metric_name") == "reported_ltm_fcf")
        self.assertIn(reported["evidence_id"], normalized.get("input_evidence_ids", []))

    def test_metric_name_reference_survives_regenerated_evidence_ids(self) -> None:
        resolved, unknown = resolve_evidence_references(
            [],
            [],
            {"EV-NEW"},
            {},
            ["market_cap_point_in_time"],
            {"market_cap_point_in_time": "EV-NEW"},
        )
        self.assertEqual(resolved, {"EV-NEW"})
        self.assertEqual(unknown, [])

    def test_reviewed_downstream_evidence_resolves_matching_upstream_warnings(self) -> None:
        filing_url = "https://www.sec.gov/example-8k"
        step2 = {
            "validation_tests": [
                {"check_id": "P1-facility-note-check", "status": "PROVISIONAL", "result": "PROVISIONAL", "issue_class": "WARNING"},
                {"check_id": "P1-subsequent-event-review", "status": "PROVISIONAL", "result": "PROVISIONAL", "issue_class": "WARNING"},
            ],
            "evidence_records": [
                {"metric_name": "subsequent_event_filing_1", "source_url": filing_url}
            ],
        }
        issuer = {
            "modules": {
                "debt_leases_covenants_refinancing": {"status": "VALIDATED"}
            }
        }
        external = [
            {
                "source_url": filing_url,
                "subsequent_event_status": "REVIEWED_NO_MATERIAL_FINANCIAL_CHANGE",
            }
        ]
        reconciled = reconcile_upstream_validation_tests(step2, issuer, {}, "blocked", {}, external)
        self.assertEqual([row["status"] for row in reconciled], ["PASS", "PASS"])
        self.assertTrue(all(row["issue_class"] == "INFO" for row in reconciled))

    def test_valid_external_evidence_gets_stable_id_and_source(self) -> None:
        research = {
            "external_evidence": [
                {
                    "status": "VALIDATED",
                    "external_key": "guidance_fy26_revenue",
                    "metric_name": "management_guidance_revenue",
                    "value": "FY26 revenue growth of 5% to 7%",
                    "unit": "text",
                    "period_end": "2026-12-31",
                    "as_of_date": "2026-05-01",
                    "evidence_class": "FACT",
                    "source": {
                        "source_level": 2,
                        "source_type": "earnings_release",
                        "source_name": "Test Co earnings release",
                        "source_url": "https://example.com/release",
                        "source_locator": "FY26 Outlook, page 3",
                        "publication_date": "2026-05-01",
                        "retrieval_date": "2026-05-02",
                    },
                    "reviewed_by": "Analyst",
                }
            ]
        }
        records, sources, issues = build_external_evidence({"ticker": "TEST"}, research)
        self.assertEqual(issues, [])
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["evidence_id"].startswith("EV-"))
        self.assertEqual(records[0]["external_key"], "guidance_fy26_revenue")
        self.assertEqual(sources[0]["source_level"], 2)

    def test_invalid_validated_external_evidence_is_hard_stop(self) -> None:
        records, _, issues = build_external_evidence(
            {"ticker": "TEST"},
            {"external_evidence": [{"status": "VALIDATED", "external_key": "broken"}]},
        )
        self.assertEqual(records, [])
        self.assertEqual(issues[0]["issue_class"], "HARD_STOP")

    def test_market_expectations_require_source_dates_and_reviewer(self) -> None:
        supplied = {
            "market_expectations": {
                "status": "SOURCED",
                "summary": "Consensus expects recovery.",
                "variant_question": "Is recovery too conservative?",
                "variant_perception": "Cash conversion may recover faster.",
                "as_of_date": "2026-05-01",
                "source": {
                    "source_level": 4,
                    "source_type": "institutional_consensus",
                    "source_name": "Consensus provider",
                    "source_locator": "FY26 estimates",
                    "publication_date": "2026-05-01",
                    "retrieval_date": "2026-05-02",
                },
            }
        }
        blocked = build_market_expectations({}, {}, {}, supplied)
        self.assertEqual(blocked["consensus_status"], "NOT_SOURCED")
        self.assertEqual(blocked["validation_issues"][0]["issue_class"], "HARD_STOP")
        supplied["market_expectations"]["reviewed_by"] = "Analyst"
        sourced_only = build_market_expectations({}, {}, {}, supplied)
        self.assertEqual(sourced_only["consensus_status"], "SOURCED")
        self.assertEqual(sourced_only["variant_status"], "NOT_DEFINED")

        evidence = [
            {
                "evidence_id": f"EV-{name.upper()}",
                "external_key": name,
                "metric_name": name,
            }
            for name in ("market_view", "public_fact", "variant_fact", "disconfirming_fact")
        ]
        supplied["market_expectations"].update(
            {
                "current_public_evidence": "Public evidence still shows pressure.",
                "potential_variant": "Cash conversion may recover faster.",
                "disconfirming_evidence": "A renewed sales decline would disconfirm the view.",
                "market_evidence_keys": ["market_view"],
                "public_evidence_keys": ["public_fact"],
                "variant_evidence_keys": ["variant_fact"],
                "disconfirming_evidence_keys": ["disconfirming_fact"],
            }
        )
        validated = build_market_expectations({}, {}, {}, supplied, evidence)
        self.assertEqual(validated["variant_status"], "ANALYST_DEFINED")
        self.assertEqual(validated["variant_structure_status"], "COMPLETE")

    def test_issuer_module_resolves_external_key_and_requires_evidence(self) -> None:
        external_records, _, _ = build_external_evidence(
            {"ticker": "TEST"},
            {
                "external_evidence": [
                    {
                        "status": "VALIDATED",
                        "external_key": "business_model",
                        "metric_name": "business_model_description",
                        "value": "Subscription revenue",
                        "unit": "text",
                        "as_of_date": "2026-03-31",
                        "evidence_class": "FACT",
                        "source": {
                            "source_level": 1,
                            "source_type": "regulatory_filing",
                            "source_name": "10-K",
                            "source_url": "https://example.com/10k",
                            "source_locator": "Item 1, page 5",
                            "publication_date": "2026-02-01",
                            "retrieval_date": "2026-02-02",
                        },
                        "reviewed_by": "Analyst",
                    }
                ]
            },
        )
        research = {
            "issuer_underwriting": {
                "business_and_industry": {
                    "status": "VALIDATED",
                    "conclusion": "Subscription revenue is the primary business model.",
                    "evidence_keys": ["business_model"],
                    "reviewed_by": "Analyst",
                },
                "stress_test": {
                    "status": "VALIDATED",
                    "conclusion": "Unsupported conclusion.",
                    "evidence_ids": [],
                    "reviewed_by": "Analyst",
                },
            }
        }
        result = build_issuer_underwriting({"evidence_records": []}, {}, {"rows": []}, research, external_records)
        self.assertEqual(result["modules"]["business_and_industry"]["status"], "VALIDATED")
        self.assertEqual(len(result["modules"]["business_and_industry"]["evidence_ids"]), 1)
        self.assertTrue(any(issue["check_id"].startswith("G2-stress_test") for issue in result["validation_issues"]))

    def test_material_source_conflict_is_hard_stop(self) -> None:
        base = {
            "metric_name": "cash",
            "period_start": "",
            "period_end": "2026-03-31",
            "period_type": "instant",
            "as_of_date": "2026-03-31",
            "measurement_basis": "reported",
            "unit": "USD",
            "currency": "USD",
        }
        issues = detect_material_conflicts(
            [
                {**base, "value": 100, "evidence_id": "EV-1"},
                {**base, "value": 130, "evidence_id": "EV-2"},
            ]
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_class, "HARD_STOP")


class GateAndScenarioTests(unittest.TestCase):
    def test_public_data_does_not_auto_create_scenarios(self) -> None:
        scenarios, status = scenario_set(
            {"price": 10, "shares": 100, "p_fcf": 5},
            {"revenue_growth_reference": 0.5},
            {"indicators": []},
            {},
        )
        self.assertEqual(scenarios, [])
        self.assertEqual(status, "blocked_normalized_fcf_not_validated")

    def test_scenario_prices_do_not_require_formal_probabilities(self) -> None:
        research = {
            "normalized_fcf": {"status": "VALIDATED", "value": 100},
            "scenario_model": {
                "status": "ANALYST_VALIDATED",
                "reviewed_by": "Analyst",
                "metric": "Normalized FCF",
                "scenarios": [
                    {"name": "Bear", "metric_value_total": 80, "growth_assumption": -0.2, "exit_multiple": 8, "key_driver": "Downside", "falsification_trigger": "FCF exceeds base"},
                    {"name": "Base", "metric_value_total": 100, "growth_assumption": 0.0, "exit_multiple": 10, "key_driver": "Stable", "falsification_trigger": "FCF misses base"},
                    {"name": "Bull", "metric_value_total": 120, "growth_assumption": 0.2, "exit_multiple": 12, "key_driver": "Upside", "falsification_trigger": "FCF fails to grow"},
                ],
            },
        }
        scenarios, status = scenario_set({"price": 10, "shares": 100, "p_fcf": 10}, {}, {}, research)
        self.assertEqual(status, "scenario_assumptions_validated")
        self.assertEqual(len(scenarios), 3)
        self.assertTrue(all(row.probability is None for row in scenarios))

    def test_scenario_metric_must_reconcile_to_normalized_fcf_growth(self) -> None:
        research = {
            "normalized_fcf": {"status": "VALIDATED", "value": 100},
            "scenario_model": {
                "status": "ANALYST_VALIDATED",
                "reviewed_by": "Analyst",
                "metric": "Normalized FCF",
                "scenarios": [
                    {"name": "Bear", "probability": 0.2, "metric_value_total": 70, "growth_assumption": -0.2, "exit_multiple": 8, "key_driver": "Downside", "falsification_trigger": "FCF exceeds base"},
                    {"name": "Base", "probability": 0.5, "metric_value_total": 100, "growth_assumption": 0.0, "exit_multiple": 10, "key_driver": "Stable", "falsification_trigger": "FCF misses base"},
                    {"name": "Bull", "probability": 0.3, "metric_value_total": 120, "growth_assumption": 0.2, "exit_multiple": 12, "key_driver": "Upside", "falsification_trigger": "FCF fails to grow"},
                ],
            },
        }
        scenarios, status = scenario_set({"price": 10, "shares": 100, "p_fcf": 10}, {}, {}, research)
        self.assertEqual(scenarios, [])
        self.assertEqual(status, "blocked_bear_metric_growth_bridge_does_not_reconcile")

    def test_illustrative_probabilities_do_not_unlock_weighted_return(self) -> None:
        result = build_probability_validation(
            {"probability_framework": {"status": "ILLUSTRATIVE"}},
            self._scenarios_with_probabilities(),
            self._probability_evidence(),
            "2026-07-16",
        )
        self.assertEqual(result["status"], "ILLUSTRATIVE")
        self.assertFalse(result["weighted_return_allowed"])

    def test_validated_probability_requires_method_freshness_sensitivity_and_approval(self) -> None:
        result = build_probability_validation(
            self._validated_probability_input(),
            self._scenarios_with_probabilities(),
            self._probability_evidence(),
            "2026-07-16",
        )
        self.assertEqual(result["status"], "VALIDATED")
        self.assertTrue(result["weighted_return_allowed"])
        self.assertEqual(len(result["sensitivity_table"]), 3)

    def test_probability_expires_and_is_superseded_by_new_earnings(self) -> None:
        research = self._validated_probability_input()
        research["probability_framework"]["probability_expiration_review_date"] = "2026-07-15"
        stale = build_probability_validation(
            research,
            self._scenarios_with_probabilities(),
            self._probability_evidence(),
            "2026-07-16",
        )
        self.assertEqual(stale["status"], "STALE")

        evidence = self._probability_evidence() + [
            {"evidence_id": "EV-NEW-EARNINGS", "source_level": 2, "publication_date": "2026-07-15"}
        ]
        superseded = build_probability_validation(
            self._validated_probability_input(),
            self._scenarios_with_probabilities(),
            evidence,
            "2026-07-16",
        )
        self.assertEqual(superseded["status"], "STALE")
        self.assertEqual(superseded["freshness_status"], "SUPERSEDED")

    def test_peer_forced_comparison_blocks_invalid_rows(self) -> None:
        records = [
            {"evidence_id": "EV-PEER-1", "external_key": "peer_one_multiple", "value": 10.0},
            {"evidence_id": "EV-PEER-2", "external_key": "peer_two_multiple", "value": 12.0},
        ]
        research = {
            "peer_valuation_context": {
                "status": "VALIDATED",
                "reviewed_by": "Analyst",
                "selection_rationale": "Comparable operating model.",
                "subject": {
                    "fiscal_period_end": "2026-06-30",
                    "currency": "USD",
                    "metric_definitions": {"P/FCF": "market_cap / LTM reported FCF"},
                },
                "peers": [
                    {
                        "ticker": "GOOD",
                        "metrics": [
                            {
                                "metric": "P/FCF",
                                "value": 10.0,
                                "denominator_value": 100.0,
                                "fiscal_period_end": "2026-06-30",
                                "currency": "USD",
                                "accounting_definition": "market_cap / LTM reported FCF",
                                "evidence_keys": ["peer_one_multiple"],
                            }
                        ],
                    },
                    {
                        "ticker": "BAD",
                        "metrics": [
                            {
                                "metric": "P/FCF",
                                "value": 12.0,
                                "denominator_value": -50.0,
                                "fiscal_period_end": "2025-12-31",
                                "currency": "EUR",
                                "accounting_definition": "price / adjusted FCF",
                                "evidence_keys": ["peer_two_multiple"],
                            }
                        ],
                    },
                ],
            }
        }
        result = build_peer_valuation_context(research, records)
        good, bad = result["rows"]
        self.assertTrue(good["auto_rank_allowed"])
        self.assertFalse(bad["auto_rank_allowed"])
        self.assertIn("negative_fcf", bad["comparability_flags"])
        self.assertIn("different_fiscal_period", bad["comparability_flags"])
        self.assertIn("currency_mismatch", bad["comparability_flags"])
        self.assertIn("accounting_definition_mismatch", bad["comparability_flags"])
        self.assertEqual(
            result["metric_summaries"][0]["ranking_status"],
            "SUPPRESSED_INSUFFICIENT_COMPARABLE_PEERS",
        )

    @staticmethod
    def _scenarios_with_probabilities():
        research = {
            "normalized_fcf": {"status": "VALIDATED", "value": 100},
            "scenario_model": {
                "status": "ANALYST_VALIDATED",
                "reviewed_by": "Analyst",
                "metric": "Normalized FCF",
                "scenarios": [
                    {"name": "Bear", "probability": 0.25, "probability_rationale": "Downside case.", "metric_value_total": 80, "growth_assumption": -0.2, "exit_multiple": 8, "key_driver": "Downside", "falsification_trigger": "FCF exceeds base"},
                    {"name": "Base", "probability": 0.50, "probability_rationale": "Central case.", "metric_value_total": 100, "growth_assumption": 0.0, "exit_multiple": 10, "key_driver": "Stable", "falsification_trigger": "FCF misses base"},
                    {"name": "Bull", "probability": 0.25, "probability_rationale": "Upside case.", "metric_value_total": 120, "growth_assumption": 0.2, "exit_multiple": 12, "key_driver": "Upside", "falsification_trigger": "FCF fails to grow"},
                ],
            },
        }
        scenarios, status = scenario_set({"price": 10, "shares": 100, "p_fcf": 10}, {}, {}, research)
        if status != "scenario_assumptions_validated":
            raise AssertionError(status)
        return scenarios

    @staticmethod
    def _probability_evidence():
        return [
            {
                "evidence_id": "EV-PROBABILITY",
                "external_key": "probability_basis",
                "metric_name": "probability_basis",
                "source_level": 2,
                "publication_date": "2026-05-01",
            }
        ]

    @staticmethod
    def _validated_probability_input():
        return {
            "probability_framework": {
                "status": "VALIDATED",
                "method_type": "SCENARIO_JUDGMENT",
                "methodology": "Allocate weights from explicit operating signposts, then test three alternative weight sets.",
                "method_details": {
                    "allocation_rationale": "Base receives the highest weight because current guidance brackets the central case.",
                    "sensitivity_completed": True,
                },
                "evidence_keys": ["probability_basis"],
                "scenario_rationales": {
                    "Bear": "Demand and margin both miss the central case.",
                    "Base": "Current operating evidence remains near the central case.",
                    "Bull": "Demand and cash conversion exceed the central case.",
                },
                "as_of_date": "2026-07-01",
                "probability_expiration_review_date": "2026-10-01",
                "review_triggers": ["NEW_EARNINGS_OR_GUIDANCE"],
                "reviewed_by": "Analyst",
                "approval": {"status": "APPROVED", "approved_by": "Investment Committee", "approval_date": "2026-07-02"},
                "sensitivity_cases": [
                    {"label": "Downside weighted", "probabilities": {"Bear": 0.50, "Base": 0.35, "Bull": 0.15}},
                    {"label": "Central", "probabilities": {"Bear": 0.25, "Base": 0.50, "Bull": 0.25}},
                    {"label": "Upside weighted", "probabilities": {"Bear": 0.15, "Base": 0.35, "Bull": 0.50}},
                ],
            }
        }

    def test_gate_suppresses_unsafe_outputs(self) -> None:
        gate = determine_data_gate(
            issues=[],
            core_data_validated=True,
            issuer_underwriting_complete=False,
            valuation_validated=False,
            scenarios_validated=False,
            portfolio_inputs_validated=False,
            human_approval=False,
        )
        contract = minimal_contract(gate)
        contract["probability_weighted_return"] = 0.2
        contract["target_price"] = 15
        contract["position_sizing"] = "1%"
        final = finalize_output_contract(contract)
        self.assertIsNone(final["probability_weighted_return"])
        self.assertIsNone(final["target_price"])
        self.assertIsNone(final["position_sizing"])
        self.assertEqual(final["portfolio_action"], "Not Evaluated")
        self.assertEqual(final["contract_validation"]["status"], "PASS")


class Gate4EligibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        contract_path = (
            TEST_DIR.parent
            / "friday_v1_outputs"
            / "crox_crocs_inc"
            / "step3"
            / "underwriting_output_contract.json"
        )
        cls.contract = json.loads(contract_path.read_text(encoding="utf-8"))
        cls.autozone_contract = json.loads(
            (
                TEST_DIR.parent
                / "friday_v1_outputs"
                / "azo_autozone_inc"
                / "step3"
                / "underwriting_output_contract.json"
            ).read_text(encoding="utf-8")
        )

    def rehash(self, contract: dict[str, object]) -> None:
        hash_input = {
            key: value
            for key, value in contract.items()
            if key not in {"contract_hash", "contract_validation"}
        }
        contract["contract_hash"] = hashlib.sha256(
            canonical_json(hash_input).encode("utf-8")
        ).hexdigest()

    def policy(self, **overrides: object) -> dict[str, object]:
        policy: dict[str, object] = {
            "max_report_age_days": 2,
            "max_financial_data_age_days": 150,
            "max_market_data_age_days": 5,
            "max_public_source_check_lag_days": 1,
            "eligible_valuation_statuses": [
                "RANGE_ONLY",
                "PARTIALLY_VALIDATED",
                "MULTI_METHOD_VALIDATED",
            ],
            "require_validated_probabilities": False,
            "allow_warning_escalation": True,
        }
        policy.update(overrides)
        return policy

    def attestation(self, **overrides: object) -> dict[str, object]:
        warning_ids = [
            "G3-probability-validation",
            "G3-peer-valuation-context",
            "G3-probability-methodology",
        ]
        attestation: dict[str, object] = {
            "gate3_report_id": self.contract["report_id"],
            "gate3_contract_hash": self.contract["contract_hash"],
            "as_of_date": "2026-07-17",
            "latest_earnings_checked_through": "2026-07-17",
            "latest_known_financial_filing_date": "2026-04-30",
            "newer_earnings_filing_known": False,
            "subsequent_events_checked_through": "2026-07-17",
            "unreviewed_material_subsequent_event_known": False,
            "reviewed_by": "Eligibility test reviewer",
            "reviewed_at": "2026-07-17T12:00:00Z",
            "warning_escalations": [
                {
                    "check_id": warning_id,
                    "reviewed_by": "Eligibility test reviewer",
                    "review_date": "2026-07-17",
                    "rationale": "Accepted for the historical Gate 4 interface test.",
                }
                for warning_id in warning_ids
            ],
        }
        attestation.update(overrides)
        return attestation

    def test_fresh_gate3_contract_reaches_private_inputs_required(self) -> None:
        result = assess_gate3_for_gate4(
            self.contract,
            policy=self.policy(),
            freshness_attestation=self.attestation(),
        )
        self.assertEqual(result["status"], "GATE_4_PRIVATE_INPUTS_REQUIRED")
        self.assertTrue(result["eligible"])
        self.assertEqual(result["blocking_check_ids"], [])
        self.assertEqual(
            result["escalated_warning_ids"],
            [
                "G3-peer-valuation-context",
                "G3-probability-methodology",
                "G3-probability-validation",
            ],
        )

    def test_gate4_policy_has_no_hidden_defaults(self) -> None:
        result = assess_gate3_for_gate4(
            self.contract,
            policy=None,
            freshness_attestation=self.attestation(),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_INELIGIBLE_GATE_3")
        self.assertIn("G4E-policy-completeness", result["ineligible_check_ids"])

    def test_range_only_requires_explicit_policy_eligibility(self) -> None:
        result = assess_gate3_for_gate4(
            self.contract,
            policy=self.policy(eligible_valuation_statuses=["MULTI_METHOD_VALIDATED"]),
            freshness_attestation=self.attestation(),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_INELIGIBLE_GATE_3")
        self.assertIn("G4E-valuation-eligibility", result["ineligible_check_ids"])

    def test_probability_requirement_blocks_illustrative_weights(self) -> None:
        result = assess_gate3_for_gate4(
            self.contract,
            policy=self.policy(require_validated_probabilities=True),
            freshness_attestation=self.attestation(),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_INELIGIBLE_GATE_3")
        self.assertIn("G4E-probability-freshness", result["ineligible_check_ids"])

    def test_unresolved_issuer_warning_blocks_gate4(self) -> None:
        result = assess_gate3_for_gate4(
            self.contract,
            policy=self.policy(),
            freshness_attestation=self.attestation(warning_escalations=[]),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_INELIGIBLE_GATE_3")
        self.assertIn(
            "G4E-warning:G3-peer-valuation-context",
            result["ineligible_check_ids"],
        )

    def test_fresh_autozone_contract_uses_same_gate4_rules(self) -> None:
        warning_ids = [
            "P0-current-debt-vs-lease-check",
            "G3-probability-validation",
            "G3-peer-valuation-context",
        ]
        result = assess_gate3_for_gate4(
            self.autozone_contract,
            policy=self.policy(),
            freshness_attestation=self.attestation(
                gate3_report_id=self.autozone_contract["report_id"],
                gate3_contract_hash=self.autozone_contract["contract_hash"],
                latest_known_financial_filing_date="2026-06-12",
                warning_escalations=[
                    {
                        "check_id": warning_id,
                        "reviewed_by": "Eligibility test reviewer",
                        "review_date": "2026-07-17",
                        "rationale": "Accepted for the cross-company Gate 4 interface test.",
                    }
                    for warning_id in warning_ids
                ],
            ),
        )
        self.assertEqual(result["status"], "GATE_4_PRIVATE_INPUTS_REQUIRED")
        self.assertTrue(result["eligible"])
        self.assertEqual(result["blocking_check_ids"], [])

    def test_stale_market_data_blocks_gate4(self) -> None:
        result = assess_gate3_for_gate4(
            self.contract,
            policy=self.policy(max_report_age_days=30),
            freshness_attestation=self.attestation(
                as_of_date="2026-07-28",
                latest_earnings_checked_through="2026-07-28",
                subsequent_events_checked_through="2026-07-28",
                reviewed_at="2026-07-28T12:00:00Z",
                warning_escalations=[
                    {
                        "check_id": warning_id,
                        "reviewed_by": "Eligibility test reviewer",
                        "review_date": "2026-07-28",
                        "rationale": "Accepted for the stale-market-data test.",
                    }
                    for warning_id in [
                        "G3-probability-validation",
                        "G3-peer-valuation-context",
                        "G3-probability-methodology",
                    ]
                ],
            ),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_STALE_GATE_3")
        self.assertIn("G4E-market-data-age", result["stale_check_ids"])

    def test_newer_earnings_filing_blocks_gate4_as_stale(self) -> None:
        result = assess_gate3_for_gate4(
            self.contract,
            policy=self.policy(),
            freshness_attestation=self.attestation(
                newer_earnings_filing_known=True,
                latest_known_financial_filing_date="2026-07-17",
            ),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_STALE_GATE_3")
        self.assertIn("G4E-newer-earnings", result["stale_check_ids"])

    def test_data_hard_stop_cannot_be_escalated(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["hard_stops"] = [
            {
                "check_id": "P0-test-hard-stop",
                "status": "FAIL",
                "issue_class": "HARD_STOP",
            }
        ]
        self.rehash(contract)
        attestation = self.attestation()
        attestation["warning_escalations"].append(
            {
                "check_id": "P0-test-hard-stop",
                "reviewed_by": "Eligibility test reviewer",
                "review_date": "2026-07-17",
                "rationale": "Attempted escalation must not work.",
            }
        )
        result = assess_gate3_for_gate4(
            contract,
            policy=self.policy(),
            freshness_attestation=attestation,
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_INELIGIBLE_GATE_3")
        self.assertIn("G4E-data-hard-stops", result["ineligible_check_ids"])

    def test_unsupported_contract_schema_blocks_gate4(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["schema_version"] = "999.0.0"
        self.rehash(contract)
        result = assess_gate3_for_gate4(
            contract,
            policy=self.policy(),
            freshness_attestation=self.attestation(
                gate3_contract_hash=contract["contract_hash"],
            ),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_INELIGIBLE_GATE_3")
        self.assertIn("G4E-contract-version", result["ineligible_check_ids"])

    def test_modified_contract_with_stale_hash_blocks_gate4(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["action_view"] = "Modified after validation"
        result = assess_gate3_for_gate4(
            contract,
            policy=self.policy(),
            freshness_attestation=self.attestation(
                gate3_contract_hash=contract["contract_hash"],
            ),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_INELIGIBLE_GATE_3")
        self.assertIn("G4E-contract-hash", result["ineligible_check_ids"])

    def test_stored_pass_cannot_bypass_current_contract_validation(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract.pop("investment_question")
        self.rehash(contract)
        result = assess_gate3_for_gate4(
            contract,
            policy=self.policy(),
            freshness_attestation=self.attestation(
                gate3_contract_hash=contract["contract_hash"],
            ),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_INELIGIBLE_GATE_3")
        self.assertIn("G4E-contract-validation", result["ineligible_check_ids"])
        self.assertTrue(result["contract_validation_errors"])

    def test_freshness_attestation_is_bound_to_exact_gate3_contract(self) -> None:
        result = assess_gate3_for_gate4(
            self.contract,
            policy=self.policy(),
            freshness_attestation=self.attestation(
                gate3_contract_hash="0" * 64,
            ),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_INELIGIBLE_GATE_3")
        self.assertIn(
            "G4E-attestation-contract-identity",
            result["ineligible_check_ids"],
        )

    def test_expired_probability_blocks_even_when_probabilities_are_optional(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["probability_validation"]["expiration_review_date"] = "2026-07-16"
        self.rehash(contract)
        result = assess_gate3_for_gate4(
            contract,
            policy=self.policy(),
            freshness_attestation=self.attestation(
                gate3_contract_hash=contract["contract_hash"],
            ),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_STALE_GATE_3")
        self.assertIn("G4E-probability-freshness", result["stale_check_ids"])

    def test_probability_without_review_expiration_blocks_as_stale(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["probability_validation"]["expiration_review_date"] = None
        self.rehash(contract)
        result = assess_gate3_for_gate4(
            contract,
            policy=self.policy(),
            freshness_attestation=self.attestation(
                gate3_contract_hash=contract["contract_hash"],
            ),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_STALE_GATE_3")
        self.assertIn("G4E-probability-freshness", result["stale_check_ids"])

    def test_unknown_probability_freshness_blocks_as_stale(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["probability_validation"]["freshness_status"] = None
        self.rehash(contract)
        result = assess_gate3_for_gate4(
            contract,
            policy=self.policy(),
            freshness_attestation=self.attestation(
                gate3_contract_hash=contract["contract_hash"],
            ),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_STALE_GATE_3")
        self.assertIn("G4E-probability-freshness", result["stale_check_ids"])

    def test_invalid_reviewer_timestamp_blocks_as_stale(self) -> None:
        result = assess_gate3_for_gate4(
            self.contract,
            policy=self.policy(),
            freshness_attestation=self.attestation(reviewed_at="not-a-date"),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_STALE_GATE_3")
        self.assertIn("G4E-freshness-attestation", result["stale_check_ids"])

    def test_attestation_cannot_predate_gate3_report(self) -> None:
        result = assess_gate3_for_gate4(
            self.contract,
            policy=self.policy(max_report_age_days=30),
            freshness_attestation=self.attestation(
                reviewed_at="2026-07-16T12:00:00Z",
            ),
        )
        self.assertEqual(result["status"], "GATE_4_BLOCKED_STALE_GATE_3")
        self.assertIn("G4E-attestation-chronology", result["stale_check_ids"])


class Gate4OverlayContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract_path = (
            TEST_DIR.parent
            / "friday_v1_outputs"
            / "crox_crocs_inc"
            / "step3"
            / "underwriting_output_contract.json"
        )
        cls.contract = json.loads(cls.contract_path.read_text(encoding="utf-8"))

    def test_loader_accepts_only_shared_gate3_contract(self) -> None:
        contract, resolved = load_gate3_contract(self.contract_path.parent)
        self.assertEqual(resolved, self.contract_path)
        self.assertEqual(contract["contract_hash"], self.contract["contract_hash"])
        with self.assertRaises(FileNotFoundError):
            load_gate3_contract(Path("CROX"))
        with self.assertRaises(ValueError):
            load_gate3_contract(self.contract_path.parent / "step3_data.json")

    def test_stale_gate3_suppresses_return_inputs(self) -> None:
        overlay = {
            "internal_expected_return": "25%",
            "internal_bear_case": "-15%",
            "internal_bull_case": "40%",
        }
        returns = return_pack(self.contract, overlay, gate3_eligible=False)
        self.assertIsNone(returns["expected_return"])
        self.assertIsNone(returns["bear_case"])
        self.assertIsNone(returns["bull_case"])
        self.assertTrue(returns["suppressed_for_gate3_ineligibility"])

    def test_legacy_approved_fields_cannot_unlock_gate4_before_s03(self) -> None:
        policy = {
            "max_report_age_days": 2,
            "max_financial_data_age_days": 150,
            "max_market_data_age_days": 5,
            "max_public_source_check_lag_days": 1,
            "eligible_valuation_statuses": ["RANGE_ONLY"],
            "require_validated_probabilities": False,
            "allow_warning_escalation": True,
        }
        warning_ids = [
            "G3-probability-validation",
            "G3-peer-valuation-context",
            "G3-probability-methodology",
        ]
        attestation = {
            "gate3_report_id": self.contract["report_id"],
            "gate3_contract_hash": self.contract["contract_hash"],
            "as_of_date": "2026-07-17",
            "latest_earnings_checked_through": "2026-07-17",
            "latest_known_financial_filing_date": "2026-04-30",
            "newer_earnings_filing_known": False,
            "subsequent_events_checked_through": "2026-07-17",
            "unreviewed_material_subsequent_event_known": False,
            "reviewed_by": "Synthetic test reviewer",
            "reviewed_at": "2026-07-17T12:00:00Z",
            "warning_escalations": [
                {
                    "check_id": warning_id,
                    "reviewed_by": "Synthetic test reviewer",
                    "review_date": "2026-07-17",
                    "rationale": "Accepted for the fail-closed interface test.",
                }
                for warning_id in warning_ids
            ],
        }
        overlay = {
            "overlay_mode": "REAL_PARTNER_INPUT",
            "input_status": "VALIDATED",
            "reviewed_by": "Synthetic test reviewer",
            "internal_expected_return": "30%",
            "internal_bear_case": "-10%",
            "internal_bull_case": "50%",
            "target_return_hurdle": "20%",
            "max_bear_case_downside": "-20%",
            "internal_variant_view": "Synthetic differentiated view",
            "internal_conviction": "High",
            "catalyst_quality": "High",
            "existing_exposure": "none",
            "opportunity_cost_view": "better",
            "max_position_size": "5%",
            "human_approval": "APPROVED",
            "approved_by": "Synthetic approver",
            "approved_portfolio_action": "Buy",
            "approved_position_range": "1%-2%",
        }
        eligibility = assess_gate3_for_gate4(
            self.contract,
            policy=policy,
            freshness_attestation=attestation,
        )
        returns = return_pack(self.contract, overlay, gate3_eligible=True)
        gates = overlay_gates(self.contract, overlay, returns, eligibility)
        action, sizing, _, _ = choose_overlay_action(gates, overlay, returns)
        gate_map = {gate.gate_id: gate for gate in gates}

        self.assertEqual(eligibility["status"], "GATE_4_PRIVATE_INPUTS_REQUIRED")
        self.assertEqual(gate_map["O2-overlay-mode"].result, "BLOCKED")
        self.assertEqual(action, "Not Evaluated")
        self.assertEqual(sizing, "No position sizing")

    def test_build_overlay_does_not_rebuild_or_modify_gate3_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            step3_dir = Path(tmp) / "step3"
            step3_dir.mkdir()
            copied_contract = step3_dir / "underwriting_output_contract.json"
            original_bytes = self.contract_path.read_bytes()
            copied_contract.write_bytes(original_bytes)
            overlay_path = Path(tmp) / "overlay.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "data_classification": "SYNTHETIC_PUBLIC_EXAMPLE",
                        "overlay_mode": "ILLUSTRATIVE_DEMO_NOT_FUND_DATA",
                        "gate3_eligibility_policy": {
                            "max_report_age_days": 30,
                            "max_financial_data_age_days": 180,
                            "max_market_data_age_days": 5,
                            "max_public_source_check_lag_days": 1,
                            "eligible_valuation_statuses": ["RANGE_ONLY"],
                            "require_validated_probabilities": False,
                            "allow_warning_escalation": True,
                        },
                        "gate3_freshness_attestation": {
                            "gate3_report_id": self.contract["report_id"],
                            "gate3_contract_hash": self.contract["contract_hash"],
                            "as_of_date": "2026-07-28",
                            "latest_earnings_checked_through": "2026-07-28",
                            "latest_known_financial_filing_date": "2026-04-30",
                            "newer_earnings_filing_known": False,
                            "subsequent_events_checked_through": "2026-07-28",
                            "unreviewed_material_subsequent_event_known": False,
                            "reviewed_by": "Synthetic test reviewer",
                            "reviewed_at": "2026-07-28T12:00:00Z",
                            "warning_escalations": [
                                {
                                    "check_id": warning_id,
                                    "reviewed_by": "Synthetic test reviewer",
                                    "review_date": "2026-07-28",
                                    "rationale": "Accepted only to isolate the stale-contract control.",
                                }
                                for warning_id in [
                                    "G3-probability-validation",
                                    "G3-peer-valuation-context",
                                    "G3-probability-methodology",
                                ]
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            output_dir = build_overlay(
                step3_dir,
                overlay_path,
                Path(tmp) / "public_demo_output",
            )
            eligibility = json.loads(
                (output_dir / "gate4_gate3_eligibility.json").read_text(encoding="utf-8")
            )
            overlay_output = json.loads(
                (output_dir / "portfolio_overlay_demo.json").read_text(encoding="utf-8")
            )

            self.assertEqual(copied_contract.read_bytes(), original_bytes)
            self.assertEqual(eligibility["status"], "GATE_4_BLOCKED_STALE_GATE_3")
            self.assertIn("G4E-market-data-age", eligibility["stale_check_ids"])
            self.assertEqual(overlay_output["gate4_status"], "GATE_4_BLOCKED_STALE_GATE_3")
            self.assertEqual(overlay_output["overlay_action_view"], "Not Evaluated")
            self.assertTrue(overlay_output["returns"]["suppressed_for_gate3_ineligibility"])
            self.assertIsNone(overlay_output["returns"]["expected_return"])
            self.assertIsNone(overlay_output["public_expected_return"])


class SupportedUniverseTests(unittest.TestCase):
    def test_financial_company_requires_overlay(self) -> None:
        result = assess_supported_universe(forms=["10-K", "10-Q"], taxonomies=["us-gaap"], sic="6021")
        self.assertEqual(result["status"], "SPECIALIZED_OVERLAY_REQUIRED")
        self.assertEqual(result["overlay_required"], "financial_institution")

    def test_unsupported_issuer_produces_gate_zero_diagnostic(self) -> None:
        step2 = {
            "company": {"name": "Foreign Issuer", "ticker": "FPI", "cik": "1"},
            "supported_universe": {
                "status": "SPECIALIZED_OVERLAY_REQUIRED",
                "overlay_required": "foreign_private_issuer",
                "reasons": ["20-F reporting requires a specialized period map."],
            },
            "as_of_registry": {},
            "source_registry": [],
            "evidence_records": [],
            "cash_flow_ledger": [],
            "hard_stops": [{"check_id": "P0-supported-universe", "status": "BLOCKED", "issue_class": "HARD_STOP"}],
            "warnings": [],
            "validation_tests": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            step3_dir = build_unsupported_investment_output(step2, Path(tmp))
            contract = json.loads((step3_dir / "underwriting_output_contract.json").read_text(encoding="utf-8"))
            self.assertEqual(contract["data_gate"]["level"], 0)
            self.assertEqual(contract["research_workflow_status"], "Data Review Required")
            self.assertEqual(contract["public_data_investment_view"], "Continue Research")
            self.assertEqual(contract["contract_validation"]["status"], "PASS")


class RenderingContractTests(unittest.TestCase):
    def test_status_text_uses_research_workflow_status(self) -> None:
        contract = {
            "research_workflow_status": "Ready for Human Review",
            "investment_decision_summary": {"current_action": "Watch"},
            "data_gate": {"level": 3},
            "decision_confidence": {"level": "Medium"},
        }
        action, gate, confidence = status_text(contract)
        self.assertEqual(action, "Ready for Human Review / 可供人工审阅")
        self.assertEqual(gate, "Gate 3 / 数据门禁 3")
        self.assertEqual(confidence, "Medium / 中")

    def test_headline_metrics_uses_selected_multiple_and_cash_fallback(self) -> None:
        contract = {
            "report_dates": {"market_price_date": "2026-07-15"},
            "valuation": {"price": 100.0},
            "valuation_framework": {"reverse_valuation": {"selected_multiple": 25.0}},
            "fcf_underwriting_base": {"value": 1_000_000_000, "normalization_status": "UNADJUSTED_PUBLIC_BASE"},
            "probability_validation": {"status": "NOT_PROVIDED"},
            "evidence_records": [
                {
                    "evidence_id": "EV-PRICE",
                    "metric_name": "market_price_unadjusted_close",
                    "value": 100.0,
                    "unit": "USD/share",
                },
                {
                    "evidence_id": "EV-NFCF",
                    "metric_name": "public_data_fcf_underwriting_base",
                    "value": 1_000_000_000,
                    "unit": "USD",
                },
                {
                    "evidence_id": "EV-REQ",
                    "metric_name": "reverse_valuation_required_metric_value",
                    "value": 1_200_000_000,
                    "unit": "USD",
                },
                {
                    "evidence_id": "EV-LIQ",
                    "metric_name": "available_liquidity_before_facility_notes",
                    "value": 2_000_000_000,
                    "unit": "USD",
                },
            ],
        }
        rendered = headline_metrics(contract)
        self.assertIn("FCF required at 25.0x", rendered)
        self.assertIn("Cash + short-term investments", rendered)
        self.assertIn("Excludes unstructured facility availability", rendered)
        self.assertNotIn("FCF required at 10x", rendered)

    def test_one_page_and_full_report_share_contract_identity(self) -> None:
        gate = determine_data_gate(
            issues=[],
            core_data_validated=True,
            issuer_underwriting_complete=False,
            valuation_validated=False,
            scenarios_validated=False,
            portfolio_inputs_validated=False,
            human_approval=False,
        )
        contract = finalize_output_contract(minimal_contract(gate))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            manifest = render(contract_path, root / "out")
            one = Path(manifest["outputs"]["one_page_html"]).read_text(encoding="utf-8")
            full = Path(manifest["outputs"]["full_report_html"]).read_text(encoding="utf-8")
            for value in (contract["report_id"], contract["contract_hash"]):
                self.assertIn(value, one)
                self.assertIn(value, full)
            self.assertNotIn("EV-1", one)
            self.assertNotIn("EV-1", full)
            appendix = Path(manifest["outputs"]["evidence_appendix_html"]).read_text(encoding="utf-8")
            self.assertIn("EV-1", appendix)


class FridayV1RegressionTests(unittest.TestCase):
    @staticmethod
    def _contract(company_slug: str) -> dict[str, object]:
        path = TEST_DIR.parent / "friday_v1_outputs" / company_slug / "step3" / "underwriting_output_contract.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_crox_semantics_and_decision_boundaries(self) -> None:
        contract = self._contract("crox_crocs_inc")
        self.assertEqual(contract["contract_validation"]["status"], "PASS")
        self.assertEqual(contract["research_workflow_status"], "Ready for Human Review")
        self.assertEqual(contract["public_data_investment_view"], "Watch")
        self.assertEqual(contract["fcf_underwriting_base"]["normalization_status"], "PARTIALLY_NORMALIZED")
        self.assertEqual(contract["valuation_status"]["status"], "RANGE_ONLY")
        self.assertEqual(contract["share_count_basis"]["proxy_status"], "PROXY")
        self.assertEqual(contract["probability_validation"]["status"], "ILLUSTRATIVE")
        self.assertEqual(
            contract["probability_validation"]["formal_probability_weighted_expected_return_status"],
            "NOT_EVALUATED",
        )
        self.assertIsNone(contract["probability_weighted_expected_return"])
        self.assertIsNone(contract["position_sizing"])
        self.assertEqual(contract["portfolio_action"], "Not Evaluated")

    def test_autozone_uses_unadjusted_base_and_no_probabilities(self) -> None:
        contract = self._contract("azo_autozone_inc")
        self.assertEqual(contract["contract_validation"]["status"], "PASS")
        self.assertEqual(contract["fcf_underwriting_base"]["normalization_status"], "UNADJUSTED_PUBLIC_BASE")
        self.assertEqual(contract["probability_validation"]["status"], "NOT_PROVIDED")
        self.assertTrue(all(row.get("probability") is None for row in contract["scenarios"]))
        self.assertEqual(contract["share_count_basis"]["proxy_status"], "PROXY")

    def test_scenario_outputs_are_price_sensitivities_without_horizon(self) -> None:
        for slug in ("crox_crocs_inc", "azo_autozone_inc"):
            contract = self._contract(slug)
            self.assertFalse(contract["return_context"]["formal_return_language_allowed"])
            price = float(contract["valuation"]["price"])
            shares = float(contract["share_count_basis"]["share_count_value"])
            records = {row["metric_name"]: row for row in contract["evidence_records"]}
            for scenario in contract["scenarios"]:
                self.assertNotIn("target_price", scenario)
                self.assertNotIn("total_return", scenario)
                metric = float(records[f"scenario_{scenario['name'].lower()}_metric_value"]["value"])
                expected_price = metric * float(scenario["exit_multiple"]) / shares
                self.assertAlmostEqual(float(scenario["implied_price"]), expected_price, places=8)
                self.assertAlmostEqual(
                    float(scenario["price_change_vs_current"]),
                    expected_price / price - 1,
                    places=8,
                )

    def test_priced_in_math_is_reproducible(self) -> None:
        for slug in ("crox_crocs_inc", "azo_autozone_inc"):
            contract = self._contract(slug)
            priced = contract["what_is_priced_in"]
            market_cap = float(contract["valuation"]["market_cap"])
            expected = market_cap / float(priced["selected_multiple"])
            self.assertAlmostEqual(float(priced["required_fcf"]), expected, places=6)
            self.assertEqual(priced["multiple_status"], "ANALYST_OWNED_REFERENCE")

    def test_evidence_aliases_are_complete_and_raw_ids_are_separate(self) -> None:
        contract = self._contract("crox_crocs_inc")
        raw_ids = {row["evidence_id"] for row in contract["evidence_records"]}
        mapped_ids = {row["evidence_id"] for row in contract["evidence_display_index"]}
        self.assertEqual(raw_ids, mapped_ids)
        self.assertTrue(contract["evidence_bundles"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = TEST_DIR.parent / "friday_v1_outputs" / "crox_crocs_inc" / "step3" / "underwriting_output_contract.json"
            manifest = render(source, root)
            one = Path(manifest["outputs"]["one_page_html"]).read_text(encoding="utf-8")
            full = Path(manifest["outputs"]["full_report_html"]).read_text(encoding="utf-8")
            appendix = Path(manifest["outputs"]["evidence_appendix_html"]).read_text(encoding="utf-8")
            self.assertNotIn("EV-", one)
            self.assertNotIn("EV-", full)
            self.assertIn("EV-", appendix)
            self.assertIn("Scenario Price Sensitivity", one)
            self.assertIn("Price change vs current", one)
            self.assertNotIn("Scenario Return Frame", one)

    def test_one_page_and_full_report_have_shared_contract_identity(self) -> None:
        contract = self._contract("azo_autozone_inc")
        with tempfile.TemporaryDirectory() as tmp:
            source = TEST_DIR.parent / "friday_v1_outputs" / "azo_autozone_inc" / "step3" / "underwriting_output_contract.json"
            manifest = render(source, Path(tmp))
            for key in ("one_page_html", "full_report_html", "evidence_appendix_html", "qa_summary_html"):
                text = Path(manifest["outputs"][key]).read_text(encoding="utf-8")
                self.assertIn(contract["report_id"], text)
                self.assertIn(str(contract["contract_hash"]), text)


def minimal_contract(gate: dict[str, object]) -> dict[str, object]:
    module = {
        "status": "INCOMPLETE",
        "conclusion": "Not complete.",
        "evidence_ids": ["EV-1"],
        "limitations": ["More evidence required."],
    }
    return {
        "schema_version": "5.0.0",
        "report_id": "RPT-TEST",
        "company": {"name": "Test Co", "ticker": "TEST", "cik": "1"},
        "investment_question": {"text": "Not Defined", "status": "NOT_DEFINED"},
        "report_dates": {"financial_statement_date": "2026-03-31", "market_price_date": "2026-07-01"},
        "data_gate": gate,
        "validation_status": "PASS_WITH_WARNINGS",
        "product_positioning": "Public-Data Issuer Underwriting and IC Pre-Read System - Friday V1",
        "research_workflow_status": "Underwriting In Progress",
        "public_data_investment_view": "Continue Research",
        "decision_confidence": {
            "level": "Low",
            "supports": ["Data boundaries are explicit."],
            "constraints": ["Question missing."],
            "evidence_to_increase": ["Complete issuer underwriting."],
            "events_to_reduce": ["A source conflict is identified."],
            "limitations": ["Question missing."],
        },
        "current_action": "Underwriting In Progress",
        "current_action_rationale": "More work required.",
        "core_investment_view": "More work required.",
        "key_debates": [
            {
                "title": "Cash conversion / 现金转化",
                "market_view": "Not Sourced",
                "alternative_view": "Not Formed",
                "missing_evidence": "Normalized FCF",
                "resolution_kpi_or_event": "Validated bridge",
                "decision_impact": "Valuation",
                "market_evidence_ids": [],
                "alternative_evidence_ids": ["EV-1"],
            }
        ],
        "what_can_be_concluded": ["Preliminary facts are available."],
        "what_cannot_be_concluded": ["Expected return."],
        "evidence_required_next": ["Normalized FCF."],
        "issuer_underwriting": {
            "modules": {
                "business_and_industry": module,
                "earnings_quality": module,
                "working_capital_and_cash_conversion": module,
                "liquidity_sources_and_uses": module,
                "debt_leases_covenants_refinancing": module,
                "stress_test": module,
            }
        },
        "evidence_records": [
            {
                "evidence_id": "EV-1",
                "metric_name": "unrestricted_cash",
                "value": 1000000,
                "unit": "USD",
                "period_start": "",
                "period_end": "2026-03-31",
                "as_of_date": "2026-03-31",
                "evidence_class": "FACT",
                "source_id": "SRC-1",
                "source_level": 1,
                "source_locator": "Balance sheet, cash line",
                "publication_date": "2026-05-01",
                "retrieval_date": "2026-05-02",
                "input_evidence_ids": [],
            }
        ],
        "evidence_display_index": [{"display_id": "E001", "evidence_id": "EV-1"}],
        "evidence_bundles": [
            {
                "bundle_id": "B1",
                "section_key": "executive_and_priced_in",
                "label": "Executive evidence / 执行摘要证据",
                "evidence_ids": ["EV-1"],
                "display_ids": ["E001"],
                "source_ids": ["SRC-1"],
                "record_count": 1,
            }
        ],
        "source_registry": [
            {
                "source_id": "SRC-1",
                "source_level": 1,
                "source_name": "Test Co 10-Q",
                "retrieval_date": "2026-05-02",
            }
        ],
        "cash_flow_ledger": [],
        "market_expectations": {"consensus_status": "NOT_SOURCED", "summary_view": "Not Sourced"},
        "return_context": {
            "status": "NOT_DEFINED",
            "valuation_as_of_date": "2026-07-01",
            "target_date": None,
            "holding_period": None,
            "metric_period": None,
            "dividend_assumption": None,
            "share_count_basis": "POINT_IN_TIME",
            "formal_return_language_allowed": False,
        },
        "fcf_underwriting_base": {
            "status": "NOT_VALIDATED",
            "calculation_validation_status": "NOT_VALIDATED",
            "normalization_status": "UNADJUSTED_PUBLIC_BASE",
            "bridge_lines": [],
            "unresolved_items": ["Issuer underwriting incomplete."],
        },
        "valuation_status": {
            "status": "RANGE_ONLY",
            "components": {
                "peer_valuation": "NOT_COMPLETED",
                "historical_valuation": "NOT_COMPLETED",
                "dcf_cross_check": "NOT_COMPLETED",
                "driver_based_forward_forecast": "NOT_COMPLETED",
                "forward_share_count_bridge": "NOT_COMPLETED",
            },
        },
        "share_count_basis": {"status": "NOT_EVALUATED"},
        "what_is_priced_in": {"status": "NOT_VALIDATED", "conditional_conclusion": "Not Evaluated"},
        "normalized_fcf_status": {"status": "NOT_VALIDATED"},
        "scenario_status": "blocked",
        "scenarios": [],
        "probability_validation": {
            "status": "NOT_PROVIDED",
            "weighted_return_allowed": False,
            "freshness_status": "NOT_APPLICABLE",
            "approval": {"status": "NOT_APPROVED", "approved_by": None},
        },
        "peer_valuation_context": {"status": "UNAVAILABLE", "rows": [], "metric_summaries": []},
        "fcf_quality_assessment": {"status": "NOT_VALIDATED", "rating": "Not Evaluated"},
        "investment_decision_summary": {
            "status": "NOT_VALIDATED",
            "current_action": "Continue Research",
            "current_view": "Research package incomplete.",
            "what_would_make_attractive": [],
            "what_would_invalidate": [],
            "what_to_monitor_next": [],
        },
        "decision_rules": {"upgrade_conditions": [], "downgrade_conditions": [], "thesis_invalidation_conditions": []},
        "hard_stops": [],
        "warnings": [],
        "missing_information": ["Normalized FCF"],
        "probability_weighted_return": None,
        "probability_weighted_expected_return": None,
        "target_price": None,
        "position_sizing": None,
        "portfolio_action": "Not Evaluated",
    }


if __name__ == "__main__":
    unittest.main()
