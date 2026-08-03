#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
INVESTMENT_ROOT = TEST_DIR.parent
REPO_ROOT = INVESTMENT_ROOT.parents[1]
ROOT_SCRIPTS = REPO_ROOT / "scripts"
INVESTMENT_SCRIPTS = INVESTMENT_ROOT / "scripts"
for path in (REPO_ROOT, ROOT_SCRIPTS, INVESTMENT_SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import underwrite  # noqa: E402
from check_private_data_boundaries import tracked_paths  # noqa: E402
from release_doctor import RELEASE_CANDIDATE, run_doctor  # noqa: E402
from validate_release_candidate import validate_release_candidate  # noqa: E402
from validate_skill_structure import validate_skill  # noqa: E402


def fixture_contract(*, gate: float = 3, hard_stop: bool = False) -> dict:
    hard_stops = [{"issue_id": "P0-test", "issue_class": "HARD_STOP"}] if hard_stop else []
    return {
        "schema_version": "5.1.0",
        "report_id": "RPT-S16-TEST",
        "contract_hash": "hash-s16-test",
        "company": {"ticker": "TEST", "name": "Test Issuer"},
        "data_gate": {"level": gate},
        "decision_confidence": {"level": "Medium"},
        "current_action": "Continue Research",
        "hard_stops": hard_stops,
        "warnings": [],
        "render_blockers": [],
        "contract_validation": {"status": "PASS"},
    }


class S16ReleaseUsabilityTests(unittest.TestCase):
    def test_environment_doctor_passes_in_offline_ci_mode(self) -> None:
        result = run_doctor(ci=True)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["release_candidate"], RELEASE_CANDIDATE)
        self.assertEqual(result["failure_count"], 0)

    def test_partner_ready_delivery_requires_gate3(self) -> None:
        self.assertFalse(underwrite.delivery_eligibility(fixture_contract(gate=2.5))["eligible"])
        self.assertTrue(underwrite.delivery_eligibility(fixture_contract(gate=3))["eligible"])
        self.assertFalse(underwrite.delivery_eligibility(fixture_contract(gate=3, hard_stop=True))["eligible"])

    def test_analyze_withholds_formal_reports_below_gate3(self) -> None:
        renderer_called = False

        def fake_builder(company: str, out_root: Path, research_input: Path | None) -> Path:
            step3 = out_root / "test_issuer" / "step3"
            step3.mkdir(parents=True)
            (step3 / "underwriting_output_contract.json").write_text(
                json.dumps(fixture_contract(gate=2.5)), encoding="utf-8"
            )
            (step3 / "analyst_input_template.json").write_text("{}", encoding="utf-8")
            return step3

        def fake_renderer(*args, **kwargs):
            nonlocal renderer_called
            renderer_called = True
            return {}

        with tempfile.TemporaryDirectory() as temporary:
            code, result = underwrite.run_analyze(
                "TEST",
                Path(temporary),
                builder=fake_builder,
                renderer=fake_renderer,
                validator=lambda contract, html_dir: {"status": "PASS"},
                skip_environment_check=True,
            )
            diagnostic = Path(temporary) / "test_issuer" / "delivery" / "pipeline_diagnostic.json"
            diagnostic_exists = diagnostic.exists()

        self.assertEqual(code, 3)
        self.assertEqual(result["status"], "RESEARCH_INPUT_REQUIRED")
        self.assertFalse(renderer_called)
        self.assertTrue(diagnostic_exists)

    def test_analyze_renders_only_after_independent_precheck(self) -> None:
        events: list[str] = []

        def fake_builder(company: str, out_root: Path, research_input: Path | None) -> Path:
            step3 = out_root / "test_issuer" / "step3"
            step3.mkdir(parents=True)
            (step3 / "underwriting_output_contract.json").write_text(
                json.dumps(fixture_contract(gate=3)), encoding="utf-8"
            )
            (step3 / "analyst_input_template.json").write_text("{}", encoding="utf-8")
            return step3

        def fake_validator(contract: dict, html_dir: Path | None) -> dict:
            events.append("validate-rendered" if html_dir else "validate-contract")
            return {"status": "PASS", "failure_count": 0, "checks": []}

        def fake_renderer(contract_path: Path, out_dir: Path, *, pdf: bool) -> dict:
            events.append("render")
            out_dir.mkdir(parents=True, exist_ok=True)
            return {"formal_report_blocked": False, "outputs": {}}

        with tempfile.TemporaryDirectory() as temporary:
            code, result = underwrite.run_analyze(
                "TEST",
                Path(temporary),
                builder=fake_builder,
                renderer=fake_renderer,
                validator=fake_validator,
                skip_environment_check=True,
            )
            manifest_exists = (Path(temporary) / result["manifest_path"]).exists()
            portable_result = json.dumps(result)

        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "DELIVERY_READY")
        self.assertEqual(events, ["validate-contract", "render", "validate-rendered"])
        self.assertTrue(manifest_exists)
        self.assertNotIn(temporary, portable_result)

    def test_public_entry_rejects_gate4_fields_without_logging_values(self) -> None:
        builder_called = False

        def fake_builder(company: str, out_root: Path, research_input: Path | None) -> Path:
            nonlocal builder_called
            builder_called = True
            raise AssertionError("Builder should not receive private Gate 4 inputs.")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            research_input = root / "research.json"
            research_input.write_text(
                json.dumps(
                    {
                        "portfolio_context": {"status": "VALIDATED"},
                        "position_sizing": {"weight": 0.123456789},
                    }
                ),
                encoding="utf-8",
            )
            code, result = underwrite.run_analyze(
                "TEST",
                root / "outputs",
                research_input=research_input,
                builder=fake_builder,
                skip_environment_check=True,
            )
            serialized = json.dumps(result)

        self.assertEqual(code, 4)
        self.assertEqual(result["status"], "PUBLIC_INPUT_BLOCKED")
        self.assertFalse(builder_called)
        self.assertNotIn("0.123456789", serialized)

    def test_static_release_candidate_contract_passes(self) -> None:
        report = validate_release_candidate()
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["failure_count"], 0)

    def test_skill_metadata_and_structure_pass(self) -> None:
        errors = validate_skill(REPO_ROOT / "public-firm-credit-liquidity-skill")
        self.assertEqual(errors, [])

    def test_tracked_path_mode_reads_repository_index(self) -> None:
        paths = tracked_paths(REPO_ROOT)
        self.assertIn(Path("README.md"), paths)
        self.assertIn(Path("public-firm-credit-liquidity-skill/SKILL.md"), paths)

    def test_cli_help_exposes_supported_flow(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "underwrite.py"), "--help"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        for command in ("doctor", "analyze", "render", "validate"):
            self.assertIn(command, result.stdout)


if __name__ == "__main__":
    unittest.main()
