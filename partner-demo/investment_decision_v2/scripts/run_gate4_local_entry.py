#!/usr/bin/env python3
"""Validate Gate 3 and Gate 4 private inputs without portfolio assessment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gate4_private_contract import (  # noqa: E402
    INPUT_STATUS_REQUIRED,
    INPUT_STATUS_VALIDATED,
    PrivateInputLoadError,
    load_and_validate_private_inputs,
    read_mapping,
    utc_now,
)
from gate4_privacy import (  # noqa: E402
    PRIVATE_CLASSIFICATION,
    SUPPORTED_CLASSIFICATIONS,
    PrivacyBoundaryError,
    assert_local_workspace,
    secure_atomic_write_json,
)
from underwriting_contract import assess_gate3_for_gate4  # noqa: E402


def resolve_gate3_contract_path(target: Path) -> Path:
    target = target.expanduser()
    if target.is_file() and target.name == "underwriting_output_contract.json":
        return target.resolve()
    if target.is_dir():
        candidate = target / "underwriting_output_contract.json"
        if candidate.is_file():
            return candidate.resolve()
    raise PrivateInputLoadError(
        "Gate 4 requires an existing underwriting_output_contract.json."
    )


def load_gate3_contract(target: Path) -> dict[str, Any]:
    path = resolve_gate3_contract_path(target)
    payload = read_mapping(path)
    if not all(
        payload.get(field)
        for field in ("schema_version", "report_id", "contract_hash")
    ):
        raise PrivateInputLoadError(
            "The selected JSON file is not a Gate 3 underwriting output contract."
        )
    return payload


def privacy_safe_eligibility(eligibility: dict[str, Any]) -> dict[str, Any]:
    safe_checks = []
    for check in eligibility.get("checks", []):
        if not isinstance(check, dict):
            continue
        safe_checks.append(
            {
                "check_id": check.get("check_id"),
                "category": check.get("category"),
                "status": check.get("status"),
                "blocking_class": check.get("blocking_class"),
                "decision_impact": check.get("decision_impact"),
                "remediation": check.get("remediation"),
            }
        )
    return {
        "status": eligibility.get("status"),
        "eligible": eligibility.get("eligible") is True,
        "evaluated_at": eligibility.get("evaluated_at"),
        "gate3_identity": eligibility.get("gate3_identity"),
        "blocking_check_ids": list(eligibility.get("blocking_check_ids", [])),
        "stale_check_ids": list(eligibility.get("stale_check_ids", [])),
        "ineligible_check_ids": list(eligibility.get("ineligible_check_ids", [])),
        "escalated_warning_ids": list(eligibility.get("escalated_warning_ids", [])),
        "checks": safe_checks,
        "private_policy_included": False,
        "private_attestation_included": False,
    }


def build_local_entry_result(
    *,
    private_diagnostic: dict[str, Any],
    eligibility: Optional[dict[str, Any]],
) -> dict[str, Any]:
    private_status = private_diagnostic.get("status", INPUT_STATUS_REQUIRED)
    if eligibility is None:
        status = INPUT_STATUS_REQUIRED
        safe_eligibility: dict[str, Any] = {
            "status": "NOT_EVALUATED",
            "eligible": False,
            "checks": [],
            "private_policy_included": False,
            "private_attestation_included": False,
        }
    else:
        safe_eligibility = privacy_safe_eligibility(eligibility)
        if eligibility.get("eligible") is not True:
            status = str(eligibility.get("status"))
        elif private_status == INPUT_STATUS_VALIDATED:
            status = INPUT_STATUS_VALIDATED
        else:
            status = INPUT_STATUS_REQUIRED

    return {
        "gate4_local_entry_version": "2.1.0",
        "generated_at": utc_now(),
        "status": status,
        "private_input_status": private_status,
        "input_mode": private_diagnostic.get("input_mode", "NOT_EVALUATED"),
        "mode_capabilities": private_diagnostic.get("mode_capabilities", {}),
        "gate3_eligibility": safe_eligibility,
        "system_portfolio_assessment": {
            "status": "NOT_EVALUATED",
            "eligible_within_constraints": None,
            "maximum_constraint_based_position": None,
            "position_range": None,
            "opportunity_cost": "NOT_EVALUATED",
        },
        "partner_decision": {
            "workflow_status": "PARTNER_APPROVAL_PENDING",
            "decision": "PENDING",
            "approved_position_range": None,
        },
        "automatic_trade_execution": False,
        "external_transmission": "DENIED",
        "privacy_safe_diagnostic": True,
        "raw_private_values_included": False,
        "private_input_diagnostic": private_diagnostic,
        "next_action": (
            "Proceed to the local S13 constraint engine."
            if status == INPUT_STATUS_VALIDATED
            else (
                "Refresh or correct the Gate 3 issuer contract."
                if status.startswith("GATE_4_BLOCKED_")
                else "Complete or correct the named private-input fields locally."
            )
        ),
    }


def run_gate4_local_entry(
    gate3_target: Path,
    manifest_path: Path,
) -> tuple[dict[str, Any], Optional[Path]]:
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

    bundle, private_diagnostic = load_and_validate_private_inputs(manifest_path)
    eligibility: Optional[dict[str, Any]] = None
    if bundle is not None and private_diagnostic.get("status") == INPUT_STATUS_VALIDATED:
        contract = load_gate3_contract(gate3_target)
        eligibility = assess_gate3_for_gate4(
            contract,
            policy=bundle.policy.get("gate3_eligibility_policy"),
            freshness_attestation=bundle.freshness_attestation,
        )

    result = build_local_entry_result(
        private_diagnostic=private_diagnostic,
        eligibility=eligibility,
    )
    output_path: Optional[Path] = None
    if bundle is not None:
        output_path = secure_atomic_write_json(
            bundle.output_dir / "gate4_local_entry_diagnostic.json",
            result,
            workspace_root=workspace_root,
        )
    return result, output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the local-only Gate 4 entry validation without portfolio sizing."
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
        result, output_path = run_gate4_local_entry(
            args.gate3_contract_or_dir,
            args.manifest,
        )
    except (PrivacyBoundaryError, PrivateInputLoadError, OSError, ValueError):
        print("status=GATE_4_LOCAL_ENTRY_BLOCKED")
        print("detail=Review the local workspace boundary and privacy-safe input diagnostic.")
        return 2
    except Exception:
        print("status=GATE_4_LOCAL_ENTRY_ERROR")
        print("detail=No private values were written; inspect the local code environment.")
        return 3

    print(f"status={result['status']}")
    print(f"private_input_status={result['private_input_status']}")
    print(f"diagnostic_written={str(output_path is not None).lower()}")
    print("raw_private_values_printed=false")
    return 0 if result["status"] == INPUT_STATUS_VALIDATED else 2


if __name__ == "__main__":
    raise SystemExit(main())
