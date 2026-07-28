#!/usr/bin/env python3
from __future__ import annotations

import ast
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
GATE4_DIR = INVESTMENT_ROOT / "gate4"
SYNTHETIC_DIR = GATE4_DIR / "synthetic_examples"
REPO_ROOT = INVESTMENT_ROOT.parents[1]
CROX_CONTRACT = (
    INVESTMENT_ROOT
    / "friday_v1_outputs"
    / "crox_crocs_inc"
    / "step3"
    / "underwriting_output_contract.json"
)
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_partner_portfolio_overlay import build_overlay  # noqa: E402
from gate4_privacy import (  # noqa: E402
    PRIVATE_CLASSIFICATION,
    PrivacyBoundaryError,
    SYNTHETIC_CLASSIFICATION,
    assert_local_workspace,
    assert_private_output_path,
    initialize_private_workspace,
    scan_repository_paths,
    secure_atomic_write_json,
)
from run_gate4_local_entry import run_gate4_local_entry  # noqa: E402


class Gate4PrivacyTests(unittest.TestCase):
    def copy_synthetic_workspace(self, destination: Path) -> Path:
        workspace = destination / "synthetic_workspace"
        shutil.copytree(SYNTHETIC_DIR, workspace)
        return workspace / "synthetic_gate4_manifest.json"

    def test_private_workspace_inside_repository_is_blocked(self) -> None:
        candidate = REPO_ROOT / "private_inputs"
        with self.assertRaisesRegex(PrivacyBoundaryError, "outside the repository"):
            assert_local_workspace(
                candidate,
                data_classification=PRIVATE_CLASSIFICATION,
            )

    def test_private_workspace_inside_another_git_worktree_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            git_root = Path(tmp) / "other_repo"
            git_root.mkdir()
            (git_root / ".git").mkdir()
            candidate = git_root / "investment_private"
            with self.assertRaisesRegex(PrivacyBoundaryError, "Git worktree"):
                assert_local_workspace(
                    candidate,
                    data_classification=PRIVATE_CLASSIFICATION,
                )

    def test_public_synthetic_fixture_is_read_only_and_explicit(self) -> None:
        resolved = assert_local_workspace(
            SYNTHETIC_DIR,
            data_classification=SYNTHETIC_CLASSIFICATION,
            allow_public_synthetic_read_only=True,
        )
        self.assertEqual(resolved, SYNTHETIC_DIR.resolve())
        with self.assertRaises(PrivacyBoundaryError):
            assert_local_workspace(
                SYNTHETIC_DIR,
                data_classification=SYNTHETIC_CLASSIFICATION,
            )

    def test_workspace_initializer_uses_secure_modes_and_no_policy_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "investment_private"
            result = initialize_private_workspace(root)
            manifest = json.loads(
                (root / "gate4_private_workspace_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            policy = yaml.safe_load(
                (root / "portfolio_policy.yaml").read_text(encoding="utf-8")
            )

            self.assertEqual(
                result["status"],
                "GATE_4_PRIVATE_WORKSPACE_INITIALIZED",
            )
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(
                (root / "private_outputs").stat().st_mode & 0o777,
                0o700,
            )
            for filename in result["created_files"]:
                self.assertEqual((root / filename).stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                manifest["data_classification"],
                PRIVATE_CLASSIFICATION,
            )
            self.assertIsNone(manifest["portfolio_nav"])
            self.assertEqual(
                policy["data_classification"],
                PRIVATE_CLASSIFICATION,
            )
            self.assertIsNone(policy["target_return"])

    def test_secure_output_is_atomic_private_and_pdf_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "investment_private"
            root.mkdir()
            destination = root / "private_outputs" / "diagnostic.json"
            secure_atomic_write_json(
                destination,
                {"status": "SYNTHETIC_TEST", "raw_values_included": False},
                workspace_root=root,
            )

            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertFalse(list(destination.parent.glob(".gate4-write-*.tmp")))
            with self.assertRaisesRegex(PrivacyBoundaryError, "PDF generation"):
                assert_private_output_path(
                    root / "private_outputs" / "private_report.pdf",
                    workspace_root=root,
                )

    def test_repository_scanner_blocks_names_and_private_content_without_echo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            named = repo / "current_holdings.csv"
            disguised = repo / "notes.yaml"
            named.write_text("header\n", encoding="utf-8")
            disguised.write_text(
                "data_classification: PRIVATE_PORTFOLIO\nportfolio_nav: 123456\n",
                encoding="utf-8",
            )

            violations = scan_repository_paths(
                [Path("current_holdings.csv"), Path("notes.yaml")],
                repo_root=repo,
            )
            serialized = json.dumps(violations)

        self.assertEqual(len(violations), 2)
        self.assertNotIn("123456", serialized)
        self.assertIn("PRIVATE_INPUT_OR_OUTPUT_FILENAME", serialized)
        self.assertIn("PRIVATE_PORTFOLIO_CONTENT_MARKER", serialized)

    def test_repository_scanner_blocks_private_notebooks_logs_and_unapproved_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            notebook = repo / "analysis.ipynb"
            log_file = repo / "debug.log"
            pdf_file = repo / "portfolio_report.pdf"
            notebook.write_text(
                json.dumps(
                    {
                        "cells": [
                            {
                                "source": [
                                    "data_classification: PRIVATE_PORTFOLIO\n",
                                    "market_value_base_currency: 999\n",
                                ]
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            log_file.write_text("redacted test log", encoding="utf-8")
            pdf_file.write_bytes(b"%PDF-1.4 synthetic test")

            violations = scan_repository_paths(
                [
                    Path("analysis.ipynb"),
                    Path("debug.log"),
                    Path("portfolio_report.pdf"),
                ],
                repo_root=repo,
            )
            rules = {violation["rule"] for violation in violations}

        self.assertEqual(
            rules,
            {
                "PRIVATE_PORTFOLIO_CONTENT_MARKER",
                "LOG_CRASH_CACHE_OR_TEMP_ARTIFACT",
                "UNAPPROVED_PDF_OUTPUT_LOCATION",
            },
        )

    def test_public_templates_and_synthetic_examples_pass_repository_scan(self) -> None:
        paths = [
            path.relative_to(REPO_ROOT)
            for root in (GATE4_DIR / "templates", GATE4_DIR / "schemas", SYNTHETIC_DIR)
            for path in root.iterdir()
            if path.is_file()
        ]
        self.assertEqual(scan_repository_paths(paths, repo_root=REPO_ROOT), [])

    def test_local_entry_validates_external_synthetic_bundle_without_raw_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.copy_synthetic_workspace(Path(tmp))
            result, output_path = run_gate4_local_entry(
                CROX_CONTRACT,
                manifest_path,
            )
            serialized = json.dumps(result)

            self.assertEqual(result["status"], "GATE_4_INPUTS_VALIDATED")
            self.assertIsNotNone(output_path)
            assert output_path is not None
            self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(result["raw_private_values_included"])
            self.assertEqual(
                result["system_portfolio_assessment"]["status"],
                "NOT_EVALUATED",
            )
            self.assertEqual(
                result["partner_decision"]["workflow_status"],
                "PARTNER_APPROVAL_PENDING",
            )
            for private_value in (
                "Synthetic Alpha Corp",
                "Synthetic Partner",
                "10000000",
                "target_return",
            ):
                self.assertNotIn(private_value, serialized)

    def test_local_entry_propagates_stale_gate3_and_suppresses_calculations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.copy_synthetic_workspace(Path(tmp))
            policy_path = manifest_path.parent / "synthetic_portfolio_policy.yaml"
            policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
            policy["gate3_eligibility_policy"]["max_market_data_age_days"] = 0
            policy_path.write_text(
                yaml.safe_dump(policy, sort_keys=False),
                encoding="utf-8",
            )

            result, _ = run_gate4_local_entry(CROX_CONTRACT, manifest_path)

        self.assertEqual(result["status"], "GATE_4_BLOCKED_STALE_GATE_3")
        self.assertIsNone(
            result["system_portfolio_assessment"][
                "maximum_constraint_based_position"
            ]
        )
        self.assertEqual(result["partner_decision"]["decision"], "PENDING")

    def test_legacy_overlay_builder_rejects_private_mode_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            overlay_path = Path(tmp) / "private_overlay.json"
            output_dir = Path(tmp) / "public_demo_output"
            overlay_path.write_text(
                json.dumps(
                    {
                        "data_classification": PRIVATE_CLASSIFICATION,
                        "overlay_mode": "REAL_PARTNER_INPUT",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "synthetic public examples"):
                build_overlay(CROX_CONTRACT, overlay_path, output_dir)

            self.assertFalse(output_dir.exists())

    def test_local_private_modules_do_not_import_network_or_logging_clients(self) -> None:
        prohibited_roots = {
            "boto3",
            "httpx",
            "logging",
            "requests",
            "sentry_sdk",
            "socket",
            "urllib",
        }
        for filename in (
            "gate4_privacy.py",
            "initialize_gate4_private_workspace.py",
            "run_gate4_local_entry.py",
        ):
            tree = ast.parse((SCRIPT_DIR / filename).read_text(encoding="utf-8"))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertFalse(
                imported.intersection(prohibited_roots),
                msg=f"{filename} imports a prohibited external or logging client.",
            )


if __name__ == "__main__":
    unittest.main()
