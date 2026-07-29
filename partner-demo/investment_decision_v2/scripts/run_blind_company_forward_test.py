#!/usr/bin/env python3
"""Run and preserve one immutable public-company blind forward test."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
INVESTMENT_ROOT = SCRIPT_DIR.parent
REPO_ROOT = SCRIPT_DIR.parents[2]
BUILDER = SCRIPT_DIR / "build_public_company_investment_layer.py"


class BlindTestProtocolError(ValueError):
    """Raised when a first-run preservation rule is violated."""


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BlindTestProtocolError("The blind-test manifest is unreadable.") from exc
    if not isinstance(payload, dict):
        raise BlindTestProtocolError("The blind-test manifest must contain one object.")
    return payload


def selected_ticker(manifest: dict[str, Any]) -> str:
    selected = manifest.get("selected_issuer")
    ticker = selected.get("ticker") if isinstance(selected, dict) else None
    if not isinstance(ticker, str) or not ticker:
        raise BlindTestProtocolError("The selected issuer ticker is missing.")
    return ticker.upper()


def reproduce_selection(manifest: dict[str, Any]) -> dict[str, Any]:
    pool = manifest.get("candidate_pool")
    method = manifest.get("selection_method")
    if not isinstance(pool, list) or not pool or not isinstance(method, dict):
        raise BlindTestProtocolError("The selection pool or method is incomplete.")
    seed_material = method.get("seed_material")
    if not isinstance(seed_material, str) or not seed_material:
        raise BlindTestProtocolError("The deterministic seed material is missing.")
    digest = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
    index = int(digest, 16) % len(pool)
    return {
        "seed_sha256": digest,
        "selected_index": index,
        "selected_ticker": str(pool[index]).upper(),
    }


def git_text(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify_manifest_and_freeze(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("status") != "SELECTED_NOT_RUN":
        raise BlindTestProtocolError("The immutable manifest is not in pre-run status.")
    if manifest.get("session") not in {"S05", "S08"}:
        raise BlindTestProtocolError("This runner accepts only Phase B S05 or S08 manifests.")

    reproduced = reproduce_selection(manifest)
    method = manifest.get("selection_method", {})
    ticker = selected_ticker(manifest)
    if reproduced["seed_sha256"] != method.get("seed_sha256"):
        raise BlindTestProtocolError("The stored selection hash is not reproducible.")
    if reproduced["selected_index"] != method.get("selected_index"):
        raise BlindTestProtocolError("The stored selection index is not reproducible.")
    if reproduced["selected_ticker"] != ticker:
        raise BlindTestProtocolError("The selected issuer does not match the deterministic draw.")

    excluded = {
        str(row.get("ticker", "")).upper()
        for row in manifest.get("excluded_prior_issuers", [])
        if isinstance(row, dict)
    }
    if ticker in excluded:
        raise BlindTestProtocolError("The selected issuer was previously used.")

    pre_run_commit = manifest.get("pre_run_commit")
    frozen = manifest.get("pre_run_shared_logic")
    if not isinstance(pre_run_commit, str) or not isinstance(frozen, dict) or not frozen:
        raise BlindTestProtocolError("The pre-run shared-logic freeze is incomplete.")
    git_text("cat-file", "-e", f"{pre_run_commit}^{{commit}}")

    current_differences: list[str] = []
    baseline_hash_failures: list[str] = []
    ticker_occurrences: list[str] = []
    for relative_path, expected_blob in frozen.items():
        actual_blob = git_text("rev-parse", f"{pre_run_commit}:{relative_path}")
        if actual_blob != expected_blob:
            baseline_hash_failures.append(relative_path)
        diff = subprocess.run(
            ["git", "diff", "--quiet", pre_run_commit, "--", relative_path],
            cwd=REPO_ROOT,
            check=False,
        )
        if diff.returncode != 0:
            current_differences.append(relative_path)
        grep = subprocess.run(
            [
                "git",
                "grep",
                "-n",
                "-i",
                "-w",
                ticker,
                pre_run_commit,
                "--",
                relative_path,
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
        )
        if grep.returncode == 0:
            ticker_occurrences.append(relative_path)
        elif grep.returncode not in {0, 1}:
            raise BlindTestProtocolError("The ticker-absence check could not be completed.")

    if baseline_hash_failures:
        raise BlindTestProtocolError("One or more stored pre-run blob hashes are invalid.")
    if current_differences:
        raise BlindTestProtocolError(
            "Shared analytical logic changed after selection and before the first run."
        )
    if ticker_occurrences:
        raise BlindTestProtocolError(
            "The selected ticker already appears in pre-run shared analytical logic."
        )
    return {
        "status": "PASS",
        "pre_run_commit": pre_run_commit,
        "selected_ticker": ticker,
        "selection_reproduced": True,
        "stored_blob_hashes_reproduced": True,
        "shared_logic_unchanged_before_first_run": True,
        "ticker_absent_from_pre_run_shared_logic": True,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_preserved_run(run_dir: Path) -> dict[str, Any]:
    """Verify every preserved artifact and reject added or removed files."""

    hash_path = run_dir / "artifact_hashes.json"
    try:
        payload = json.loads(hash_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BlindTestProtocolError(
            f"The preserved run hash registry is unreadable: {run_dir}."
        ) from exc
    artifacts = payload.get("artifacts")
    if payload.get("hash_method") != "SHA256" or not isinstance(artifacts, dict):
        raise BlindTestProtocolError("The preserved run hash registry is invalid.")

    expected_paths = set(artifacts)
    actual_paths = {
        str(path.relative_to(run_dir))
        for path in run_dir.rglob("*")
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    if actual_paths != expected_paths:
        added = sorted(actual_paths - expected_paths)
        removed = sorted(expected_paths - actual_paths)
        raise BlindTestProtocolError(
            f"The preserved run file set changed; added={added}; removed={removed}."
        )

    mismatches: list[str] = []
    for relative_path, expected_hash in artifacts.items():
        path = run_dir / relative_path
        if sha256_file(path) != expected_hash:
            mismatches.append(relative_path)
    if mismatches:
        raise BlindTestProtocolError(
            f"The preserved run artifact hashes changed: {sorted(mismatches)}."
        )
    if payload.get("artifact_count") != len(artifacts):
        raise BlindTestProtocolError(
            "The preserved run artifact count does not match its registry."
        )
    return {
        "status": "PASS",
        "run_directory": str(run_dir),
        "hash_method": "SHA256",
        "artifact_count": len(artifacts),
        "file_set_unchanged": True,
        "artifact_hashes_unchanged": True,
    }


def summarize_first_run(
    *,
    output_root: Path,
    return_code: int,
    timed_out: bool,
) -> dict[str, Any]:
    contracts = sorted(output_root.rglob("underwriting_output_contract.json"))
    contract: dict[str, Any] | None = None
    contract_path: Path | None = None
    contract_error: str | None = None
    if len(contracts) == 1:
        contract_path = contracts[0]
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            contract_error = "The generated underwriting contract is unreadable."
    elif not contracts:
        contract_error = "No underwriting output contract was generated."
    else:
        contract_error = "Multiple underwriting output contracts were generated."

    validation_issues = (
        list(contract.get("validation_issues", []))
        if isinstance(contract, dict)
        else []
    )
    hard_stops = (
        list(contract.get("hard_stops", []))
        if isinstance(contract, dict)
        else []
    )
    warnings = (
        list(contract.get("warnings", []))
        if isinstance(contract, dict)
        else []
    )
    contract_status = (
        contract.get("contract_validation", {}).get("status")
        if isinstance(contract, dict)
        else "NOT_AVAILABLE"
    )
    execution_errors: list[str] = []
    if timed_out:
        execution_errors.append("The first run exceeded the configured timeout.")
    if return_code != 0:
        execution_errors.append("The public-only builder returned a nonzero exit code.")
    if contract_error:
        execution_errors.append(contract_error)

    return {
        "status": (
            "FIRST_RUN_COMPLETED"
            if not execution_errors and contract_status == "PASS"
            else "FIRST_RUN_DIAGNOSTIC_REQUIRED"
        ),
        "return_code": return_code,
        "timed_out": timed_out,
        "contract_relative_path": (
            str(contract_path.relative_to(output_root))
            if contract_path is not None
            else None
        ),
        "contract_validation_status": contract_status,
        "report_id": contract.get("report_id") if isinstance(contract, dict) else None,
        "contract_hash": contract.get("contract_hash") if isinstance(contract, dict) else None,
        "supported_universe": (
            contract.get("supported_universe") if isinstance(contract, dict) else None
        ),
        "data_gate": contract.get("data_gate") if isinstance(contract, dict) else None,
        "research_workflow_status": (
            contract.get("research_workflow_status")
            if isinstance(contract, dict)
            else None
        ),
        "public_data_investment_view": (
            contract.get("public_data_investment_view")
            if isinstance(contract, dict)
            else None
        ),
        "decision_confidence": (
            contract.get("decision_confidence") if isinstance(contract, dict) else None
        ),
        "validation_issue_count": len(validation_issues),
        "hard_stop_count": len(hard_stops),
        "warning_count": len(warnings),
        "execution_errors": execution_errors,
        "hard_stops": hard_stops,
        "warnings": warnings,
        "validation_issues": validation_issues,
        "first_run_is_investment_approval": False,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def run_first_test(
    manifest_path: Path,
    *,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = load_manifest(manifest_path)
    integrity = verify_manifest_and_freeze(manifest)
    first_run_dir = manifest_path.parent / manifest["first_run_protocol"]["output_directory"]
    if first_run_dir.exists():
        raise BlindTestProtocolError(
            "The first-run directory already exists and cannot be overwritten."
        )
    first_run_dir.mkdir(parents=True)
    builder_output = first_run_dir / "builder_output"
    command = [
        sys.executable,
        str(BUILDER),
        selected_ticker(manifest),
        "--out-root",
        str(builder_output),
    ]
    runtime = {
        "started_at": utc_now(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "timezone": list(__import__("time").tzname),
        "current_commit": git_text("rev-parse", "HEAD"),
        "pre_run_commit": manifest["pre_run_commit"],
        "selection_integrity": integrity,
        "network_scope": "PUBLIC_DATA_ONLY",
        "research_input": None,
        "command": command,
    }
    write_json(first_run_dir / "execution_context.json", runtime)

    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "0"
    timed_out = False
    try:
        process = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return_code = process.returncode
        stdout = process.stdout
        stderr = process.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""

    (first_run_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
    (first_run_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    diagnostic = summarize_first_run(
        output_root=builder_output,
        return_code=return_code,
        timed_out=timed_out,
    )
    diagnostic["completed_at"] = utc_now()
    write_json(first_run_dir / "first_run_diagnostic.json", diagnostic)

    artifact_hashes = {
        str(path.relative_to(first_run_dir)): sha256_file(path)
        for path in sorted(first_run_dir.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    write_json(
        first_run_dir / "artifact_hashes.json",
        {
            "hash_method": "SHA256",
            "artifact_count": len(artifact_hashes),
            "artifacts": artifact_hashes,
        },
    )
    return diagnostic


def verify_post_fix_prerequisites(
    manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    reproduced = reproduce_selection(manifest)
    ticker = selected_ticker(manifest)
    if reproduced["selected_ticker"] != ticker:
        raise BlindTestProtocolError(
            "The selected issuer no longer matches the deterministic draw."
        )
    if reproduced["seed_sha256"] != manifest.get("selection_method", {}).get(
        "seed_sha256"
    ):
        raise BlindTestProtocolError("The deterministic selection hash changed.")

    pre_run_commit = manifest.get("pre_run_commit")
    frozen = manifest.get("pre_run_shared_logic")
    if not isinstance(pre_run_commit, str) or not isinstance(frozen, dict):
        raise BlindTestProtocolError("The pre-run shared-logic baseline is incomplete.")
    git_text("cat-file", "-e", f"{pre_run_commit}^{{commit}}")
    for relative_path, expected_blob in frozen.items():
        if git_text("rev-parse", f"{pre_run_commit}:{relative_path}") != expected_blob:
            raise BlindTestProtocolError(
                f"The frozen pre-run blob hash changed for {relative_path}."
            )

    first_run_dir = (
        manifest_path.parent / manifest["first_run_protocol"]["output_directory"]
    )
    first_run_integrity = verify_preserved_run(first_run_dir)
    return {
        "status": "PASS",
        "selected_ticker": ticker,
        "selection_reproduced": True,
        "frozen_pre_run_blobs_reproduced": True,
        "first_run_integrity": first_run_integrity,
    }


def run_post_fix_test(
    manifest_path: Path,
    *,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    """Rerun the selected issuer without modifying the immutable first run."""

    manifest_path = manifest_path.resolve()
    manifest = load_manifest(manifest_path)
    prerequisites = verify_post_fix_prerequisites(manifest_path, manifest)
    post_fix_dir = manifest_path.parent / "post_fix"
    if post_fix_dir.exists():
        raise BlindTestProtocolError(
            "The post-fix directory already exists and cannot be overwritten."
        )
    post_fix_dir.mkdir(parents=True)
    builder_output = post_fix_dir / "builder_output"
    command = [
        sys.executable,
        str(BUILDER),
        selected_ticker(manifest),
        "--out-root",
        str(builder_output),
    ]
    runtime = {
        "started_at": utc_now(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "timezone": list(__import__("time").tzname),
        "current_commit": git_text("rev-parse", "HEAD"),
        "pre_run_commit": manifest["pre_run_commit"],
        "post_fix_prerequisites": prerequisites,
        "network_scope": "PUBLIC_DATA_ONLY",
        "research_input": None,
        "command": command,
    }
    write_json(post_fix_dir / "execution_context.json", runtime)

    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "0"
    timed_out = False
    try:
        process = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return_code = process.returncode
        stdout = process.stdout
        stderr = process.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""

    (post_fix_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
    (post_fix_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    diagnostic = summarize_first_run(
        output_root=builder_output,
        return_code=return_code,
        timed_out=timed_out,
    )
    diagnostic["status"] = (
        "POST_FIX_COMPLETED"
        if diagnostic["status"] == "FIRST_RUN_COMPLETED"
        else "POST_FIX_DIAGNOSTIC_REQUIRED"
    )
    diagnostic["completed_at"] = utc_now()
    write_json(post_fix_dir / "post_fix_diagnostic.json", diagnostic)

    artifact_hashes = {
        str(path.relative_to(post_fix_dir)): sha256_file(path)
        for path in sorted(post_fix_dir.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    write_json(
        post_fix_dir / "artifact_hashes.json",
        {
            "hash_method": "SHA256",
            "artifact_count": len(artifact_hashes),
            "artifacts": artifact_hashes,
        },
    )
    return diagnostic


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one immutable public-only blind-company forward test."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify deterministic selection and shared-logic freeze without network access.",
    )
    parser.add_argument(
        "--verify-preserved-first-run",
        action="store_true",
        help="Verify the immutable first-run file set and SHA256 registry.",
    )
    parser.add_argument(
        "--post-fix",
        action="store_true",
        help="Run one separately preserved post-fix test after verifying the first run.",
    )
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest)
        selected_modes = sum(
            bool(mode)
            for mode in (
                args.verify_only,
                args.verify_preserved_first_run,
                args.post_fix,
            )
        )
        if selected_modes > 1:
            raise BlindTestProtocolError(
                "Choose only one verification or execution mode."
            )
        if args.verify_only:
            print(json.dumps(verify_manifest_and_freeze(manifest), indent=2))
            return 0
        if args.verify_preserved_first_run:
            first_run_dir = (
                args.manifest.resolve().parent
                / manifest["first_run_protocol"]["output_directory"]
            )
            print(json.dumps(verify_preserved_run(first_run_dir), indent=2))
            return 0
        if args.post_fix:
            result = run_post_fix_test(
                args.manifest,
                timeout_seconds=args.timeout_seconds,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
            return 0 if result["status"] == "POST_FIX_COMPLETED" else 1
        result = run_first_test(
            args.manifest,
            timeout_seconds=args.timeout_seconds,
        )
    except BlindTestProtocolError as exc:
        print(f"status=BLIND_TEST_PROTOCOL_BLOCKED; reason={exc}")
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result["status"] == "FIRST_RUN_COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
