# Runbook: Policy admin quarterly release

1. Four weeks before the vendor release, obtain the new API schema and update the contract fixtures in `tests/contract`.
2. Run contract tests; any break is fixed only in `adapters/policy_admin.py` (`VendorTranslator`), never in domain code.
3. Bump `PINNED_API_VERSION` only after the vendor sandbox passes the contract suite and an end-to-end quote in staging.
4. On release day, freeze quoting for the vendor maintenance window via a banner; quotes created are idempotent (Idempotency-Key) so retries are safe.
5. Rollback: redeploy the previous image; the pinned version remains compatible during the vendor's overlap period.
