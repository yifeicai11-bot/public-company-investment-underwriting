#!/usr/bin/env python3
"""Run the S13 Gate 4 constraint engine in a local-only workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gate4_constraint_engine import (  # noqa: E402
    BLOCKED_CHANGED_STATUS,
    CALCULATED_STATUS,
    calculate_portfolio_constraints,
    suppressed_constraint_result,
    validate_constraint_output,
)
from gate4_private_contract import (  # noqa: E402
    INPUT_STATUS_REQUIRED,
    INPUT_STATUS_VALIDATED,
    PrivateInputLoadError,
    load_and_validate_private_inputs,
    read_mapping,
)
from gate4_privacy import (  # noqa: E402
    PRIVATE_CLASSIFICATION,
    SUPPORTED_CLASSIFICATIONS,
    PrivacyBoundaryError,
    assert_local_workspace,
    secure_atomic_write_json,
)
from run_gate4_local_entry import load_gate3_contract  # noqa: E402
from underwriting_contract import assess_gate3_for_gate4  # noqa: E402


def _gate3_identity(contract: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (
        contract.get("schema_version"),
        contract.get("report_id"),
        contract.get("contract_hash"),
    )


def _finalize_result(
    result: dict[str, Any],
    *,
    private_diagnostic: dict[str, Any],
    input_mode: str,
    private_status: str,
    gate3_precheck: dict[str, Any] | None,
    gate3_recheck: dict[str, Any] | None,
) -> dict[str, Any]:
    result["private_input_diagnostic"] = private_diagnostic
    output_errors = validate_constraint_output(result)
    if not output_errors:
        result["output_validation"] = {
            "status": "PASS",
            "error_count": 0,
            "error_paths": [],
        }
        return result

    fallback = suppressed_constraint_result(
        status="GATE_4_CONSTRAINT_OUTPUT_INVALID",
        input_mode=input_mode,
        private_input_status=private_status,
        gate3_precheck=gate3_precheck,
        gate3_recheck=gate3_recheck,
        missing_items=["constraint_output_contract_validation"],
    )
    fallback["private_input_diagnostic"] = private_diagnostic
    fallback["output_validation"] = {
        "status": "FAIL",
        "error_count": len(output_errors),
        "error_paths": output_errors,
    }
    return fallback


def run_gate4_constraint_engine(
    gate3_target: Path,
    manifest_path: Path,
    *,
    system_assessment_ready: bool = False,
) -> tuple[dict[str, Any], Path | None]:
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

    bundle, private_diagnostic = load_and_validate_private_inputs(
        manifest_path,
        system_assessment_ready=system_assessment_ready,
    )
    private_status = str(
        private_diagnostic.get("status", INPUT_STATUS_REQUIRED)
    )
    if bundle is None or private_status != INPUT_STATUS_VALIDATED:
        result = suppressed_constraint_result(
            status=INPUT_STATUS_REQUIRED,
            input_mode=str(
                private_diagnostic.get("input_mode", "NOT_EVALUATED")
            ),
            private_input_status=private_status,
            gate3_precheck=None,
            gate3_recheck=None,
            missing_items=list(
                private_diagnostic.get("blocking_check_ids", [])
            ),
        )
        result = _finalize_result(
            result,
            private_diagnostic=private_diagnostic,
            input_mode=str(
                private_diagnostic.get("input_mode", "NOT_EVALUATED")
            ),
            private_status=private_status,
            gate3_precheck=None,
            gate3_recheck=None,
        )
        output_path = None
        if bundle is not None:
            output_path = secure_atomic_write_json(
                bundle.output_dir / "gate4_constraint_engine_result.json",
                result,
                workspace_root=workspace_root,
            )
        return result, output_path

    first_contract = load_gate3_contract(gate3_target)
    gate3_precheck = assess_gate3_for_gate4(
        first_contract,
        policy=bundle.policy.get("gate3_eligibility_policy"),
        freshness_attestation=bundle.freshness_attestation,
    )
    if gate3_precheck.get("eligible") is not True:
        result = suppressed_constraint_result(
            status=str(gate3_precheck.get("status")),
            input_mode=str(bundle.manifest.get("input_mode")),
            private_input_status=private_status,
            gate3_precheck=gate3_precheck,
            gate3_recheck=None,
        )
        result = _finalize_result(
            result,
            private_diagnostic=private_diagnostic,
            input_mode=str(bundle.manifest.get("input_mode")),
            private_status=private_status,
            gate3_precheck=gate3_precheck,
            gate3_recheck=None,
        )
        output_path = secure_atomic_write_json(
            bundle.output_dir / "gate4_constraint_engine_result.json",
            result,
            workspace_root=workspace_root,
        )
        return result, output_path

    # Reload and revalidate immediately before any private portfolio calculation.
    second_contract = load_gate3_contract(gate3_target)
    gate3_recheck = assess_gate3_for_gate4(
        second_contract,
        policy=bundle.policy.get("gate3_eligibility_policy"),
        freshness_attestation=bundle.freshness_attestation,
    )
    if _gate3_identity(first_contract) != _gate3_identity(second_contract):
        result = suppressed_constraint_result(
            status=BLOCKED_CHANGED_STATUS,
            input_mode=str(bundle.manifest.get("input_mode")),
            private_input_status=private_status,
            gate3_precheck=gate3_precheck,
            gate3_recheck=gate3_recheck,
            missing_items=["gate3_contract_identity_changed"],
        )
    elif gate3_recheck.get("eligible") is not True:
        result = suppressed_constraint_result(
            status=str(gate3_recheck.get("status")),
            input_mode=str(bundle.manifest.get("input_mode")),
            private_input_status=private_status,
            gate3_precheck=gate3_precheck,
            gate3_recheck=gate3_recheck,
        )
    else:
        result = calculate_portfolio_constraints(
            bundle=bundle,
            gate3_contract=second_contract,
            gate3_precheck=gate3_precheck,
            gate3_recheck=gate3_recheck,
            private_input_status=private_status,
        )

    result = _finalize_result(
        result,
        private_diagnostic=private_diagnostic,
        input_mode=str(bundle.manifest.get("input_mode")),
        private_status=private_status,
        gate3_precheck=gate3_precheck,
        gate3_recheck=gate3_recheck,
    )
    output_path = secure_atomic_write_json(
        bundle.output_dir / "gate4_constraint_engine_result.json",
        result,
        workspace_root=workspace_root,
    )
    return result, output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run S13 constraint ceilings locally. The result is not a suggested "
            "position, approval, portfolio action, or trade."
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
        result, output_path = run_gate4_constraint_engine(
            args.gate3_contract_or_dir,
            args.manifest,
        )
    except (PrivacyBoundaryError, PrivateInputLoadError, OSError, ValueError):
        print("status=GATE_4_CONSTRAINT_ENGINE_BLOCKED")
        print(
            "detail=Review the local workspace boundary and privacy-safe diagnostic."
        )
        print("raw_private_values_printed=false")
        return 2
    except Exception:
        print("status=GATE_4_CONSTRAINT_ENGINE_ERROR")
        print(
            "detail=No private values were printed; inspect the local code environment."
        )
        print("raw_private_values_printed=false")
        return 3

    print(f"status={result['status']}")
    print(f"constraint_result_written={str(output_path is not None).lower()}")
    print("maximum_constraint_based_position_printed=false")
    print("raw_private_values_printed=false")
    return 0 if result["status"] == CALCULATED_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
