# Runbook: Workbench latency above target

1. Alert: p95 read latency above 300 ms for 10 minutes.
2. Check database CPU and slow queries (`pg_stat_statements`); queue reads use the `(region, status)` index.
3. Check worker saturation: heavy OCR can starve shared nodes; KEDA should scale workers on queue depth.
4. Scale core-api replicas (HPA) and verify connection pool limits against PostgreSQL `max_connections`.
5. Run `make load` in staging to reproduce before changing indexes.
