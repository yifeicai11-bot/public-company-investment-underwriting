# Troubleshooting

Start every diagnosis from the repository root:

```bash
python underwrite.py doctor
```

Add `--live` before ticker retrieval and `--pdf` before PDF generation. Save a machine-readable copy with `--output /path/to/diagnostic.json`.

## Python or dependencies fail

The supported runtime is Python 3.11 or 3.12. macOS may still map `python3` to an older system Python.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python underwrite.py doctor
```

Do not install only `requirements-gate4.txt` for a full issuer run. It is now a compatibility pointer to the repository-wide lock.

## Live retrieval is blocked

Set an identifying SEC user agent with a monitored contact address:

```bash
export SEC_USER_AGENT="Your Name your.email@example.com"
python underwrite.py doctor --live
```

If SEC or market-data retrieval is temporarily unavailable, do not fill missing facts manually in the rendering layer. Preserve the diagnostic and retry the shared builder later.

## No One-Page or Full Report appears

This is expected when the contract is below Gate 3, has a Hard Stop, has render blockers, or fails independent validation. Inspect:

- `underwriting_output_contract.json`
- `analyst_input_template.json`
- `delivery/pipeline_diagnostic.json`
- `delivery/pipeline_manifest.json`

Complete a public, sourced research-input JSON and rerun with `--research-input`. Do not copy another company's assumptions.

## Validation fails after Gate 3

Open `delivery/validation_report.json` and fix the shared data or analysis component identified by the failed check. Do not edit the rendered HTML/PDF, report a rounded display value as a raw-number mismatch, or patch only one ticker's artifact builder.

## PDF generation fails

HTML generation does not require a browser. PDF generation requires local Google Chrome or Chromium:

```bash
python underwrite.py doctor --pdf
python underwrite.py render /path/to/underwriting_output_contract.json \
  --out-dir /path/to/delivery --pdf
```

For private Gate 4 PDFs, do not use the public renderer directly. Follow `docs/PRIVATE_DATA.md` and the sanitizer-only workflow.

## Git privacy scan blocks a file

Move real policy, holdings, exposures, opportunity-set, approval, sizing, and private outputs outside the repository. Re-run:

```bash
python user-demo/investment_decision_v2/scripts/check_private_data_boundaries.py --staged
```

The scanner reports file paths and rule IDs, not private values. Do not weaken the rule to make a commit pass.

## CI fails while local tests pass

Use the exact lock and run the CI-equivalent offline checks:

```bash
python underwrite.py doctor --ci
python scripts/validate_release_candidate.py
python -m unittest discover -s user-demo/investment_decision_v2/tests -p 'test_*.py' -v
python user-demo/investment_decision_v2/scripts/check_private_data_boundaries.py --tracked
```

CI intentionally performs no live ticker retrieval and does not select an S17 held-out company.
