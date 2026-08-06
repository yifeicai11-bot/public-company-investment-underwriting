#!/usr/bin/env python3
"""Verify and optionally regenerate the frozen v1.0.0 release baseline."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any


BASELINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASELINE_DIR.parents[1]
MANIFEST_PATH = BASELINE_DIR / "baseline_manifest.json"


def tagged_path_candidates(path: str) -> list[str]:
    """Resolve neutral v1.0.0 paths against the immutable pre-rename tree."""

    candidates = [path]
    legacy = path
    replacements = (
        ("user-demo/", "partner-demo/"),
        ("v1_0_0_outputs", "friday_v1_outputs"),
        ("v1_0_0_validation.json", "friday_v1_validation.json"),
        ("v1_0_0_output_standard.md", "friday_v1_output_standard.md"),
        ("V1_0_0_QA_Summary", "Friday_V1_QA_Summary"),
        ("validate_v1_delivery.py", "validate_friday_v1_delivery.py"),
        ("upgrade_v1_contract.py", "upgrade_friday_v1_contract.py"),
        ("build_user_portfolio_overlay.py", "build_partner_portfolio_overlay.py"),
        ("build_crox_user_artifacts.py", "build_crox_partner_ready_artifacts.py"),
    )
    for current, old in replacements:
        legacy = legacy.replace(current, old)
    if legacy != path:
        candidates.append(legacy)
    return candidates


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def command_output(args: list[str], *, cwd: Path) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def tagged_file(tag: str, path: str) -> bytes:
    last_error: subprocess.CalledProcessError | None = None
    for candidate in tagged_path_candidates(path):
        try:
            return subprocess.run(
                ["git", "show", f"{tag}:{candidate}"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
            ).stdout
        except subprocess.CalledProcessError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def tagged_checkout_path(root: Path, path: str) -> Path:
    for candidate in tagged_path_candidates(path):
        resolved = root / candidate
        if resolved.exists():
            return resolved
    return root / path


def tagged_output_path(directory: Path, name: str) -> Path:
    candidates = [name, name.replace("V1_0_0_QA_Summary", "Friday_V1_QA_Summary")]
    for candidate in candidates:
        path = directory / candidate
        if path.exists():
            return path
    return directory / name


def record(checks: list[dict[str, Any]], check_id: str, passed: bool, detail: str) -> None:
    checks.append(
        {
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "detail": detail,
        }
    )


def pdf_pages(pdfinfo: str, path: Path) -> int:
    output = command_output([pdfinfo, str(path)], cwd=REPO_ROOT)
    for line in output.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError(f"Could not read page count from {path}")


def raster_hashes(pdftoppm: str, path: Path, target_dir: Path) -> list[str]:
    target_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [pdftoppm, "-png", "-r", "72", str(path), str(target_dir / "page")],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return [sha256_file(page) for page in sorted(target_dir.glob("page-*.png"))]


def extract_tag(tag: str, destination: Path) -> None:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", tag],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        destination_root = destination.resolve()
        for member in stream.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination_root):
                raise RuntimeError(f"Unsafe path in tagged archive: {member.name}")
        if sys.version_info >= (3, 12):
            stream.extractall(destination, filter="data")
        else:
            stream.extractall(destination)


def verify_static(manifest: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    tag = str(manifest["tag"])
    expected_commit = str(manifest["commit_hash"])
    actual_commit = command_output(["git", "rev-list", "-n", "1", tag], cwd=REPO_ROOT).strip()
    record(checks, "tag-commit", actual_commit == expected_commit, f"{tag} -> {actual_commit}")

    for path, expected_hash in manifest["frozen_file_sha256"].items():
        try:
            actual_hash = sha256_bytes(tagged_file(tag, path))
        except subprocess.CalledProcessError:
            record(checks, f"frozen-file:{path}", False, "File is missing from the frozen tag.")
            continue
        record(
            checks,
            f"frozen-file:{path}",
            actual_hash == expected_hash,
            f"sha256={actual_hash}",
        )

    for ticker, case in manifest["cases"].items():
        contract = json.loads(tagged_file(tag, case["contract_path"]).decode("utf-8"))
        case_checks = {
            "report_id": contract.get("report_id") == case["report_id"],
            "contract_hash": contract.get("contract_hash") == case["contract_hash"],
            "schema_version": contract.get("schema_version") == case["schema_version"],
            "data_gate": contract.get("data_gate", {}).get("level") == case["data_gate"],
            "contract_validation": contract.get("contract_validation", {}).get("status")
            == case["contract_validation"],
            "hard_stop_count": len(contract.get("hard_stops", [])) == case["hard_stop_count"],
            "warning_count": len(contract.get("warnings", [])) == case["warning_count"],
            "source_record_count": len(contract.get("source_registry", [])) == case["source_record_count"],
            "evidence_record_count": len(contract.get("evidence_records", [])) == case["evidence_record_count"],
            "report_dates": all(
                contract.get("report_dates", {}).get(key) == value
                for key, value in case["report_dates"].items()
            ),
        }
        for name, passed in case_checks.items():
            record(checks, f"{ticker}:{name}", passed, f"expected baseline value for {name}")


def regenerate(
    manifest: dict[str, Any],
    checks: list[dict[str, Any]],
    *,
    pdf: bool,
    pixel_compare: bool,
) -> None:
    pdfinfo = shutil.which("pdfinfo") if pdf else None
    pdftoppm = shutil.which("pdftoppm") if pixel_compare else None
    if pdf and not pdfinfo:
        raise RuntimeError("pdfinfo is required for --pdf baseline verification.")
    if pixel_compare and not pdftoppm:
        raise RuntimeError("pdftoppm is required for --pixel-compare.")

    with tempfile.TemporaryDirectory(prefix="v1.0.0-baseline-") as temporary:
        temporary_root = Path(temporary)
        tagged_root = temporary_root / "tagged-source"
        tagged_root.mkdir()
        extract_tag(str(manifest["tag"]), tagged_root)

        renderer = tagged_checkout_path(
            tagged_root,
            "user-demo/investment_decision_v2/scripts/render_public_company_artifacts.py",
        )
        validator = tagged_checkout_path(
            tagged_root,
            "user-demo/investment_decision_v2/scripts/validate_v1_delivery.py",
        )
        for ticker, case in manifest["cases"].items():
            contract = tagged_checkout_path(tagged_root, case["contract_path"])
            expected_dir = tagged_root / case["example_dir"]
            regenerated_dir = temporary_root / f"regenerated-{ticker.lower()}"
            command = [
                sys.executable,
                str(renderer),
                str(contract),
                "--out-dir",
                str(regenerated_dir),
            ]
            if pdf:
                command.append("--pdf")
            subprocess.run(command, cwd=tagged_root, check=True, capture_output=True)
            subprocess.run(
                [
                    sys.executable,
                    str(validator),
                    str(contract),
                    "--html-dir",
                    str(regenerated_dir),
                ],
                cwd=tagged_root,
                check=True,
                capture_output=True,
            )

            html_names = [
                f"{ticker}_One_Page_Summary_Bilingual.html",
                f"{ticker}_Full_Report_Bilingual.html",
                f"{ticker}_Evidence_Audit_Appendix_Bilingual.html",
                f"{ticker}_V1_0_0_QA_Summary_Bilingual.html",
            ]
            for name in html_names:
                expected = tagged_output_path(expected_dir, name)
                actual = tagged_output_path(regenerated_dir, name)
                record(
                    checks,
                    f"{ticker}:render:{name}",
                    expected.read_bytes() == actual.read_bytes(),
                    "Regenerated HTML must be byte-identical.",
                )

            if not pdf:
                continue
            for name, expected_pages in case["pdf_pages"].items():
                expected = tagged_output_path(expected_dir, name)
                actual = tagged_output_path(regenerated_dir, name)
                actual_pages = pdf_pages(str(pdfinfo), actual)
                record(
                    checks,
                    f"{ticker}:pages:{name}",
                    actual_pages == expected_pages,
                    f"pages={actual_pages}; expected={expected_pages}",
                )
                if pixel_compare:
                    expected_hashes = raster_hashes(
                        str(pdftoppm),
                        expected,
                        temporary_root / f"{ticker}-{name}-expected",
                    )
                    actual_hashes = raster_hashes(
                        str(pdftoppm),
                        actual,
                        temporary_root / f"{ticker}-{name}-actual",
                    )
                    record(
                        checks,
                        f"{ticker}:pixels:{name}",
                        actual_hashes == expected_hashes,
                        f"raster_pages={len(actual_hashes)} at 72 dpi",
                    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", action="store_true", help="Regenerate HTML from the frozen tag.")
    parser.add_argument("--pdf", action="store_true", help="Regenerate PDFs and compare page counts.")
    parser.add_argument(
        "--pixel-compare",
        action="store_true",
        help="Compare submitted and regenerated PDF pages after 72-dpi rasterization.",
    )
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise SystemExit("v1.0.0 requires Python 3.11 or newer.")
    if (args.pdf or args.pixel_compare) and not args.render:
        parser.error("--pdf and --pixel-compare require --render.")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    verify_static(manifest, checks)
    if args.render:
        regenerate(manifest, checks, pdf=args.pdf or args.pixel_compare, pixel_compare=args.pixel_compare)

    failures = [check for check in checks if check["status"] == "FAIL"]
    summary = {
        "status": "PASS" if not failures else "FAIL",
        "baseline_id": manifest["baseline_id"],
        "tag": manifest["tag"],
        "commit_hash": manifest["commit_hash"],
        "python": sys.version.split()[0],
        "check_count": len(checks),
        "failure_count": len(failures),
        "failures": failures,
    }
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if not failures else 1)


if __name__ == "__main__":
    main()
