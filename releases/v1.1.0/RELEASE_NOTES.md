# v1.1.0 Final Release

This release completes S17 true held-out acceptance for the reusable public-company investment-underwriting system.

The first live post-freeze issuer, RPM, exposed a shared facility-parser defect. The preserved result incorrectly extracted USD 0.5 million from a USD 1,089.5 million total-liquidity sentence. The value remained provisional and did not support an investment conclusion, but the shared parser was corrected and covered by regression tests. A new live RPM run then verified the fix against the current 10-K.

After the shared fix was frozen, the deterministic held-out protocol selected Travel + Leisure Co. (TNL), a different business model that had not participated in development. Its first run was preserved without replacement and passed selection integrity, shared-code freeze, evidence hashing, contract validation, output suppression, and anti-hardcoding checks. The system correctly remained at Gate 1 where public research inputs were incomplete.

Final acceptance also includes 404 shared tests, cross-industry and S12 valuation acceptance, Gate 4 synthetic validation, repository privacy scanning, skill validation, and 82 frozen PDF regeneration and pixel checks.

This is a research-support release. It does not automatically approve an investment or execute a trade. Formal public-data reports require Gate 3, and fund-specific sizing or portfolio action requires separately validated private Gate 4 inputs and human approval.
