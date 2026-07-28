#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
INVESTMENT_ROOT = TEST_DIR.parent
SCRIPT_DIR = INVESTMENT_ROOT / "scripts"
REPO_ROOT = INVESTMENT_ROOT.parents[1]
MANIFEST_PATH = INVESTMENT_ROOT / "blind_tests" / "s05_odfl" / "manifest.json"
SCHEMA_PATH = INVESTMENT_ROOT / "blind_tests" / "blind_test_manifest.schema.json"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_blind_company_forward_test import (  # noqa: E402
    BlindTestProtocolError,
    load_manifest,
    reproduce_selection,
    verify_manifest_and_freeze,
    verify_post_fix_prerequisites,
    verify_preserved_run,
)

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover
    Draft202012Validator = None
    FormatChecker = None


class BlindTestProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_manifest(MANIFEST_PATH)

    def test_manifest_matches_schema(self) -> None:
        self.assertIsNotNone(Draft202012Validator)
        assert Draft202012Validator is not None
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        )
        errors = sorted(validator.iter_errors(self.manifest), key=lambda error: list(error.path))
        self.assertEqual(errors, [])

    def test_deterministic_selection_reproduces_odfl(self) -> None:
        reproduced = reproduce_selection(self.manifest)
        self.assertEqual(reproduced["selected_ticker"], "ODFL")
        self.assertEqual(reproduced["selected_index"], 7)
        self.assertEqual(
            reproduced["seed_sha256"],
            self.manifest["selection_method"]["seed_sha256"],
        )

    def test_selected_company_was_not_a_prior_fixture(self) -> None:
        excluded = {
            row["ticker"] for row in self.manifest["excluded_prior_issuers"]
        }
        selected = self.manifest["selected_issuer"]["ticker"]
        self.assertNotIn(selected, excluded)
        self.assertEqual(len(self.manifest["candidate_pool"]), 16)
        self.assertEqual(len(set(self.manifest["candidate_pool"])), 16)

    def test_pre_run_blob_hashes_are_bound_to_frozen_commit(self) -> None:
        commit = self.manifest["pre_run_commit"]
        for relative_path, expected_blob in self.manifest[
            "pre_run_shared_logic"
        ].items():
            actual = subprocess.check_output(
                ["git", "rev-parse", f"{commit}:{relative_path}"],
                cwd=REPO_ROOT,
                text=True,
            ).strip()
            self.assertEqual(actual, expected_blob)

    def test_selected_ticker_absent_from_pre_run_shared_logic(self) -> None:
        commit = self.manifest["pre_run_commit"]
        ticker = self.manifest["selected_issuer"]["ticker"]
        for relative_path in self.manifest["pre_run_shared_logic"]:
            result = subprocess.run(
                ["git", "grep", "-i", ticker, commit, "--", relative_path],
                cwd=REPO_ROOT,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)

    def test_pre_run_verifier_rejects_post_run_shared_changes(self) -> None:
        with self.assertRaisesRegex(
            BlindTestProtocolError,
            "Shared analytical logic changed",
        ):
            verify_manifest_and_freeze(self.manifest)

    def test_manifest_tampering_is_detected(self) -> None:
        tampered = json.loads(json.dumps(self.manifest))
        tampered["selected_issuer"]["ticker"] = "CTAS"
        with self.assertRaisesRegex(BlindTestProtocolError, "deterministic draw"):
            verify_manifest_and_freeze(tampered)

    def test_first_run_directory_is_immutable_and_complete(self) -> None:
        first_run = MANIFEST_PATH.parent / "first_run"
        result = verify_preserved_run(first_run)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["file_set_unchanged"])
        self.assertTrue(result["artifact_hashes_unchanged"])
        self.assertGreater(result["artifact_count"], 0)

    def test_post_fix_prerequisites_preserve_selection_and_first_run(self) -> None:
        result = verify_post_fix_prerequisites(MANIFEST_PATH, self.manifest)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["selected_ticker"], "ODFL")
        self.assertTrue(result["selection_reproduced"])
        self.assertTrue(
            result["first_run_integrity"]["artifact_hashes_unchanged"]
        )

    def test_post_fix_attempts_and_final_run_are_immutable(self) -> None:
        for run_name in ("post_fix_attempt_1", "post_fix_attempt_2", "post_fix"):
            with self.subTest(run_name=run_name):
                result = verify_preserved_run(MANIFEST_PATH.parent / run_name)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["artifact_count"], 22)
                self.assertTrue(result["file_set_unchanged"])
                self.assertTrue(result["artifact_hashes_unchanged"])


if __name__ == "__main__":
    unittest.main()
