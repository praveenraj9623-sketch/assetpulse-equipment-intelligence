-- Non-destructive migration: append audit fields, preserving existing columns,
-- candidate_status, dependencies and the unchanged pressure-v1 decision rule.
-- INSUFFICIENT_HISTORY is retained only for legacy export compatibility.
CREATE OR REPLACE VIEW mart_hourly_investigation AS
WITH eligibility AS (
 SELECT c.*,
        COALESCE(loaded_readings, 0) < 30 AS current_samples_insufficient,
        COALESCE(prior_loaded_readings, 0) < 300 AS baseline_samples_insufficient
 FROM mart_candidate_hours c
)
SELECT c.hour_ts, c.readings, c.panel_pressure_sum, c.oil_temperature_sum,
 c.pressure_gap_sum, c.avg_panel_pressure_bar, c.avg_reservoir_pressure_bar,
 c.avg_motor_current_a, c.avg_oil_temperature_c, c.avg_pressure_gap_bar,
 c.loaded_readings, c.unloaded_readings, c.idle_readings,
 c.low_pressure_loaded_readings, c.lps_active_readings, c.prior_low_readings,
 c.prior_loaded_readings, c.prior_observed_hours, c.current_low_fraction,
 c.prior_low_fraction, c.rule_version, c.candidate_status,
 EXISTS (SELECT 1 FROM failure_reports f
         WHERE c.hour_ts < f.ends_at AND c.hour_ts + INTERVAL '1 hour' > f.starts_at)
   AS overlaps_reported_failure,
 c.current_samples_insufficient, c.baseline_samples_insufficient,
 NOT (c.current_samples_insufficient OR c.baseline_samples_insufficient)
   AND c.current_low_fraction IS NOT NULL AND c.prior_low_fraction IS NOT NULL
   AS rule_eligible,
 CASE
  WHEN c.current_samples_insufficient OR c.baseline_samples_insufficient
       OR c.current_low_fraction IS NULL OR c.prior_low_fraction IS NULL
    THEN 'Not evaluated'
  WHEN c.candidate_status = 'REVIEW_PRESSURE' THEN 'Evaluated: breach'
  WHEN c.candidate_status = 'NO_CANDIDATE' THEN 'Evaluated: no breach'
  ELSE 'Not evaluated'
 END AS evaluation_status,
 CASE
  WHEN c.current_samples_insufficient AND c.baseline_samples_insufficient
    THEN 'Both: current <30 and prior <300'
  WHEN c.current_samples_insufficient THEN 'Current only: loaded observations <30'
  WHEN c.baseline_samples_insufficient THEN 'Baseline only: prior loaded observations <300'
  WHEN c.current_low_fraction IS NULL OR c.prior_low_fraction IS NULL
    THEN 'Missing rate despite sufficient counts'
  ELSE 'None: evaluated'
 END AS exclusion_reason,
 30::INTEGER AS required_current_loaded_observations,
 300::INTEGER AS required_prior_loaded_observations,
 c.hour_ts - INTERVAL '7 days' AS baseline_start_inclusive,
 c.hour_ts AS baseline_end_exclusive,
 168 - c.prior_observed_hours AS prior_unobserved_hour_windows
FROM eligibility c;
