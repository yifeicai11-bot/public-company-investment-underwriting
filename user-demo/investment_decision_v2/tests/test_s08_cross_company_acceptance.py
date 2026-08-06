#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
INVESTMENT_ROOT = TEST_DIR.parent
SCRIPT_DIR = INVESTMENT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from render_public_company_artifacts import render  # noqa: E402
from run_s08_cross_company_acceptance import (  # noqa: E402
    DEFAULT_MANIFEST,
    REPO_ROOT,
    build_hard_stop_contract,
    build_synthetic_safe_failure_results,
    normalize_manifest_path,
    validate_manifest,
    validate_note_event_assessment,
)


V1_CROX_CONTRACT = (
    INVESTMENT_ROOT
    / "v1_0_0_outputs"
    / "crox_crocs_inc"
    / "step3"
    / "underwriting_output_contract.json"
)


class S08ManifestAndAssessmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))

    def test_manifest_freezes_exact_s08_scope(self) -> None:
        self.assertEqual(validate_manifest(self.manifest), [])
        self.assertEqual(
            [row["ticker"] for row in self.manifest["cases"]],
            ["CROX", "AZO", "ODFL", "ITT"],
        )
        self.assertEqual(
            self.manifest["cases"][2]["role"],
            "preserved_unfamiliar_company",
        )
        self.assertEqual(
            self.manifest["cases"][3]["role"],
            "new_unfamiliar_company",
        )
        self.assertEqual(
            self.manifest["notes_and_events_control_version"],
            "1.1.0",
        )
        self.assertEqual(
            self.manifest["required_note_event_modules"],
            [
                "debt",
                "revolver",
                "leases",
                "covenants",
                "receivables",
                "bad_debt",
                "supplier_finance",
                "acquisitions",
                "amendments",
                "restatements",
                "subsequent_events",
            ],
        )

    def test_runner_resolves_relative_manifest_before_reporting(self) -> None:
        relative = DEFAULT_MANIFEST.relative_to(REPO_ROOT)
        self.assertFalse(relative.is_absolute())
        self.assertEqual(
            normalize_manifest_path(relative),
            DEFAULT_MANIFEST.resolve(),
        )

    def test_missing_module_requires_explicit_missing_information(self) -> None:
        modules = {
            module_id: {
                "module_id": module_id,
                "status": "VALIDATED",
                "required_elements": {},
                "evidence_ids": [],
                "missing_information": [],
            }
            for module_id in self.manifest["required_note_event_modules"]
        }
        modules["bad_debt"]["status"] = "MISSING"
        assessment = {
            "control_version": self.manifest[
                "notes_and_events_control_version"
            ],
            "modules": modules,
        }
        errors = validate_note_event_assessment(
            assessment,
            expected_control_version=self.manifest[
                "notes_and_events_control_version"
            ],
            required_modules=self.manifest["required_note_event_modules"],
            allowed_statuses=set(self.manifest["allowed_module_statuses"]),
            evidence_ids=set(),
            allow_hard_stop=False,
        )
        self.assertTrue(
            any("bad_debt: MISSING lacks explicit missing information" in row for row in errors)
        )

    def test_unknown_note_evidence_id_is_rejected(self) -> None:
        synthetic = build_synthetic_safe_failure_results()
        hard = synthetic["hard_stop_assessment"]
        modules = hard["modules"]
        modules["subsequent_events"]["evidence_ids"] = ["EV-UNKNOWN"]
        errors = validate_note_event_assessment(
            hard,
            expected_control_version=self.manifest[
                "notes_and_events_control_version"
            ],
            required_modules=self.manifest["required_note_event_modules"],
            allowed_statuses=set(self.manifest["allowed_module_statuses"]),
            evidence_ids=set(),
            allow_hard_stop=True,
        )
        self.assertTrue(any("unknown evidence ID EV-UNKNOWN" in row for row in errors))

    def test_synthetic_cases_cover_all_required_s08_safe_statuses(self) -> None:
        result = build_synthetic_safe_failure_results()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["errors"], [])
        self.assertTrue(
            {
                "MISSING",
                "NOT_APPLICABLE",
                "WARNING",
                "HARD_STOP",
            }.issubset(result["observed_statuses"])
        )
        self.assertIn("subsequent_events", result["hard_stop_modules"])
        self.assertIn("restatements", result["hard_stop_modules"])


class S08HardStopRenderingTests(unittest.TestCase):
    def test_hard_stop_contract_is_gate_zero_and_suppressed(self) -> None:
        live = json.loads(V1_CROX_CONTRACT.read_text(encoding="utf-8"))
        synthetic = build_synthetic_safe_failure_results()
        contract = build_hard_stop_contract(
            live,
            synthetic["hard_stop_assessment"],
        )
        self.assertEqual(contract["contract_validation"]["status"], "PASS")
        self.assertEqual(contract["data_gate"]["level"], 0)
        self.assertGreater(len(contract["hard_stops"]), 0)
        self.assertIsNone(contract["target_price"])
        self.assertIsNone(contract["probability_weighted_return"])
        self.assertIsNone(contract["position_sizing"])
        self.assertEqual(contract["portfolio_action"], "Not Evaluated")

    def test_hard_stop_renderer_outputs_diagnostic_only(self) -> None:
        live = json.loads(V1_CROX_CONTRACT.read_text(encoding="utf-8"))
        synthetic = build_synthetic_safe_failure_results()
        contract = build_hard_stop_contract(
            live,
            synthetic["hard_stop_assessment"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            manifest = render(contract_path, root / "render")
            outputs = manifest["outputs"]
            self.assertTrue(manifest["formal_report_blocked"])
            self.assertEqual(set(outputs), {"diagnostic_html"})
            diagnostic = Path(outputs["diagnostic_html"]).read_text(encoding="utf-8")
            self.assertIn("Formal report generation blocked", diagnostic)
            self.assertIn("P1-subsequent-event-review", diagnostic)
            self.assertNotIn("One_Page_Summary", diagnostic)
            self.assertNotIn("Full_Report", diagnostic)


if __name__ == "__main__":
    unittest.main()
