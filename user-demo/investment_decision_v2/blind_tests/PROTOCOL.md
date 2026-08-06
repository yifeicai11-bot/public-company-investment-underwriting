# Reproducible Blind-Company Forward Tests

This directory preserves forward tests used to detect company-specific
overfitting in the shared public-company underwriting system.

## Required Sequence

1. Record the pre-run shared-logic commit and blob hashes.
2. Exclude every company previously used for development, demos, or regression.
3. Select from a predeclared eligible pool using the manifest's deterministic
   method.
4. Commit the manifest and runner before any company request is sent.
5. Confirm the selected ticker is absent from pre-run shared logic.
6. Run the public-only builder once, with no research-input file.
7. Preserve command, runtime, stdout, stderr, builder output, errors, warnings,
   diagnostics, and file hashes.
8. Do not replace a company because the run fails.
9. Diagnose the shared root cause before changing code.
10. Fix only shared components, then rerun all existing regressions.

The first run is not required to reach Gate 3. A correct diagnostic, `MISSING`,
`NOT_APPLICABLE`, Warning, or Hard Stop may be the expected safe result. The
test fails when the system fabricates data, mixes periods, emits an
unsupported conclusion, crashes without a diagnostic, or needs a
ticker-specific analytical patch.

Run a frozen manifest with:

```bash
python3 user-demo/investment_decision_v2/scripts/run_blind_company_forward_test.py \
  user-demo/investment_decision_v2/blind_tests/s05_odfl/manifest.json
```

The runner refuses to overwrite an existing `first_run/` directory.

After a shared fix is committed, verify the immutable first run and execute the
separate post-fix run with:

```bash
python3 user-demo/investment_decision_v2/scripts/run_blind_company_forward_test.py \
  user-demo/investment_decision_v2/blind_tests/s05_odfl/manifest.json \
  --verify-preserved-first-run

python3 user-demo/investment_decision_v2/scripts/run_blind_company_forward_test.py \
  user-demo/investment_decision_v2/blind_tests/s05_odfl/manifest.json \
  --post-fix
```

The runner also refuses to overwrite `post_fix/`.
