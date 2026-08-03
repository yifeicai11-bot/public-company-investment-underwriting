#!/usr/bin/env python3
"""Run the complete S14 assessment and approval workflow locally."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gate4_assessment_engine import (  # noqa: E402
    READY_STATUS,
    build_gate4_assessment,
)
from gate4_private_contract import (  # noqa: E402
    PrivateInputLoadError,
    load_and_validate_private_inputs,
    read_mapping,
)
from gate4_privacy import (  # noqa: E402
    PRIVATE_CLASSIFICATION,
    SUPPORTED_CLASSIFICATIONS,
    PrivacyBoundaryError,
    assert_local_workspace,
    secure_atomic_write_bytes,
    secure_atomic_write_json,
)
from gate4_reports import markdown_reports  # noqa: E402
from run_gate4_constraint_engine import run_gate4_constraint_engine  # noqa: E402
from run_gate4_local_entry import load_gate3_contract  # noqa: E402


REPORT_OUTPUT_NAMES = {
    "one_page": "gate4_one_page_summary_bilingual.md",
    "full_report": "gate4_full_report_bilingual.md",
    "evidence_appendix": "gate4_evidence_appendix_bilingual.md",
    "validation_report": "gate4_validation_report_bilingual.md",
}


def _bundle_fingerprint(
    manifest_path: Path,
    *,
    include_partner_decision: bool,
) -> str:
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    manifest = read_mapping(manifest_path)
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        raise PrivateInputLoadError("The private manifest file map is invalid.")
    paths = [("manifest", manifest_path)]
    for document, relative in sorted(files.items()):
        if document == "private_output_dir" or relative in {None, ""}:
            continue
        path = (manifest_path.parent / str(relative)).resolve(strict=True)
        paths.append((str(document), path))
    digest = hashlib.sha256()
    for document, path in paths:
        digest.update(document.encode("utf-8"))
        digest.update(b"\0")
        if document == "approval_config" and not include_partner_decision:
            approval = read_mapping(path)
            approval = dict(approval)
            approval.pop("partner_decision", None)
            payload = json.dumps(
                approval,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        else:
            payload = path.read_bytes()
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def _gate3_identity_matches_current(
    gate3_target: Path,
    s13_result: dict[str, Any],
) -> bool:
    try:
        current = load_gate3_contract(gate3_target)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    expected = s13_result.get("gate3_recheck", {}).get("gate3_identity", {})
    return (
        current.get("schema_version") == expected.get("schema_version")
        and current.get("report_id") == expected.get("report_id")
        and current.get("contract_hash") == expected.get("contract_hash")
        and current.get("company") == expected.get("company")
    )


def run_gate4_assessment(
    gate3_target: Path,
    manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Path]]:
    manifest_path = manifest_path.expanduser().resolve(strict=False)
    manifest = read_mapping(manifest_path)
    classification = manifest.get("data_classification")
    boundary_classification = (
        str(classification)
        if classification in SUPPORTED_CLASSIFICATIONS
        else PRIVATE_CLASSIFICATION
    )
    workspace_root = assert_local_workspace(
        manifest_path.parent,
        data_classification=boundary_classification,
    )
    full_fingerprint_before = _bundle_fingerprint(
        manifest_path,
        include_partner_decision=True,
    )
    assessment_fingerprint_before = _bundle_fingerprint(
        manifest_path,
        include_partner_decision=False,
    )
    s13_result, _ = run_gate4_constraint_engine(
        gate3_target,
        manifest_path,
        system_assessment_ready=True,
    )
    full_fingerprint_after = _bundle_fingerprint(
        manifest_path,
        include_partner_decision=True,
    )
    assessment_fingerprint_after = _bundle_fingerprint(
        manifest_path,
        include_partner_decision=False,
    )
    bundle, _ = load_and_validate_private_inputs(
        manifest_path,
        system_assessment_ready=True,
    )
    full_fingerprint_final = _bundle_fingerprint(
        manifest_path,
        include_partner_decision=True,
    )
    assessment_fingerprint_final = _bundle_fingerprint(
        manifest_path,
        include_partner_decision=False,
    )
    bundle_unchanged = (
        full_fingerprint_before == full_fingerprint_after
        and full_fingerprint_after == full_fingerprint_final
        and assessment_fingerprint_before == assessment_fingerprint_after
        and assessment_fingerprint_after == assessment_fingerprint_final
        and _gate3_identity_matches_current(gate3_target, s13_result)
    )
    approval_config = (
        bundle.approval
        if bundle is not None
        else {"partner_decision": {"status": "PENDING"}}
    )
    result = build_gate4_assessment(
        s13_result,
        approval_config,
        assessment_input_fingerprint=assessment_fingerprint_final,
        private_bundle_unchanged=bundle_unchanged,
    )
    outputs: dict[str, Path] = {}
    if bundle is None:
        return result, outputs

    outputs["assessment_contract"] = secure_atomic_write_json(
        bundle.output_dir / "gate4_system_assessment.json",
        result,
        workspace_root=workspace_root,
    )
    for key, payload in markdown_reports(result).items():
        outputs[key] = secure_atomic_write_bytes(
            bundle.output_dir / REPORT_OUTPUT_NAMES[key],
            payload.encode("utf-8"),
            workspace_root=workspace_root,
        )
    return result, outputs


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run S14 locally. The system assessment and Partner decision remain "
            "separate, and no trade is executed."
        )
    )
    parser.add_argument(
        "gate3_contract_or_dir",
        type=Path,
        help="Path to underwriting_output_contract.json or its containing directory.",
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Path to the local gate4_private_workspace_manifest.json.",
    )
    args = parser.parse_args()
    try:
        result, outputs = run_gate4_assessment(
            args.gate3_contract_or_dir,
            args.manifest,
        )
    except (PrivacyBoundaryError, PrivateInputLoadError, OSError, ValueError):
        print("status=GATE_4_ASSESSMENT_BLOCKED")
        print("detail=Review the local privacy-safe diagnostic.")
        print("raw_private_values_printed=false")
        return 2
    except Exception:
        print("status=GATE_4_ASSESSMENT_ERROR")
        print("detail=No private values were printed.")
        print("raw_private_values_printed=false")
        return 3

    print(f"status={result['status']}")
    print(
        "system_assessment="
        f"{result['system_portfolio_assessment']['assessment']}"
    )
    print(f"partner_decision={result['partner_decision']['decision']}")
    print(f"reports_written={str(bool(outputs)).lower()}")
    print("constraint_ceiling_printed=false")
    print("raw_private_values_printed=false")
    passed = (
        result["status"] == READY_STATUS
        and result["contract_validation"]["status"] == "PASS"
        and result["validation"]["status"] == "PASS"
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
