# Gate 4 Local Private-Data Workflow

Use this reference whenever fund policy, exposure, holdings, opportunity-set, approval,
or portfolio-sizing context is requested.

## Non-Negotiable Boundary

Never ask the User to paste or upload real portfolio data into Codex,
Claude, a hosted model, an external API, telemetry, remote logs, or the public
repository. Use the local Python workflow. The repository contains only empty
templates, schemas, and clearly classified synthetic examples.

Do not write private data into:

- Git or Git history
- normal or debug logs
- crash dumps
- temporary directories outside the private workspace
- notebooks or notebook outputs
- caches
- public PDFs or PDF metadata
- Diagnostic Reports
- public demo directories

## Local Setup

Install the local parsers:

```bash
python3 -m pip install -r requirements-gate4.txt
```

Create the default local workspace:

```bash
python3 user-demo/investment_decision_v2/scripts/initialize_gate4_private_workspace.py \
  --input-mode EXPOSURE_ONLY
```

The default is `~/investment_private`. It must remain outside every Git
worktree. Replace the example mode only when more granular local data is
approved. Omitting `--input-mode` leaves the manifest intentionally incomplete.
Directories use mode `0700`; files use mode `0600`.

Complete these files locally:

- `gate4_private_workspace_manifest.json`
- `portfolio_policy.yaml`
- `exposure_summary.csv` when required by the selected mode
- `current_holdings.csv` when required by the selected mode
- `opportunity_set.csv` or an XLSX equivalent named in the manifest
- `portfolio_constraint_inputs.yaml`
- `approval_config.yaml`
- `gate3_freshness_attestation.yaml`

No policy or holdings default is valid. Missing inputs return
`GATE_4_PRIVATE_INPUTS_REQUIRED`.

Select exactly one manifest mode:

- `EXPOSURE_ONLY`: exposure summary required; holdings prohibited.
- `AGGREGATED_PORTFOLIO`: exposure summary and issuer-level aggregate holdings required.
- `FULL_HOLDINGS`: complete security-level holdings required; independent exposure summary optional.

Every schema-required field is `CORE_REQUIRED` unless the shared governance
contract explicitly marks it `CONDITIONAL`, `OPTIONAL`, or
`REVIEWER_CONFIRMED_NOT_APPLICABLE`. A core field cannot be waived. A blank
not-applicable field requires one matching row-specific rationale, reviewer,
and review timestamp.

## Entry Validation

Run:

```bash
python3 user-demo/investment_decision_v2/scripts/run_gate4_local_entry.py \
  path/to/step3/underwriting_output_contract.json \
  --manifest ~/investment_private/gate4_private_workspace_manifest.json
```

The local entry:

1. Validates the private schemas and reconciliations.
2. Binds freshness to the exact Gate 3 report ID and contract hash.
3. Re-runs Gate 3 freshness and eligibility.
4. Propagates stale or ineligible Gate 3 status.
5. Writes only a privacy-safe JSON diagnostic to `private_outputs/`.
6. Leaves system assessment `NOT_EVALUATED`.
7. Leaves User decision `PENDING`.
8. Leaves every sizing, action, and trade field null.

`GATE_4_INPUTS_VALIDATED` means the local documents are structurally valid and
explicitly identify provisional or missing constraint values. It is not an
investment approval and does not guarantee that S13 can calculate every
ceiling.

## S13 Constraint Calculation

After entry validation, run:

```bash
python3 user-demo/investment_decision_v2/scripts/run_gate4_constraint_engine.py \
  path/to/step3/underwriting_output_contract.json \
  --manifest ~/investment_private/gate4_private_workspace_manifest.json
```

The S13 runner reloads and rechecks Gate 3 immediately before calculation. It
then calculates existing issuer, single-name, sector, country, correlated
exposure, liquidity, holding period, downside, risk budget, opportunity cost,
and applicable hedge constraints. Every row stores the limit, current and
candidate values, formula, source fields, missing fields, escalation threshold,
and binding status.

The complete local result is written to:

`~/investment_private/private_outputs/gate4_constraint_engine_result.json`

It contains private values and must remain local. The terminal prints only
status flags.

- `GATE_4_CONSTRAINTS_CALCULATED` means every required ceiling is reproducible.
- `GATE_4_CONSTRAINTS_INCOMPLETE` means at least one required input remains
  missing; final maximum and binding constraints remain null or empty.

The maximum is a constraint ceiling, not a suggested position. S13 leaves
System Portfolio Assessment `NOT_EVALUATED`, User Decision `PENDING`, and
approved position range null. Read `portfolio_constraint_engine.md` for binding
formulas and language rules.

## Git Protection

Enable the tracked hook once per clone:

```bash
git config core.hooksPath .githooks
```

The scanner reports paths and rule IDs only. Never bypass the hook to commit
real portfolio data. If it blocks a file, unstage it and move it to
`~/investment_private`.

## Output Controls

Private outputs and public outputs must remain in separate directories. Direct
private PDF writes are blocked. Sanitize and verify a local PDF with:

```bash
python3 user-demo/investment_decision_v2/scripts/sanitize_gate4_private_pdf.py \
  ~/investment_private/private_outputs/raw_report.pdf \
  --output ~/investment_private/private_outputs/sanitized_report.pdf \
  --root ~/investment_private
```

The sanitizer rebuilds the pages, uses fixed non-identifying metadata, removes
XMP, rejects attachments and document-level active actions, verifies page
count, reopens the file, and writes mode `0600`. Its terminal diagnostic does
not print private paths. Sanitization does not authorize transmission.

## S14 Assessment and Approval

After a complete S13 result, run:

```bash
python3 user-demo/investment_decision_v2/scripts/run_gate4_assessment.py \
  path/to/step3/underwriting_output_contract.json \
  --manifest ~/investment_private/gate4_private_workspace_manifest.json
```

The system assessment uses `ELIGIBLE`, `ELIGIBLE_WITH_ESCALATION`,
`REVIEW_REQUIRED`, `NOT_ELIGIBLE`, or `NOT_EVALUATED`. The User decision is
separate and uses `PENDING`, `APPROVED`, `MODIFIED`, `REJECTED`, or `DEFERRED`.
Every non-pending decision must reference the current assessment hash. An
approval or modification must additionally use a total-issuer gross-long
basis, remain within the constraint ceiling, and acknowledge every active
escalation ID.

The local runner writes one S14 JSON contract plus bilingual One-Page, Full
Report, Evidence Appendix, and Validation Report Markdown files. These files
contain private values and remain local. Direct private PDF writes remain
prohibited; use the sanitizer workflow.

The system never automatically places a trade. S13 calculates a constraint
ceiling, S14 classifies eligibility, and only the named User owns a completed
decision and approved range.
