# Changelog

## v1.1.0 - 2026-08-04

Final release after S17 true held-out acceptance.

### Validated

- Preserved the first live post-freeze RPM result and its shared facility-parser defect without overwriting the evidence.
- Corrected numeric-boundary handling in the shared facility parser and added cross-company regression coverage.
- Revalidated RPM through GitHub Actions with current SEC filing data and privacy-safe repository-secret handling.
- Selected TNL through the frozen deterministic candidate pool after the shared fix; preserved and accepted its first run without replacement or ticker-specific code.
- Passed 404 shared tests, cross-industry and S12 valuation acceptance, Gate 4 synthetic delivery, privacy and skill checks, plus 82 frozen PDF and pixel checks.

### Boundaries

- A valid Gate 1 held-out result demonstrates safe data handling, not a complete investment recommendation.
- Formal public-data reports still require Gate 3. Portfolio sizing and action still require private Gate 4 inputs and human approval.
- The system does not automatically approve investments or execute trades.

## v1.1.0-rc.1 - 2026-08-03

S16 release candidate for usability and delivery hardening.

### Added

- One supported `underwrite.py` entry point for environment checks, ticker/company analysis, gated rendering, and independent validation.
- Machine-readable environment diagnostics covering Python, exact dependencies, repository layout, Git privacy hook, SEC identification, PDF browser, and output-path readiness.
- Repository-wide exact dependency lock for Python 3.11 and 3.12.
- GitHub Actions checks for shared tests, cross-company acceptance, frozen baseline integrity, synthetic Gate 4 delivery, skill structure, and tracked-file privacy.
- Troubleshooting, migration, private-data, and release-candidate documentation.
- Codex skill UI metadata and a repository-local skill validator.

### Changed

- The recommended partner-ready workflow now requires Gate 3 plus an independent validation pass before formal report rendering.
- `requirements-gate4.txt` delegates to the repository-wide lock.
- The privacy scanner supports `--tracked` for CI in addition to staged and explicit-path checks.

### Boundaries

- Friday V1 remains frozen at `v1.0.0-friday`.
- S16 does not select or run the S17 true held-out company.
- S16 does not publish a final release and does not change Gate 4's private, human-owned decision boundary.

## v1.0.0-friday - 2026-07-17

- Frozen partner-submitted public-company underwriting baseline.
- Preserved by tag, input/output hashes, runtime manifest, and offline verifier.
