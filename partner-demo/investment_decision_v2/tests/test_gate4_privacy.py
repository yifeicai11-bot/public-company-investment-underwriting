#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, TextStringObject


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
    sanitize_private_pdf,
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

    def test_workspace_initializer_applies_only_an_explicit_input_mode(self) -> None:
        expected_paths = {
            "EXPOSURE_ONLY": (None, "exposure_summary.csv"),
            "AGGREGATED_PORTFOLIO": (
                "current_holdings.csv",
                "exposure_summary.csv",
            ),
            "FULL_HOLDINGS": ("current_holdings.csv", None),
        }
        for input_mode, (
            expected_holdings,
            expected_exposures,
        ) in expected_paths.items():
            with self.subTest(input_mode=input_mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "investment_private"
                result = initialize_private_workspace(
                    root,
                    input_mode=input_mode,
                )
                manifest = json.loads(
                    (root / "gate4_private_workspace_manifest.json").read_text(
                        encoding="utf-8"
                    )
                )

                self.assertEqual(result["selected_input_mode"], input_mode)
                self.assertEqual(manifest["input_mode"], input_mode)
                self.assertEqual(
                    manifest["files"]["current_holdings"],
                    expected_holdings,
                )
                self.assertEqual(
                    manifest["files"]["exposure_summary"],
                    expected_exposures,
                )
                self.assertIsNone(manifest["portfolio_nav"])

    def test_secure_output_is_atomic_and_direct_pdf_write_is_blocked(self) -> None:
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
            with self.assertRaisesRegex(PrivacyBoundaryError, "metadata sanitizer"):
                assert_private_output_path(
                    root / "private_outputs" / "private_report.pdf",
                    workspace_root=root,
                )

    def test_private_pdf_sanitizer_removes_document_info_and_xmp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "investment_private"
            output_dir = root / "private_outputs"
            output_dir.mkdir(parents=True)
            source = output_dir / "raw_private_report.pdf"
            destination = output_dir / "sanitized_private_report.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.add_blank_page(width=100, height=100)
            writer.add_metadata(
                {
                    "/Title": "Sensitive Portfolio Name",
                    "/Author": "Private Analyst",
                    "/Creator": "/Users/private-user/internal-renderer",
                }
            )
            xmp = DecodedStreamObject()
            xmp.set_data(b"<x:xmpmeta>private-user secret-path</x:xmpmeta>")
            xmp.update(
                {
                    NameObject("/Type"): NameObject("/Metadata"),
                    NameObject("/Subtype"): NameObject("/XML"),
                }
            )
            writer.root_object[NameObject("/Metadata")] = writer._add_object(xmp)
            writer.pages[0][NameObject("/Metadata")] = writer._add_object(xmp)
            writer.pages[0][NameObject("/LastModified")] = TextStringObject(
                "D:20260717120000Z"
            )
            with source.open("wb") as handle:
                writer.write(handle)

            result = sanitize_private_pdf(
                source,
                destination,
                workspace_root=root,
            )
            reader = PdfReader(destination)
            root_object = reader.trailer["/Root"].get_object()
            serialized_result = json.dumps(result)
            output_bytes = destination.read_bytes()
            output_mode = destination.stat().st_mode & 0o777
            sanitized_metadata = dict(reader.metadata or {})
            metadata_stream_present = "/Metadata" in root_object
            page_metadata_present = any(
                any(
                    key in page
                    for key in ("/Metadata", "/LastModified", "/PieceInfo")
                )
                for page in reader.pages
            )

        self.assertEqual(result["status"], "GATE_4_PRIVATE_PDF_SANITIZED")
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(output_mode, 0o600)
        self.assertEqual(
            sanitized_metadata,
            {
                "/Producer": "Gate 4 PDF Sanitizer",
                "/Title": "Private Gate 4 Report",
                "/Author": "Local Gate 4",
                "/Creator": "Gate 4 PDF Sanitizer",
            },
        )
        self.assertFalse(metadata_stream_present)
        self.assertFalse(page_metadata_present)
        self.assertNotIn(b"Sensitive Portfolio Name", output_bytes)
        self.assertNotIn(b"private-user", output_bytes)
        self.assertNotIn("raw_private_report", serialized_result)
        self.assertNotIn(str(root), serialized_result)

    def test_private_pdf_sanitizer_blocks_attachments_and_external_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "investment_private"
            output_dir = root / "private_outputs"
            output_dir.mkdir(parents=True)
            attached_source = output_dir / "attached.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.add_attachment("private.txt", b"private attachment")
            with attached_source.open("wb") as handle:
                writer.write(handle)

            with self.assertRaisesRegex(PrivacyBoundaryError, "attachments"):
                sanitize_private_pdf(
                    attached_source,
                    output_dir / "sanitized.pdf",
                    workspace_root=root,
                )
            outside_source = Path(tmp) / "outside.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            with outside_source.open("wb") as handle:
                writer.write(handle)
            with self.assertRaisesRegex(PrivacyBoundaryError, "sources"):
                sanitize_private_pdf(
                    outside_source,
                    output_dir / "sanitized.pdf",
                    workspace_root=root,
                )
            with self.assertRaisesRegex(PrivacyBoundaryError, "outputs"):
                sanitize_private_pdf(
                    attached_source,
                    Path(tmp) / "outside-output.pdf",
                    workspace_root=root,
                )

    def test_private_pdf_cli_omits_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "investment_private"
            output_dir = root / "private_outputs"
            output_dir.mkdir(parents=True)
            source = output_dir / "sensitive_portfolio_name.pdf"
            destination = output_dir / "sanitized_output.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            with source.open("wb") as handle:
                writer.write(handle)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "sanitize_gate4_private_pdf.py"),
                    str(source),
                    "--output",
                    str(destination),
                    "--root",
                    str(root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("status=GATE_4_PRIVATE_PDF_SANITIZED", result.stdout)
        self.assertIn("private_paths_printed=false", result.stdout)
        self.assertNotIn(str(root), result.stdout)
        self.assertNotIn("sensitive_portfolio_name", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_repository_scanner_blocks_names_and_private_content_without_echo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            named = repo / "current_holdings.csv"
            disguised = repo / "notes.yaml"
            disguised_exposure = repo / "exposure_notes.yaml"
            named.write_text("header\n", encoding="utf-8")
            disguised.write_text(
                "data_classification: PRIVATE_PORTFOLIO\nportfolio_nav: 123456\n",
                encoding="utf-8",
            )
            disguised_exposure.write_text(
                "data_classification: PRIVATE_PORTFOLIO\nexposure_weight: 0.314159\n",
                encoding="utf-8",
            )

            violations = scan_repository_paths(
                [
                    Path("current_holdings.csv"),
                    Path("notes.yaml"),
                    Path("exposure_notes.yaml"),
                ],
                repo_root=repo,
            )
            serialized = json.dumps(violations)

        self.assertEqual(len(violations), 3)
        self.assertNotIn("123456", serialized)
        self.assertNotIn("0.314159", serialized)
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
            for path in root.rglob("*")
            if path.is_file()
        ]
        paths.append((GATE4_DIR / "field_governance.json").relative_to(REPO_ROOT))
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

    def test_local_entry_accepts_each_validated_input_mode(self) -> None:
        for manifest_name, expected_mode in (
            ("synthetic_exposure_only_manifest.json", "EXPOSURE_ONLY"),
            (
                "synthetic_aggregated_portfolio_manifest.json",
                "AGGREGATED_PORTFOLIO",
            ),
            ("synthetic_gate4_manifest.json", "FULL_HOLDINGS"),
        ):
            with self.subTest(manifest=manifest_name), tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp) / "synthetic_workspace"
                shutil.copytree(SYNTHETIC_DIR, workspace)
                result, output_path = run_gate4_local_entry(
                    CROX_CONTRACT,
                    workspace / manifest_name,
                )

                self.assertEqual(result["status"], "GATE_4_INPUTS_VALIDATED")
                self.assertEqual(result["input_mode"], expected_mode)
                self.assertIsNotNone(output_path)
                self.assertEqual(
                    result["system_portfolio_assessment"]["status"],
                    "NOT_EVALUATED",
                )

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
            "gate4_constraint_engine.py",
            "run_gate4_constraint_engine.py",
            "sanitize_gate4_private_pdf.py",
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
