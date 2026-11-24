# Runbook: Actuarial rating workbook update

1. Actuarial delivers the new filed workbook with the filing reference. It must not contain macros or external links.
2. Compute its SHA-256 and register it in `integration_configs.rating_workbooks` with `version` and `filing_ref` (maker-checker through Admin > Integrations).
3. Deploy the workbook file (or set `NSIP_RATING_WORKBOOK_PATH`). Ratings with an unregistered hash are refused.
4. Run the reference cases in staging and compare premiums with actuarial's expected values; sign off in the change record.
5. Existing rating runs keep their workbook hash; submissions rated on the old version must be re-rated before quoting if the effective date requires it.
