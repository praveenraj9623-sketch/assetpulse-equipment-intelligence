# AssetPulse Superset workspace

The [eligibility audit](RULE_ELIGIBILITY_AUDIT.md) updates this workspace to
16 charts and 42 chart/period checks. It adds eligibility percentage and
exclusive exclusion reasons, with "Not evaluated" separated from "Evaluated:
no breach". The prior `INSUFFICIENT_HISTORY` code is retained only for legacy
export compatibility; it combines current and baseline sample exclusions.

Superset is the primary SQL/BI workspace. Streamlit is the public presentation
layer using checksum-verified aggregate exports from the same PostgreSQL models.
This deployment is local; Streamlit has not been published by this task.

## Start the existing installation

Start Docker Desktop, then run from the project directory in PowerShell:

```powershell
docker compose start db app
docker start assetpulse-superset
docker compose ps
Invoke-WebRequest -UseBasicParsing http://localhost:8089/health
```

These commands reuse existing containers and volumes. Wait for PostgreSQL to be
healthy before opening charts. If Superset shows chart errors after a computer
restart, check `docker compose ps -a`: the database may still be stopped while
Superset and Streamlit have started. Start `db`, then reload the dashboard.

- [Equipment Intelligence dashboard](http://localhost:8089/superset/dashboard/assetpulse-equipment-intelligence/)
- [Superset SQL Lab](http://localhost:8089/sqllab/)
- [Streamlit presentation](http://localhost:8502)
- PostgreSQL: host port **5434**, internal Docker address **db:5432**.
- Superset container: **assetpulse-superset**, image **apache/superset:3.0.0**.
- Metadata/credential volume: **assetpulse_superset_home**.

Use the existing admin login privately. The separate Superset stack on port 8088
is unrelated and is not used. Do not delete volumes, run `down -v`, regenerate
the Superset secret key, repeat initialization, or reload telemetry just to
start the application.

## Rerunnable provisioning and verification

```powershell
py -3.11 scripts/setup_superset.py
```

The host wrapper needs Python 3.11 standard library and local Docker admin access;
all Superset, psycopg2 and YAML dependencies already exist in the Superset image.
It discovers the existing Compose database container, reads its credential into
memory, and sends it to the worker over stdin. It does not put passwords in
command arguments, source files, exports, or console output.

The worker authenticates an isolated Flask test client as the existing active
Superset Admin user and calls the installed Superset 3 REST endpoints, including
CSRF protection. It does not reset the admin password, modify authentication
configuration, create an HTTP login bypass, or regenerate the secret key. This
is local container administration, not a remotely usable API credential flow.

Provisioning creates/reuses `assetpulse_analytics`. Its generated password is
stored with mode 0600 at `/app/superset_home/assetpulse_analytics.json`, outside
this repository, and in Superset's encrypted database connection. Existing
passwords are reused. If a role exists without its saved credential, setup
stops instead of rotating it. Preserve the volume and existing secret key.

The role has SELECT on the explicitly granted marts/context views, CONNECT and
schema USAGE. It has no table-write or schema-create privileges, role creation,
database creation, superuser, replication, or RLS-bypass privileges. A read-only
transaction default and 60-second statement timeout provide additional limits.
Superset SQL Lab exposes the connection with DML, CTAS, CVAS, file uploads and
asynchronous query execution disabled. The raw telemetry table is not directly
granted to this role; the source-quality view exposes only aggregate checks.

Setup adds only the two helper views in `sql/05_superset_analytics.sql`. It never
runs the ingestion/rebuild SQL. Existing asset IDs and metric IDs are reused;
ambiguous names or a chart owned by another dataset stop setup instead of
overwriting that chart. Reruns update the managed chart definitions and layout,
so keep intentional UI customizations in the script before running it again.

After an intentional full pipeline rebuild, run setup again: the existing
pipeline drops/recreates marts with CASCADE, which also removes dependent BI
helpers and table grants. Setup restores helpers/grants without reloading data.
Do not run the pipeline and setup simultaneously.

## Registered datasets and metrics

| Dataset | Grain and intended use |
| --- | --- |
| `mart_hourly` | One observed hour; additive counts and sensor sums. |
| `mart_daily` | One observed date; daily weighted metrics. |
| `mart_hourly_investigation` | One hour plus prior seven-day baseline, eligibility and unchanged pressure-v1 status. |
| `mart_incidents` | One island of consecutive candidate hours; currently empty. |
| `mart_report_review` | One externally reported maintenance interval; four records. |
| `analytics_operating_states` | Three mutually exclusive current-based states per observed hour. |
| `analytics_data_quality` | One whole-source reconciliation/provenance record. |

Reusable metrics use `SUM(readings)` for observations and
`100 * SUM(low_pressure_loaded_readings) / NULLIF(SUM(loaded_readings), 0)` for
low-pressure loaded share. The denominator is loaded observations, not all
observations. No loaded observations produces NULL, not an invented 0%.

Hourly pressure and temperature use sensor sums divided by total observations.
Daily models expose means and counts, so multi-day metrics use
`SUM(daily_mean * readings) / SUM(readings)`. Daily and hourly rollups were
independently reconciled to raw sensor averages and numerator/denominator counts.

Prior seven-day rates are ratios of prior counts, excluding the current hour.
The baseline chart is hourly. Baseline/2x-baseline metrics return NULL if a query
combines multiple hours, preventing invalid aggregation of overlapping windows.
The fixed 15% floor and 2x prior baseline are shown separately; both thresholds
and both sample minima must pass. No rule thresholds were changed.

Time-series resampling adds only NULL points for missing dates/hours; it does
not interpolate or zero-fill sensors. Superset's pivot uses one already
aggregated point per timestamp, so its internal pivot does not average unequal
hour/day populations.

## Dashboard behavior

Sixteen charts provide the headline counts, eligibility percentage, exclusion
reasons, daily pressure and oil-temperature
trends, operating-state observation bars, rule-coverage counts, the hourly rule
and baseline comparison, an incident queue, maintenance context, quality checks,
and source provenance. Tables support search and sorting; trends support zoom.

The native date filter defaults to **2020-02-01 inclusive through 2020-09-02
exclusive**, covering the last recorded reading on September 1. Recorded
timestamps are naive; UCI provides no timezone. Pipeline load time is separately
labeled UTC and is not the age of the historical telemetry.

The filter affects telemetry/rule charts and filters incidents by their start
date. It deliberately excludes the clearly labeled full-source maintenance,
quality and provenance tables. Baselines keep the prior seven-day context even
when the visible period is narrowed. Date-only selections are recommended for
daily charts; the daily source cannot represent partial-day boundaries.

Zero candidates and an empty incident table are valid. `INSUFFICIENT_HISTORY`
means the rule cannot assess that hour. Unobserved windows do not imply downtime.
Published maintenance intervals are context overlays, not rule inputs, complete
fault labels, proof of predictive lead time, or evidence that other periods were
healthy.

## Verification and exports

`superset/verification.json` records generated SQL and 42 chart/period checks:
the full recorded period, April 2020, and an empty 2021 period for filtered
charts; full source for the three context charts. Every returned SQL scalar was
compared with PostgreSQL results. Added resampling points were checked to be
NULL. It also records four independent raw-to-mart weighting checks, read-only
privilege checks, full-source reconciliation and dashboard HTML HTTP 200.

`superset/asset_ids.json` records the managed identities. A second setup run
asserted that all IDs remained unchanged. Native dashboard/chart/dataset YAML
is under `superset/definitions/`; `superset/export_manifest.json` lists files.
The exported database URI has **no password**. Use the setup script to restore
this local installation. Native import into another installation requires a
privately supplied analytics credential and compatible PostgreSQL models.

The source records 1,516,948 observations, 4,416 observed hours, 212 observed
dates, 700 unobserved hourly windows, zero duplicate timestamps, and zero
missing TP3/oil-temperature/motor-current values. Hourly and operating-state
counts reconcile with no difference. Loaded/unloaded/idle counts are
71,664 / 616,284 / 829,000. Rule coverage is 186 eligible and 4,230 insufficient
history hours, with zero candidates and zero incidents.

Rendered verification in the signed-in browser passed: all thirteen charts
loaded, the incident queue showed its legitimate empty state, and the April
filter showed 198,734 observations and 18 eligible hours, matching PostgreSQL.
All four maintenance rows and the full-source quality record stayed visible
when that filter changed. Daily sensor charts visibly broke at missing dates.
The full 2020 default view was restored after the test. See
`evidence/superset_dashboard.png` and `evidence/superset_browser_verification.json`.

The existing container test suite ran eight tests: six passed and two isolated
database integration tests were skipped. The database integration tests were
not run against the preserved production dataset. The live BI checks above ran
against the real PostgreSQL models.

The [local alert stack](ALERT_DELIVERY.md) provides an AssetPulse-specific
worker, single scheduler, Redis broker, and Mailpit SMTP capture. Its fixture
verification is separate from the disabled historical rule. External email,
live monitoring, downtime, prediction accuracy and savings are not claimed.

API behavior was checked against the installed 3.0 code and the
[official Superset API documentation](https://superset.apache.org/developer-docs/api/).
Version-specific gap handling follows the
[3.0 resampling operator](https://github.com/apache/superset/blob/3.0.0/superset-frontend/packages/superset-ui-chart-controls/src/operators/resampleOperator.ts).
