# Investigation-rule eligibility audit

Audited against the actual PostgreSQL data on September 28, 2026. The question
was why 4,230 of 4,416 observed hours were labeled `INSUFFICIENT_HISTORY`.

## Finding

The numerical eligibility result is correct for pressure-v1. The label was
misleading: it combined current-hour sample scarcity with inadequate baseline
samples. No window, denominator or threshold implementation error was found in
the actual rule results. The correction separates these reasons and distinguishes
not evaluated from an evaluated hour with no breach.

| Mutually exclusive outcome | Hours | Meaning |
| --- | ---: | --- |
| Current samples insufficient only | 4,204 | Current loaded count <30; prior loaded count >=300. |
| Baseline samples insufficient only | 0 | Current count >=30; prior count <300. |
| Both sample requirements fail | 26 | Current count <30 and prior count <300. |
| Evaluated, no breach | 186 | Both sample minima pass; rule does not breach. |
| Evaluated, breach | 0 | No observed rule breaches. |
| **Total observed hours** | **4,416** | Complete reconciliation. |

Thus 4,230 hours are **not evaluated**, and 186 / 4,416 = **4.2119565%** are
eligible. The baseline-insufficient marginal count is 26, already included in
the "both" row; adding it again would double-count exclusions. All 26 occur
among observed hours from February 1 00:00 through February 2 08:00.

## Why so few current-hour samples qualify?

The current proxy selects 71,664 of 1,516,948 observations. Per observed hour,
the median loaded-proxy count is 17 and the 95th percentile is 29, just below
the unchanged minimum of 30. The count range is 0–147. Of the 4,230 excluded
hours, 401 contain zero qualifying observations and 3,829 contain 1–29.

This is primarily scarcity of samples meeting the current proxy, not merely
missing telemetry: 3,636 excluded hours have at least 350 total observations.
The median total is 363 observations per hour. Counts are observations, not
continuous loaded minutes; gaps prevent interpreting them directly as duty time.

## Window, gaps, thresholds and NULLs

- The existing SQL `RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 hour'
  PRECEDING` operates on hour-aligned timestamps. It is equivalent to
  `[hour - 7 days, hour)`: the exact seven-day boundary is included, the current
  hour and future hours are excluded. It is elapsed calendar time, not the
  previous 168 rows. A raw-reading hourly aggregation followed by an independent
  interval join matched all current/prior counts and eligibility for all 4,416
  hours, with **zero mismatches**.
- Eligibility requires at least **30 current** and **300 prior** loaded-proxy
  observations, inclusive. It does **not** require seven complete days or 168
  observed hours. Of 4,416 prior windows, 4,407 have fewer than 168 observed hour
  bins; this includes source-start truncation and later gaps. All 186 eligible
  hours have an incomplete window but enough prior samples under the stated
  policy. No extra coverage criterion was silently introduced.
- The source has 700 missing hourly bins across its observed span. There are
  351 inter-reading gaps longer than 20 seconds; the longest is 172,918 seconds
  (48 hours, 1 minute, 58 seconds), April 25 01:10:51–April 27 01:12:49.
  No duplicate timestamps or source-order reversals were found. The median
  reading interval is 10 seconds. Timestamps remain timezone-unspecified.
- No raw timestamp/current/TP3 input is NULL. The first hour has an empty prior
  window, producing NULL prior sums and rate; `COALESCE(prior_loaded_readings,0)`
  correctly excludes it. The 401 zero-loaded current hours have NULL current
  rates due to `NULLIF(loaded_readings,0)`, and are excluded. There are **zero
  eligible hours with NULL rates**. Zero prior low-pressure numerator with a
  positive denominator is a legitimate zero rate, not missing history.
- The absolute threshold remains **15%**, relative threshold **2x** the prior
  ratio, low pressure **TP3 <7 bar**, and loaded proxy **current >=6 A**. All must
  be interpreted alongside sample eligibility. There are zero observations
  satisfying both current >=6 A and TP3 <7 bar, so zero breaches/incidents remain
  legitimate. These results do not establish equipment health or downtime.

## Is the loaded-state proxy supported?

[UCI's variable documentation](https://archive.ics.uci.edu/dataset/791/metropt%2B3%2Bdataset)
describes characteristic motor currents near 0 A when off, 4 A when unloaded,
7 A when loaded and 9 A during startup. This supports a current-based proxy in
principle, but does not validate the exact >=6 A threshold. That cutoff also
admits startup transients. The same documentation identifies an active DV
electric signal with loaded operation and active COMP with off/unloaded states.

The actual signals are not interchangeable: DV electric is active on 243,638
observations, while the current proxy selects 71,664. Their loaded intersection
is 71,385; 279 observations are current-only and 172,253 valve-only. This shows
the current proxy selects a narrower population. It does not prove that either
signal is a complete ground-truth state label. The rule was **not** switched to
the valve signal or recalibrated to generate incidents. The UCI page also mixes
1 Hz collection language with 0.1 Hz attribute information; the actual median
cadence above is the basis for this audit.

Before operational notification delivery, the current proxy and sample minima
still warrant domain validation. That is a measurement-policy question, not a
reason to lower thresholds just to populate an investigation queue.

## Changes and checks

- `sql/06_rule_eligibility.sql` appends independent exclusion flags,
  `rule_eligible`, readable `evaluation_status`, exclusive `exclusion_reason`,
  sample requirements and window bounds to the existing investigation view.
  Existing columns, dependencies and legacy `candidate_status` are retained
  for Streamlit/export compatibility. Missing-rate cases are defensively labeled
  not evaluated rather than falling through to no breach.
- The pipeline applies this view migration after creating the rule models.
  The live update used CREATE OR REPLACE VIEW and did not run ingestion or
  recreate materializations.
- The same Superset dashboard now has **16 charts**: all 13 existing chart IDs
  are retained, with eligibility percentage, not-evaluated hours and an
  exclusion-reason table added. The existing coverage table now groups by
  readable evaluation status. Reasons include explicit zero baseline-only and
  missing-rate counts. The percentage is a ratio of counts over selected
  observed hours; an empty selection yields NULL, not 0% eligibility.
- Dataset metadata, metrics and secret-free native exports were refreshed.
  All seven dataset IDs, the database ID and dashboard ID remain unchanged.
- **42 chart/period checks** matched PostgreSQL across the full period, April
  and an empty future period (context charts remain full-source). Four existing
  independent raw-to-mart weighting checks also passed.
- **Eight focused PostgreSQL regression tests passed**, using only session-local
  temporary tables/views followed by rollback. They cover current-only,
  baseline-only, both exclusions, empty and zero baselines, exact minima,
  seven-day boundaries, missing hours, future/current-hour exclusion, both
  breach criteria, and a defensive missing-rate exclusion. No synthetic data
  were written to public tables or exported as telemetry.

Reproduce from PowerShell with the existing database running:

```powershell
py -3.11 scripts/setup_superset.py
py -3.11 scripts/audit_eligibility.py
$env:ASSET_TEST_RULE_ELIGIBILITY = "1"
py -3.11 -m unittest discover -s tests -p test_rule_eligibility.py -v
```

Evidence: `evidence/rule_eligibility_audit.json`; query text:
`sql/07_rule_eligibility_audit.sql`; chart checks: `superset/verification.json`.
Existing credentials, volumes, ports and unrelated dashboards were preserved.
No notification worker, scheduler or delivery channel was configured.
