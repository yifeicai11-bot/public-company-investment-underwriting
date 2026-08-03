# Changelog

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
