#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

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
AZO_CONTRACT = (
    INVESTMENT_ROOT
    / "friday_v1_outputs"
    / "azo_autozone_inc"
    / "step3"
    / "underwriting_output_contract.json"
)
CRM_CONTRACT = (
    INVESTMENT_ROOT
    / "friday_v1_outputs"
    / "crm_salesforce_inc"
    / "step3"
    / "underwriting_output_contract.json"
)
for path in (SCRIPT_DIR, TEST_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from gate4_assessment_engine import (  # noqa: E402
    build_gate4_assessment,
    s13_result_hash,
    validate_assessment_output,
)
from gate4_private_contract import read_mapping  # noqa: E402
from gate4_reports import html_reports, markdown_reports  # noqa: E402
from run_gate4_assessment import run_gate4_assessment  # noqa: E402
from run_gate4_constraint_engine import run_gate4_constraint_engine  # noqa: E402
import test_s13_portfolio_constraint_engine as s13_test_module  # noqa: E402


class S14Gate4AssessmentTests(unittest.TestCase):
    def copy_workspace(self, destination: Path) -> Path:
        workspace = destination / "synthetic_workspace"
        shutil.copytree(SYNTHETIC_DIR, workspace)
        manifest_path = workspace / "synthetic_gate4_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["private_output_dir"] = "private_outputs"
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        return workspace

    def run_s13(self, workspace: Path) -> dict:
        result, _ = run_gate4_constraint_engine(
            CROX_CONTRACT,
            workspace / "synthetic_gate4_manifest.json",
            system_assessment_ready=True,
        )
        return result

    def build_from_s13(self, workspace: Path, s13_result: dict) -> dict:
        approval = read_mapping(workspace / "synthetic_approval_config.yaml")
        return build_gate4_assessment(
            s13_result,
            approval,
            assessment_input_fingerprint="a" * 64,
        )

    @staticmethod
    def write_decision(
        workspace: Path,
        first: dict,
        *,
        status: str,
        maximum: float | None = None,
        acknowledgements: list[str] | None = None,
        approved_by: str = "Synthetic Partner",
    ) -> None:
        path = workspace / "synthetic_approval_config.yaml"
        approval = yaml.safe_load(path.read_text(encoding="utf-8"))
        approved = status in {"APPROVED", "MODIFIED"}
        approval["partner_decision"] = {
            "status": status,
            "assessment_hash": first.get("assessment_hash"),
            "approved_by": approved_by,
            "approved_at": "2026-07-17T12:00:00Z",
            "decision_rationale": (
                "Synthetic decision used only for S14 workflow testing."
            ),
            "approved_position_basis": (
                "TOTAL_ISSUER_GROSS_LONG_WEIGHT" if approved else None
            ),
            "approved_position_min": 0.01 if approved else None,
            "approved_position_max": maximum if approved else None,
            "acknowledged_escalation_ids": (
                acknowledgements
                if acknowledgements is not None
                else (
                    list(
                        first["system_portfolio_assessment"]["escalation_ids"]
                    )
                    if approved
                    else []
                )
            ),
        }
        path.write_text(
            yaml.safe_dump(approval, sort_keys=False),
            encoding="utf-8",
        )

    def test_pending_synthetic_case_is_eligible_with_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            result, outputs = run_gate4_assessment(
                CROX_CONTRACT,
                workspace / "synthetic_gate4_manifest.json",
            )
            modes = [path.stat().st_mode & 0o777 for path in outputs.values()]

        self.assertEqual(
            result["system_portfolio_assessment"]["assessment"],
            "ELIGIBLE_WITH_ESCALATION",
        )
        self.assertEqual(result["partner_decision"]["decision"], "PENDING")
        self.assertIsNone(
            result["system_portfolio_assessment"]["position_range"]
        )
        self.assertFalse(
            result["system_portfolio_assessment"][
                "system_generated_position_recommendation"
            ]
        )
        self.assertFalse(
            result["constraint_snapshot"][
                "maximum_constraint_based_position_is_recommendation"
            ]
        )
        self.assertFalse(result["automatic_trade_execution"])
        self.assertEqual(validate_assessment_output(result), [])
        self.assertEqual(len(outputs), 5)
        self.assertTrue(all(mode == 0o600 for mode in modes))

    def test_approved_decision_binds_to_stable_assessment_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            manifest = workspace / "synthetic_gate4_manifest.json"
            first, _ = run_gate4_assessment(CROX_CONTRACT, manifest)
            self.write_decision(
                workspace,
                first,
                status="APPROVED",
                maximum=0.04,
            )
            second, _ = run_gate4_assessment(CROX_CONTRACT, manifest)

        self.assertEqual(first["assessment_hash"], second["assessment_hash"])
        self.assertEqual(second["partner_decision"]["decision"], "APPROVED")
        self.assertEqual(
            second["partner_decision"]["validation_status"], "VALIDATED"
        )
        self.assertEqual(
            second["partner_decision"]["approved_position_range"]["maximum"],
            0.04,
        )
        self.assertFalse(
            second["partner_decision"]["approved_position_range"][
                "is_system_recommendation"
            ]
        )

    def test_s13_hash_ignores_only_volatile_recheck_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            first = self.run_s13(workspace)
            later = copy.deepcopy(first)
            later["gate3_recheck"]["evaluated_at"] = "2099-12-31T23:59:59Z"

        self.assertEqual(s13_result_hash(first), s13_result_hash(later))
        later["gate3_recheck"]["status"] = "BLOCKED"
        self.assertNotEqual(s13_result_hash(first), s13_result_hash(later))

    def test_modified_decision_is_a_distinct_valid_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            manifest = workspace / "synthetic_gate4_manifest.json"
            first, _ = run_gate4_assessment(CROX_CONTRACT, manifest)
            self.write_decision(
                workspace,
                first,
                status="MODIFIED",
                maximum=0.03,
            )
            result, _ = run_gate4_assessment(CROX_CONTRACT, manifest)

        self.assertEqual(result["partner_decision"]["decision"], "MODIFIED")
        self.assertEqual(
            result["partner_decision"]["workflow_status"], "GATE_4_MODIFIED"
        )

    def test_position_above_constraint_ceiling_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            manifest = workspace / "synthetic_gate4_manifest.json"
            first, _ = run_gate4_assessment(CROX_CONTRACT, manifest)
            self.write_decision(
                workspace,
                first,
                status="APPROVED",
                maximum=0.06,
            )
            result, _ = run_gate4_assessment(CROX_CONTRACT, manifest)

        self.assertEqual(result["partner_decision"]["decision"], "PENDING")
        self.assertEqual(
            result["partner_decision"]["validation_status"], "BLOCKED"
        )
        self.assertIn(
            "APPROVED_POSITION_EXCEEDS_CONSTRAINT_CEILING",
            result["partner_decision"]["blocking_reason_codes"],
        )

    def test_unacknowledged_escalation_blocks_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            manifest = workspace / "synthetic_gate4_manifest.json"
            first, _ = run_gate4_assessment(CROX_CONTRACT, manifest)
            self.write_decision(
                workspace,
                first,
                status="APPROVED",
                maximum=0.04,
                acknowledgements=[],
            )
            result, _ = run_gate4_assessment(CROX_CONTRACT, manifest)

        self.assertIn(
            "ESCALATION_ACKNOWLEDGEMENT_MISMATCH",
            result["partner_decision"]["blocking_reason_codes"],
        )

    def test_wrong_approver_blocks_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            manifest = workspace / "synthetic_gate4_manifest.json"
            first, _ = run_gate4_assessment(CROX_CONTRACT, manifest)
            self.write_decision(
                workspace,
                first,
                status="APPROVED",
                maximum=0.04,
                approved_by="Synthetic Analyst",
            )
            result, _ = run_gate4_assessment(CROX_CONTRACT, manifest)

        self.assertIn(
            "DESIGNATED_PARTNER_MISMATCH",
            result["partner_decision"]["blocking_reason_codes"],
        )

    def test_non_required_warning_returns_review_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            s13 = self.run_s13(workspace)
            hedge = next(
                row for row in s13["constraints"] if row["constraint_id"] == "hedge"
            )
            hedge["status"] = "WARNING"
            result = self.build_from_s13(workspace, s13)

        self.assertEqual(
            result["system_portfolio_assessment"]["assessment"],
            "REVIEW_REQUIRED",
        )
        self.assertFalse(
            result["system_portfolio_assessment"][
                "can_support_partner_approval"
            ]
        )

    def test_clean_constraints_return_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            s13 = self.run_s13(workspace)
            for row in s13["constraints"]:
                row["escalation_triggered"] = False
            s13["gate3_recheck"]["escalated_warning_ids"] = []
            result = self.build_from_s13(workspace, s13)

        self.assertEqual(
            result["system_portfolio_assessment"]["assessment"],
            "ELIGIBLE",
        )
        self.assertEqual(
            result["system_portfolio_assessment"]["escalation_ids"], []
        )
        self.assertTrue(
            result["system_portfolio_assessment"][
                "can_support_partner_approval"
            ]
        )

    def test_required_breach_returns_not_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            s13 = self.run_s13(workspace)
            target = next(
                row
                for row in s13["constraints"]
                if row["constraint_id"] == "target_return"
            )
            target["status"] = "BREACH"
            target["maximum_incremental_position_weight"] = 0.0
            target["binding"] = True
            for row in s13["constraints"]:
                if row["constraint_id"] == "sector":
                    row["binding"] = False
            s13["binding_constraints"] = [
                {
                    "constraint_id": "target_return",
                    "maximum_incremental_position_weight": 0.0,
                }
            ]
            s13["maximum_constraint_based_incremental_position_weight"] = 0.0
            s13["maximum_constraint_based_total_position_weight"] = 0.0
            result = self.build_from_s13(workspace, s13)

        self.assertEqual(
            result["system_portfolio_assessment"]["assessment"],
            "NOT_ELIGIBLE",
        )
        self.assertIn(
            "target_return",
            result["system_portfolio_assessment"]["breach_ids"],
        )

    def test_incomplete_s13_returns_not_evaluated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            manifest = workspace / "synthetic_exposure_only_manifest.json"
            result, _ = run_gate4_assessment(CROX_CONTRACT, manifest)

        self.assertEqual(
            result["system_portfolio_assessment"]["assessment"],
            "NOT_EVALUATED",
        )
        self.assertIsNone(result["assessment_hash"])
        self.assertIsNone(
            result["system_portfolio_assessment"][
                "maximum_constraint_ceiling"
            ]["incremental_weight"]
        )

    def test_rejected_and_deferred_remain_human_owned(self) -> None:
        for decision in ("REJECTED", "DEFERRED"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as tmp:
                workspace = self.copy_workspace(Path(tmp))
                manifest = workspace / "synthetic_gate4_manifest.json"
                first, _ = run_gate4_assessment(CROX_CONTRACT, manifest)
                self.write_decision(
                    workspace,
                    first,
                    status=decision,
                )
                result, _ = run_gate4_assessment(CROX_CONTRACT, manifest)
            self.assertEqual(result["partner_decision"]["decision"], decision)
            self.assertIsNone(
                result["partner_decision"]["approved_position_range"]
            )
            self.assertFalse(result["partner_decision"]["system_generated"])

    def test_reports_share_contract_and_use_controlled_ceiling_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.copy_workspace(Path(tmp))
            result, _ = run_gate4_assessment(
                CROX_CONTRACT,
                workspace / "synthetic_gate4_manifest.json",
            )
        html_payloads = html_reports(result)
        markdown_payloads = markdown_reports(result)
        for payload in [*html_payloads.values(), *markdown_payloads.values()]:
            self.assertNotIn("suggested position", payload.lower())
            self.assertNotIn("recommended position", payload.lower())
            self.assertNotIn("建议仓位", payload)
            self.assertNotIn("推荐仓位", payload)
        for payload in (
            html_payloads["one_page"],
            html_payloads["full_report"],
            markdown_payloads["one_page"],
            markdown_payloads["full_report"],
        ):
            self.assertIn("Eligible with Escalation", payload)
            self.assertIn("PENDING", payload)
        self.assertIn("Constraint ceiling", html_payloads["one_page"])
        self.assertIn("约束上限", html_payloads["one_page"])

    def test_same_engine_runs_across_three_gate3_companies(self) -> None:
        helper = s13_test_module.S13PortfolioConstraintEngineTests()
        for contract_path in (CROX_CONTRACT, AZO_CONTRACT, CRM_CONTRACT):
            with self.subTest(contract=contract_path), tempfile.TemporaryDirectory() as tmp:
                workspace = self.copy_workspace(Path(tmp))
                helper.rebind_workspace_to_gate3(workspace, contract_path)
                result, _ = run_gate4_assessment(
                    contract_path,
                    workspace / "synthetic_gate4_manifest.json",
                )
            self.assertNotEqual(
                result["system_portfolio_assessment"]["assessment"],
                "NOT_EVALUATED",
            )
            self.assertEqual(result["contract_validation"]["status"], "PASS")
            self.assertEqual(result["partner_decision"]["decision"], "PENDING")


if __name__ == "__main__":
    unittest.main()
