# Open decisions

These are decisions the platform cannot make for the business. Each has a recommended option, which the build currently implements conservatively, and needs an accountable sign-off.

| # | Decision | Options | Recommendation | Current build behaviour | Owner to decide |
|---|---|---|---|---|---|
| 1 | Which outcome wins when speed and loss ratio conflict | (a) loss ratio is a hard guardrail; (b) trade-off case by case | (a) Loss ratio as a hard guardrail | Dashboards show loss ratio as the guardrail, time to quote as primary, win rate as lagging; a guardrail breach raises a critical alert | CUO |
| 2 | Can out-of-appetite declines be sent with lighter review | (a) one-click human confirmation; (b) automatic send; (c) full review | (a) One-click human confirmation | Decline is drafted at triage and sent only when an underwriter confirms | CUO with Distribution head |
| 3 | Can any small risk be quoted without an underwriter | (a) no, until the AI policy is amended; (b) yes below a threshold | (a) No | Fast lane for premiums under Rs 2 lakh within authority still needs one underwriter confirmation; no code path exists for unattended quotes | CUO and AI governance committee |
| 4 | Email versus portal | (a) email-first, honour "no new portals"; (b) push brokers to a portal | (a) Email-first | Regional mailboxes are primary; the 2023 portal is read as a secondary channel | Distribution head |
| 5 | Accountable owner | Single owner or split | Commercial Lines owns the outcome; Operations owns the Pune team process; Distribution owns broker communication | RACI reflected in dashboard audiences and runbooks | Executive sponsor |
| 6 | DPDP retention per purpose and erasure versus statutory record-keeping | Retention period; precedence rule | 3 years for submission data not bound to a policy; retain sealed quote evidence for the statutory period with restricted access | Default 3 years; sealed originals retained | Legal and Compliance |
| 7 | Broker-of-record rule for duplicates | First received; existing relationship; manual | First received, with manual override | Configurable in `integration_configs.clearance` | Distribution head |
| 8 | Pilot region | West or South first | West (largest volume, Pune ops team co-located) | Flags enable west and south; north and east off | Operations |
