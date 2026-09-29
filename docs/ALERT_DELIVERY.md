# Local Superset alert delivery

## Verified result — 2026-09-29 UTC

Real scheduled executions: **02:19** returned 0 (`Not triggered`, no email);
**02:20** returned 1 (`Success`, first captured email); **02:21** and **02:22**
recorded `On Grace` without another email; **02:23** returned 1 and delivered
the repeat. The two SMTP messages arrived about **180.10 seconds** apart.
The 02:22 execution fell just short of 120 seconds since the prior success,
so the next minute delivered the repeat. Both named alerts were then disabled.

Scheduled execution, condition evaluation, local SMTP capture, repeat
suppression, and repeat delivery all passed. External email delivery remains
**not configured or tested**. Four timestamp compatibility regression checks
passed. Existing metadata rows were compared to the pre-alert snapshot; the
only intentional dashboard change is its delivery-status disclosure. The
secret key, users, connection credentials, dataset/chart IDs, and historical
eligibility counts were preserved. See the machine-readable evidence in
`evidence/alert_delivery_verification.json`.

This stack uses the installed Superset **3.0.0**, Redis 7.2, one Celery worker
(concurrency 1), one Celery beat, and Mailpit 1.27.8. Mailpit captures SMTP on
Docker port 1025 and exposes its inbox only at http://localhost:8026.
SMTP has no host port and no relay or external provider configured.

## Start and reproduce

Run from this repository in PowerShell after starting Docker Desktop:

```powershell
docker compose start db app
docker start assetpulse-superset
py -3.11 scripts/setup_alerts.py
py -3.11 scripts/verify_alerts.py
```

The verifier takes several real minute boundaries. It does not enqueue tasks
manually. It tests a false SQL condition, a true condition, repeat suppression
within 120 seconds, and delivery again after the grace period. It disables both
named alerts in `finally`; see `evidence/alert_delivery_verification.json` for
the recorded outcomes and scheduled timestamps. Its exported definitions in
`superset/alert_definitions.json` are disabled by default. Existing report IDs
are reused by exact name. Old test execution logs and captured emails remain.
The interval is a minimum, not an exact delivery timer: the repeat occurs on
the next minute's scheduled execution after 120 seconds have elapsed.

Focused compatibility regression checks:

```powershell
py -3.11 -m unittest discover -s tests -p test_alert_eta.py -v
```

For routine startup after configuration is installed:

```powershell
docker compose start db app
docker start assetpulse-superset
docker compose -f compose.alerts.yaml up -d
```

Do not scale beat or run another scheduler for this broker. The unrelated
Superset 6 development stack uses a separate broker and is untouched.

## Preservation and scope

Setup backs up the live SQLite metadata with SQLite's backup API into the
existing `assetpulse_superset_home` volume before changing configuration. This
backup contains private metadata and must not be committed. It retains the
original secret key inside that volume in a mode-0600 file and verifies key
equality on reruns. No credentials appear in source, command arguments, or
exports. The web container is restarted, not recreated; no upgrade/init runs.
The loader in `/app/pythonpath/superset_config.py` references the persistent
configuration. If the web container is ever recreated, rerun setup to reinstall
that loader, with the original secret key and volume intact.

SQLite is preserved for this local, low-concurrency verification. This is not
a production deployment recommendation; a separately planned metadata
migration to PostgreSQL is needed before scaling concurrent workloads.
Superset 3.0 passes Celery's ISO-string ETA to the execution log; SQLite rejects
that value without conversion. A SQLite-only `before_insert` hook normalizes
the scheduled timestamp to a UTC datetime. Four focused regression tests cover
ISO text, timezone offsets, native datetime values, and invalid input. This
does not change scheduling, SQL conditions, or notification state transitions.

Alerts & Reports is enabled, but `ALERTS_ATTACH_REPORTS=False`: tested alerts
contain a description and dashboard link. Screenshot/PDF/CSV reports have not
been verified and need their own browser/rendering configuration. A passing
SQL email test does not prove report rendering.

The TEST ONLY alert uses a CTE `VALUES (0)` or `VALUES (1)`, read through the
existing analytics connection. It creates no table and changes no historical
data. Its condition is value > 0. The linked dashboard provides navigation;
the message clearly identifies the synthetic fixture.

The separate HISTORICAL ONLY alert counts eligible breached hours in the fixed
2020 source range. It remains disabled with a local-only capture recipient.
Querying these static readings repeatedly is not live equipment monitoring.
Only **186/4,416 hours (4.21%)** are eligible. The **>=6 A** loaded-state proxy
still needs domain validation. Zero candidates remain valid. No rule threshold
was changed to obtain notifications.

## Inspect and troubleshoot

```powershell
docker compose -f compose.alerts.yaml ps
docker logs --tail 60 assetpulse-alert-beat
docker logs --tail 100 assetpulse-alert-worker
docker exec assetpulse-alert-redis redis-cli ping
Invoke-WebRequest -UseBasicParsing http://localhost:8089/health
Invoke-RestMethod http://localhost:8026/api/v1/messages
docker exec assetpulse-superset python /tmp/alert_admin.py status
```

Beat should log `reports.scheduler` every minute; the worker then logs a
scheduled `reports.execute` with an ETA. Execution logs distinguish `Not
triggered`, `Success`, `On Grace`, and `Error`. Grace suppresses reevaluation
and repeat notification until the configured interval passes. A `Success`
record plus an actual captured email proves local delivery; dry-run logging
alone does not. If chart/alert queries fail after a reboot, check the existing
Compose `db` container is running and healthy. Do not reload telemetry.

If the verifier is forcibly killed or the host shuts down, its cleanup cannot
run. Disable the test immediately in Settings > Alerts & Reports, or run:

```powershell
docker exec assetpulse-superset python /tmp/alert_admin.py disable
```

Those temporary scripts are recopied by the verifier after container recreation.
For a full local alert stop, use `docker compose -f compose.alerts.yaml stop`.
Never use `down -v` or delete the existing metadata volume.

## External SMTP later (not configured or tested)

After explicit authorization, obtain the provider's host, port, TLS mode,
sender identity, and permitted recipients. Store credentials outside Git in a
protected mounted secret file; read them into `SMTP_USER` and `SMTP_PASSWORD`
from that file, never from command-line literals. Set `SMTP_HOST`, `SMTP_PORT`,
`SMTP_MAIL_FROM`, and the provider-required `SMTP_STARTTLS`/`SMTP_SSL` values;
enable certificate verification (`SMTP_SSL_SERVER_AUTH=True`). Never copy
Mailpit's no-auth/no-TLS settings to an external provider. Apply the same
configuration to web and worker, restart them, and test only an authorized
recipient before enabling any operational schedule. Record received delivery
separately from scheduler success and local capture. Do not enable the
historical candidate alert as a substitute for a live data pipeline.
