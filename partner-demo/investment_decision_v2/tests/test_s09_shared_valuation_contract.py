#!/usr/bin/env python3
"""System-level acceptance tests for the shared S09 valuation contract."""

from __future__ import annotations

import math
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from equity_valuation_contract import (  # noqa: E402
    build_shared_valuation_contract,
    legacy_return_context,
    suppress_shared_valuation_outputs,
    validate_shared_valuation_contract,
)
from build_public_company_investment_layer import (  # noqa: E402
    analyst_input_template,
    build_probability_validation,
    build_share_count_basis,
    scenario_set,
)
from render_public_company_artifacts import valuation_return_outputs_html  # noqa: E402
from build_partner_portfolio_overlay import return_pack  # noqa: E402
from validate_friday_v1_delivery import validate_delivery  # noqa: E402
from underwriting_contract import (  # noqa: E402
    SCHEMA_VERSION,
    SUPPORTED_GATE3_SCHEMA_VERSIONS,
    suppress_disallowed_outputs,
)


def forecast_period_fixture() -> dict:
    return {
        "status": "VALIDATED",
        "start_date": "2026-07-02",
        "end_date": "2027-07-01",
        "label": "Forward operating forecast to target date",
        "period_type": "FORECAST",
        "basis": "HOLDING_PERIOD_FORECAST",
        "evidence_ids": [],
    }


def metric_period_fixture() -> dict:
    return {
        "status": "VALIDATED",
        "start_date": "2026-07-02",
        "end_date": "2027-07-01",
        "label": "Forward twelve-month FCF at exit",
        "period_type": "FORWARD_METRIC",
        "basis": "FORWARD_PERIOD_ENDING_AT_TARGET",
        "evidence_ids": [],
    }


