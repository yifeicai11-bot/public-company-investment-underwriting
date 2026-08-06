#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


TEST_DIR = Path(__file__).resolve().parent
INVESTMENT_ROOT = TEST_DIR.parent
SCRIPT_DIR = INVESTMENT_ROOT / "scripts"
CROX_CONTRACT = (
    INVESTMENT_ROOT
    / "v1_0_0_outputs"
    / "crox_crocs_inc"
    / "step3"
    / "underwriting_output_contract.json"
)
AZO_CONTRACT = (
    INVESTMENT_ROOT
    / "v1_0_0_outputs"
    / "azo_autozone_inc"
    / "step3"
    / "underwriting_output_contract.json"
)
CRM_CONTRACT = (
    INVESTMENT_ROOT
    / "v1_0_0_outputs"
    / "crm_salesforce_inc"
    / "step3"
    / "underwriting_output_contract.json"
)
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from monitoring_contract import (  # noqa: E402
    calculate_monitoring_hash,
    canonical_json,
    validate_monitoring_output,
)
from monitoring_engine import build_monitoring_update  # noqa: E402
from run_monitoring_update import run_monitoring_update  # noqa: E402
from underwriting_contract import validate_output_contract  # noqa: E402


class S15MonitoringTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.previous = json.loads(CROX_CONTRACT.read_text(encoding="utf-8"))

    @staticmethod
    def policy(*rules: dict, scenario_affects: bool = False) -> dict:
        return {
            "monitoring_policy_version": "1.0.0",
            "policy_id": "CROX-S15-TEST",
            "issuer_identifier": "0001334036",
            "effective_date": "2026-07-01",
            "expiration_date": "2027-12-31",
            "review_status": "APPROVED",
            "reviewed_by": "Synthetic Monitoring Reviewer",
            "probability_review_warning_days": 30,
            "scenario_materiality_threshold_pct": 0.10,
            "scenario_changes_affect_system_assessment": scenario_affects,
            "kpi_rules": list(rules),
        }

    @staticmethod
    def rule(
        kpi_id: str,
        metric_name: str,
        *,
        evidence_class: str,
        operator: str,
        threshold: float,
        trigger_type: str,
        comparison_basis: str = "CURRENT_VALUE",
        unit: str = "USD",
        currency: str = "USD",
    ) -> dict:
        return {
            "kpi_id": kpi_id,
            "metric_name": metric_name,
            "evidence_class": evidence_class,
            "comparison_basis": comparison_basis,
            "operator": operator,
            "threshold": threshold,
            "unit": unit,
            "currency": currency,
            "trigger_type": trigger_type,
            "effective_date": "2026-07-01",
            "expiration_date": "2027-12-31",
            "rationale": "Synthetic rule for shared S15 behavior testing.",
            "reviewed_by": "Synthetic Monitoring Reviewer",
            "review_status": "APPROVED",
        }

    @staticmethod
    def metric(contract: dict, metric_name: str) -> dict:
        return next(
            row
            for row in contract["evidence_records"]
            if row.get("metric_name") == metric_name
        )

    @staticmethod
    def rehash(contract: dict) -> dict:
        contract.pop("contract_hash", None)
        contract.pop("contract_validation", None)
        contract["contract_hash"] = hashlib.sha256(
            canonical_json(contract).encode("utf-8")
        ).hexdigest()
        contract["contract_validation"] = {
            "status": "PASS",
            "errors": [],
            "validated_at": "2026-08-03T00:00:00Z",
        }
        errors = validate_output_contract(contract)
        if errors:
            raise AssertionError(errors)
        return contract

    def build(self, current: dict, policy: dict, as_of: str = "2026-08-03") -> dict:
        return build_monitoring_update(
            self.previous,
            current,
            policy,
            as_of,
            generated_at="2026-08-03T01:02:03Z",
        )

    def test_unchanged_contract_is_complete_but_formal_thesis_stays_pending(self) -> None:
        rule = self.rule(
            "REVENUE-DOWNGRADE",
            "latest_quarter_revenue",
            evidence_class="FACT",
            operator="LT",
            threshold=900_000_000,
            trigger_type="DOWNGRADE",
        )
        result = self.build(copy.deepcopy(self.previous), self.policy(rule))

        self.assertEqual(result["status"], "MONITORING_COMPLETE")
        self.assertEqual(result["system_thesis_assessment"]["assessment"], "UNCHANGED")
        self.assertEqual(result["formal_thesis_status"]["status"], "PENDING_HUMAN_REVIEW")
        self.assertIsNone(result["formal_thesis_status"]["selected_status"])
        self.assertFalse(result["automatic_trade_execution"])
        self.assertEqual(validate_monitoring_output(result), [])

    def test_fact_kpi_downgrade_trigger_produces_weakening(self) -> None:
        current = copy.deepcopy(self.previous)
        self.metric(current, "latest_quarter_revenue")["value"] = 850_000_000
        self.rehash(current)
        rule = self.rule(
            "REVENUE-DOWNGRADE",
            "latest_quarter_revenue",
            evidence_class="FACT",
            operator="LT",
            threshold=900_000_000,
            trigger_type="DOWNGRADE",
        )
        result = self.build(current, self.policy(rule))

        self.assertEqual(result["system_thesis_assessment"]["assessment"], "WEAKENING")
        self.assertEqual(result["kpi_breach_summary"]["triggered_breach_count"], 1)
        self.assertTrue(
            any(row["metric_name"] == "latest_quarter_revenue" for row in result["fact_changes"])
        )

    def test_judgment_kpi_can_flag_potential_thesis_break(self) -> None:
        current = copy.deepcopy(self.previous)
        self.metric(current, "public_data_fcf_underwriting_base")["value"] = 450_000_000
        self.rehash(current)
        rule = self.rule(
            "FCF-THESIS-BREAK",
            "public_data_fcf_underwriting_base",
            evidence_class="JUDGMENT",
            operator="LT",
            threshold=500_000_000,
            trigger_type="THESIS_BREAK",
        )
        result = self.build(current, self.policy(rule))

        self.assertEqual(
            result["system_thesis_assessment"]["assessment"],
            "POTENTIALLY_BROKEN",
        )
        self.assertEqual(result["formal_thesis_status"]["status"], "PENDING_HUMAN_REVIEW")

    def test_upgrade_and_downgrade_triggers_produce_mixed(self) -> None:
        current = copy.deepcopy(self.previous)
        self.metric(current, "latest_quarter_revenue")["value"] = 960_000_000
        self.metric(current, "latest_quarter_fcf")["value"] = -150_000_000
        self.rehash(current)
        upgrade = self.rule(
            "REVENUE-UPGRADE",
            "latest_quarter_revenue",
            evidence_class="FACT",
            operator="GT",
            threshold=950_000_000,
            trigger_type="UPGRADE",
        )
        downgrade = self.rule(
            "FCF-DOWNGRADE",
            "latest_quarter_fcf",
            evidence_class="CALC",
            operator="LT",
            threshold=-120_000_000,
            trigger_type="DOWNGRADE",
        )
        result = self.build(current, self.policy(upgrade, downgrade))

        self.assertEqual(result["system_thesis_assessment"]["assessment"], "MIXED")
        self.assertEqual(result["kpi_breach_summary"]["triggered_breach_count"], 1)
        self.assertEqual(result["kpi_breach_summary"]["upgrade_trigger_count"], 1)

    def test_upgrade_trigger_produces_strengthening(self) -> None:
        current = copy.deepcopy(self.previous)
        self.metric(current, "latest_quarter_revenue")["value"] = 960_000_000
        self.rehash(current)
        rule = self.rule(
            "REVENUE-UPGRADE",
            "latest_quarter_revenue",
            evidence_class="FACT",
            operator="GT",
            threshold=950_000_000,
            trigger_type="UPGRADE",
        )
        result = self.build(current, self.policy(rule))

        self.assertEqual(
            result["system_thesis_assessment"]["assessment"],
            "STRENGTHENING",
        )
        self.assertEqual(result["kpi_breach_summary"]["upgrade_trigger_count"], 1)

    def test_missing_kpi_does_not_create_a_thesis_view(self) -> None:
        rule = self.rule(
            "MISSING-KPI",
            "metric_that_does_not_exist",
            evidence_class="FACT",
            operator="LT",
            threshold=1,
            trigger_type="DOWNGRADE",
        )
        result = self.build(copy.deepcopy(self.previous), self.policy(rule))

        self.assertEqual(result["kpi_assessments"][0]["status"], "MISSING")
        self.assertEqual(result["system_thesis_assessment"]["assessment"], "NOT_EVALUATED")

    def test_negative_prior_denominator_suppresses_percent_change(self) -> None:
        current = copy.deepcopy(self.previous)
        self.metric(current, "latest_quarter_fcf")["value"] = -120_000_000
        self.rehash(current)
        rule = self.rule(
            "FCF-PERCENT",
            "latest_quarter_fcf",
            evidence_class="CALC",
            operator="LT",
            threshold=-0.10,
            trigger_type="DOWNGRADE",
            comparison_basis="PERCENT_CHANGE",
        )
        result = self.build(current, self.policy(rule))

        self.assertEqual(result["kpi_assessments"][0]["status"], "NOT_COMPARABLE")
        self.assertIn("zero or negative", result["kpi_assessments"][0]["limitation"])

    def test_scenario_shift_is_recorded_but_not_used_when_policy_disables_it(self) -> None:
        current = copy.deepcopy(self.previous)
        next(row for row in current["scenarios"] if row["name"] == "Base")["implied_price"] *= 0.8
        self.rehash(current)
        rule = self.rule(
            "REVENUE-DOWNGRADE",
            "latest_quarter_revenue",
            evidence_class="FACT",
            operator="LT",
            threshold=900_000_000,
            trigger_type="DOWNGRADE",
        )
        result = self.build(current, self.policy(rule, scenario_affects=False))

        self.assertEqual(result["scenario_impact"]["overall_impact"], "MATERIAL_DOWNSIDE_SHIFT")
        self.assertEqual(result["system_thesis_assessment"]["assessment"], "UNCHANGED")

    def test_approved_scenario_policy_can_inform_provisional_assessment(self) -> None:
        current = copy.deepcopy(self.previous)
        next(row for row in current["scenarios"] if row["name"] == "Base")["implied_price"] *= 0.8
        self.rehash(current)
        rule = self.rule(
            "REVENUE-DOWNGRADE",
            "latest_quarter_revenue",
            evidence_class="FACT",
            operator="LT",
            threshold=900_000_000,
            trigger_type="DOWNGRADE",
        )
        result = self.build(current, self.policy(rule, scenario_affects=True))

        self.assertEqual(result["system_thesis_assessment"]["assessment"], "WEAKENING")
        self.assertFalse(result["scenario_impact"]["formal_expected_return_recalculated"])

    def test_probability_expiration_is_dated_and_does_not_rewrite_contract(self) -> None:
        result = self.build(
            copy.deepcopy(self.previous),
            self.policy(),
            as_of="2026-11-01",
        )

        self.assertEqual(result["probability_expiration"]["status"], "EXPIRED")
        self.assertFalse(
            result["probability_expiration"]["formal_probability_outputs_remain_eligible"]
        )

    def test_new_filing_triggers_probability_review(self) -> None:
        current = copy.deepcopy(self.previous)
        current["report_dates"]["financial_statement_date"] = "2026-06-30"
        current["report_dates"]["latest_financial_filing_date"] = "2026-08-01"
        current["report_dates"]["subsequent_event_index_review_through"] = "2026-08-02"
        self.rehash(current)
        result = self.build(current, self.policy())

        self.assertEqual(result["probability_expiration"]["status"], "REVIEW_REQUIRED")
        self.assertIn(
            "NEW_EARNINGS_OR_GUIDANCE",
            result["probability_expiration"]["triggered_review_events"],
        )

    def test_tampered_contract_hash_blocks_monitoring(self) -> None:
        current = copy.deepcopy(self.previous)
        current["market_snapshot"]["price"] = 1
        result = self.build(current, self.policy())

        self.assertEqual(result["status"], "MONITORING_BLOCKED")
        self.assertEqual(result["system_thesis_assessment"]["assessment"], "NOT_EVALUATED")
        self.assertEqual(result["scenario_impact"]["status"], "NOT_EVALUATED")

    def test_different_cik_blocks_even_when_ticker_matches(self) -> None:
        current = copy.deepcopy(self.previous)
        current["company"]["cik"] = "0000000001"
        self.rehash(current)
        result = self.build(current, self.policy())

        self.assertEqual(result["status"], "MONITORING_BLOCKED")
        failed = {
            row["check_id"]
            for row in result["input_validation"]["checks"]
            if row["status"] == "FAIL"
        }
        self.assertIn("S15-issuer-identity", failed)

    def test_regressed_financial_date_blocks_monitoring(self) -> None:
        current = copy.deepcopy(self.previous)
        current["report_dates"]["financial_statement_date"] = "2025-12-31"
        self.rehash(current)
        result = self.build(current, self.policy())

        self.assertEqual(result["status"], "MONITORING_BLOCKED")

    def test_expired_policy_blocks_without_extending_dates(self) -> None:
        policy = self.policy()
        policy["expiration_date"] = "2026-07-31"
        result = self.build(copy.deepcopy(self.previous), policy)

        self.assertEqual(result["status"], "MONITORING_BLOCKED")
        self.assertEqual(result["kpi_assessments"], [])

    def test_invalid_monitoring_date_returns_a_valid_blocked_diagnostic(self) -> None:
        result = self.build(
            copy.deepcopy(self.previous),
            self.policy(),
            as_of="not-a-date",
        )

        self.assertEqual(result["status"], "MONITORING_BLOCKED")
        self.assertEqual(result["requested_monitoring_as_of_date"], "not-a-date")
        self.assertIsNone(result["monitoring_as_of_date"])
        self.assertEqual(result["contract_validation"]["status"], "PASS")

    def test_current_hard_stop_suppresses_system_thesis_reassessment(self) -> None:
        current = copy.deepcopy(self.previous)
        current["hard_stops"] = [
            {
                "check_id": "P0-S15-SYNTHETIC",
                "category": "data_integrity",
                "status": "FAIL",
                "issue_class": "HARD_STOP",
                "severity": "P0",
                "message": "Synthetic current-period integrity failure.",
                "decision_impact": "Blocks thesis reassessment.",
                "remediation": "Correct the current issuer contract.",
                "evidence_ids": [],
                "scope": "shared_data_engine",
            }
        ]
        self.rehash(current)
        result = self.build(current, self.policy())

        self.assertEqual(result["system_thesis_assessment"]["assessment"], "NOT_EVALUATED")
        self.assertEqual(result["formal_thesis_status"]["status"], "PENDING_HUMAN_REVIEW")

    def test_warning_addition_is_recorded_without_automatic_direction(self) -> None:
        current = copy.deepcopy(self.previous)
        current["warnings"].append(
            {
                "check_id": "S15-SYNTHETIC-WARNING",
                "category": "monitoring",
                "status": "WARNING",
                "issue_class": "WARNING",
                "severity": "P1",
                "message": "Synthetic warning.",
                "decision_impact": "Requires review.",
                "remediation": "Review evidence.",
                "evidence_ids": [],
                "scope": "shared_monitoring_engine",
            }
        )
        self.rehash(current)
        result = self.build(current, self.policy())

        self.assertEqual(result["warning_changes"][-1]["change_type"], "ADDED")
        self.assertEqual(result["system_thesis_assessment"]["assessment"], "NOT_EVALUATED")

    def test_monitoring_hash_detects_substantive_tampering(self) -> None:
        result = self.build(copy.deepcopy(self.previous), self.policy())
        self.assertEqual(result["monitoring_hash"], calculate_monitoring_hash(result))
        result["automatic_trade_execution"] = True
        errors = validate_monitoring_output(result)
        self.assertIn("automatic_trade_execution", errors)
        self.assertIn("monitoring_hash", errors)

    def test_cross_field_tampering_fails_even_after_hash_is_recalculated(self) -> None:
        rule = self.rule(
            "REVENUE-DOWNGRADE",
            "latest_quarter_revenue",
            evidence_class="FACT",
            operator="LT",
            threshold=900_000_000,
            trigger_type="DOWNGRADE",
        )
        result = self.build(copy.deepcopy(self.previous), self.policy(rule))
        result["kpi_assessments"][0]["status"] = "TRIGGERED"
        result["system_thesis_assessment"]["assessment"] = "WEAKENING"
        result["monitoring_hash"] = calculate_monitoring_hash(result)

        errors = validate_monitoring_output(result)

        self.assertIn(
            "kpi_assessments.status_not_reproducible:REVENUE-DOWNGRADE",
            errors,
        )

    def test_duplicate_warning_identity_blocks_monitoring(self) -> None:
        current = copy.deepcopy(self.previous)
        current["warnings"].append(copy.deepcopy(current["warnings"][0]))
        self.rehash(current)
        result = self.build(current, self.policy())

        self.assertEqual(result["status"], "MONITORING_BLOCKED")
        failed = {
            row["check_id"]
            for row in result["input_validation"]["checks"]
            if row["status"] == "FAIL"
        }
        self.assertIn("S15-current-comparison-identities", failed)

    def test_cli_writes_restrictive_contract_and_bilingual_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous_path = root / "previous.json"
            current_path = root / "current.json"
            policy_path = root / "policy.yaml"
            previous_path.write_text(json.dumps(self.previous), encoding="utf-8")
            current_path.write_text(json.dumps(self.previous), encoding="utf-8")
            policy_path.write_text(
                yaml.safe_dump(self.policy(), sort_keys=False),
                encoding="utf-8",
            )
            result, paths = run_monitoring_update(
                previous_path,
                current_path,
                policy_path,
                "2026-08-03",
                root / "out",
            )

            modes = [path.stat().st_mode & 0o777 for path in paths.values()]
            summary = paths["summary"].read_text(encoding="utf-8")

        self.assertEqual(result["contract_validation"]["status"], "PASS")
        self.assertTrue(all(mode == 0o600 for mode in modes))
        self.assertIn("持续监控更新", summary)
        self.assertIn("PENDING_HUMAN_REVIEW", summary)
        self.assertIn("Automatic trade execution", summary)

    def test_shared_engine_accepts_multiple_issuer_business_models(self) -> None:
        cases = [CROX_CONTRACT, AZO_CONTRACT, CRM_CONTRACT]
        results = []
        for path in cases:
            contract = json.loads(path.read_text(encoding="utf-8"))
            policy = self.policy()
            policy["policy_id"] = f"{contract['company']['ticker']}-S15-TEST"
            policy["issuer_identifier"] = contract["company"]["cik"]
            result = build_monitoring_update(
                contract,
                copy.deepcopy(contract),
                policy,
                "2026-08-03",
                generated_at="2026-08-03T01:02:03Z",
            )
            results.append(result)

        self.assertTrue(all(row["status"] == "MONITORING_COMPLETE" for row in results))
        self.assertTrue(all(row["contract_validation"]["status"] == "PASS" for row in results))
        self.assertTrue(all(row["automatic_trade_execution"] is False for row in results))


if __name__ == "__main__":
    unittest.main()
