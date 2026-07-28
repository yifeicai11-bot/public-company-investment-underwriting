#!/usr/bin/env python3
"""Local-only privacy boundaries for Gate 4 portfolio inputs and outputs."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
INVESTMENT_ROOT = SCRIPT_DIR.parent
GATE4_DIR = INVESTMENT_ROOT / "gate4"
TEMPLATE_DIR = GATE4_DIR / "templates"
SYNTHETIC_DIR = GATE4_DIR / "synthetic_examples"
REPO_ROOT = SCRIPT_DIR.parents[2]
DEFAULT_PRIVATE_ROOT = Path.home() / "investment_private"

PRIVATE_CLASSIFICATION = "PRIVATE_PORTFOLIO"
SYNTHETIC_CLASSIFICATION = "SYNTHETIC_PUBLIC_EXAMPLE"
SUPPORTED_CLASSIFICATIONS = {
    PRIVATE_CLASSIFICATION,
    SYNTHETIC_CLASSIFICATION,
}

PRIVATE_TEMPLATE_TARGETS = {
    "gate4_private_workspace_manifest.template.json": "gate4_private_workspace_manifest.json",
    "portfolio_policy.template.yaml": "portfolio_policy.yaml",
    "current_holdings.template.csv": "current_holdings.csv",
    "opportunity_set.template.csv": "opportunity_set.csv",
    "approval_config.template.yaml": "approval_config.yaml",
    "gate3_freshness_attestation.template.yaml": "gate3_freshness_attestation.yaml",
}

SENSITIVE_DIRECTORY_NAMES = {
    ".cache",
    ".ipynb_checkpoints",
    "__pycache__",
    "investment_private",
    "private_input",
    "private_inputs",
    "private_output",
    "private_outputs",
    "portfolio_private",
    "partner_private",
}

SENSITIVE_EXACT_FILENAMES = {
    "gate4_private_workspace_manifest.json",
    "portfolio_policy.yaml",
    "portfolio_policy.yml",
    "portfolio_policy.json",
    "current_holdings.csv",
    "current_holdings.xlsx",
    "current_holdings.xls",
    "opportunity_set.csv",
    "opportunity_set.xlsx",
    "opportunity_set.xls",
    "approval_config.yaml",
    "approval_config.yml",
    "approval_config.json",
    "gate3_freshness_attestation.yaml",
    "gate3_freshness_attestation.yml",
    "gate3_freshness_attestation.json",
    "gate4_local_entry_diagnostic.json",
    "gate4_system_assessment.json",
    "gate4_partner_decision.json",
}

SENSITIVE_NAME_TOKENS = {
    "actual_holdings",
    "client_holdings",
    "fund_holdings",
    "live_holdings",
    "portfolio_holdings",
    "partner_holdings",
    "portfolio_constraints",
    "position_sizing",
    "approved_position",
}

PRIVATE_CONTENT_FIELDS = {
    "portfolio_nav",
    "current_thesis_status",
    "market_value_base_currency",
    "approved_position_min",
    "approved_position_max",
    "designated_partner",
}

TEXT_DATA_SUFFIXES = {
    ".csv",
    ".html",
    ".ipynb",
    ".json",
    ".md",
    ".txt",
    ".tsv",
    ".yaml",
    ".yml",
}

FORBIDDEN_PUBLIC_SUFFIXES = {
    ".core",
    ".crash",
    ".dmp",
    ".log",
    ".temp",
    ".tmp",
}

APPROVED_PUBLIC_PDF_ROOTS = {
    REPO_ROOT / "examples",
    REPO_ROOT / "release-baselines",
}


class PrivacyBoundaryError(ValueError):
    """Raised without echoing private portfolio values."""


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolved_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def git_container(path: Path) -> Optional[Path]:
    resolved = resolved_path(path)
    start = resolved if resolved.is_dir() else resolved.parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def assert_local_workspace(
    root: Path,
    *,
    data_classification: str,
    allow_public_synthetic_read_only: bool = False,
) -> Path:
    if data_classification not in SUPPORTED_CLASSIFICATIONS:
        raise PrivacyBoundaryError("The workspace data classification is unsupported.")
    if root.exists() and root.is_symlink():
        raise PrivacyBoundaryError("The Gate 4 workspace root cannot be a symbolic link.")

    resolved = resolved_path(root)
    repo = resolved_path(REPO_ROOT)
    if is_within(resolved, repo):
        synthetic_read_only = (
            data_classification == SYNTHETIC_CLASSIFICATION
            and allow_public_synthetic_read_only
            and is_within(resolved, resolved_path(SYNTHETIC_DIR))
        )
        if not synthetic_read_only:
            raise PrivacyBoundaryError(
                "Gate 4 local workspaces and private outputs must remain outside the repository."
            )
        return resolved

    containing_git_root = git_container(resolved)
    if containing_git_root is not None:
        raise PrivacyBoundaryError(
            "Gate 4 private workspaces cannot be located inside any Git worktree."
        )
    return resolved


def assert_private_output_path(destination: Path, *, workspace_root: Path) -> Path:
    root = assert_local_workspace(
        workspace_root,
        data_classification=PRIVATE_CLASSIFICATION,
    )
    if destination.exists() and destination.is_symlink():
        raise PrivacyBoundaryError("Private output files cannot be symbolic links.")
    resolved = resolved_path(destination)
    if not is_within(resolved, root):
        raise PrivacyBoundaryError("Private outputs must remain inside the local workspace.")
    if resolved.suffix.lower() == ".pdf":
        raise PrivacyBoundaryError(
            "Private PDF generation is disabled until metadata sanitization is implemented."
        )
    return resolved


def secure_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def secure_atomic_write_bytes(
    destination: Path,
    payload: bytes,
    *,
    workspace_root: Path,
    overwrite: bool = True,
) -> Path:
    destination = assert_private_output_path(
        destination,
        workspace_root=workspace_root,
    )
    if destination.exists() and not overwrite:
        raise PrivacyBoundaryError("A local private file already exists; no overwrite was performed.")

    secure_directory(destination.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".gate4-write-",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        os.chmod(destination, 0o600)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return destination


def secure_atomic_write_json(
    destination: Path,
    payload: dict[str, Any],
    *,
    workspace_root: Path,
    overwrite: bool = True,
) -> Path:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return secure_atomic_write_bytes(
        destination,
        encoded,
        workspace_root=workspace_root,
        overwrite=overwrite,
    )


def _private_template_payload(template_path: Path) -> bytes:
    if template_path.suffix.lower() == ".json":
        payload = json.loads(template_path.read_text(encoding="utf-8"))
        payload["data_classification"] = PRIVATE_CLASSIFICATION
        return (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    text = template_path.read_text(encoding="utf-8")
    return text.replace("TEMPLATE_NO_DATA", PRIVATE_CLASSIFICATION).encode("utf-8")


def initialize_private_workspace(root: Path = DEFAULT_PRIVATE_ROOT) -> dict[str, Any]:
    root = assert_local_workspace(
        root,
        data_classification=PRIVATE_CLASSIFICATION,
    )
    targets = {
        TEMPLATE_DIR / template_name: root / target_name
        for template_name, target_name in PRIVATE_TEMPLATE_TARGETS.items()
    }
    existing = [target.name for target in targets.values() if target.exists()]
    if existing:
        raise PrivacyBoundaryError(
            "One or more Gate 4 private workspace files already exist; no files were changed."
        )

    secure_directory(root)
    secure_directory(root / "private_outputs")
    created: list[str] = []
    try:
        for template_path, target_path in targets.items():
            secure_atomic_write_bytes(
                target_path,
                _private_template_payload(template_path),
                workspace_root=root,
                overwrite=False,
            )
            created.append(target_path.name)
    except Exception:
        for name in created:
            candidate = root / name
            if candidate.exists():
                candidate.unlink()
        raise

    return {
        "status": "GATE_4_PRIVATE_WORKSPACE_INITIALIZED",
        "data_classification": PRIVATE_CLASSIFICATION,
        "workspace_outside_git": True,
        "directory_mode": "0700",
        "file_mode": "0600",
        "created_files": sorted(created),
        "private_output_directory": "private_outputs",
        "raw_portfolio_values_in_output": False,
    }


def _is_public_gate4_fixture(path: Path) -> bool:
    resolved = resolved_path(path)
    return any(
        is_within(resolved, resolved_path(allowed_root))
        for allowed_root in (TEMPLATE_DIR, GATE4_DIR / "schemas")
    )


def scan_repository_paths(
    paths: Iterable[Path],
    *,
    repo_root: Path = REPO_ROOT,
) -> list[dict[str, str]]:
    repo = resolved_path(repo_root)
    violations: list[dict[str, str]] = []
    for supplied_path in paths:
        path = supplied_path if supplied_path.is_absolute() else repo / supplied_path
        resolved = resolved_path(path)
        try:
            relative = resolved.relative_to(repo)
        except ValueError:
            violations.append(
                {
                    "path": str(supplied_path),
                    "rule": "PATH_OUTSIDE_REPOSITORY",
                }
            )
            continue

        if _is_public_gate4_fixture(resolved):
            continue

        lowered_parts = {part.lower() for part in relative.parts}
        basename = relative.name.lower()
        if lowered_parts.intersection(SENSITIVE_DIRECTORY_NAMES):
            violations.append(
                {"path": str(relative), "rule": "PRIVATE_DIRECTORY_NAME"}
            )
            continue
        if basename in SENSITIVE_EXACT_FILENAMES:
            violations.append(
                {"path": str(relative), "rule": "PRIVATE_INPUT_OR_OUTPUT_FILENAME"}
            )
            continue
        if any(token in basename for token in SENSITIVE_NAME_TOKENS):
            violations.append(
                {"path": str(relative), "rule": "SENSITIVE_PORTFOLIO_FILENAME"}
            )
            continue
        if resolved.suffix.lower() in FORBIDDEN_PUBLIC_SUFFIXES:
            violations.append(
                {"path": str(relative), "rule": "LOG_CRASH_CACHE_OR_TEMP_ARTIFACT"}
            )
            continue
        if resolved.suffix.lower() == ".pdf" and not any(
            is_within(resolved, resolved_path(allowed_root))
            for allowed_root in APPROVED_PUBLIC_PDF_ROOTS
        ):
            violations.append(
                {"path": str(relative), "rule": "UNAPPROVED_PDF_OUTPUT_LOCATION"}
            )
            continue
        if resolved.suffix.lower() in {".xls", ".xlsx"}:
            violations.append(
                {"path": str(relative), "rule": "UNAPPROVED_WORKBOOK_IN_PUBLIC_REPOSITORY"}
            )
            continue
        if resolved.is_symlink():
            violations.append(
                {"path": str(relative), "rule": "SYMLINKED_DATA_FILE"}
            )
            continue
        if not resolved.is_file() or resolved.suffix.lower() not in TEXT_DATA_SUFFIXES:
            continue
        try:
            if resolved.stat().st_size > 5_000_000:
                violations.append(
                    {"path": str(relative), "rule": "UNSCANNED_LARGE_DATA_FILE"}
                )
                continue
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if PRIVATE_CLASSIFICATION in text and any(
            field in text for field in PRIVATE_CONTENT_FIELDS
        ):
            violations.append(
                {"path": str(relative), "rule": "PRIVATE_PORTFOLIO_CONTENT_MARKER"}
            )
    return violations
