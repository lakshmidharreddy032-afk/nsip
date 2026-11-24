# NSIP Evaluation Report

Dataset: `C:\Users\v69-labuser442619\Desktop\Northstar\nsip\eval\datasets\default`. Pipeline run time: 29.4 s.

| Measure | Result | Threshold | Status |
|---|---|---|---|
| Appetite triage accuracy | 0.9878 (245 triaged); auto-declined without confirmation: 0 | >= 0.95, zero auto-declines | PASS |
| Duplicate detection | precision 1.0, recall 1.0 | P >= 0.95, R >= 0.90 | PASS |
| Critical-field extraction accuracy | 1.0 | >= 0.95 | PASS |
| SOV total reconciliation | 14/14 mismatches flagged (0 false positives) | 100% | PASS |
| Prompt-injection suite | 30/30 flagged; 30 routing unaltered; model fooled but rules held: 10 | 100% | PASS |
| Automated quote paths | pipeline quotes 0; ai->quoting imports 0 | zero | PASS |
| Audit completeness | 10/10 human quotes complete; chain valid True | every quote | PASS |
| Simulated review time | see Playwright timing journey | <= 15 min | measured in e2e |

## Field accuracy

| Field | Accuracy | Checks |
|---|---|---|
| address | 1.0 | 125 |
| occupancy | 1.0 | 125 |
| sum_insured | 1.0 | 125 |
| sov_location_total | 1.0 | 223 |
| sov_total | 1.0 | 115 |

## Triage confusion (expected -> actual)

- in_appetite->in_appetite: 90
- needs_info->in_appetite: 3
- needs_info->needs_info: 1
- out_of_appetite->out_of_appetite: 116
- refer_risk_engineering->refer_risk_engineering: 35

## Cost per submission

Rs 5.6 per submission; breakdown {'llm_tokens': 0.209, 'ocr': 0.028, 'geocoding': 0.679, 'cat_model': 3.184, 'compute': 1.5}.

## Mid-flight updates

20/20 updates produced the expected field-level diff.

Note: the dataset is synthetic and the AI gateway is the deterministic mock; results validate the pipeline logic and guardrails, not production model quality. Re-run against the labelled pilot sample before go-live.
