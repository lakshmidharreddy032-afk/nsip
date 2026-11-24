# NSIP pilot: executive summary

For: Ashok Menon, the Chief Underwriting Officer and the Head of Distribution.

NSIP removes the manual work in front of underwriting decisions: it declines out-of-appetite submissions at intake, catches duplicates before anyone keys them, and hands underwriters a pre-filled, source-linked submission to review. It does not price or quote on its own; every premium comes from our filed rates and every quote is issued by an underwriter within their authority.

## Why not "AI that generates quotes"

Our data showed where the time goes: about 45% of submissions are out of appetite yet keyed in full, 18% are duplicates, and keying takes about 70 minutes per submission. Fixing those three problems shortens time to quote without touching pricing, which stays with filed rates (IRDAI file-and-use) and with underwriters (our AI policy).

## Baselines and pilot targets

| Measure | Baseline | Pilot target |
|---|---|---|
| Out-of-appetite handling | Keyed in full | Declined at triage, under 5 minutes of handling |
| Duplicates (18%) | Found late, if at all | Flagged before extraction |
| Data entry | About 70 minutes | Under 15 minutes reviewing pre-filled data |
| Median time to quote | 6 working days | Under 48 hours for in-appetite, non-referred risks |
| Risk engineering referral (12%) | Raised after pricing, adds about 4 days | Raised at triage, in parallel |
| Win rate on quoted business | 11% | Tracked, not promised |
| Property loss ratio | 68% | Must not worsen (guardrail) |

## The guardrail

Loss ratio is a guardrail, not a target to trade. The CUO dashboard compares the AI-assisted cohort with the baseline cohort from the monthly claims snapshot and raises a critical alert if the assisted cohort runs above the 68% baseline. Time to quote is the primary operational measure; win rate is the lagging business measure.

## How we will know underwriters trust it

Every field correction is recorded, so the Underwriting dashboard shows the AI override rate for each field. A rising override rate on a field triggers a drift alert. Triage overrides, assistant-versus-rules disagreement, review minutes per submission and authority blocks are all reported. Distribution sees each broker's turnaround and win rate without other brokers' data.

## What the evaluation shows

On 330 synthetic broker emails (300 submissions, 54 duplicates, 20 revised schedules, 30 prompt-injection attempts), all seven acceptance gates pass: triage accuracy 98.8% with no in-appetite risk declined without confirmation, duplicate precision and recall of 1.0, critical-field extraction 100%, every SOV mismatch flagged, every injection attempt flagged with no effect on routing, zero automated quote paths, and complete audit evidence on every quote. These results use synthetic data and a deterministic model stand-in; they prove the controls and the pipeline, and they must be repeated on a labelled sample of real West-region submissions before go-live.

## Decisions we need from you

Five items are listed in [open decisions](open-decisions.md). The most important: confirm loss ratio as a hard guardrail (CUO), confirm one-click human confirmation for declines (CUO and Distribution), and confirm that no risk is quoted without an underwriter until the AI policy is amended.
