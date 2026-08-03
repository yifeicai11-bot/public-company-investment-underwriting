#!/usr/bin/env python3
"""Select and freeze a true S17 held-out issuer after code freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
EXCHANGE_LIST_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SUBMISSION_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# Predeclared across unrelated industries; none was an analytical fixture before S17.
PRIMARY_CANDIDATE_POOL = [
    "AWI",
    "BCC",
    "CHRW",
    "CLH",
    "CNM",
    "ENS",
    "FTI",
    "GEF",
    "GTLS",
    "HRI",
    "KD",
    "KMX",
    "LEA",
    "MMS",
    "MUSA",
    "OSK",
    "ROL",
    "RPM",
    "SON",
    "TNL",
    "TTEK",
    "TXRH",
    "UHS",
    "VVV",
    "WMS",
]

EXCLUDED_PRIOR_ISSUERS = [
    {"ticker": "AAPL", "reason": "Existing cross-industry and capital-allocation fixture."},
    {"ticker": "ADBE", "reason": "Existing software and cross-industry fixture."},
    {"ticker": "AZO", "reason": "Existing Friday V1 and retail fixture."},
    {"ticker": "BA", "reason": "Previously used liquidity and refinancing review."},
    {"ticker": "CMT", "reason": "Previously used partner-facing issuer review."},
    {"ticker": "CRM", "reason": "Existing software valuation fixture."},
    {"ticker": "CROX", "reason": "Existing Friday V1 and valuation fixture."},
    {"ticker": "ITT", "reason": "Preserved S08 blind-company fixture."},
    {"ticker": "ODFL", "reason": "Preserved S05 blind-company fixture."},
    {"ticker": "PFGC", "reason": "Existing working-capital and distribution fixture."},
]

FROZEN_SHARED_LOGIC = [
    "underwrite.py",
    "scripts/release_doctor.py",
    "partner-demo/investment_decision_v2/scripts/build_public_company_decision_pack.py",
    "partner-demo/investment_decision_v2/scripts/notes_events_controls.py",
    "partner-demo/investment_decision_v2/scripts/build_public_company_investment_layer.py",
    "partner-demo/investment_decision_v2/scripts/underwriting_contract.py",
    "partner-demo/investment_decision_v2/scripts/equity_valuation_contract.py",
    "partner-demo/investment_decision_v2/scripts/forward_operating_model.py",
    "partner-demo/investment_decision_v2/scripts/valuation_cross_checks.py",
    "partner-demo/investment_decision_v2/scripts/render_public_company_artifacts.py",
    "partner-demo/investment_decision_v2/scripts/validate_friday_v1_delivery.py",
    "partner-demo/investment_decision_v2/scripts/run_blind_company_forward_test.py",
]


class S17SelectionError(ValueError):
    """Raised before a held-out manifest can be written."""


def git_text(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def fetch_bytes(url: str, user_agent: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept-Encoding": "identity"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def exchange_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = payload.get("fields")
    data = payload.get("data")
    if fields != ["cik", "name", "ticker", "exchange"] or not isinstance(data, list):
        raise S17SelectionError("The SEC exchange-list structure is unsupported.")
    rows: dict[str, dict[str, Any]] = {}
    for values in data:
        if not isinstance(values, list) or len(values) != 4:
            continue
        row = dict(zip(fields, values))
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            rows[ticker] = row
    return rows


def deterministic_selection(pool: list[str], seed_material: str) -> dict[str, Any]:
    digest = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
    index = int(digest, 16) % len(pool)
    return {
        "seed_sha256": digest,
        "selected_index": index,
        "selected_ticker": pool[index],
    }


def frozen_blobs(freeze_commit: str) -> dict[str, str]:
    blobs: dict[str, str] = {}
    for path in FROZEN_SHARED_LOGIC:
        blobs[path] = git_text("rev-parse", f"{freeze_commit}:{path}")
        if subprocess.run(
            ["git", "diff", "--quiet", freeze_commit, "--", path],
            cwd=REPO_ROOT,
            check=False,
        ).returncode != 0:
            raise S17SelectionError(
                "Shared logic differs from the requested code-freeze commit."
            )
    return blobs


def assert_candidates_absent_from_shared_logic(
    freeze_commit: str,
    pool: list[str],
) -> None:
    for ticker in pool:
        for path in FROZEN_SHARED_LOGIC:
            result = subprocess.run(
                ["git", "grep", "-i", "-w", ticker, freeze_commit, "--", path],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
            )
            if result.returncode == 0:
                raise S17SelectionError(
                    f"Candidate {ticker} already appears in frozen shared logic."
                )
            if result.returncode not in {0, 1}:
                raise S17SelectionError("The candidate-blindness scan failed.")


def build_manifest(
    *,
    freeze_commit: str,
    selection_date: str,
    attempt: str,
    exchange_payload_bytes: bytes,
    submission_payload: dict[str, Any],
    excluded_tickers: list[str] | None = None,
    retrieved_at: str,
) -> dict[str, Any]:
    excluded_tickers = [value.upper() for value in (excluded_tickers or [])]
    pool = [ticker for ticker in PRIMARY_CANDIDATE_POOL if ticker not in excluded_tickers]
    if len(pool) < 8:
        raise S17SelectionError("The remaining S17 candidate pool is too small.")
    exchange_payload = json.loads(exchange_payload_bytes)
    rows = exchange_rows(exchange_payload)
    missing = [ticker for ticker in pool if ticker not in rows]
    invalid_exchange = [
        ticker for ticker in pool if rows.get(ticker, {}).get("exchange") not in {"NYSE", "Nasdaq"}
    ]
    if missing or invalid_exchange:
        raise S17SelectionError(
            f"The predeclared candidate pool failed current SEC validation; missing={missing}; invalid_exchange={invalid_exchange}."
        )
    seed_material = f"{freeze_commit}|{selection_date}|S17-TRUE-HELD-OUT-{attempt}"
    selection = deterministic_selection(pool, seed_material)
    selected = rows[selection["selected_ticker"]]
    selected_cik = f"{int(selected['cik']):010d}"
    submission_cik = f"{int(submission_payload.get('cik')):010d}"
    if submission_cik != selected_cik:
        raise S17SelectionError("The selected SEC submission does not match the deterministic draw.")
    sic = str(submission_payload.get("sic") or "")
    sic_description = str(submission_payload.get("sicDescription") or "").strip()
    if not re.fullmatch(r"[0-9]{4}", sic) or not sic_description:
        raise S17SelectionError("The selected issuer has no usable SEC SIC classification.")

    excluded = list(EXCLUDED_PRIOR_ISSUERS)
    excluded.extend(
        {"ticker": ticker, "reason": "Previously used S17 attempt."}
        for ticker in excluded_tickers
    )
    return {
        "schema_version": "1.0.0",
        "document_type": "blind_company_forward_test_manifest",
        "phase": "F",
        "session": "S17",
        "status": "SELECTED_NOT_RUN",
        "selection_date": selection_date,
        "attempt": attempt,
        "pre_run_commit": freeze_commit,
        "pre_run_shared_logic": frozen_blobs(freeze_commit),
        "selection_method": {
            "method": "SHA256_MODULO_PREDECLARED_POOL",
            "seed_material": seed_material,
            "seed_sha256": selection["seed_sha256"],
            "index_formula": "int(seed_sha256, 16) % candidate_pool_length",
            "selected_index": selection["selected_index"],
        },
        "candidate_pool": pool,
        "excluded_prior_issuers": excluded,
        "selected_issuer": {
            "ticker": selection["selected_ticker"],
            "company_name": str(selected["name"]),
            "exchange": str(selected["exchange"]),
            "industry": sic_description,
        },
        "selection_source": {
            "exchange_list_url": EXCHANGE_LIST_URL,
            "exchange_list_sha256": hashlib.sha256(exchange_payload_bytes).hexdigest(),
            "retrieved_at": retrieved_at,
            "selected_cik": selected_cik,
            "selected_submission_url": SUBMISSION_URL.format(cik=selected_cik),
            "selected_sic": sic,
            "selected_sic_description": sic_description,
        },
        "intended_stress_characteristics": [
            "Unseen SEC-reporting non-financial issuer selected without using an expected analytical result.",
            "Quarter, YTD, FY, LTM, instant/flow, unit, currency, and share-count controls must fail safely.",
            "All issuer modules must preserve VALIDATED, MISSING, NOT_APPLICABLE, WARNING, or HARD_STOP without forced completeness.",
            "The public-only run must not invent valuation assumptions, scenario probabilities, expected return, or portfolio sizing.",
            "No selected-issuer branch or hard-coded value may be added to shared analytical logic.",
        ],
        "blindness_attestation": {
            "selected_before_first_run": True,
            "no_ticker_specific_adjustment_before_first_run": True,
            "selected_ticker_absent_from_pre_run_shared_logic": True,
            "company_will_not_be_replaced_if_first_run_fails": True,
            "selection_not_based_on_expected_result": True,
        },
        "first_run_protocol": {
            "builder": "underwrite.py",
            "research_input": None,
            "output_directory": "first_run",
            "network_scope": "PUBLIC_DATA_ONLY",
            "overwrite_existing_first_run": False,
        },
        "required_preservation": [
            "EXACT_COMMAND",
            "RUNTIME_AND_COMMIT",
            "STDOUT",
            "STDERR",
            "BUILDER_OUTPUT",
            "ERRORS",
            "WARNINGS",
            "DIAGNOSTIC_REPORT",
            "FIX_RECORD",
            "POST_FIX_REGRESSION",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", choices=("PRIMARY", "SECONDARY"), default="PRIMARY")
    parser.add_argument("--selection-date", default=date.today().isoformat())
    parser.add_argument("--exclude-ticker", action="append", default=[])
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("The S17 held-out manifest already exists and cannot be overwritten.")
    if git_text("rev-parse", "HEAD") != args.freeze_commit:
        raise SystemExit("The requested S17 freeze commit is not the current HEAD.")
    git_text("cat-file", "-e", f"{args.freeze_commit}^{{commit}}")
    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise SystemExit("SEC_USER_AGENT is required for S17 selection-source validation.")
    assert_candidates_absent_from_shared_logic(args.freeze_commit, PRIMARY_CANDIDATE_POOL)
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    exchange_bytes = fetch_bytes(EXCHANGE_LIST_URL, user_agent)
    rows = exchange_rows(json.loads(exchange_bytes))
    pool = [ticker for ticker in PRIMARY_CANDIDATE_POOL if ticker not in set(args.exclude_ticker)]
    seed = f"{args.freeze_commit}|{args.selection_date}|S17-TRUE-HELD-OUT-{args.attempt}"
    selected = deterministic_selection(pool, seed)["selected_ticker"]
    selected_cik = f"{int(rows[selected]['cik']):010d}"
    submission = json.loads(fetch_bytes(SUBMISSION_URL.format(cik=selected_cik), user_agent))
    manifest = build_manifest(
        freeze_commit=args.freeze_commit,
        selection_date=args.selection_date,
        attempt=args.attempt,
        exchange_payload_bytes=exchange_bytes,
        submission_payload=submission,
        excluded_tickers=args.exclude_ticker,
        retrieved_at=retrieved_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "S17_HELD_OUT_SELECTED_NOT_RUN",
        "attempt": args.attempt,
        "manifest": str(args.output),
        "selected_ticker": manifest["selected_issuer"]["ticker"],
        "pre_run_commit": args.freeze_commit,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
