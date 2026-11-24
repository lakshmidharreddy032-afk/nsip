# Runbook: Mailbox outage (MS Graph or IMAP unavailable)

1. Alert: no new `email.ingested` audit events for a region for 30 minutes during business hours, or worker logs show Graph 401/429/5xx.
2. Check Graph service health and the app registration secret expiry in the secrets manager; for 429 the poller backs off automatically.
3. If Graph is down for more than 1 hour, switch the region to IMAP: set `integration_configs.mailbox.adapter=imap` and restart workers.
4. If both are down, brokers keep emailing (mail queues upstream). Staff can forward urgent emails as .eml to Admin > upload (`POST /api/v1/admin/ingestion/upload-eml`); ingestion is idempotent on Message-ID so later polling will not duplicate them.
5. After recovery, confirm the backlog drains (queue depth) and SLA timers; consider extending SLA for affected submissions and record the decision.
