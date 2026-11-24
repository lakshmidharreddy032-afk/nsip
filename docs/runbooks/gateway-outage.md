# Runbook: AI gateway outage (fall back to manual queue)

1. Alert: `GatewayOutageManualQueue` (more than 50% of AI calls failing for 10 minutes).
2. No action is needed to protect decisions: triage is rule-based and continues; quotes never depend on the gateway.
3. Submissions that need the model (free-text proposals, unknown SOV layouts, scans via cloud OCR) land in the Manual queue (`status=manual_review`) or with notes asking for manual completion. Operations assigns them to the Pune team, who key the gaps in the review screen.
4. Check the gateway status page and request IDs from `ai_calls` for the provider ticket.
5. After recovery, re-run affected submissions by resolving them in the workbench; do not bulk re-run without checking cost projections.