def parent_contract(
    *,
    gate_level: float = 3,
    probability_status: str = "VALIDATED",
    forward_shares: bool = True,
) -> dict:
    share_basis = {
        "status": "COMPLETED" if forward_shares else "PROVISIONAL",
        "share_count_value": 10_000_000,
        "share_count_date": "2027-07-01" if forward_shares else "2026-04-30",
        "share_count_type": "FORWARD_DILUTED_SHARES",
        "share_count_source": "Validated forward share-count bridge",
        "point_in_time_or_forward": "FORWARD" if forward_shares else "POINT_IN_TIME",
        "proxy_status": "CURRENT" if forward_shares else "PROXY",
        "forward_share_count_bridge_status": "COMPLETED" if forward_shares else "NOT_COMPLETED",
        "known_subsequent_event_status": "REVIEWED_CHANGE_REFLECTED",
        "known_subsequent_event_note": "Known events reviewed through the valuation date.",
        "forward_share_count_bridge": {
            "status": "COMPLETED" if forward_shares else "NOT_COMPLETED",
            "value": 10_000_000 if forward_shares else None,
            "date": "2027-07-01" if forward_shares else None,
            "source": "Validated forward share-count bridge" if forward_shares else None,
            "evidence_ids": ["EV-FORWARD-SHARES"] if forward_shares else [],
            "reviewed_by": "Share-count reviewer" if forward_shares else None,
        },
    }
    scenarios = [
        {
            "name": "Bear",
            "metric": "Forward FCF",
            "metric_per_share": 8.0,
            "exit_multiple": 10.0,
            "implied_price": 80.0,
            "price_change_vs_current": -0.20,
            "probability": 0.20,
            "share_count_basis_value": 10_000_000,
            "share_count_basis_date": "2027-07-01",
            "forecast_period": forecast_period_fixture(),
            "metric_period": metric_period_fixture(),
        },
        {
            "name": "Base",
            "metric": "Forward FCF",
            "metric_per_share": 10.0,
            "exit_multiple": 11.0,
            "implied_price": 110.0,
            "price_change_vs_current": 0.10,
            "probability": 0.50,
            "share_count_basis_value": 10_000_000,
            "share_count_basis_date": "2027-07-01",
            "forecast_period": forecast_period_fixture(),
            "metric_period": metric_period_fixture(),
        },
        {
            "name": "Bull",
            "metric": "Forward FCF",
            "metric_per_share": 12.5,
            "exit_multiple": 12.0,
            "implied_price": 150.0,
            "price_change_vs_current": 0.50,
            "probability": 0.30,
            "share_count_basis_value": 10_000_000,
            "share_count_basis_date": "2027-07-01",
            "forecast_period": forecast_period_fixture(),
            "metric_period": metric_period_fixture(),
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "data_gate": {"level": gate_level},
        "report_dates": {"market_price_date": "2026-07-01"},
        "valuation": {
            "price": 100.0,
            "price_currency": "USD",
            "price_date": "2026-07-01",
        },
        "share_count_basis": share_basis,
        "evidence_records": [{"evidence_id": "EV-FORWARD-SHARES"}],
        "scenarios": scenarios,
        "probability_validation": {
            "status": probability_status,
            "freshness_status": "CURRENT",
            "approval": {
                "status": "APPROVED" if probability_status == "VALIDATED" else "NOT_APPROVED",
                "approved_by": "Independent reviewer" if probability_status == "VALIDATED" else None,
            },
        },
    }


def valid_input(*, dividend: float = 2.0) -> dict:
    return {
        "status": "VALIDATED",
        "valuation_as_of_date": "2026-07-01",
        "target_date": "2027-07-01",
        "holding_period_days": 365,
        "forecast_period": forecast_period_fixture(),
        "metric_period": metric_period_fixture(),
        "dividend_assumption": {
            "status": "VALIDATED",
            "amount_per_share": dividend,
            "currency": "USD",
            "basis": "CUMULATIVE_CASH_DIVIDENDS_THROUGH_TARGET_DATE",
            "payment_timing": "DURING_HOLDING_PERIOD",
            "reinvestment": False,
            "reviewed_by": "Valuation reviewer",
        },
        "exit_basis": {
            "status": "VALIDATED",
            "method": "SCENARIO_EXIT_MULTIPLE",
            "metric": "Forward FCF",
            "terminal_or_exit": "EXIT",
            "reviewed_by": "Valuation reviewer",
        },
        "reviewed_by": "Valuation reviewer",
    }


class SharedValuationContractTests(unittest.TestCase):
    def test_schema_transition_preserves_frozen_gate3_compatibility(self) -> None:
        self.assertEqual(SCHEMA_VERSION, "5.1.0")
        self.assertEqual(SUPPORTED_GATE3_SCHEMA_VERSIONS, {"5.0.0", "5.1.0"})

    def test_default_is_price_sensitivity_only(self) -> None:
        parent = parent_contract()
        result = build_shared_valuation_contract(parent, {})
        parent["valuation_contract"] = result
        outputs = result["outputs"]
        self.assertEqual(result["status"], "NOT_DEFINED")
        self.assertEqual(outputs["price_sensitivity"]["status"], "VALIDATED")
        self.assertEqual(outputs["base_case_return"]["status"], "NOT_EVALUATED")
        self.assertEqual(outputs["probability_weighted_return"]["status"], "NOT_EVALUATED")
        self.assertEqual(
            outputs["partner_internal_return"]["status"],
            "DISABLED_PRIVATE_GATE_4_ONLY",
        )
        self.assertEqual(validate_shared_valuation_contract(parent), [])

    def test_price_sensitivity_reproduces_metric_per_share_times_multiple(self) -> None:
        parent = parent_contract()
        parent["scenarios"][1]["implied_price"] = 111.0
        parent["scenarios"][1]["price_change_vs_current"] = 0.11
        result = build_shared_valuation_contract(parent, {})
        self.assertEqual(result["outputs"]["price_sensitivity"]["status"], "NOT_EVALUATED")

    def test_complete_horizon_unlocks_base_and_weighted_returns(self) -> None:
        parent = parent_contract()
        result = build_shared_valuation_contract(parent, valid_input())
        parent["valuation_contract"] = result
        base = result["outputs"]["base_case_return"]
        weighted = result["outputs"]["probability_weighted_return"]
        self.assertEqual(result["status"], "VALIDATED")
        self.assertEqual(base["status"], "VALIDATED")
        self.assertTrue(math.isclose(base["price_return"], 0.10, abs_tol=1e-12))
        self.assertTrue(math.isclose(base["dividend_return"], 0.02, abs_tol=1e-12))
        self.assertTrue(math.isclose(base["total_return"], 0.12, abs_tol=1e-12))
        self.assertEqual(weighted["status"], "VALIDATED")
        self.assertTrue(math.isclose(weighted["expected_exit_price"], 116.0, abs_tol=1e-12))
        self.assertTrue(math.isclose(weighted["total_return"], 0.18, abs_tol=1e-12))
        self.assertEqual(validate_shared_valuation_contract(parent), [])

    def test_base_return_does_not_require_scenario_probability_approval(self) -> None:
        parent = parent_contract(probability_status="ILLUSTRATIVE")
        result = build_shared_valuation_contract(parent, valid_input())
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "VALIDATED")
        self.assertEqual(result["outputs"]["probability_weighted_return"]["status"], "NOT_EVALUATED")
        self.assertIn(
            "PROBABILITY_GOVERNANCE_NOT_VALIDATED",
            result["outputs"]["probability_weighted_return"]["blocking_reasons"],
        )

    def test_validated_probabilities_must_total_one_hundred_percent(self) -> None:
        parent = parent_contract()
        parent["scenarios"][2]["probability"] = 0.20
        result = build_shared_valuation_contract(parent, valid_input())
        weighted = result["outputs"]["probability_weighted_return"]
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "VALIDATED")
        self.assertEqual(weighted["status"], "NOT_EVALUATED")
        self.assertIn("SCENARIO_PROBABILITIES_INVALID", weighted["blocking_reasons"])

    def test_probability_sensitivity_is_price_based_not_a_formal_return(self) -> None:
        scenarios = [
            SimpleNamespace(
                name=name,
                probability=probability,
                target_price=price,
                total_return=price / 100.0 - 1.0,
                probability_rationale=f"{name} rationale",
            )
            for name, probability, price in (
                ("Bear", 0.2, 80.0),
                ("Base", 0.5, 110.0),
                ("Bull", 0.3, 150.0),
            )
        ]
        supplied = {
            "probability_framework": {
                "status": "VALIDATED",
                "method_type": "SCENARIO_JUDGMENT",
                "methodology": "Allocate weights from explicit operating cases and test alternative allocations.",
                "method_details": {
                    "allocation_rationale": "Base path has the strongest current evidence.",
                    "sensitivity_completed": True,
                },
                "evidence_ids": ["EV-PROB"],
                "scenario_rationales": {
                    "Bear": "Downside evidence",
                    "Base": "Central evidence",
                    "Bull": "Upside evidence",
                },
                "as_of_date": "2026-07-01",
                "probability_expiration_review_date": "2026-12-31",
                "review_triggers": ["NEW_EARNINGS_OR_GUIDANCE"],
                "reviewed_by": "Probability reviewer",
                "approval": {
                    "status": "APPROVED",
                    "approved_by": "Independent approver",
                    "approval_date": "2026-07-01",
                    "approval_scope": "PROBABILITY_METHODOLOGY_AND_WEIGHTS",
                    "independent_research_review": True,
                },
                "sensitivity_cases": [
                    {
                        "label": label,
                        "probabilities": weights,
                    }
                    for label, weights in (
                        ("Downside", {"Bear": 0.5, "Base": 0.35, "Bull": 0.15}),
                        ("Central", {"Bear": 0.2, "Base": 0.5, "Bull": 0.3}),
                        ("Upside", {"Bear": 0.1, "Base": 0.3, "Bull": 0.6}),
                    )
                ],
            }
        }
        result = build_probability_validation(
            supplied,
            scenarios,
            [
                {
                    "evidence_id": "EV-PROB",
                    "validation_status": "PASS",
                    "publication_date": "2026-07-01",
                    "source_level": 2,
                }
            ],
            "2026-07-01",
        )
        self.assertEqual(result["status"], "VALIDATED")
        for row in result["sensitivity_table"]:
            self.assertIn("weighted_implied_price_sensitivity", row)
            self.assertNotIn("probability_weighted_return", row)
            self.assertIsNone(row["formal_weighted_expected_return"])

    def test_explicit_validated_zero_dividend_is_not_treated_as_missing(self) -> None:
        parent = parent_contract()
        result = build_shared_valuation_contract(parent, valid_input(dividend=0.0))
        parent["valuation_contract"] = result
        self.assertEqual(result["dividend_assumption"]["status"], "VALIDATED")
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "VALIDATED")
        self.assertTrue(
            math.isclose(result["outputs"]["base_case_return"]["total_return"], 0.10, abs_tol=1e-12)
        )
        self.assertEqual(validate_shared_valuation_contract(parent), [])

    def test_missing_dividend_and_as_of_mismatch_block_returns_not_price_sensitivity(self) -> None:
        parent = parent_contract()
        supplied = valid_input()
        supplied["valuation_as_of_date"] = "2026-06-30"
        supplied["dividend_assumption"] = {"status": "NOT_DEFINED"}
        result = build_shared_valuation_contract(parent, supplied)
        codes = {row["code"] for row in result["validation_issues"]}
        self.assertIn("VALUATION_AS_OF_DATE_MISMATCH", codes)
        self.assertIn("DIVIDEND_ASSUMPTION_NOT_VALIDATED", codes)
        self.assertEqual(result["outputs"]["price_sensitivity"]["status"], "VALIDATED")
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "NOT_EVALUATED")

    def test_dividend_currency_must_match_price_currency(self) -> None:
        parent = parent_contract()
        supplied = valid_input()
        supplied["dividend_assumption"]["currency"] = "EUR"
        result = build_shared_valuation_contract(parent, supplied)
        codes = {row["code"] for row in result["validation_issues"]}
        self.assertIn("DIVIDEND_ASSUMPTION_NOT_VALIDATED", codes)
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "NOT_EVALUATED")

    def test_target_date_must_follow_valuation_as_of_date(self) -> None:
        parent = parent_contract()
        supplied = valid_input()
        supplied["target_date"] = "2026-06-30"
        supplied["holding_period_days"] = None
        result = build_shared_valuation_contract(parent, supplied)
        codes = {row["code"] for row in result["validation_issues"]}
        self.assertIn("TARGET_DATE_NOT_AFTER_AS_OF_DATE", codes)
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "NOT_EVALUATED")

    def test_holding_period_must_reconcile_to_dated_endpoints(self) -> None:
        parent = parent_contract()
        supplied = valid_input()
        supplied["holding_period_days"] = 360
        result = build_shared_valuation_contract(parent, supplied)
        codes = {row["code"] for row in result["validation_issues"]}
        self.assertIn("HOLDING_PERIOD_DATE_MISMATCH", codes)
        self.assertEqual(result["status"], "INVALID")

    def test_target_date_must_be_covered_by_forecast_period(self) -> None:
        parent = parent_contract()
        supplied = valid_input()
        supplied["forecast_period"]["end_date"] = "2026-12-31"
        result = build_shared_valuation_contract(parent, supplied)
        codes = {row["code"] for row in result["validation_issues"]}
        self.assertIn("FORECAST_PERIOD_HORIZON_MISMATCH", codes)
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "NOT_EVALUATED")

    def test_exit_metric_must_match_scenario_metric(self) -> None:
        parent = parent_contract()
        supplied = valid_input()
        supplied["exit_basis"]["metric"] = "Forward EBITDA"
        result = build_shared_valuation_contract(parent, supplied)
        codes = {row["code"] for row in result["validation_issues"]}
        self.assertIn("EXIT_BASIS_NOT_VALIDATED", codes)
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "NOT_EVALUATED")

    def test_scenario_price_share_basis_must_match_forward_share_basis(self) -> None:
        parent = parent_contract()
        parent["share_count_basis"]["share_count_value"] = 9_500_000
        parent["share_count_basis"]["forward_share_count_bridge"]["value"] = 9_500_000
        result = build_shared_valuation_contract(parent, valid_input())
        codes = {row["code"] for row in result["validation_issues"]}
        self.assertEqual(result["exit_basis"]["share_basis_reconciliation_status"], "FAIL")
        self.assertIn("EXIT_BASIS_NOT_VALIDATED", codes)
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "NOT_EVALUATED")

    def test_scenario_periods_must_match_valuation_periods(self) -> None:
        parent = parent_contract()
        parent["scenarios"][1]["metric_period"]["label"] = "Unrelated period"
        result = build_shared_valuation_contract(parent, valid_input())
        self.assertEqual(result["exit_basis"]["metric_period_reconciliation_status"], "FAIL")
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "NOT_EVALUATED")

    def test_point_in_time_share_proxy_blocks_formal_return(self) -> None:
        parent = parent_contract(forward_shares=False)
        result = build_shared_valuation_contract(parent, valid_input())
        codes = {row["code"] for row in result["validation_issues"]}
        self.assertIn("FORWARD_SHARE_BASIS_NOT_VALIDATED", codes)
        self.assertEqual(result["outputs"]["price_sensitivity"]["status"], "VALIDATED")
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "NOT_EVALUATED")

    def test_forward_share_status_cannot_be_completed_by_label_only(self) -> None:
        contract = {
            "valuation": {
                "shares": 12_000_000,
                "shares_as_of_date": "2026-04-30",
                "price_date": "2026-07-01",
                "shares_source": {
                    "form": "10-Q",
                    "accn": "000-test",
                    "filed": "2026-05-01",
                },
            },
            "evidence_records": [],
        }
        research = {
            "share_count_basis": {
                "forward_share_count_bridge_status": "COMPLETED",
                "known_subsequent_event_status": "REVIEWED_CHANGE_REFLECTED",
            }
        }
        result = build_share_count_basis(contract, research)
        self.assertEqual(result["forward_share_count_bridge_status"], "NOT_COMPLETED")
        self.assertEqual(result["point_in_time_or_forward"], "POINT_IN_TIME")
        self.assertEqual(result["share_count_value"], 12_000_000)

    def test_complete_forward_share_input_replaces_reported_proxy(self) -> None:
        contract = {
            "valuation": {
                "shares": 12_000_000,
                "shares_as_of_date": "2026-04-30",
                "price_date": "2026-07-01",
                "shares_source": {
                    "form": "10-Q",
                    "accn": "000-test",
                    "filed": "2026-05-01",
                },
            },
            "evidence_records": [{"evidence_id": "EV-FORWARD-SHARES"}],
        }
        research = {
            "share_count_basis": {
                "forward_share_count_bridge_status": "COMPLETED",
                "forward_share_count_value": 11_500_000,
                "forward_share_count_date": "2027-07-01",
                "forward_share_count_source": "Reviewed forward share bridge",
                "forward_share_count_evidence_ids": ["EV-FORWARD-SHARES"],
                "known_subsequent_event_status": "REVIEWED_CHANGE_REFLECTED",
                "reviewed_by": "Share-count reviewer",
            }
        }
        result = build_share_count_basis(contract, research)
        self.assertEqual(result["forward_share_count_bridge_status"], "COMPLETED")
        self.assertEqual(result["point_in_time_or_forward"], "FORWARD")
        self.assertEqual(result["share_count_value"], 11_500_000)
        self.assertEqual(result["proxy_status"], "CURRENT")

    def test_scenario_builder_uses_validated_forward_share_basis_and_periods(self) -> None:
        valuation = {
            "price": 100.0,
            "price_currency": "USD",
            "shares": 12_000_000,
            "shares_as_of_date": "2026-04-30",
            "p_fcf": 12.0,
        }
        research = {
            "normalized_fcf": {
                "status": "VALIDATED",
                "value": 100_000_000,
                "reviewed_by": "FCF reviewer",
            },
            "valuation_contract": {
                "forecast_period": forecast_period_fixture(),
                "metric_period": metric_period_fixture(),
            },
            "scenario_model": {
                "status": "ANALYST_VALIDATED",
                "reviewed_by": "Scenario reviewer",
                "metric": "Normalized FCF",
                "scenarios": [
                    {
                        "name": "Bear",
                        "probability": 0.2,
                        "metric_value_total": 80_000_000,
                        "growth_assumption": -0.2,
                        "exit_multiple": 10.0,
                        "key_driver": "Downside",
                        "falsification_trigger": "Recovery",
                    },
                    {
                        "name": "Base",
                        "probability": 0.5,
                        "metric_value_total": 100_000_000,
                        "growth_assumption": 0.0,
                        "exit_multiple": 11.0,
                        "key_driver": "Base path",
                        "falsification_trigger": "Miss",
                    },
                    {
                        "name": "Bull",
                        "probability": 0.3,
                        "metric_value_total": 125_000_000,
                        "growth_assumption": 0.25,
                        "exit_multiple": 12.0,
                        "key_driver": "Upside",
                        "falsification_trigger": "No acceleration",
                    },
                ],
            },
        }
        share_basis = {
            "share_count_value": 10_000_000,
            "share_count_date": "2027-07-01",
            "point_in_time_or_forward": "FORWARD",
            "forward_share_count_bridge_status": "COMPLETED",
        }
        scenarios, status = scenario_set(
            valuation,
            {},
            {},
            research,
            share_basis,
        )
        self.assertEqual(status, "scenario_assumptions_validated")
        base = next(row for row in scenarios if row.name == "Base")
        self.assertEqual(base.share_count_basis_value, 10_000_000)
        self.assertEqual(base.share_count_basis_date, "2027-07-01")
        self.assertEqual(base.metric_per_share, 10.0)
        self.assertEqual(base.target_price, 110.0)
        self.assertEqual(base.forecast_period, forecast_period_fixture())
        self.assertEqual(base.metric_period, metric_period_fixture())

    def test_forward_share_bridge_rejects_unknown_evidence_id(self) -> None:
        contract = {
            "valuation": {
                "shares": 12_000_000,
                "shares_as_of_date": "2026-04-30",
                "price_date": "2026-07-01",
                "shares_source": {},
            },
            "evidence_records": [],
        }
        research = {
            "share_count_basis": {
                "forward_share_count_bridge_status": "COMPLETED",
                "forward_share_count_value": 11_500_000,
                "forward_share_count_date": "2027-07-01",
                "forward_share_count_source": "Reviewed forward share bridge",
                "forward_share_count_evidence_ids": ["EV-UNKNOWN"],
                "known_subsequent_event_status": "REVIEWED_CHANGE_REFLECTED",
                "reviewed_by": "Share-count reviewer",
            }
        }
        result = build_share_count_basis(contract, research)
        self.assertEqual(result["forward_share_count_bridge_status"], "NOT_COMPLETED")
        self.assertEqual(result["point_in_time_or_forward"], "POINT_IN_TIME")

    def test_below_gate3_suppresses_all_public_valuation_values(self) -> None:
        parent = parent_contract(gate_level=2.5)
        result = build_shared_valuation_contract(parent, valid_input())
        parent["valuation_contract"] = result
        suppress_shared_valuation_outputs(parent)
        self.assertEqual(
            result["outputs"]["price_sensitivity"]["status"],
            "SUPPRESSED_BELOW_GATE_3",
        )
        self.assertEqual(result["outputs"]["price_sensitivity"]["scenarios"], [])
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "NOT_EVALUATED")
        self.assertEqual(result["outputs"]["probability_weighted_return"]["status"], "NOT_EVALUATED")
        self.assertTrue(
            all(
                row["implied_price"] is None
                and row["price_change_vs_current"] is None
                for row in result["exit_basis"]["scenario_assumptions"]
            )
        )

    def test_private_partner_return_is_discarded_from_public_contract(self) -> None:
        parent = parent_contract()
        supplied = valid_input()
        supplied["partner_internal_return"] = {
            "target_return": 0.25,
            "position_sizing": 0.03,
        }
        result = build_shared_valuation_contract(parent, supplied)
        partner = result["outputs"]["partner_internal_return"]
        self.assertTrue(partner["private_input_detected_and_discarded"])
        self.assertIsNone(partner["target_return"])
        self.assertIsNone(partner["position_sizing"])

    def test_schema_5_1_always_suppresses_legacy_return_scalars(self) -> None:
        contract = parent_contract()
        contract.update(
            {
                "return_context": {"formal_return_language_allowed": True},
                "probability_weighted_expected_return": 0.18,
                "probability_weighted_return": 0.18,
                "target_price": 116.0,
            }
        )
        suppress_disallowed_outputs(contract)
        self.assertIsNone(contract["probability_weighted_expected_return"])
        self.assertIsNone(contract["probability_weighted_return"])
        self.assertIsNone(contract["target_price"])

    def test_tampered_return_fails_recalculation(self) -> None:
        parent = parent_contract()
        result = build_shared_valuation_contract(parent, valid_input())
        parent["valuation_contract"] = deepcopy(result)
        parent["valuation_contract"]["outputs"]["base_case_return"]["total_return"] = 0.99
        errors = validate_shared_valuation_contract(parent)
        self.assertIn(
            "Base-case total_return does not reproduce from authoritative inputs.",
            errors,
        )

    def test_internally_consistent_tampered_return_cannot_replace_authoritative_inputs(self) -> None:
        parent = parent_contract()
        parent["valuation_contract"] = build_shared_valuation_contract(parent, valid_input())
        base = parent["valuation_contract"]["outputs"]["base_case_return"]
        base.update(
            {
                "current_price": 50.0,
                "exit_price": 999.0,
                "price_return": 999.0 / 50.0 - 1.0,
                "dividend_return": 2.0 / 50.0,
                "total_return": (999.0 + 2.0) / 50.0 - 1.0,
                "annualized_return": ((999.0 + 2.0) / 50.0) ** (365.25 / 365) - 1.0,
            }
        )
        weighted = parent["valuation_contract"]["outputs"]["probability_weighted_return"]
        weighted["current_price"] = 50.0
        weighted["price_return"] = weighted["expected_exit_price"] / 50.0 - 1.0
        weighted["dividend_return"] = 2.0 / 50.0
        weighted["total_return"] = (weighted["expected_exit_price"] + 2.0) / 50.0 - 1.0
        weighted["annualized_return"] = (
            (weighted["expected_exit_price"] + 2.0) / 50.0
        ) ** (365.25 / 365) - 1.0
        errors = validate_shared_valuation_contract(parent)
        self.assertIn(
            "Base-case current price disagrees with the authoritative valuation object.",
            errors,
        )
        self.assertIn(
            "Base-case exit price disagrees with the authoritative Base scenario.",
            errors,
        )
        self.assertIn(
            "Probability-weighted current price disagrees with the authoritative valuation object.",
            errors,
        )

    def test_gate_below_three_suppression_remains_self_validating(self) -> None:
        parent = parent_contract(gate_level=2.5)
        parent["valuation_contract"] = build_shared_valuation_contract(parent, valid_input())
        suppress_shared_valuation_outputs(parent)
        self.assertEqual(
            parent["valuation_contract"]["exit_basis"]["status"],
            "SUPPRESSED_BELOW_GATE_3",
        )
        self.assertEqual(validate_shared_valuation_contract(parent), [])

    def test_formal_horizon_rejects_semantically_unrelated_periods(self) -> None:
        parent = parent_contract()
        supplied = valid_input()
        supplied["forecast_period"]["start_date"] = "1990-01-01"
        supplied["metric_period"].update(
            {
                "start_date": "2000-01-01",
                "end_date": "2000-12-31",
            }
        )
        result = build_shared_valuation_contract(parent, supplied)
        codes = {row["code"] for row in result["validation_issues"]}
        self.assertIn("FORECAST_PERIOD_HORIZON_MISMATCH", codes)
        self.assertIn("VALUATION_METRIC_PERIOD_TARGET_MISMATCH", codes)
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "NOT_EVALUATED")

    def test_dividend_and_exit_semantics_must_be_explicit(self) -> None:
        parent = parent_contract()
        supplied = valid_input()
        supplied["dividend_assumption"].update(
            {
                "basis": "one annual dividend",
                "payment_timing": "",
                "reinvestment": None,
            }
        )
        supplied["exit_basis"].update(
            {
                "method": "ARBITRARY_METHOD",
                "terminal_or_exit": "TERMINAL",
            }
        )
        result = build_shared_valuation_contract(parent, supplied)
        codes = {row["code"] for row in result["validation_issues"]}
        self.assertIn("DIVIDEND_ASSUMPTION_NOT_VALIDATED", codes)
        self.assertIn("EXIT_BASIS_NOT_VALIDATED", codes)
        self.assertEqual(result["outputs"]["base_case_return"]["status"], "NOT_EVALUATED")

    def test_delivery_qa_uses_reported_shares_for_current_market_cap(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "friday_v1_outputs"
            / "crox_crocs_inc"
            / "step3"
            / "underwriting_output_contract.json"
        )
        contract = json.loads(source.read_text(encoding="utf-8"))
        reported_value = contract["valuation"]["shares"]
        reported_date = contract["valuation"]["shares_as_of_date"]
        contract["share_count_basis"].update(
            {
                "share_count_value": reported_value * 0.90,
                "share_count_date": "2027-07-15",
                "point_in_time_or_forward": "FORWARD",
                "forward_share_count_bridge_status": "COMPLETED",
                "proxy_status": "CURRENT",
                "latest_reported_share_count": {
                    "value": reported_value,
                    "date": reported_date,
                    "source": "Existing reported source",
                    "evidence_ids": [],
                },
            }
        )
        result = validate_delivery(contract)
        checks = {row["check_id"]: row["status"] for row in result["checks"]}
        self.assertEqual(checks["market-cap-reproduction"], "PASS")
        self.assertEqual(checks["share-date-alignment"], "PASS")
        self.assertEqual(checks["current-share-basis-reconciliation"], "PASS")

    def test_gate4_pack_never_uses_price_sensitivity_as_downside_return(self) -> None:
        parent = parent_contract()
        parent["valuation_contract"] = build_shared_valuation_contract(parent, valid_input())
        returns = return_pack(parent, {}, gate3_eligible=True)
        self.assertTrue(math.isclose(returns["expected_return"], 0.18, abs_tol=1e-12))
        self.assertIsNone(returns["bear_case"])
        self.assertIsNone(returns["bull_case"])
        self.assertTrue(
            math.isclose(
                returns["public_bear_price_sensitivity"],
                -0.20,
                abs_tol=1e-12,
            )
        )
        self.assertFalse(returns["return_and_price_sensitivity_classes_mixed"])

    def test_non_fcf_scenario_metric_uses_explicit_generic_basis(self) -> None:
        valuation = {
            "price": 50.0,
            "price_currency": "EUR",
            "shares": 10_000_000,
            "shares_as_of_date": "2026-07-01",
        }
        research = {
            "valuation_contract": {
                "forecast_period": forecast_period_fixture(),
                "metric_period": metric_period_fixture(),
            },
            "scenario_model": {
                "status": "ANALYST_VALIDATED",
                "metric": "Forward EBITDA",
                "metric_unit": "EUR",
                "metric_currency": "EUR",
                "metric_basis": {
                    "status": "VALIDATED",
                    "value": 100_000_000,
                    "unit": "EUR",
                    "currency": "EUR",
                    "period_end": "2026-07-01",
                    "evidence_ids": ["EV-EBITDA"],
                    "reviewed_by": "Metric reviewer",
                },
                "reviewed_by": "Scenario reviewer",
                "scenarios": [
                    {
                        "name": name,
                        "probability": probability,
                        "metric_value_total": metric_value,
                        "growth_assumption": growth,
                        "exit_multiple": multiple,
                        "key_driver": f"{name} driver",
                        "falsification_trigger": f"{name} trigger",
                    }
                    for name, probability, metric_value, growth, multiple in (
                        ("Bear", 0.2, 80_000_000, -0.2, 4.0),
                        ("Base", 0.5, 100_000_000, 0.0, 5.0),
                        ("Bull", 0.3, 120_000_000, 0.2, 6.0),
                    )
                ],
            },
        }
        scenarios, status = scenario_set(valuation, {}, {}, research, {})
        self.assertEqual(status, "scenario_assumptions_validated")
        self.assertEqual(len(scenarios), 3)
        self.assertTrue(all(row.metric_currency == "EUR" for row in scenarios))
        self.assertTrue(all(row.metric_unit == "EUR" for row in scenarios))
        self.assertEqual(next(row for row in scenarios if row.name == "Base").target_price, 50.0)

    def test_legacy_projection_contains_all_s09_horizon_fields(self) -> None:
        result = build_shared_valuation_contract(parent_contract(), valid_input())
        projected = legacy_return_context(result)
        for field in (
            "valuation_as_of_date",
            "target_date",
            "holding_period",
            "forecast_period",
            "metric_period",
            "dividend_assumption",
            "share_count_basis",
            "exit_basis",
        ):
            self.assertIn(field, projected)
        self.assertTrue(projected["formal_return_language_allowed"])

    def test_generated_analyst_template_contains_complete_s09_input_surface(self) -> None:
        valuation_input = analyst_input_template(
            {"name": "Test Company", "ticker": "TEST"}
        )["valuation_contract"]
        for field in (
            "valuation_as_of_date",
            "target_date",
            "holding_period_days",
            "forecast_period",
            "metric_period",
            "dividend_assumption",
            "exit_basis",
        ):
            self.assertIn(field, valuation_input)
        self.assertEqual(
            valuation_input["forecast_period"]["basis"],
            "HOLDING_PERIOD_FORECAST",
        )
        self.assertEqual(
            valuation_input["metric_period"]["basis"],
            "FORWARD_PERIOD_ENDING_AT_TARGET",
        )
        self.assertIs(valuation_input["dividend_assumption"]["reinvestment"], False)

    def test_renderer_displays_four_classes_without_recalculation(self) -> None:
        parent = parent_contract()
        parent["valuation_contract"] = build_shared_valuation_contract(parent, valid_input())
        html = valuation_return_outputs_html(parent)
        self.assertIn("Price Sensitivity", html)
        self.assertIn("Base-Case Return", html)
        self.assertIn("Probability-Weighted Return", html)
        self.assertIn("Partner Internal Return", html)
        self.assertIn("12.0%", html)
        self.assertIn("18.0%", html)


if __name__ == "__main__":
    unittest.main()
