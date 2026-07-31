#!/usr/bin/env python3
"""Acceptance tests for S12 cross-business-model valuation behavior."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_s12_valuation_cross_company_acceptance import (  # noqa: E402
    DEFAULT_MANIFEST,
    SYNTHETIC_LABEL,
    build_guard_case,
    build_status_case,
    run_acceptance,
    validate_manifest,
)
from regression_governance import load_json  # noqa: E402


class S12ValuationCrossCompanyAcceptanceTests(unittest.TestCase):
    def test_frozen_manifest_is_valid(self) -> None:
        manifest = load_json(DEFAULT_MANIFEST)
        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(
            manifest["pre_run_commit"],
            "2a3eeaee1abb2d536f4f36001dc7ef5f0caee229",
        )

    def test_all_controlled_business_models_use_synthetic_acceptance_only(self) -> None:
        result = run_acceptance()
        self.assertEqual(
            {row["business_model"] for row in result["driver_model_acceptance"]},
            {
                "RETAIL",
                "CONSUMER_BRAND",
                "SUBSCRIPTION_SOFTWARE",
                "INDUSTRIAL",
                "ACQUISITION_HEAVY",
                "DISTRIBUTION",
            },
        )
        self.assertTrue(
            all(
                row["fixture_classification"] == SYNTHETIC_LABEL
                for row in result["driver_model_acceptance"]
            )
        )

    def test_frozen_status_paths_match_evidence(self) -> None:
        expected = {
            "S12-RANGE-CONSUMER-BRAND": "RANGE_ONLY",
            "S12-PARTIAL-RETAIL": "PARTIALLY_VALIDATED",
            "S12-MULTI-INDUSTRIAL": "MULTI_METHOD_VALIDATED",
        }
        for case_id, status in expected.items():
            with self.subTest(case_id=case_id):
                result = build_status_case(case_id)
                self.assertEqual(result["scope"]["status"], status)

    def test_one_sided_support_cannot_upgrade_range_only(self) -> None:
        for case_id in (
            "S12-GUARD-INDEPENDENT-ONLY",
            "S12-GUARD-FORWARD-ONLY",
        ):
            with self.subTest(case_id=case_id):
                result = build_guard_case(case_id)
                self.assertEqual(result["scope"]["status"], "RANGE_ONLY")

    def test_multi_method_without_s09_horizon_is_only_partial(self) -> None:
        result = build_guard_case("S12-GUARD-MULTI-WITHOUT-HORIZON")
        self.assertEqual(
            result["s11"]["status"],
            "MULTI_METHOD_VALIDATED",
        )
        self.assertFalse(
            result["valuation_contract"]["formal_return_language_allowed"]
        )
        self.assertEqual(
            result["scope"]["status"],
            "PARTIALLY_VALIDATED",
        )

    def test_return_language_fails_closed_by_status(self) -> None:
        range_case = build_status_case("S12-RANGE-CONSUMER-BRAND")
        range_outputs = range_case["valuation_contract"]["outputs"]
        self.assertEqual(
            range_outputs["price_sensitivity"]["status"],
            "VALIDATED",
        )
        self.assertEqual(
            range_outputs["base_case_return"]["status"],
            "NOT_EVALUATED",
        )
        self.assertEqual(
            range_outputs["probability_weighted_return"]["status"],
            "NOT_EVALUATED",
        )

        partial_case = build_status_case("S12-PARTIAL-RETAIL")
        partial_outputs = partial_case["valuation_contract"]["outputs"]
        self.assertEqual(
            partial_outputs["base_case_return"]["status"],
            "VALIDATED",
        )
        self.assertEqual(
            partial_outputs["probability_weighted_return"]["status"],
            "NOT_EVALUATED",
        )

        multi_case = build_status_case("S12-MULTI-INDUSTRIAL")
        multi_outputs = multi_case["valuation_contract"]["outputs"]
        self.assertEqual(
            multi_outputs["base_case_return"]["status"],
            "VALIDATED",
        )
        self.assertEqual(
            multi_outputs["probability_weighted_return"]["status"],
            "VALIDATED",
        )
        for outputs in (range_outputs, partial_outputs, multi_outputs):
            self.assertEqual(
                outputs["partner_internal_return"]["status"],
                "DISABLED_PRIVATE_GATE_4_ONLY",
            )

    def test_real_contracts_are_not_backfilled_with_synthetic_valuation(self) -> None:
        result = run_acceptance()
        rows = result["real_contract_no_backfill_acceptance"]
        self.assertEqual(
            {row["ticker"] for row in rows},
            {"CROX", "AZO", "CRM", "ODFL", "ITT"},
        )
        for row in rows:
            with self.subTest(ticker=row["ticker"]):
                self.assertEqual(
                    row["no_input_s10_status"],
                    "DRIVER_MODEL_NOT_AVAILABLE",
                )
                self.assertEqual(row["no_input_s11_status"], "NOT_PROVIDED")
                self.assertEqual(row["no_input_valuation_scope"], "RANGE_ONLY")
                self.assertFalse(row["synthetic_valuation_backfill"])

    def test_complete_acceptance_runner_passes(self) -> None:
        result = run_acceptance()
        self.assertEqual(result["status"], "PASS", result["errors"])
        self.assertEqual(result["summary"]["failed_cases"], 0)
        self.assertEqual(result["anti_hardcoding"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
