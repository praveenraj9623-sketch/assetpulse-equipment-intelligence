# AssetPulse | Equipment Intelligence

An equipment investigation project built on **real historical railway compressor
telemetry**, with PostgreSQL modeling, data validation, a working local Apache
Superset SQL/BI workspace, and a Streamlit presentation of the same aggregates.

## What decision does it support?

An engineer investigates panel pressure while a compressor appears under load.
When an hourly low-pressure share meets the pressure-v1 thresholds relative to
the preceding week, the system produces a **review candidate**. The engineer
checks sensor trends and published maintenance reports before drawing a
conclusion. The exploratory rule is not a proven failure detector or a message
sent to an operator.

**Dataset:** [MetroPT-3, UCI Machine Learning Repository](https://archive.ics.uci.edu/dataset/791/metropt%2B3%2Bdataset),
DOI **10.24432/C5VW3R**, CC BY 4.0. It contains **1,516,948 observations**, 15
sensor signals and four externally reported failure intervals from a metro
train compressor. There are no factory produced-unit counts, OEE, shift targets
or manufacturing yield. Maintenance intervals are limited context, not
exhaustive healthy/fault labels. This historical dataset cannot demonstrate
live alerts or validated failure prediction.

## Architecture

```text
Original UCI archive
  -> streaming Python validation -> PostgreSQL readings (1,516,948 rows)
      -> hourly/daily SQL marts -> Superset (primary SQL/BI workspace)
      -> trailing seven-day rule -> candidate hours and incident islands
      -> checksum-verified aggregate exports -> Streamlit presentation
```

Loading and materialization run in one transaction; invalid or truncated input
rolls back. Raw CSV data are not committed or published. Only aggregate exports
are used by Streamlit. Provenance includes the original CSV SHA-256.

## Run the existing Windows installation

Start Docker Desktop, then run from this project directory:

```powershell
docker compose start db app
docker start assetpulse-superset
```

Open the [Superset Equipment Intelligence dashboard](http://localhost:8089/superset/dashboard/assetpulse-equipment-intelligence/)
or the [Streamlit presentation](http://localhost:8502). PostgreSQL remains on
host port **5434**; Superset connects internally to **db:5432** with a dedicated
read-only analytics role. Sign in privately with the existing admin account.

Startup, metric definitions, credential handling and verification are documented
in [docs/SUPERSET.md](docs/SUPERSET.md). See [START_HERE.md](START_HERE.md) for
intentional source refresh and public-presentation deployment instructions.

To rerun provisioning, validate charts and export definitions:

```powershell
py -3.11 scripts/setup_superset.py
```

This reuses the existing seven datasets, sixteen charts and dashboard. It does
not reload telemetry, recreate containers, delete volumes or rotate existing
credentials. The default filter uses the recorded **2020** period.

## Verification

The live PostgreSQL data reconcile to **1,516,948 observations**, **4,416 observed
hours** and **212 dates**. Superset passed 42 chart/period checks against
PostgreSQL, plus four independent raw-to-mart weighting checks. The analytics
role has read-only privileges; reruns retained all asset IDs. See
[superset/verification.json](superset/verification.json) and
[docs/VERIFICATION.md](docs/VERIFICATION.md).

The unchanged pressure-v1 rule produces **zero candidate hours and incidents**.
Only 186 hours (4.21%) meet its sample eligibility criteria; 4,230 are not
evaluated: 4,204 lack current samples only and 26 lack both current and prior
samples. See the [eligibility audit](docs/RULE_ELIGIBILITY_AUDIT.md).
Zero candidates does not certify healthy equipment. The data include
700 unobserved hourly windows; these are not known downtime.

Definitions and metrics are exported under
[superset/definitions](superset/definitions), with connection credentials
removed. The existing application test suite ran six passing tests; two tests
requiring isolated databases were skipped to preserve the actual dataset.

## Share responsibly

Streamlit is the public presentation layer, but it has not been cloud-deployed
by this task. Publish reviewed source plus `data/export/` to your Git repository
and use `app.py` as the Streamlit Community Cloud entry point. Exclude raw data,
`.env` files, private credentials and Python environments. The current workspace
does not contain a `.git` directory; this task did not initialize or publish a
repository. Localhost URLs work only on this computer.

The [local alert stack](docs/ALERT_DELIVERY.md) adds Redis, one Celery worker,
one beat scheduler, and Mailpit capture. Its deterministic TEST ONLY fixture
verifies delivery separately from the disabled historical candidate rule.
External email and live equipment monitoring are not configured. No downtime,
prediction accuracy or intervention savings are claimed.
