#!/usr/bin/env python3
"""System-level acceptance tests for S10 modular forward operating bridges."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from forward_operating_model import (  # noqa: E402
    CASH_FLOW_MEASUREMENT_BASES,
    DRIVER_MODULE_REGISTRY,
    FORWARD_FCF_BASIS,
    build_forward_valuation_contract,
    driver_module_catalog,
    forward_share_basis_input,
    validate_forward_valuation_contract,
)
from build_public_company_investment_layer import (  # noqa: E402
    analyst_input_template,
    build_analysis_evidence,
    build_share_count_basis,
    build_valuation_scope_status,
    scenario_set,
)
from render_public_company_artifacts import (  # noqa: E402
    forward_operating_bridge_html,
    render,
)


EVIDENCE_ID = "EV-ASSUMPTION"
BUSINESS_ID = "EV-BUSINESS-MODEL"
SHARES_ID = "EV-SHARES"


def assumption(
    value: float,
    *,
    evidence_id: str = EVIDENCE_ID,
    evidence_class: str = "JUDGMENT",
    unit: str = "RATIO",
    currency: str = "",
) -> dict:
    return {
        "value": value,
        "evidence_class": evidence_class,
        "evidence_ids": [evidence_id],
        "reviewed_by": "S10 reviewer",
        "rationale": "Scenario assumption supported by the linked public evidence.",
        "unit": unit,
        "currency": currency,
    }


def base_assumption(value: float) -> dict:
    line = assumption(
        value,
        evidence_id=f"EV-CALC-BASE-REVENUE-{value:g}",
        evidence_class="CALC",
        unit="USD",
        currency="USD",
    )
    line["formula"] = "Reconciled from linked public revenue evidence."
    return line


def valuation_input_contract() -> dict:
    return {
        "valuation_as_of_date": "2026-07-01",
        "target_date": "2027-07-01",
        "forecast_period": {
            "status": "VALIDATED",
            "start_date": "2026-07-02",
            "end_date": "2027-07-01",
            "label": "Forward operating forecast to target date",
            "period_type": "FORECAST",
            "basis": "HOLDING_PERIOD_FORECAST",
            "evidence_ids": [],
        },
        "metric_period": {
            "status": "VALIDATED",
            "start_date": "2026-07-02",
            "end_date": "2027-07-01",
            "label": "Forward twelve-month FCF at exit",
            "period_type": "FORWARD_METRIC",
            "basis": "FORWARD_PERIOD_ENDING_AT_TARGET",
            "evidence_ids": [],
        },
    }


def parent_contract() -> dict:
    return {
        "valuation": {
            "shares": 100.0,
            "shares_as_of_date": "2026-06-30",
            "price": 50.0,
            "price_date": "2026-07-01",
            "price_currency": "USD",
        },
        "valuation_contract": valuation_input_contract(),
        "evidence_records": [
            {"evidence_id": EVIDENCE_ID, "metric_name": "public_assumption_support"},
            {"evidence_id": BUSINESS_ID, "metric_name": "business_model_evidence"},
            *[
                {
                    "evidence_id": f"EV-CALC-BASE-REVENUE-{value:g}",
                    "metric_name": "valuation_basis_revenue",
                    "value": value,
                    "unit": "USD",
                    "currency": "USD",
                    "scale": 1.0,
                    "period_start": "2025-07-01",
                    "period_end": "2026-06-30",
                    "as_of_date": "2026-06-30",
                    "evidence_class": "CALC",
                    "validation_status": "PASS",
                }
                for value in (20.0, 40.0, 60.0, 80.0, 100.0)
            ],
            {
                "evidence_id": SHARES_ID,
                "metric_name": "shares_outstanding_point_in_time",
                "value": 100.0,
                "unit": "shares",
                "scale": 1.0,
                "as_of_date": "2026-06-30",
                "evidence_class": "FACT",
                "validation_status": "PASS",
            },
        ],
    }


def revenue_driver(module: str) -> dict:
    if module == "RETAIL":
        return {
            "base_revenue": base_assumption(100.0),
            "comparable_sales_growth": assumption(0.05),
            "net_store_growth": assumption(0.02),
            "other_revenue_growth": assumption(0.01),
        }
    if module == "CONSUMER_BRAND":
        return {
            "brand_segments": [
                {
                    "name": "Core Brand",
                    "base_revenue": base_assumption(60.0),
                    "revenue_growth": assumption(0.05),
                },
                {
                    "name": "Growth Brand",
                    "base_revenue": base_assumption(40.0),
                    "revenue_growth": assumption(-0.02),
                },
            ]
        }
    if module == "SUBSCRIPTION_SOFTWARE":
        return {
            "revenue_streams": [
                {
                    "name": "Subscription",
                    "base_revenue": base_assumption(80.0),
                    "revenue_growth": assumption(0.10),
                },
                {
                    "name": "Services",
                    "base_revenue": base_assumption(20.0),
                    "revenue_growth": assumption(0.00),
                },
            ]
        }
    if module == "INDUSTRIAL":
        return {
            "base_revenue": base_assumption(100.0),
            "volume_growth": assumption(0.03),
            "price_mix_growth": assumption(0.02),
            "acquisition_revenue": assumption(
                5.0, unit="USD", currency="USD"
            ),
            "divestiture_revenue": assumption(
                2.0, unit="USD", currency="USD"
            ),
        }
    if module == "ACQUISITION_HEAVY":
        return {
            "base_revenue": base_assumption(100.0),
            "organic_growth": assumption(0.03),
            "acquired_revenue": assumption(
                10.0, unit="USD", currency="USD"
            ),
            "divested_revenue": assumption(
                2.0, unit="USD", currency="USD"
            ),
        }
    if module == "DISTRIBUTION":
        return {
            "base_revenue": base_assumption(100.0),
            "volume_growth": assumption(0.03),
            "price_mix_growth": assumption(0.02),
        }
    raise AssertionError(f"Missing test driver for {module}")


def cash_flow_driver(*, operating_margin: float = 0.30) -> dict:
    values = {
        "operating_margin": assumption(operating_margin),
        "cash_interest": assumption(5.0),
        "cash_taxes": assumption(5.0),
        "depreciation_and_amortization": assumption(15.0),
        "stock_based_compensation": assumption(5.0),
        "other_non_cash_items": assumption(0.0),
        "working_capital_investment": assumption(5.0),
        "capex": assumption(10.0),
        "restructuring_cash": assumption(0.0),
        "acquisition_integration_cash": assumption(0.0),
        "other_cash_adjustments": assumption(0.0),
    }
    for field, line in values.items():
        line["measurement_basis"] = CASH_FLOW_MEASUREMENT_BASES[field]
        if field != "operating_margin":
            line["unit"] = "USD"
            line["currency"] = "USD"
    return values


def forward_research_input(
    module: str,
    *,
    operating_margin: float = 0.30,
) -> dict:
    return {
        "valuation_contract": valuation_input_contract(),
        "forward_valuation": {
            "status": "ANALYST_VALIDATED",
            "driver_module": module,
            "module_selection": {
                "status": "ANALYST_VALIDATED",
                "rationale": "The selected module matches the issuer's disclosed revenue model.",
                "evidence_ids": [BUSINESS_ID],
                "reviewed_by": "Module reviewer",
            },
            "currency": "USD",
            "unit": "USD",
            "fcf_basis": FORWARD_FCF_BASIS,
            "reviewed_by": "S10 reviewer",
            "scenarios": [
                {
                    "name": name,
                    "scenario_rationale": f"{name} operating path.",
                    "revenue_driver": deepcopy(revenue_driver(module)),
                    "cash_flow_driver": cash_flow_driver(
                        operating_margin=operating_margin
                    ),
                    "reviewed_by": "S10 reviewer",
                }
                for name in ("Bear", "Base", "Bull")
            ],
            "share_count_bridge": {
                "status": "ANALYST_VALIDATED",
                "target_date": "2027-07-01",
                "known_subsequent_event_status": "REVIEWED_CHANGE_REFLECTED",
                "known_subsequent_event_note": (
                    "Repurchase and issuance assumptions reflect reviewed public events."
                ),
                "reviewed_by": "Share reviewer",
                "changes": {
                    "repurchases": assumption(
                        5.0, unit="SHARES", currency="SHARES"
                    ),
                    "stock_based_compensation_issuance": assumption(
                        2.0, unit="SHARES", currency="SHARES"
                    ),
                    "employee_plan_issuance": assumption(
                        1.0, unit="SHARES", currency="SHARES"
                    ),
                    "convertible_dilution": assumption(
                        0.0, unit="SHARES", currency="SHARES"
                    ),
                    "acquisition_share_issuance": assumption(
                        0.0, unit="SHARES", currency="SHARES"
                    ),
                    "other_net_change": assumption(
                        0.0, unit="SHARES", currency="SHARES"
                    ),
                },
            },
        },
    }


class S10ForwardOperatingBridgeTests(unittest.TestCase):
    def test_registry_covers_first_batch_business_models(self) -> None:
        self.assertEqual(
            set(DRIVER_MODULE_REGISTRY),
            {
                "RETAIL",
                "CONSUMER_BRAND",
                "SUBSCRIPTION_SOFTWARE",
                "INDUSTRIAL",
                "ACQUISITION_HEAVY",
                "DISTRIBUTION",
            },
        )
        catalog = driver_module_catalog()
        self.assertEqual(catalog["registry_version"], "1.0.0")
        self.assertNotIn(
            "revenue_builder",
            catalog["modules"]["RETAIL"],
        )

    def test_all_modules_produce_the_same_validated_output_contract(self) -> None:
        output_shapes = set()
        for module in DRIVER_MODULE_REGISTRY:
            parent = parent_contract()
            result = build_forward_valuation_contract(
                parent,
                forward_research_input(module),
            )
            parent["forward_valuation_contract"] = result
            self.assertEqual(result["status"], "VALIDATED", module)
            self.assertEqual(result["driver_model_status"], "VALIDATED", module)
            self.assertEqual(len(result["scenarios"]), 3, module)
            self.assertTrue(
                all(row["forward_fcf"] is not None for row in result["scenarios"]),
                module,
            )
            self.assertEqual(
                result["forward_share_count_bridge"]["forward_diluted_shares"],
                98.0,
                module,
            )
            self.assertEqual(validate_forward_valuation_contract(parent), [], module)
            output_shapes.add(tuple(sorted(result)))
        self.assertEqual(len(output_shapes), 1)

    def test_unknown_module_fails_closed_without_a_forecast(self) -> None:
        result = build_forward_valuation_contract(
            parent_contract(),
            forward_research_input("RETAIL")
            | {
                "forward_valuation": {
                    **forward_research_input("RETAIL")["forward_valuation"],
                    "driver_module": "BIOTECH_PRE_REVENUE",
                }
            },
        )
        self.assertEqual(result["status"], "DRIVER_MODEL_NOT_AVAILABLE")
        self.assertEqual(result["scenarios"], [])
        self.assertFalse(
            result["scenario_metric_eligibility"]["positive_fcf_multiple_allowed"]
        )

    def test_persisted_s09_forward_fcf_requires_validated_s10(self) -> None:
        parent = parent_contract()
        supplied = forward_research_input("RETAIL")
        supplied["forward_valuation"]["driver_module"] = "UNSUPPORTED_MODEL"
        result = build_forward_valuation_contract(parent, supplied)
        parent["forward_valuation_contract"] = result
        parent["valuation_contract"]["exit_basis"] = {
            "status": "VALIDATED",
            "metric": "Forward FCF",
            "scenario_assumptions": [
                {"name": name, "metric": "Forward FCF"}
                for name in ("Bear", "Base", "Bull")
            ],
        }
        parent["valuation_contract"]["outputs"] = {
            "base_case_return": {"status": "VALIDATED"}
        }
        self.assertIn(
            "S09 Forward FCF scenarios require a VALIDATED S10 contract.",
            validate_forward_valuation_contract(parent),
        )

    def test_missing_required_driver_invalidates_the_shared_model(self) -> None:
        supplied = forward_research_input("RETAIL")
        del supplied["forward_valuation"]["scenarios"][0]["revenue_driver"][
            "comparable_sales_growth"
        ]
        parent = parent_contract()
        result = build_forward_valuation_contract(parent, supplied)
        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(
            next(row for row in result["scenarios"] if row["name"] == "Bear")[
                "forward_fcf"
            ],
            None,
        )
        self.assertIn(
            "FORWARD_DRIVER_MISSING",
            {row["code"] for row in result["validation_issues"]},
        )
        parent["forward_valuation_contract"] = result
        self.assertEqual(validate_forward_valuation_contract(parent), [])

    def test_cfo_subtotal_cannot_be_mixed_into_the_fcf_bridge(self) -> None:
        supplied = forward_research_input("RETAIL")
        supplied["forward_valuation"]["scenarios"][0]["cash_flow_driver"]["cfo"] = (
            assumption(50.0)
        )
        result = build_forward_valuation_contract(parent_contract(), supplied)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn(
            "UNSUPPORTED_CASH_FLOW_FIELD",
            {row["code"] for row in result["validation_issues"]},
        )

    def test_cash_flow_measurement_basis_is_mandatory_and_controlled(self) -> None:
        supplied = forward_research_input("RETAIL")
        supplied["forward_valuation"]["scenarios"][0]["cash_flow_driver"][
            "operating_margin"
        ]["measurement_basis"] = "EBITDA_MARGIN"
        result = build_forward_valuation_contract(parent_contract(), supplied)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn(
            "FORWARD_DRIVER_MEASUREMENT_BASIS_INVALID",
            {row["code"] for row in result["validation_issues"]},
        )

    def test_assumption_units_must_be_explicit_not_inferred(self) -> None:
        supplied = forward_research_input("RETAIL")
        capex = supplied["forward_valuation"]["scenarios"][0][
            "cash_flow_driver"
        ]["capex"]
        capex.pop("unit")
        capex.pop("currency")
        result = build_forward_valuation_contract(parent_contract(), supplied)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn(
            "FORWARD_DRIVER_UNIT_OR_CURRENCY_MISMATCH",
            {row["code"] for row in result["validation_issues"]},
        )

    def test_forecast_and_metric_periods_must_match_the_dated_horizon(self) -> None:
        supplied = forward_research_input("RETAIL")
        supplied["valuation_contract"]["forecast_period"]["end_date"] = "2027-06-30"
        supplied["valuation_contract"]["metric_period"]["end_date"] = "2027-06-30"
        result = build_forward_valuation_contract(parent_contract(), supplied)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn(
            "FORWARD_FORECAST_PERIOD_HORIZON_MISMATCH",
            {row["code"] for row in result["validation_issues"]},
        )
        self.assertIn(
            "FORWARD_METRIC_PERIOD_TARGET_MISMATCH",
            {row["code"] for row in result["validation_issues"]},
        )

    def test_malformed_period_and_evidence_list_fail_closed(self) -> None:
        supplied = forward_research_input("RETAIL")
        supplied["valuation_contract"]["forecast_period"][
            "start_date"
        ] = "not-an-iso-date"
        supplied["forward_valuation"]["scenarios"][0]["cash_flow_driver"][
            "capex"
        ]["evidence_ids"] = None
        result = build_forward_valuation_contract(parent_contract(), supplied)
        self.assertEqual(result["status"], "INVALID")
        codes = {row["code"] for row in result["validation_issues"]}
        self.assertIn("FORWARD_FORECAST_PERIOD_NOT_VALIDATED", codes)
        self.assertIn("FORWARD_DRIVER_EVIDENCE_MISSING", codes)

    def test_forward_fcf_cannot_use_a_point_in_time_metric_period(self) -> None:
        supplied = forward_research_input("RETAIL")
        supplied["valuation_contract"]["metric_period"] = {
            "status": "VALIDATED",
            "start_date": "2027-07-01",
            "end_date": "2027-07-01",
            "label": "Invalid point-in-time FCF",
            "period_type": "POINT_IN_TIME_METRIC",
            "basis": "POINT_IN_TIME_AT_TARGET",
            "evidence_ids": [],
        }
        result = build_forward_valuation_contract(parent_contract(), supplied)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn(
            "FORWARD_METRIC_PERIOD_TARGET_MISMATCH",
            {row["code"] for row in result["validation_issues"]},
        )

    def test_scaled_currency_unit_is_rejected_before_per_share_valuation(self) -> None:
        supplied = forward_research_input("RETAIL")
        supplied["forward_valuation"]["unit"] = "USD_MILLIONS"
        supplied["forward_valuation"]["amount_scale"] = 1_000_000.0
        result = build_forward_valuation_contract(parent_contract(), supplied)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn(
            "FORWARD_MODEL_UNIT_SCALE_UNSUPPORTED",
            {row["code"] for row in result["validation_issues"]},
        )
        self.assertIn(
            "FORWARD_MODEL_AMOUNT_SCALE_UNSUPPORTED",
            {row["code"] for row in result["validation_issues"]},
        )
        self.assertFalse(
            result["scenario_metric_eligibility"]["positive_fcf_multiple_allowed"]
        )

    def test_fact_or_calc_value_must_bind_to_matching_dated_evidence(self) -> None:
        supplied = forward_research_input("RETAIL")
        supplied["forward_valuation"]["scenarios"][0]["revenue_driver"][
            "base_revenue"
        ]["evidence_ids"] = [EVIDENCE_ID]
        result = build_forward_valuation_contract(parent_contract(), supplied)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn(
            "FORWARD_DRIVER_EVIDENCE_BINDING_FAILED",
            {row["code"] for row in result["validation_issues"]},
        )

    def test_negative_forward_fcf_is_valid_but_not_multiple_eligible(self) -> None:
        result = build_forward_valuation_contract(
            parent_contract(),
            forward_research_input("INDUSTRIAL", operating_margin=-0.30),
        )
        self.assertEqual(result["status"], "VALIDATED")
        self.assertTrue(all(row["forward_fcf"] < 0 for row in result["scenarios"]))
        self.assertEqual(
            result["scenario_metric_eligibility"]["status"],
            "NOT_ELIGIBLE_FOR_POSITIVE_FCF_MULTIPLE",
        )

    def test_share_bridge_conflict_is_not_silently_resolved(self) -> None:
        supplied = forward_research_input("CONSUMER_BRAND")
        supplied["share_count_basis"] = {
            "forward_share_count_bridge_status": "COMPLETED",
            "forward_share_count_value": 90.0,
            "forward_share_count_date": "2027-07-01",
        }
        result = build_forward_valuation_contract(parent_contract(), supplied)
        self.assertEqual(result["status"], "PARTIALLY_VALIDATED")
        self.assertEqual(
            result["forward_share_count_bridge"]["status"],
            "NOT_COMPLETED",
        )
        self.assertIn(
            "FORWARD_SHARE_INPUT_CONFLICT",
            {row["code"] for row in result["validation_issues"]},
        )
        parent = parent_contract()
        parent["forward_valuation_contract"] = result
        self.assertEqual(validate_forward_valuation_contract(parent), [])

    def test_share_bridge_projection_is_compatible_with_s09_input(self) -> None:
        result = build_forward_valuation_contract(
            parent_contract(),
            forward_research_input("SUBSCRIPTION_SOFTWARE"),
        )
        projected = forward_share_basis_input(result)
        self.assertIsNotNone(projected)
        self.assertEqual(projected["forward_share_count_bridge_status"], "COMPLETED")
        self.assertEqual(projected["forward_share_count_value"], 98.0)
        self.assertEqual(projected["forward_share_count_date"], "2027-07-01")

    def test_scenario_engine_consumes_calculated_forward_fcf_and_shares(self) -> None:
        parent = parent_contract()
        research = forward_research_input("RETAIL")
        research["normalized_fcf"] = {
            "status": "VALIDATED",
            "value": 30.0,
            "reviewed_by": "FCF reviewer",
        }
        research["scenario_model"] = {
            "status": "ANALYST_VALIDATED",
            "metric": "Forward FCF",
            "reviewed_by": "Scenario reviewer",
            "scenarios": [
                {
                    "name": name,
                    "probability": probability,
                    "metric_value_total": None,
                    "growth_assumption": None,
                    "exit_multiple": multiple,
                    "key_driver": f"{name} operating bridge",
                    "falsification_trigger": f"{name} bridge failure",
                    "assumption_sources": [],
                }
                for name, probability, multiple in (
                    ("Bear", 0.2, 10.0),
                    ("Base", 0.5, 11.0),
                    ("Bull", 0.3, 12.0),
                )
            ],
        }
        forward = build_forward_valuation_contract(parent, research)
        share_basis = build_share_count_basis(parent, research, forward)
        scenarios, status = scenario_set(
            parent["valuation"],
            {},
            {},
            research,
            share_basis,
            forward,
        )
        self.assertEqual(status, "scenario_assumptions_validated")
        self.assertEqual(len(scenarios), 3)
        forward_by_name = {
            row["name"]: row["forward_fcf"] for row in forward["scenarios"]
        }
        for scenario in scenarios:
            self.assertEqual(scenario.metric, "Forward FCF")
            self.assertAlmostEqual(
                scenario.metric_per_share,
                forward_by_name[scenario.name] / 98.0,
            )
            self.assertEqual(scenario.share_count_basis_date, "2027-07-01")
            self.assertEqual(scenario.evidence_type, "CALC")

    def test_persisted_s09_forward_fcf_reconciles_to_s10(self) -> None:
        parent = parent_contract()
        result = build_forward_valuation_contract(
            parent,
            forward_research_input("RETAIL"),
        )
        shares = result["forward_share_count_bridge"]["forward_diluted_shares"]
        parent["forward_valuation_contract"] = result
        parent["scenarios"] = [
            {
                "name": row["name"],
                "metric": "Forward FCF",
                "metric_per_share": row["forward_fcf"] / shares,
                "share_count_basis_value": shares,
                "share_count_basis_date": "2027-07-01",
                "evidence_ids": [],
            }
            for row in result["scenarios"]
        ]
        self.assertEqual(validate_forward_valuation_contract(parent), [])
        parent["scenarios"][1]["metric_per_share"] = 999.0
        self.assertIn(
            "S09 Base per-share Forward FCF does not reconcile to S10.",
            validate_forward_valuation_contract(parent),
        )

    def test_manual_scenario_total_cannot_override_forward_model(self) -> None:
        parent = parent_contract()
        research = forward_research_input("INDUSTRIAL")
        research["scenario_model"] = {
            "status": "ANALYST_VALIDATED",
            "metric": "Forward FCF",
            "reviewed_by": "Scenario reviewer",
            "scenarios": [
                {
                    "name": name,
                    "metric_value_total": 999.0 if name == "Base" else None,
                    "exit_multiple": 10.0,
                    "key_driver": "Driver",
                    "falsification_trigger": "Trigger",
                }
                for name in ("Bear", "Base", "Bull")
            ],
        }
        forward = build_forward_valuation_contract(parent, research)
        share_basis = build_share_count_basis(parent, research, forward)
        scenarios, status = scenario_set(
            parent["valuation"],
            {},
            {},
            research,
            share_basis,
            forward,
        )
        self.assertEqual(scenarios, [])
        self.assertEqual(
            status,
            "blocked_base_manual_metric_conflicts_with_forward_model",
        )

    def test_missing_driver_model_cannot_fall_back_to_manual_forward_fcf(self) -> None:
        parent = parent_contract()
        research = forward_research_input("RETAIL")
        research["forward_valuation"]["driver_module"] = "UNSUPPORTED_MODEL"
        research["normalized_fcf"] = {
            "status": "VALIDATED",
            "value": 30.0,
            "reviewed_by": "FCF reviewer",
        }
        research["scenario_model"] = {
            "status": "ANALYST_VALIDATED",
            "metric": "Forward FCF",
            "reviewed_by": "Scenario reviewer",
            "scenarios": [
                {
                    "name": name,
                    "metric_value_total": value,
                    "growth_assumption": value / 30.0 - 1.0,
                    "exit_multiple": 10.0,
                    "key_driver": "Manual forward value",
                    "falsification_trigger": "Manual forward value fails",
                }
                for name, value in (("Bear", 24.0), ("Base", 30.0), ("Bull", 36.0))
            ],
        }
        forward = build_forward_valuation_contract(parent, research)
        share_basis = build_share_count_basis(parent, research, forward)
        scenarios, status = scenario_set(
            parent["valuation"],
            {},
            {},
            research,
            share_basis,
            forward,
        )
        self.assertEqual(scenarios, [])
        self.assertEqual(status, "blocked_forward_driver_model_not_validated")

    def test_valuation_status_uses_engine_result_not_manual_completion_label(self) -> None:
        parent = parent_contract()
        research = forward_research_input("DISTRIBUTION")
        research["valuation_completion"] = {
            "driver_based_forward_forecast": "NOT_COMPLETED"
        }
        forward = build_forward_valuation_contract(parent, research)
        share_basis = build_share_count_basis(parent, research, forward)
        status = build_valuation_scope_status(
            {
                "peer_valuation_context": {},
                "scenarios": [],
                "valuation_framework": {},
            },
            research,
            share_basis,
            {"formal_return_language_allowed": False},
            forward,
        )
        self.assertEqual(
            status["components"]["driver_based_forward_forecast"],
            "COMPLETED",
        )
        self.assertEqual(
            status["components"]["forward_share_count_bridge"],
            "COMPLETED",
        )

    def test_analyst_template_exposes_shared_s10_surface(self) -> None:
        template = analyst_input_template(
            {"name": "Test Company", "ticker": "TEST"}
        )["forward_valuation"]
        self.assertEqual(template["fcf_basis"], FORWARD_FCF_BASIS)
        self.assertEqual(
            set(template["module_catalog"]["modules"]),
            set(DRIVER_MODULE_REGISTRY),
        )
        self.assertEqual(
            {row["name"] for row in template["scenarios"]},
            {"Bear", "Base", "Bull"},
        )
        self.assertIn("working_capital_investment", template["scenarios"][0]["cash_flow_driver"])
        self.assertIn("convertible_dilution", template["share_count_bridge"]["changes"])

    def test_evidence_layer_records_forward_revenue_fcf_and_share_calculations(self) -> None:
        parent = parent_contract()
        research = forward_research_input("RETAIL")
        research["scenario_model"] = {
            "status": "ANALYST_VALIDATED",
            "metric": "Forward FCF",
            "reviewed_by": "Scenario reviewer",
            "scenarios": [
                {
                    "name": name,
                    "probability": probability,
                    "exit_multiple": multiple,
                    "key_driver": "Operating bridge",
                    "falsification_trigger": "Bridge failure",
                }
                for name, probability, multiple in (
                    ("Bear", 0.2, 10.0),
                    ("Base", 0.5, 11.0),
                    ("Bull", 0.3, 12.0),
                )
            ],
        }
        forward = build_forward_valuation_contract(parent, research)
        share_basis = build_share_count_basis(parent, research, forward)
        scenarios, status = scenario_set(
            parent["valuation"],
            {},
            {},
            research,
            share_basis,
            forward,
        )
        self.assertEqual(status, "scenario_assumptions_validated")
        records, _, _ = build_analysis_evidence(
            {"ticker": "TEST", "cik": "0000000001"},
            {"evidence_records": []},
            {
                "source_url": "https://example.test/price",
                "provider": "Synthetic approved feed",
                "source_level": 3,
                "provider_approval_status": "APPROVED_FOR_RESEARCH",
            },
            {
                "source_url": "https://example.test/benchmark",
                "provider": "Synthetic approved feed",
                "source_level": 3,
                "provider_approval_status": "APPROVED_FOR_RESEARCH",
            },
            {
                **parent["valuation"],
                "market_cap": 5000.0,
                "shares_source": {},
                "ltm": {},
            },
            {},
            {},
            scenarios,
            {"status": "ILLUSTRATIVE"},
            research,
            parent["evidence_records"],
            forward,
        )
        names = {row["metric_name"] for row in records}
        for metric in (
            "forward_bear_revenue",
            "forward_base_fcf",
            "forward_bull_fcf",
            "forward_share_count_basis",
        ):
            self.assertIn(metric, names)
        forward_fcf_record = next(
            row for row in records if row["metric_name"] == "forward_base_fcf"
        )
        self.assertEqual(forward_fcf_record["evidence_class"], "CALC")
        self.assertTrue(forward_fcf_record["formula"])
        self.assertTrue(forward_fcf_record["input_evidence_ids"])
        audited_parent = deepcopy(parent)
        audited_parent["evidence_records"] = [
            *parent["evidence_records"],
            *records,
        ]
        audited_parent["forward_valuation_contract"] = forward
        audited_parent["scenarios"] = [asdict(row) for row in scenarios]
        self.assertEqual(
            validate_forward_valuation_contract(audited_parent),
            [],
        )

    def test_renderer_displays_safe_fallback_and_validated_bridge(self) -> None:
        fallback = forward_operating_bridge_html(
            {
                "forward_valuation_contract": {
                    "status": "DRIVER_MODEL_NOT_AVAILABLE"
                }
            }
        )
        self.assertIn("DRIVER_MODEL_NOT_AVAILABLE", fallback)
        result = build_forward_valuation_contract(
            parent_contract(),
            forward_research_input("CONSUMER_BRAND"),
        )
        html = forward_operating_bridge_html(
            {"forward_valuation_contract": result}
        )
        self.assertIn("CONSUMER_BRAND", html)
        self.assertIn("Forward FCF", html)
        self.assertIn("98.0", html)

    def test_renderer_suppresses_invalid_forward_numbers(self) -> None:
        result = build_forward_valuation_contract(
            parent_contract(),
            forward_research_input("RETAIL"),
        )
        result["status"] = "INVALID"
        result["driver_model_status"] = "INVALID"
        result["scenarios"][1]["forward_fcf"] = 999.0
        html = forward_operating_bridge_html(
            {"forward_valuation_contract": result}
        )
        self.assertIn("suppressed", html)
        self.assertNotIn("999.0", html)

    def test_unknown_evidence_blocks_forward_model(self) -> None:
        supplied = forward_research_input("DISTRIBUTION")
        supplied["forward_valuation"]["scenarios"][1]["cash_flow_driver"]["capex"][
            "evidence_ids"
        ] = ["EV-UNKNOWN"]
        result = build_forward_valuation_contract(parent_contract(), supplied)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn(
            "FORWARD_DRIVER_EVIDENCE_UNKNOWN",
            {row["code"] for row in result["validation_issues"]},
        )

    def test_tampered_fcf_and_revenue_fail_recalculation(self) -> None:
        parent = parent_contract()
        result = build_forward_valuation_contract(
            parent,
            forward_research_input("ACQUISITION_HEAVY"),
        )
        parent["forward_valuation_contract"] = result
        result["scenarios"][1]["revenue_bridge"]["forward_revenue"]["value"] = 999.0
        result["scenarios"][1]["forward_fcf"] = 999.0
        errors = validate_forward_valuation_contract(parent)
        self.assertIn("S10 Base forward revenue does not reproduce.", errors)
        self.assertIn("S10 Base forward FCF does not reproduce.", errors)

    def test_status_downgrade_cannot_bypass_numeric_recalculation(self) -> None:
        parent = parent_contract()
        result = build_forward_valuation_contract(
            parent,
            forward_research_input("RETAIL"),
        )
        parent["forward_valuation_contract"] = result
        result["status"] = "INVALID"
        status_errors = validate_forward_valuation_contract(parent)
        self.assertIn(
            "S10 contract status does not reproduce; expected VALIDATED.",
            status_errors,
        )
        result["scenarios"][1]["forward_fcf"] = 999.0
        errors = validate_forward_valuation_contract(parent)
        self.assertIn("S10 Base forward FCF does not reproduce.", errors)

    def test_persisted_governance_and_measurement_basis_are_revalidated(self) -> None:
        parent = parent_contract()
        result = build_forward_valuation_contract(
            parent,
            forward_research_input("RETAIL"),
        )
        parent["forward_valuation_contract"] = result
        result["module_selection"]["reviewed_by"] = None
        result["scenarios"][0]["cash_flow_bridge"]["input_lines"][0][
            "measurement_basis"
        ] = "EBITDA_MARGIN"
        base_revenue = result["scenarios"][0]["revenue_bridge"]["input_lines"][0]
        base_revenue["evidence_class"] = "JUDGMENT"
        base_revenue["evidence_binding_status"] = "CONTEXTUAL"
        result["scenarios"][0]["revenue_bridge"]["forward_revenue"][
            "formula"
        ] = "unsupported formula"
        errors = validate_forward_valuation_contract(parent)
        self.assertIn("S10 validated module selection does not reproduce.", errors)
        self.assertIn(
            "S10 Bear cash-flow input operating_margin has an invalid measurement basis.",
            errors,
        )
        self.assertIn(
            "S10 Bear revenue input base_revenue uses a prohibited evidence class.",
            errors,
        )
        self.assertIn(
            "S10 Bear Forward revenue formula disagrees with the controlled method.",
            errors,
        )

    def test_tampered_forward_share_count_fails_recalculation(self) -> None:
        parent = parent_contract()
        result = build_forward_valuation_contract(
            parent,
            forward_research_input("RETAIL"),
        )
        parent["forward_valuation_contract"] = result
        result["forward_share_count_bridge"]["forward_diluted_shares"] = 999.0
        self.assertIn(
            "S10 forward share-count bridge does not reproduce.",
            validate_forward_valuation_contract(parent),
        )

    def test_tampered_share_and_scenario_evidence_fail_revalidation(self) -> None:
        parent = parent_contract()
        result = build_forward_valuation_contract(
            parent,
            forward_research_input("RETAIL"),
        )
        parent["forward_valuation_contract"] = result
        result["forward_share_count_bridge"]["input_lines"][0][
            "evidence_ids"
        ] = ["EV-UNKNOWN"]
        result["scenarios"][0]["evidence_ids"] = ["EV-UNKNOWN"]
        result["scenarios"][0]["calculation_evidence_ids"] = ["EV-UNKNOWN"]
        errors = validate_forward_valuation_contract(parent)
        self.assertIn(
            "S10 reported-share input line does not reproduce authoritative evidence.",
            errors,
        )
        self.assertTrue(
            any(
                "unknown scenario evidence IDs" in message
                for message in errors
            )
        )

    def test_malformed_persisted_contract_returns_validation_error(self) -> None:
        parent = parent_contract()
        result = build_forward_valuation_contract(
            parent,
            forward_research_input("RETAIL"),
        )
        parent["forward_valuation_contract"] = result
        result["scenarios"] = None
        errors = validate_forward_valuation_contract(parent)
        self.assertTrue(errors)
        self.assertTrue(errors[0].startswith("Malformed S10 forward-valuation contract:"))

    def test_renderer_emits_diagnostic_for_malformed_s10_contract(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        source = (
            repo_root
            / "user-demo"
            / "investment_decision_v2"
            / "v1_0_0_outputs"
            / "crox_crocs_inc"
            / "step3"
            / "underwriting_output_contract.json"
        )
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["forward_valuation_contract"] = {
            "contract_version": "1.0.0",
            "registry_version": "1.0.0",
            "status": "VALIDATED",
            "scenarios": None,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            contract_path = temp / "contract.json"
            contract_path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            manifest = render(contract_path, temp / "rendered")
            self.assertTrue(manifest["formal_report_blocked"])
            self.assertIn("diagnostic_html", manifest["outputs"])

    def test_tampered_s10_period_fails_parent_contract_reconciliation(self) -> None:
        parent = parent_contract()
        result = build_forward_valuation_contract(
            parent,
            forward_research_input("RETAIL"),
        )
        parent["forward_valuation_contract"] = result
        result["forecast_period"]["end_date"] = "2027-06-30"
        errors = validate_forward_valuation_contract(parent)
        self.assertIn(
            "S10 forecast period disagrees with the S09 valuation contract.",
            errors,
        )
        self.assertIn(
            "S10 forecast period does not reproduce the valuation horizon.",
            errors,
        )

    def test_new_engine_contains_no_ticker_specific_branch(self) -> None:
        source = (
            SCRIPT_DIR / "forward_operating_model.py"
        ).read_text(encoding="utf-8")
        lowered = source.lower()
        self.assertNotIn("if ticker", lowered)
        self.assertNotIn('ticker ==', lowered)
        self.assertNotIn("crox", lowered)
        self.assertNotIn("azo", lowered)


if __name__ == "__main__":
    unittest.main()
