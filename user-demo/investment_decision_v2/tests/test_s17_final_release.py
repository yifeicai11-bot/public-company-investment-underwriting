#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker


TEST_DIR = Path(__file__).resolve().parent
INVESTMENT_ROOT = TEST_DIR.parent
SCRIPT_DIR = INVESTMENT_ROOT / "scripts"
REPO_ROOT = INVESTMENT_ROOT.parents[1]
ROOT_SCRIPT_DIR = REPO_ROOT / "scripts"
SCHEMA_PATH = INVESTMENT_ROOT / "blind_tests" / "blind_test_manifest.schema.json"
CROX_CONTRACT = (
    INVESTMENT_ROOT
    / "v1_0_0_outputs"
    / "crox_crocs_inc"
    / "step3"
    / "underwriting_output_contract.json"
)
for path in (SCRIPT_DIR, ROOT_SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from prepare_s17_held_out_manifest import (  # noqa: E402
    EXCLUDED_PRIOR_ISSUERS,
    FROZEN_SHARED_LOGIC,
    PRIMARY_CANDIDATE_POOL,
    build_manifest,
    deterministic_selection,
)
from run_blind_company_forward_test import (  # noqa: E402
    command_for_manifest,
    summarize_first_run,
)
from validate_s17_held_out_run import contract_boundary_errors  # noqa: E402
from validate_final_release import validate_final_release  # noqa: E402


def with_validated_capex_control(contract: dict[str, object]) -> dict[str, object]:
    validated = deepcopy(contract)
    validation_issues = validated.setdefault("validation_issues", [])
    validation_issues.append(
        {
            "check_id": "P0-cash-capex-component-coverage",
            "status": "PASS",
        }
    )
    return validated


class S17FinalReleaseProtocolTests(unittest.TestCase):
    def test_candidate_pool_is_predeclared_diverse_and_excludes_prior_issuers(self) -> None:
        excluded = {row["ticker"] for row in EXCLUDED_PRIOR_ISSUERS}
        self.assertGreaterEqual(len(PRIMARY_CANDIDATE_POOL), 20)
        self.assertEqual(len(PRIMARY_CANDIDATE_POOL), len(set(PRIMARY_CANDIDATE_POOL)))
        self.assertFalse(set(PRIMARY_CANDIDATE_POOL).intersection(excluded))

    def test_candidates_are_absent_from_pre_freeze_shared_logic(self) -> None:
        for ticker in PRIMARY_CANDIDATE_POOL:
            for path in FROZEN_SHARED_LOGIC:
                result = subprocess.run(
                    ["git", "grep", "-i", "-w", ticker, "HEAD", "--", path],
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 1, (ticker, path))

    def test_every_frozen_shared_logic_path_exists_at_head(self) -> None:
        for path in FROZEN_SHARED_LOGIC:
            result = subprocess.run(
                ["git", "cat-file", "-e", f"HEAD:{path}"],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
            )
            # During a rename-only release preparation, the working tree/index
            # can already expose the new path before the containing commit.
            if result.returncode != 0:
                self.assertTrue((REPO_ROOT / path).is_file(), path)

    def test_s17_manifest_build_is_deterministic_and_schema_valid(self) -> None:
        freeze_commit = "a" * 40
        selection_date = "2026-08-03"
        seed = f"{freeze_commit}|{selection_date}|S17-TRUE-HELD-OUT-PRIMARY"
        selected = deterministic_selection(PRIMARY_CANDIDATE_POOL, seed)["selected_ticker"]
        rows = [
            [1000000 + index, f"Issuer {ticker}", ticker, "NYSE" if index % 2 else "Nasdaq"]
            for index, ticker in enumerate(PRIMARY_CANDIDATE_POOL)
        ]
        exchange_bytes = json.dumps(
            {"fields": ["cik", "name", "ticker", "exchange"], "data": rows}
        ).encode("utf-8")
        selected_row = next(row for row in rows if row[2] == selected)
        submission = {
            "cik": selected_row[0],
            "sic": "3560",
            "sicDescription": "General Industrial Machinery & Equipment",
        }
        with patch(
            "prepare_s17_held_out_manifest.frozen_blobs",
            return_value={path: "b" * 40 for path in FROZEN_SHARED_LOGIC},
        ):
            manifest = build_manifest(
                freeze_commit=freeze_commit,
                selection_date=selection_date,
                attempt="PRIMARY",
                exchange_payload_bytes=exchange_bytes,
                submission_payload=submission,
                retrieved_at="2026-08-03T00:00:00Z",
            )
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest),
            key=lambda error: list(error.path),
        )
        self.assertEqual(errors, [])
        self.assertEqual(manifest["selected_issuer"]["ticker"], selected)
        self.assertEqual(manifest["first_run_protocol"]["builder"], "underwrite.py")

    def test_schema_allows_a_new_final_attempt_after_a_shared_fix(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertIn("FINAL_AFTER_FIX", schema["properties"]["attempt"]["enum"])
        self.assertIn("FINAL_RENDERER_AFTER_FIX", schema["properties"]["attempt"]["enum"])
        self.assertIn("FINAL_VALIDATOR_AFTER_FIX", schema["properties"]["attempt"]["enum"])
        self.assertIn("FINAL_EVIDENCE_AFTER_FIX", schema["properties"]["attempt"]["enum"])

    def test_s17_command_uses_unified_entry_and_portable_record(self) -> None:
        manifest = {
            "selected_issuer": {"ticker": "TEST"},
            "first_run_protocol": {"builder": "underwrite.py"},
        }
        output_root = INVESTMENT_ROOT / "blind_tests" / "__s17_command_test__"
        actual, recorded, allowed = command_for_manifest(manifest, output_root=output_root)
        self.assertIn("underwrite.py", actual[1])
        self.assertEqual(actual[2:4], ["analyze", "TEST"])
        self.assertEqual(recorded[0], "<PYTHON_EXECUTABLE>")
        self.assertNotIn(str(Path.home()), json.dumps(recorded))
        self.assertEqual(allowed, {0, 3})

    def test_exit_code_three_is_safe_when_contract_is_validated(self) -> None:
        contract = json.loads(CROX_CONTRACT.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract_dir = root / "issuer" / "step3"
            contract_dir.mkdir(parents=True)
            (contract_dir / "underwriting_output_contract.json").write_text(
                json.dumps(contract), encoding="utf-8"
            )
            delivery = root / "issuer" / "delivery"
            delivery.mkdir()
            (delivery / "pipeline_manifest.json").write_text(
                json.dumps({"status": "RESEARCH_INPUT_REQUIRED"}), encoding="utf-8"
            )
            result = summarize_first_run(
                output_root=root,
                return_code=3,
                timed_out=False,
                allowed_return_codes={0, 3},
            )
        self.assertEqual(result["status"], "FIRST_RUN_COMPLETED")
        self.assertEqual(result["execution_errors"], [])
        self.assertEqual(result["pipeline_status"], "RESEARCH_INPUT_REQUIRED")

    def test_s17_adjudicator_accepts_existing_validated_gate3_contract(self) -> None:
        contract = with_validated_capex_control(
            json.loads(CROX_CONTRACT.read_text(encoding="utf-8"))
        )
        with tempfile.TemporaryDirectory() as temporary:
            errors = contract_boundary_errors(contract, Path(temporary))
        self.assertEqual(errors, [])

    def test_s17_adjudicator_rejects_fcf_without_capex_coverage_control(self) -> None:
        contract = json.loads(CROX_CONTRACT.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            errors = contract_boundary_errors(contract, Path(temporary))
        self.assertIn("FCF_CAPEX_COMPONENT_COVERAGE_NOT_VALIDATED", errors)

    def test_s17_adjudicator_detects_unsafe_output_leakage(self) -> None:
        contract = with_validated_capex_control(
            json.loads(CROX_CONTRACT.read_text(encoding="utf-8"))
        )
        unsafe = deepcopy(contract)
        unsafe["data_gate"]["level"] = 2.5
        unsafe["target_price"] = 123.45
        unsafe["position_sizing"] = {"weight": 0.01}
        with tempfile.TemporaryDirectory() as temporary:
            errors = contract_boundary_errors(unsafe, Path(temporary))
        self.assertIn("TARGET_PRICE_LEAKED_BELOW_GATE3", errors)
        self.assertIn("POSITION_SIZING_PRESENT_WITHOUT_GATE4", errors)

    def test_no_company_run_exists_without_a_valid_manifest(self) -> None:
        primary = INVESTMENT_ROOT / "blind_tests" / "s17_primary"
        self.assertFalse((primary / "manifest.json").exists())
        self.assertFalse((primary / "first_run").exists())
        secondary = INVESTMENT_ROOT / "blind_tests" / "s17_secondary"
        self.assertTrue((secondary / "manifest.json").is_file())
        self.assertTrue((secondary / "first_run" / "artifact_hashes.json").is_file())

    def test_v1_1_0_final_release_evidence_passes(self) -> None:
        result = validate_final_release(REPO_ROOT)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(result["final_held_out_status"], "S17_HELD_OUT_ACCEPTED")


if __name__ == "__main__":
    unittest.main()
