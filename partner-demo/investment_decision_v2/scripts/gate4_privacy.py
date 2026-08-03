#!/usr/bin/env python3
"""Local-only privacy boundaries for Gate 4 portfolio inputs and outputs."""

from __future__ import annotations

import json
import os
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject
except ImportError:  # pragma: no cover - exercised through dependency diagnostics
    PdfReader = None
    PdfWriter = None
    NameObject = None


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
    "exposure_summary.template.csv": "exposure_summary.csv",
    "current_holdings.template.csv": "current_holdings.csv",
    "opportunity_set.template.csv": "opportunity_set.csv",
    "portfolio_constraint_inputs.template.yaml": "portfolio_constraint_inputs.yaml",
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
    "exposure_summary.csv",
    "exposure_summary.xlsx",
    "exposure_summary.xls",
    "opportunity_set.csv",
    "opportunity_set.xlsx",
    "opportunity_set.xls",
    "portfolio_constraint_inputs.yaml",
    "portfolio_constraint_inputs.yml",
    "portfolio_constraint_inputs.json",
    "approval_config.yaml",
    "approval_config.yml",
    "approval_config.json",
    "gate3_freshness_attestation.yaml",
    "gate3_freshness_attestation.yml",
    "gate3_freshness_attestation.json",
    "gate4_local_entry_diagnostic.json",
    "gate4_constraint_engine_result.json",
    "gate4_system_assessment.json",
    "gate4_partner_decision.json",
    "gate4_one_page_summary_bilingual.md",
    "gate4_full_report_bilingual.md",
    "gate4_evidence_appendix_bilingual.md",
    "gate4_validation_report_bilingual.md",
}

SENSITIVE_NAME_TOKENS = {
    "actual_holdings",
    "client_holdings",
    "fund_holdings",
    "live_holdings",
    "portfolio_holdings",
    "portfolio_exposures",
    "current_exposures",
    "aggregate_exposures",
    "partner_holdings",
    "portfolio_constraints",
    "position_sizing",
    "constraint_inputs",
    "approved_position",
}

