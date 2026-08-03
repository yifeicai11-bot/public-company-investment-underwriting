# Private Data Boundary

The GitHub repository, public ticker workflow, examples, fixtures, and CI are public-data-only. They must not contain real fund or client information.

## Never place in the repository or hosted AI chat

- Fund NAV, holdings, security identifiers tied to positions, or position sizes
- Current issuer, sector, country, factor, correlated, or hedge exposures
- Internal target return, downside tolerance, risk budget, limits, or liquidity needs
- Opportunity sets, internal rankings, Partner approvals, or trade instructions
- Broker statements, client information, transaction history, or private diagnostics

Redaction is not enough when remaining rows can reconstruct a portfolio. Use the least-granular Gate 4 mode that supports the decision.

## Approved local workflow

1. Keep the validated Gate 3 issuer contract as the public boundary object.
2. Initialize `~/investment_private` or another non-repository, non-cloud-synced local directory.
3. Complete one explicit mode: `EXPOSURE_ONLY`, `AGGREGATED_PORTFOLIO`, or `FULL_HOLDINGS`.
4. Run Gate 4 locally with networking, telemetry, remote logging, and external-model calls disabled.
5. Keep private outputs in the local workspace with restrictive permissions.
6. Use `sanitize_gate4_private_pdf.py` for any private PDF and verify its metadata report.

Example initialization:

```bash
python partner-demo/investment_decision_v2/scripts/initialize_gate4_private_workspace.py \
  --input-mode EXPOSURE_ONLY
```

The system must never invent missing private values. Invalid, stale, missing, or conflicting inputs produce a diagnostic and suppress portfolio calculations.

## Repository controls

Enable the privacy hook in every clone:

```bash
git config core.hooksPath .githooks
```

Scan staged files before committing:

```bash
python partner-demo/investment_decision_v2/scripts/check_private_data_boundaries.py --staged
```

CI separately scans every Git-tracked file with `--tracked`. The scanner is a guardrail, not permission to upload a file that happens to pass.

## If private data is accidentally staged or committed

Stop sharing and pushing immediately. Remove the file from the pending change without deleting the local source, move it outside the repository, notify the repository owner or compliance contact, and assess whether credentials, links, approvals, or counterparties must be rotated or notified. Do not rewrite shared Git history without the repository owner's explicit coordination.
