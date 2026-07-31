#!/usr/bin/env python3
from __future__ import annotations

import copy
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import yaml


TEST_DIR = Path(__file__).resolve().parent
INVESTMENT_ROOT = TEST_DIR.parent
SCRIPT_DIR = INVESTMENT_ROOT / "scripts"
SYNTHETIC_DIR = INVESTMENT_ROOT / "gate4" / "synthetic_examples"
CROX_CONTRACT = (
    INVESTMENT_ROOT
    / "friday_v1_outputs"
    / "crox_crocs_inc"
    / "step3"
    / "underwriting_output_contract.json"
)
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gate4_constraint_engine import (  # noqa: E402
    BLOCKED_CHANGED_STATUS,
    CALCULATED_STATUS,
    INCOMPLETE_STATUS,
    validate_constraint_output,
)
from run_gate4_constraint_engine import run_gate4_constraint_engine  # noqa: E402
from run_gate4_local_entry import load_gate3_contract  # noqa: E402
from underwriting_contract import active_warnings  # noqa: E402


class S13PortfolioConstraintEngineTests(unittest.TestCase):
    def copy_workspace(self, destination: Path) -> Path:
        workspace = destination / "synthetic_workspace"
        shutil.copytree(SYNTHETIC_DIR, workspace)
        return workspace

    def run_mode(
        self,
        workspace: Path,
        manifest_name: str = "synthetic_gate4_manifest.json",
    ) -> dict:
        result, output_path = run_gate4_constraint_engine(
            CROX_CONTRACT,
            workspace / manifest_name,
        )
        self.assertIsNotNone(output_path)
        assert output_path is not None
        self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)
        return result

    def rebind_workspace_to_gate3(
        self,
        workspace: Path,
        contract_path: Path,
    ) -> None:
        contract = load_gate3_contract(contract_path)
        report_dates = contract["report_dates"]
        report_date = date.fromisoformat(
            str(report_dates["analysis_generated_at"])[:10]
        )
        market_date = date.fromisoformat(report_dates["market_price_date"])
        target_date = market_date + timedelta(days=365)
        as_of = report_date.isoformat()
        reviewed_at = f"{as_of}T12:00:00Z"

        manifest_path = workspace / "synthetic_gate4_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["as_of_date"] = as_of
        manifest_path.write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )

        policy_path = workspace / "synthetic_portfolio_policy.yaml"
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        policy["as_of_date"] = as_of
        policy["expiration_review_date"] = (
            report_date + timedelta(days=365)
        ).isoformat()
        policy["reviewed_at"] = reviewed_at
        policy["gate3_eligibility_policy"].update(
            {
                "max_report_age_days": 0,
                "max_financial_data_age_days": 730,
                "max_market_data_age_days": 30,
                "max_public_source_check_lag_days": 0,
            }
        )
        policy_path.write_text(
            yaml.safe_dump(policy, sort_keys=False),
            encoding="utf-8",
        )

        for filename in (
            "synthetic_current_holdings.csv",
            "synthetic_opportunity_set.csv",
        ):
            path = workspace / filename
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
                fields = list(rows[0])
            for row in rows:
                row["as_of_date"] = as_of
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

        approval_path = workspace / "synthetic_approval_config.yaml"
        approval = yaml.safe_load(approval_path.read_text(encoding="utf-8"))
        approval["as_of_date"] = as_of
        approval["reviewed_at"] = reviewed_at
        approval_path.write_text(
            yaml.safe_dump(approval, sort_keys=False),
            encoding="utf-8",
        )

        issue_rows = list(contract.get("validation_issues", []))
        warning_rows = active_warnings(issue_rows) + active_warnings(
            contract.get("warnings", [])
        )
        warning_ids = sorted(
            {
                str(row.get("check_id"))
                for row in warning_rows
                if row.get("check_id") and row.get("category") != "portfolio"
            }
        )
        freshness_path = (
            workspace / "synthetic_gate3_freshness_attestation.yaml"
        )
        freshness = yaml.safe_load(freshness_path.read_text(encoding="utf-8"))
        freshness.update(
            {
                "gate3_report_id": contract["report_id"],
                "gate3_contract_hash": contract["contract_hash"],
                "as_of_date": as_of,
                "latest_earnings_checked_through": as_of,
                "latest_known_financial_filing_date": report_dates[
                    "latest_financial_filing_date"
                ],
                "newer_earnings_filing_known": False,
                "subsequent_events_checked_through": as_of,
                "unreviewed_material_subsequent_event_known": False,
                "reviewed_at": reviewed_at,
                "warning_escalations": [
                    {
                        "check_id": warning_id,
                        "reviewed_by": "Synthetic Freshness Reviewer",
                        "review_date": as_of,
                        "rationale": (
                            "Synthetic cross-company S13 interface test; "
                            "the underlying issuer warning remains unchanged."
                        ),
                    }
                    for warning_id in warning_ids
                ],
            }
        )
        freshness_path.write_text(
            yaml.safe_dump(freshness, sort_keys=False),
            encoding="utf-8",
        )

        candidate_path = workspace / "synthetic_s13_candidate_fixture.yaml"
        candidate_doc = yaml.safe_load(
            candidate_path.read_text(encoding="utf-8")
        )
        candidate_doc["as_of_date"] = as_of
        candidate_doc["gate3_binding"] = {
            "report_id": contract["report_id"],
            "contract_hash": contract["contract_hash"],
        }
        company = contract["company"]
        candidate = candidate_doc["candidate"]
        candidate.update(
            {
                "security_identifier": company["ticker"],
                "issuer_identifier": company["cik"],
                "issuer_name": company["name"],
                "sector": f"Synthetic Target Sector {company['ticker']}",
                "country": "United States",
                "correlation_bucket": (
                    f"Synthetic Target Bucket {company['ticker']}"
                ),
            }
        )
        for return_name in ("expected_return", "downside_return"):
            return_input = candidate[return_name]
            return_input.update(
                {
                    "as_of_date": market_date.isoformat(),
                    "target_date": target_date.isoformat(),
                    "holding_period_days": 365,
                    "source_contract_hash": contract["contract_hash"],
                    "reviewed_at": reviewed_at,
                }
            )
        candidate["liquidity"]["source_as_of_date"] = market_date.isoformat()
        candidate["liquidity"]["reviewed_at"] = reviewed_at
        for state in candidate_doc["portfolio_state"].values():
            state["reviewed_at"] = reviewed_at
        candidate_path.write_text(
            yaml.safe_dump(candidate_doc, sort_keys=False),
            encoding="utf-8",
        )

    @staticmethod
    def rows_by_id(result: dict) -> dict[str, dict]:
        return {row["constraint_id"]: row for row in result["constraints"]}

    def test_full_holdings_calculates_sector_binding_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_mode(self.copy_workspace(Path(tmp)))

        rows = self.rows_by_id(result)
        self.assertEqual(result["status"], CALCULATED_STATUS)
        self.assertEqual(result["output_validation"]["status"], "PASS")
        self.assertEqual(
            result["binding_constraints"],
            [
                {
                    "constraint_id": "sector",
                    "maximum_incremental_position_weight": 0.05,
                }
            ],
        )
        self.assertEqual(
            result["maximum_constraint_based_incremental_position_weight"],
            0.05,
        )
        self.assertEqual(
            result["maximum_constraint_based_total_position_weight"],
            0.05,
        )
        self.assertEqual(rows["single_name"]["maximum_incremental_position_weight"], 0.10)
        self.assertEqual(rows["sector"]["maximum_incremental_position_weight"], 0.05)
        self.assertEqual(
            rows["correlated_exposure"]["maximum_incremental_position_weight"],
            0.10,
        )
        self.assertEqual(rows["country"]["maximum_incremental_position_weight"], 0.30)
        self.assertEqual(rows["risk_budget"]["maximum_incremental_position_weight"], 0.45)
        self.assertFalse(
            result["maximum_constraint_based_position_is_recommendation"]
        )
        self.assertEqual(
            result["system_portfolio_assessment"]["status"],
            "NOT_EVALUATED",
        )
        self.assertEqual(result["partner_decision"]["decision"], "PENDING")
        self.assertFalse(result["automatic_trade_execution"])
        self.assertEqual(validate_constraint_output(result), [])

    def test_aggregated_mode_uses_complete_issuer_holdings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_mode(
                self.copy_workspace(Path(tmp)),
                "synthetic_aggregated_portfolio_manifest.json",
            )

        self.assertEqual(result["status"], CALCULATED_STATUS)
        self.assertEqual(result["input_mode"], "AGGREGATED_PORTFOLIO")
        self.assertEqual(
            result["binding_constraints"][0]["constraint_id"],
            "sector",
        )

    def test_exposure_only_mode_does_not_invent_nav_for_liquidity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_mode(
                self.copy_workspace(Path(tmp)),
                "synthetic_exposure_only_manifest.json",
            )

        rows = self.rows_by_id(result)
        self.assertEqual(result["status"], INCOMPLETE_STATUS)
        self.assertEqual(result["input_mode"], "EXPOSURE_ONLY")
        self.assertEqual(rows["existing_issuer_exposure"]["current_value"], 0.0)
        self.assertEqual(rows["liquidity_exit_capacity"]["status"], "MISSING")
        self.assertIn("manifest.portfolio_nav", result["missing_items"])
        self.assertIsNone(
            result["maximum_constraint_based_incremental_position_weight"]
        )
        self.assertEqual(result["binding_constraints"], [])
        self.assertTrue(
            result["tightest_known_constraint"]["not_final_while_inputs_missing"]
        )

    def test_missing_exposure_only_issuer_row_is_not_treated_as_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            exposure_path = workspace / "synthetic_exposure_only_summary.csv"
            with exposure_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
                fields = list(rows[0])
            rows = [row for row in rows if row["exposure_id"] != "SYNTH-ONLY-ISSUER"]
            with exposure_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            manifest_path = workspace / "synthetic_exposure_only_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["field_governance"][
                "reviewer_confirmed_not_applicable"
            ] = [
                row
                for row in manifest["field_governance"][
                    "reviewer_confirmed_not_applicable"
                ]
                if row.get("row_id") != "SYNTH-ONLY-ISSUER"
            ]
            manifest_path.write_text(
                json.dumps(manifest, indent=2),
                encoding="utf-8",
            )
            result = self.run_mode(
                workspace,
                "synthetic_exposure_only_manifest.json",
            )

        rows_by_id = self.rows_by_id(result)
        self.assertEqual(rows_by_id["existing_issuer_exposure"]["status"], "MISSING")
        self.assertEqual(rows_by_id["single_name"]["status"], "MISSING")
        self.assertIsNone(rows_by_id["single_name"]["current_value"])

    def test_exposure_only_dimension_rejects_net_measurement_basis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            exposure_path = workspace / "synthetic_exposure_only_summary.csv"
            with exposure_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
                fields = list(rows[0])
            next(
                row
                for row in rows
                if row["exposure_id"] == "SYNTH-ONLY-SECTOR"
            )["measurement_basis"] = "AGGREGATE_NET_EXPOSURE"
            with exposure_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            result = self.run_mode(
                workspace,
                "synthetic_exposure_only_manifest.json",
            )

        self.assertEqual(result["status"], "GATE_4_PRIVATE_INPUTS_REQUIRED")
        self.assertEqual(result["constraints"], [])

    def test_risk_budget_formula_uses_remaining_budget_and_formal_downside(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_mode(self.copy_workspace(Path(tmp)))

        risk = self.rows_by_id(result)["risk_budget"]
        self.assertEqual(risk["formula_inputs"]["risk_budget_limit"], 0.15)
        self.assertEqual(risk["formula_inputs"]["current_risk_budget_usage"], 0.06)
        self.assertEqual(
            risk["formula_inputs"]["candidate_validated_downside_return"],
            -0.20,
        )
        self.assertEqual(risk["remaining_capacity"], 0.09)
        self.assertEqual(risk["maximum_incremental_position_weight"], 0.45)

    def test_each_numeric_capacity_can_become_binding(self) -> None:
        cases = (
            (
                "country",
                lambda policy, candidate: policy.update(
                    {"country_concentration_limit": 0.51}
                ),
                0.01,
            ),
            (
                "correlated_exposure",
                lambda policy, candidate: policy.update(
                    {"correlated_exposure_limit": 0.32}
                ),
                0.02,
            ),
            (
                "liquidity_exit_capacity",
                lambda policy, candidate: (
                    policy["liquidity_requirement"].update(
                        {"minimum_average_daily_value_traded": 100000}
                    ),
                    candidate["candidate"]["liquidity"].update(
                        {"average_daily_value_traded": 400000}
                    ),
                ),
                0.02,
            ),
            (
                "risk_budget",
                lambda policy, candidate: candidate["portfolio_state"][
                    "current_risk_budget_usage"
                ].update({"value": 0.145}),
                0.025,
            ),
        )
        for constraint_id, mutate, expected_ceiling in cases:
            with self.subTest(constraint_id=constraint_id):
                with tempfile.TemporaryDirectory() as tmp:
                    workspace = self.copy_workspace(Path(tmp))
                    policy_path = workspace / "synthetic_portfolio_policy.yaml"
                    candidate_path = (
                        workspace / "synthetic_s13_candidate_fixture.yaml"
                    )
                    policy = yaml.safe_load(
                        policy_path.read_text(encoding="utf-8")
                    )
                    candidate = yaml.safe_load(
                        candidate_path.read_text(encoding="utf-8")
                    )
                    mutate(policy, candidate)
                    policy_path.write_text(
                        yaml.safe_dump(policy, sort_keys=False),
                        encoding="utf-8",
                    )
                    candidate_path.write_text(
                        yaml.safe_dump(candidate, sort_keys=False),
                        encoding="utf-8",
                    )
                    result = self.run_mode(workspace)

                self.assertEqual(result["status"], CALCULATED_STATUS)
                self.assertEqual(
                    result["binding_constraints"][0]["constraint_id"],
                    constraint_id,
                )
                self.assertTrue(
                    abs(
                        result[
                            "maximum_constraint_based_incremental_position_weight"
                        ]
                        - expected_ceiling
                    )
                    < 1e-12
                )

    def test_existing_issuer_exposure_can_bind_single_name_at_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            holdings_path = workspace / "synthetic_current_holdings.csv"
            with holdings_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
                fields = list(rows[0])
            rows[0]["issuer_identifier"] = "0001334036"
            with holdings_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            result = self.run_mode(workspace)

        rows_by_id = self.rows_by_id(result)
        self.assertEqual(
            rows_by_id["existing_issuer_exposure"]["current_value"],
            0.30,
        )
        self.assertEqual(rows_by_id["single_name"]["status"], "BREACH")
        self.assertEqual(
            result["maximum_constraint_based_incremental_position_weight"],
            0.0,
        )
        self.assertEqual(
            result["binding_constraints"][0]["constraint_id"],
            "single_name",
        )

    def test_each_binary_policy_constraint_can_block_incremental_weight(self) -> None:
        cases = (
            (
                "target_return",
                lambda policy, candidate: policy.update({"target_return": 0.30}),
            ),
            (
                "holding_period",
                lambda policy, candidate: policy.update(
                    {"holding_period_days": 180}
                ),
            ),
            (
                "downside",
                lambda policy, candidate: policy.update(
                    {"downside_tolerance": -0.15}
                ),
            ),
            (
                "liquidity_portfolio_floor",
                lambda policy, candidate: candidate["portfolio_state"][
                    "current_liquid_portfolio_weight"
                ].update({"value": 0.20}),
            ),
        )
        for constraint_id, mutate in cases:
            with self.subTest(constraint_id=constraint_id):
                with tempfile.TemporaryDirectory() as tmp:
                    workspace = self.copy_workspace(Path(tmp))
                    policy_path = workspace / "synthetic_portfolio_policy.yaml"
                    candidate_path = (
                        workspace / "synthetic_s13_candidate_fixture.yaml"
                    )
                    policy = yaml.safe_load(
                        policy_path.read_text(encoding="utf-8")
                    )
                    candidate = yaml.safe_load(
                        candidate_path.read_text(encoding="utf-8")
                    )
                    mutate(policy, candidate)
                    policy_path.write_text(
                        yaml.safe_dump(policy, sort_keys=False),
                        encoding="utf-8",
                    )
                    candidate_path.write_text(
                        yaml.safe_dump(candidate, sort_keys=False),
                        encoding="utf-8",
                    )
                    result = self.run_mode(workspace)

                row = self.rows_by_id(result)[constraint_id]
                self.assertEqual(row["status"], "BREACH")
                self.assertEqual(
                    row["maximum_incremental_position_weight"],
                    0.0,
                )
                self.assertEqual(
                    result[
                        "maximum_constraint_based_incremental_position_weight"
                    ],
                    0.0,
                )
                self.assertIn(
                    constraint_id,
                    {
                        item["constraint_id"]
                        for item in result["binding_constraints"]
                    },
                )

    def test_opportunity_cost_failure_creates_zero_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            path = workspace / "synthetic_s13_candidate_fixture.yaml"
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["candidate"]["expected_return"]["value"] = 0.24
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            result = self.run_mode(workspace)

        row = self.rows_by_id(result)["opportunity_cost"]
        self.assertEqual(result["status"], CALCULATED_STATUS)
        self.assertEqual(row["status"], "BREACH")
        self.assertEqual(row["maximum_incremental_position_weight"], 0.0)
        self.assertEqual(
            result["binding_constraints"][0]["constraint_id"],
            "opportunity_cost",
        )
        self.assertEqual(
            result["maximum_constraint_based_incremental_position_weight"],
            0.0,
        )

    def test_public_bear_price_sensitivity_cannot_enter_downside_constraint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            path = workspace / "synthetic_s13_candidate_fixture.yaml"
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["candidate"]["downside_return"][
                "basis"
            ] = "FORMAL_BEAR_CASE_RETURN"
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            result = self.run_mode(workspace)

        rows = self.rows_by_id(result)
        self.assertEqual(result["status"], INCOMPLETE_STATUS)
        self.assertEqual(rows["downside"]["status"], "MISSING")
        self.assertEqual(rows["risk_budget"]["status"], "MISSING")
        self.assertIn(
            "constraint_inputs.candidate.downside_return",
            result["missing_items"],
        )

    def test_required_invalid_hedge_cannot_raise_unhedged_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            path = workspace / "synthetic_s13_candidate_fixture.yaml"
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["candidate"]["proposed_hedge"] = {
                "status": "PROPOSED",
                "instrument": "UNPERMITTED_SYNTHETIC_HEDGE",
                "hedge_ratio": 0.60,
                "effectiveness_status": "NOT_EVALUATED",
                "required_for_candidate": True,
                "reviewed_by": "Synthetic Hedge Reviewer",
                "reviewed_at": "2026-07-17T12:00:00Z",
            }
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            result = self.run_mode(workspace)

        hedge = self.rows_by_id(result)["hedge"]
        self.assertEqual(hedge["status"], "BREACH")
        self.assertEqual(hedge["maximum_incremental_position_weight"], 0.0)
        self.assertFalse(hedge["formula_inputs"]["hedge_relief_credited"])
        self.assertEqual(result["binding_constraints"][0]["constraint_id"], "hedge")

    def test_reviewed_country_not_applicable_is_excluded_from_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            path = workspace / "synthetic_portfolio_policy.yaml"
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["country_limit_status"] = "NOT_APPLICABLE"
            payload["country_concentration_limit"] = None
            payload["country_limit_rationale"] = (
                "Synthetic policy does not apply a country limit."
            )
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            result = self.run_mode(workspace)

        country = self.rows_by_id(result)["country"]
        self.assertEqual(country["status"], "NOT_APPLICABLE")
        self.assertFalse(country["required_for_ceiling"])
        self.assertEqual(
            result["binding_constraints"][0]["constraint_id"],
            "sector",
        )

    def test_stale_gate3_suppresses_every_constraint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            path = workspace / "synthetic_portfolio_policy.yaml"
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["gate3_eligibility_policy"]["max_market_data_age_days"] = 0
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            result = self.run_mode(workspace)

        self.assertEqual(result["status"], "GATE_4_BLOCKED_STALE_GATE_3")
        self.assertEqual(result["constraints"], [])
        self.assertIsNone(
            result["maximum_constraint_based_incremental_position_weight"]
        )
        self.assertEqual(result["partner_decision"]["decision"], "PENDING")

    def test_stale_advt_is_blocked_before_liquidity_calculation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            path = workspace / "synthetic_s13_candidate_fixture.yaml"
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["candidate"]["liquidity"][
                "source_as_of_date"
            ] = "2026-07-01"
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            result = self.run_mode(workspace)

        self.assertEqual(result["status"], "GATE_4_PRIVATE_INPUTS_REQUIRED")
        self.assertEqual(result["constraints"], [])
        self.assertIn(
            "G4I-constraint-liquidity-chronology-currency",
            result["private_input_diagnostic"]["blocking_check_ids"],
        )

    def test_gate3_is_reloaded_and_rechecked_immediately_before_calculation(self) -> None:
        original = load_gate3_contract(CROX_CONTRACT)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            with patch(
                "run_gate4_constraint_engine.load_gate3_contract",
                side_effect=[copy.deepcopy(original), copy.deepcopy(original)],
            ) as loader:
                result = self.run_mode(workspace)

        self.assertEqual(loader.call_count, 2)
        self.assertEqual(result["status"], CALCULATED_STATUS)
        self.assertTrue(result["gate3_recheck"]["eligible"])

    def test_gate3_identity_change_between_checks_is_blocked(self) -> None:
        original = load_gate3_contract(CROX_CONTRACT)
        changed = copy.deepcopy(original)
        changed["report_id"] = "RPT-CHANGED-DURING-RECHECK"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            with patch(
                "run_gate4_constraint_engine.load_gate3_contract",
                side_effect=[original, changed],
            ):
                result = self.run_mode(workspace)

        self.assertEqual(result["status"], BLOCKED_CHANGED_STATUS)
        self.assertEqual(result["constraints"], [])
        self.assertIsNone(
            result["maximum_constraint_based_incremental_position_weight"]
        )

    def test_candidate_must_match_gate3_company_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            path = workspace / "synthetic_s13_candidate_fixture.yaml"
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["candidate"]["issuer_identifier"] = "0000320193"
            payload["candidate"]["security_identifier"] = "AAPL"
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            result = self.run_mode(workspace)

        self.assertEqual(result["status"], "GATE_4_BLOCKED_INELIGIBLE_GATE_3")
        self.assertEqual(result["constraints"], [])
        self.assertIn(
            "constraints.candidate.gate3_company_identity",
            result["missing_items"],
        )

    def test_cross_company_gate3_contracts_use_same_shared_engine(self) -> None:
        contracts = (
            INVESTMENT_ROOT
            / "friday_v1_outputs"
            / "azo_autozone_inc"
            / "step3"
            / "underwriting_output_contract.json",
            INVESTMENT_ROOT
            / "friday_v1_outputs"
            / "crm_salesforce_inc"
            / "step3"
            / "underwriting_output_contract.json",
        )
        for contract_path in contracts:
            with self.subTest(contract=contract_path.parent.parent.name):
                with tempfile.TemporaryDirectory() as tmp:
                    workspace = self.copy_workspace(Path(tmp))
                    self.rebind_workspace_to_gate3(workspace, contract_path)
                    result, _ = run_gate4_constraint_engine(
                        contract_path,
                        workspace / "synthetic_gate4_manifest.json",
                    )

                self.assertEqual(result["status"], CALCULATED_STATUS)
                self.assertEqual(
                    result["candidate_identity"]["security_identifier"],
                    result["gate3_identity"]["company"]["ticker"],
                )
                self.assertEqual(result["output_validation"]["status"], "PASS")

    def test_shared_engine_contains_no_company_specific_branch(self) -> None:
        source = (
            SCRIPT_DIR / "gate4_constraint_engine.py"
        ).read_text(encoding="utf-8")
        for token in ("CROX", "Crocs", "AZO", "AutoZone", "CRM", "Salesforce"):
            self.assertNotIn(token, source)

    def test_explicit_missing_risk_state_produces_incomplete_not_default_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            path = workspace / "synthetic_s13_candidate_fixture.yaml"
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["portfolio_state"]["current_risk_budget_usage"] = {
                "status": "MISSING",
                "value": None,
                "methodology": None,
                "source_locator": None,
                "reviewed_by": None,
                "reviewed_at": None,
            }
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            result = self.run_mode(workspace)

        risk = self.rows_by_id(result)["risk_budget"]
        self.assertEqual(result["status"], INCOMPLETE_STATUS)
        self.assertEqual(risk["status"], "MISSING")
        self.assertIsNone(risk["current_value"])
        self.assertIsNone(
            result["maximum_constraint_based_incremental_position_weight"]
        )

    def test_cli_never_prints_private_values_or_constraint_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "run_gate4_constraint_engine.py"),
                    str(CROX_CONTRACT),
                    "--manifest",
                    str(workspace / "synthetic_gate4_manifest.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0)
        self.assertIn(f"status={CALCULATED_STATUS}", completed.stdout)
        self.assertIn(
            "maximum_constraint_based_position_printed=false",
            completed.stdout,
        )
        self.assertIn("raw_private_values_printed=false", completed.stdout)
        self.assertNotIn("Crocs", completed.stdout)
        self.assertNotIn("0.05", completed.stdout)
        self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
