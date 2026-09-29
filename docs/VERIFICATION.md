# Verification boundaries

## Eligibility audit update

See [RULE_ELIGIBILITY_AUDIT.md](RULE_ELIGIBILITY_AUDIT.md) for the detailed audit.
The current dashboard has 16 charts, with 42 chart/period checks passed and
eight focused temporary-fixture SQL regression tests passed. All existing asset
IDs were preserved. Eligibility is 186 / 4,416 = 4.21%. Exclusions are 4,204
current-only, zero baseline-only and 26 both. Raw-to-window recomputation
matched all 4,416 hours. The prior build record below is historical evidence.

## Executed on Windows Docker Desktop, September 28, 2026

- PostgreSQL 16, Streamlit and Superset 3.0.0 were inspected in the existing
  containers. Superset `/health` returned HTTP 200. No services or volumes were
  recreated. PostgreSQL was started after it was found stopped on resume.
- The live source contains 1,516,948 observations, 4,416 observed hours and 212
  observed dates, spanning February 1 through September 1, 2020.
- Hourly and operating-state observation totals both reconcile exactly to the
  raw row count. There are zero duplicate timestamps and zero missing core
  pressure/oil-temperature/motor-current values. There are 700 unobserved hourly
  windows and two unobserved dates; these are not known downtime.
- The unchanged pressure-v1 rule produces zero candidate hours and incidents;
  186 hours are eligible and 4,230 have insufficient history.
- Seven datasets, reusable metrics, thirteen charts and the Equipment
  Intelligence dashboard were created through Superset REST handlers. The
  dedicated analytics role has read-only privileges.
- Thirty-three chart/period queries matched PostgreSQL values, including a
  narrowed April period and a future empty period. Resampling inserted only
  NULL gaps. Four independent raw-to-mart checks verified weighted means and
  low-pressure numerator/loaded-observation denominator counts.
- Repeated provisioning retained database, dashboard, dataset and chart IDs.
- Signed-in browser rendering passed for all thirteen charts, including the
  valid empty incident queue. The April filter showed 198,734 observations,
  18 eligible hours and 571 insufficient-history hours, matching PostgreSQL.
  The four maintenance records and source-quality tables remained unfiltered.
  Missing dates visibly broke trend lines. The default 2020 view was restored.
- The analytics password was verified absent from Superset event logs.
- Native YAML dashboard/chart/dataset definitions were exported without
  connection credentials. See `superset/export_manifest.json`.
- Existing application tests ran inside the working app image: eight tests
  discovered, six passed, two isolated-database tests skipped. Streamlit AppTest
  exercised the snapshot and all four maintenance-report selections.

Machine-readable SQL, results and IDs are in `superset/verification.json` and
`superset/asset_ids.json`. Historical pipeline evidence remains in
`evidence/full_data_verification.json`.

## Scope

Superset is the primary local SQL/BI workspace. Streamlit is the presentation
layer and has not been cloud-deployed by this task. Published maintenance
intervals are context, not complete fault labels. Synthetic positive cases in
tests are never presented as observed telemetry.

Notification delivery is not configured or tested. An AssetPulse worker,
scheduler and delivery channel still need implementation and end-to-end testing.
No live stream, downtime, validated prediction accuracy or savings are claimed.
