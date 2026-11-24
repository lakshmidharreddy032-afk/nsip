# Runbook: Audit chain verification failure

1. Severity 1. `/api/v1/audit/verify` returns `valid=false` with the first broken sequence number.
2. Freeze admin changes; capture a database snapshot for forensics.
3. Compare the broken event with the latest backup and database logs; UPDATE/DELETE on `audit_events` is blocked by trigger, so a break indicates privileged tampering or restore inconsistency.
4. Notify the CISO and Compliance; follow the incident response plan. Do not repair the chain in place.
