# Run AssetPulse

## Open the working dashboard first (Windows PowerShell)

Open the extracted project folder in VS Code. Start Docker Desktop, then run:

```powershell
docker compose start db app
docker start assetpulse-superset
```

Open the primary BI dashboard at http://localhost:8089/superset/dashboard/assetpulse-equipment-intelligence/
and the Streamlit presentation at http://localhost:8502. The checksum-verified aggregate snapshot
supports the dashboard immediately, without downloading the full raw dataset.
The snapshot represents 1,516,948 historical sensor observations, 4,416 observed
hours and 212 observed dates. The current rule produced zero candidates; the
app should show an empty investigation queue rather than invent incidents.

## Rebuild from original data

```powershell
docker compose up -d db
docker compose --profile refresh run --rm pipeline
```

This downloads the original UCI dataset, validates and loads it transactionally,
builds PostgreSQL SQL marts, then publishes a checksum-verified export. A failed
load leaves the previous export available. After completion, run
`py -3.11 scripts/setup_superset.py` to restore BI helper views and read grants
removed by the mart rebuild, then reload the dashboards.
On Linux, the mounted data directory must be writable by container UID 10001.
Do not run simultaneous refresh jobs against the same database/export directory.

## Inspect and stop

```powershell
docker compose ps
docker compose logs --tail 80 app
docker compose stop
```

The app reads only aggregate exports; PostgreSQL is required for refresh and
Superset access, not for opening the included snapshot. Superset setup is complete;
see [docs/SUPERSET.md](docs/SUPERSET.md) for rerunnable automation and verification. Live
notification delivery is not implemented. The Compose setup is local development.

## Publish manually

Upload the source, SQL, tests and data/export folder to your existing GitHub
repository. Exclude data/raw, .env, virtual environments and Python caches.
Streamlit Community Cloud entry point: app.py. Dependencies: requirements.txt.
Do not upload just the old placeholder app.py: upload the complete project.