PRIVATE_CONTENT_FIELDS = {
    "portfolio_nav",
    "target_return",
    "downside_tolerance",
    "position_weight",
    "exposure_id",
    "exposure_type",
    "exposure_weight",
    "source_basis",
    "current_thesis_status",
    "market_value_base_currency",
    "approved_position_min",
    "approved_position_max",
    "designated_partner",
    "current_risk_budget_usage",
    "current_liquid_portfolio_weight",
    "correlated_exposure_limit",
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

SAFE_PRIVATE_PDF_METADATA = {
    "/Title": "Private Gate 4 Report",
    "/Author": "Local Gate 4",
    "/Creator": "Gate 4 PDF Sanitizer",
    "/Producer": "Gate 4 PDF Sanitizer",
}
PRIVATE_PDF_METADATA_KEYS = {
    "/LastModified",
    "/Metadata",
    "/PieceInfo",
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


def _assert_private_output_path(
    destination: Path,
    *,
    workspace_root: Path,
    allow_sanitized_pdf: bool,
) -> Path:
    root = assert_local_workspace(
        workspace_root,
        data_classification=PRIVATE_CLASSIFICATION,
    )
    if destination.exists() and destination.is_symlink():
        raise PrivacyBoundaryError("Private output files cannot be symbolic links.")
    resolved = resolved_path(destination)
    if not is_within(resolved, root):
        raise PrivacyBoundaryError("Private outputs must remain inside the local workspace.")
    if resolved.suffix.lower() == ".pdf" and not allow_sanitized_pdf:
        raise PrivacyBoundaryError(
            "Private PDFs must be written through the tested metadata sanitizer."
        )
    return resolved


def assert_private_output_path(destination: Path, *, workspace_root: Path) -> Path:
    return _assert_private_output_path(
        destination,
        workspace_root=workspace_root,
        allow_sanitized_pdf=False,
    )


def secure_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _secure_atomic_write_bytes(
    destination: Path,
    payload: bytes,
    *,
    workspace_root: Path,
    overwrite: bool = True,
    allow_sanitized_pdf: bool = False,
) -> Path:
    destination = _assert_private_output_path(
        destination,
        workspace_root=workspace_root,
        allow_sanitized_pdf=allow_sanitized_pdf,
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


def secure_atomic_write_bytes(
    destination: Path,
    payload: bytes,
    *,
    workspace_root: Path,
    overwrite: bool = True,
) -> Path:
    return _secure_atomic_write_bytes(
        destination,
        payload,
        workspace_root=workspace_root,
        overwrite=overwrite,
        allow_sanitized_pdf=False,
    )


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


def _private_pdf_source(source: Path, *, workspace_root: Path) -> tuple[Path, Path]:
    root = assert_local_workspace(
        workspace_root,
        data_classification=PRIVATE_CLASSIFICATION,
    )
    if source.exists() and source.is_symlink():
        raise PrivacyBoundaryError("Private PDF sources cannot be symbolic links.")
    resolved = resolved_path(source)
    if not is_within(resolved, root):
        raise PrivacyBoundaryError(
            "Private PDF sources must remain inside the local workspace."
        )
    if resolved.suffix.lower() != ".pdf" or not resolved.is_file():
        raise PrivacyBoundaryError("The sanitizer requires an existing local PDF.")
    return resolved, root


def _pdf_contains_disallowed_document_payload(reader: Any) -> bool:
    root = reader.trailer.get("/Root")
    if hasattr(root, "get_object"):
        root = root.get_object()
    if not isinstance(root, dict):
        return True
    if root.get("/OpenAction") is not None or root.get("/AA") is not None:
        return True
    try:
        if list(reader.attachments.keys()):
            return True
    except Exception:
        return True
    return False


def _strip_pdf_metadata_entries(
    value: Any,
    *,
    seen: set[int],
) -> None:
    try:
        resolved = value.get_object() if hasattr(value, "get_object") else value
    except Exception as exc:
        raise PrivacyBoundaryError(
            "The private PDF metadata tree could not be inspected."
        ) from exc
    object_id = id(resolved)
    if object_id in seen:
        return
    seen.add(object_id)
    if isinstance(resolved, dict):
        for key in PRIVATE_PDF_METADATA_KEYS:
            resolved.pop(NameObject(key), None)
        for child in list(resolved.values()):
            _strip_pdf_metadata_entries(child, seen=seen)
    elif isinstance(resolved, (list, tuple)):
        for child in resolved:
            _strip_pdf_metadata_entries(child, seen=seen)


def _pdf_metadata_entries_present(value: Any, *, seen: set[int]) -> bool:
    try:
        resolved = value.get_object() if hasattr(value, "get_object") else value
    except Exception:
        return True
    object_id = id(resolved)
    if object_id in seen:
        return False
    seen.add(object_id)
    if isinstance(resolved, dict):
        if any(key in resolved for key in PRIVATE_PDF_METADATA_KEYS):
            return True
        return any(
            _pdf_metadata_entries_present(child, seen=seen)
            for child in resolved.values()
        )
    if isinstance(resolved, (list, tuple)):
        return any(
            _pdf_metadata_entries_present(child, seen=seen)
            for child in resolved
        )
    return False


def _sanitized_pdf_bytes(source: Path) -> tuple[bytes, int]:
    if PdfReader is None or PdfWriter is None or NameObject is None:
        raise PrivacyBoundaryError(
            "PDF sanitization is unavailable; install requirements-gate4.txt."
        )
    try:
        reader = PdfReader(str(source), strict=True)
    except Exception as exc:
        raise PrivacyBoundaryError("The private PDF could not be parsed.") from exc
    if reader.is_encrypted:
        raise PrivacyBoundaryError("Encrypted private PDFs cannot be sanitized.")
    if _pdf_contains_disallowed_document_payload(reader):
        raise PrivacyBoundaryError(
            "The private PDF contains attachments or document-level active actions."
        )

    writer = PdfWriter()
    try:
        for page in reader.pages:
            _strip_pdf_metadata_entries(page, seen=set())
            sanitized_page = writer.add_page(page)
            _strip_pdf_metadata_entries(sanitized_page, seen=set())
        writer.add_metadata(SAFE_PRIVATE_PDF_METADATA)
        _strip_pdf_metadata_entries(writer.root_object, seen=set())
        output = BytesIO()
        writer.write(output)
        payload = output.getvalue()
    except Exception as exc:
        raise PrivacyBoundaryError("The private PDF could not be sanitized.") from exc
    return payload, len(reader.pages)


def _verify_sanitized_pdf(payload: bytes, *, expected_pages: int) -> None:
    if PdfReader is None:
        raise PrivacyBoundaryError(
            "PDF verification is unavailable; install requirements-gate4.txt."
        )
    try:
        reader = PdfReader(BytesIO(payload), strict=True)
        metadata = dict(reader.metadata or {})
        root = reader.trailer.get("/Root")
        if hasattr(root, "get_object"):
            root = root.get_object()
        metadata_stream_present = (
            not isinstance(root, dict)
            or _pdf_metadata_entries_present(root, seen=set())
        )
        valid = (
            not reader.is_encrypted
            and len(reader.pages) == expected_pages
            and metadata == SAFE_PRIVATE_PDF_METADATA
            and not metadata_stream_present
            and not _pdf_contains_disallowed_document_payload(reader)
        )
    except Exception as exc:
        raise PrivacyBoundaryError(
            "The sanitized private PDF failed verification."
        ) from exc
    if not valid:
        raise PrivacyBoundaryError(
            "The sanitized private PDF failed metadata or page verification."
        )


def sanitize_private_pdf(
    source: Path,
    destination: Path,
    *,
    workspace_root: Path,
    overwrite: bool = True,
) -> dict[str, Any]:
    source, root = _private_pdf_source(source, workspace_root=workspace_root)
    destination = _assert_private_output_path(
        destination,
        workspace_root=root,
        allow_sanitized_pdf=True,
    )
    payload, page_count = _sanitized_pdf_bytes(source)
    _verify_sanitized_pdf(payload, expected_pages=page_count)
    _secure_atomic_write_bytes(
        destination,
        payload,
        workspace_root=root,
        overwrite=overwrite,
        allow_sanitized_pdf=True,
    )
    try:
        written_payload = destination.read_bytes()
    except OSError as exc:
        raise PrivacyBoundaryError(
            "The sanitized private PDF could not be reopened."
        ) from exc
    _verify_sanitized_pdf(written_payload, expected_pages=page_count)
    return {
        "status": "GATE_4_PRIVATE_PDF_SANITIZED",
        "page_count": page_count,
        "metadata_sanitized": True,
        "xmp_removed": True,
        "attachments_absent": True,
        "output_mode": "0600",
        "source_path_included": False,
        "private_values_included_in_diagnostic": False,
    }


def _private_template_payload(
    template_path: Path,
    *,
    input_mode: str | None,
) -> bytes:
    if template_path.suffix.lower() == ".json":
        payload = json.loads(template_path.read_text(encoding="utf-8"))
        payload["data_classification"] = PRIVATE_CLASSIFICATION
        if template_path.name == "gate4_private_workspace_manifest.template.json":
            payload["input_mode"] = input_mode
            if input_mode == "EXPOSURE_ONLY":
                payload["files"]["current_holdings"] = None
            elif input_mode == "FULL_HOLDINGS":
                payload["files"]["exposure_summary"] = None
        return (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    text = template_path.read_text(encoding="utf-8")
    return text.replace("TEMPLATE_NO_DATA", PRIVATE_CLASSIFICATION).encode("utf-8")


def initialize_private_workspace(
    root: Path = DEFAULT_PRIVATE_ROOT,
    *,
    input_mode: str | None = None,
) -> dict[str, Any]:
    if input_mode is not None and input_mode not in {
        "EXPOSURE_ONLY",
        "AGGREGATED_PORTFOLIO",
        "FULL_HOLDINGS",
    }:
        raise PrivacyBoundaryError("The selected Gate 4 input mode is unsupported.")
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
                _private_template_payload(
                    template_path,
                    input_mode=input_mode,
                ),
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
        "selected_input_mode": input_mode or "NOT_SELECTED",
        "raw_portfolio_values_in_output": False,
    }


def _is_public_gate4_fixture(path: Path) -> bool:
    resolved = resolved_path(path)
    return resolved == resolved_path(GATE4_DIR / "field_governance.json") or any(
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
