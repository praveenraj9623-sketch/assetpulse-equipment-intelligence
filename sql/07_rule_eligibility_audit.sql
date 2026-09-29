-- Read-only, reproducible audit queries. Sections executed independently.
-- audit: reconciliation
SELECT count(*) AS observed_hours,
 count(*) FILTER (WHERE rule_eligible) AS eligible_hours,
 100.0 * count(*) FILTER (WHERE rule_eligible) / count(*) AS eligibility_percentage,
 count(*) FILTER (WHERE evaluation_status='Not evaluated') AS not_evaluated_hours,
 count(*) FILTER (WHERE evaluation_status='Evaluated: no breach') AS evaluated_no_breach,
 count(*) FILTER (WHERE evaluation_status='Evaluated: breach') AS evaluated_breach,
 count(*) FILTER (WHERE current_samples_insufficient AND NOT baseline_samples_insufficient) AS current_only,
 count(*) FILTER (WHERE baseline_samples_insufficient AND NOT current_samples_insufficient) AS baseline_only,
 count(*) FILTER (WHERE current_samples_insufficient AND baseline_samples_insufficient) AS both,
 count(*) FILTER (WHERE loaded_readings=0) AS zero_current_loaded,
 count(*) FILTER (WHERE loaded_readings BETWEEN 1 AND 29) AS current_loaded_1_to_29,
 count(*) FILTER (WHERE prior_loaded_readings IS NULL) AS null_prior_counts,
 count(*) FILTER (WHERE current_low_fraction IS NULL) AS null_current_rate,
 count(*) FILTER (WHERE prior_low_fraction IS NULL) AS null_prior_rate,
 count(*) FILTER (WHERE rule_eligible AND (current_low_fraction IS NULL OR prior_low_fraction IS NULL)) AS eligible_null_rate,
 count(*) FILTER (WHERE prior_observed_hours=168) AS complete_prior_hour_windows,
 min(hour_ts) AS first_hour, max(hour_ts) AS last_hour
FROM mart_hourly_investigation;

-- audit: exclusion_periods
SELECT exclusion_reason, count(*) AS hours, min(hour_ts) AS first_hour, max(hour_ts) AS last_hour
FROM mart_hourly_investigation GROUP BY 1 ORDER BY 1;

-- audit: independent_raw_window_reconciliation
WITH raw_hours AS MATERIALIZED (
 SELECT date_trunc('hour',observed_at) AS hour_ts, count(*) AS readings,
 count(*) FILTER (WHERE motor_current>=6) AS loaded,
 count(*) FILTER (WHERE motor_current>=6 AND tp3<7) AS low
 FROM readings GROUP BY 1
), independently_joined AS (
 SELECT c.hour_ts, c.readings, c.loaded, c.low,
 sum(p.loaded) AS prior_loaded, sum(p.low) AS prior_low, count(p.hour_ts) AS prior_hours
 FROM raw_hours c LEFT JOIN raw_hours p
 ON p.hour_ts >= c.hour_ts-INTERVAL '7 days' AND p.hour_ts < c.hour_ts
 GROUP BY c.hour_ts,c.readings,c.loaded,c.low
)
SELECT count(*) AS compared_hours,
 count(*) FILTER (WHERE ROW(a.readings,a.loaded,a.low,a.prior_loaded,a.prior_low,a.prior_hours)
 IS DISTINCT FROM ROW(b.readings,b.loaded_readings,b.low_pressure_loaded_readings,b.prior_loaded_readings,b.prior_low_readings,b.prior_observed_hours)) AS mismatched_hours,
 count(*) FILTER (WHERE (a.loaded>=30 AND COALESCE(a.prior_loaded,0)>=300) IS DISTINCT FROM b.rule_eligible) AS mismatched_eligibility
FROM independently_joined a FULL JOIN mart_hourly_investigation b USING (hour_ts);

-- audit: cadence_and_order
WITH ordered AS (
 SELECT observed_at, observed_at-LAG(observed_at) OVER(ORDER BY observed_at) AS delta,
 observed_at-LAG(observed_at) OVER(ORDER BY source_row) AS source_delta
 FROM readings
)
SELECT count(*) AS observations, count(*) FILTER(WHERE delta=INTERVAL '0 seconds') AS duplicate_timestamps,
 count(*) FILTER(WHERE source_delta<INTERVAL '0 seconds') AS source_order_reversals,
 percentile_disc(0.5) WITHIN GROUP(ORDER BY EXTRACT(EPOCH FROM delta)) AS median_interval_seconds,
 count(*) FILTER(WHERE delta>INTERVAL '20 seconds') AS gaps_over_20_seconds,
 max(EXTRACT(EPOCH FROM delta)) AS largest_gap_seconds
FROM ordered;

-- audit: hourly_sample_distribution
SELECT percentile_disc(ARRAY[0.0,0.25,0.5,0.75,0.9,0.95,1.0]) WITHIN GROUP(ORDER BY loaded_readings) AS loaded_percentiles,
 percentile_disc(ARRAY[0.0,0.25,0.5,0.75,1.0]) WITHIN GROUP(ORDER BY readings) AS total_percentiles,
 count(*) FILTER(WHERE loaded_readings<30 AND readings>=350) AS excluded_current_despite_350_total_samples,
 count(*) FILTER(WHERE prior_observed_hours<168) AS incomplete_prior_windows,
 count(*) FILTER(WHERE prior_observed_hours<168 AND rule_eligible) AS eligible_despite_incomplete_prior_window
FROM mart_hourly_investigation;

-- audit: largest_gaps
WITH gaps AS (
 SELECT observed_at, LAG(observed_at) OVER(ORDER BY observed_at) AS previous_at FROM readings
)
SELECT previous_at,observed_at,EXTRACT(EPOCH FROM observed_at-previous_at) AS gap_seconds
FROM gaps WHERE previous_at IS NOT NULL ORDER BY observed_at-previous_at DESC LIMIT 10;

-- audit: proxy_comparison
SELECT dv_electric,comp,count(*) AS observations,
 count(*) FILTER(WHERE motor_current>=6) AS current_loaded,
 count(*) FILTER(WHERE motor_current>=6 AND tp3<7) AS current_loaded_low_pressure,
 min(motor_current) AS min_current_a,max(motor_current) AS max_current_a,
 avg(motor_current) AS mean_current_a
FROM readings GROUP BY 1,2 ORDER BY 1,2;

-- audit: core_nulls_and_integrity
SELECT count(*) FILTER(WHERE observed_at IS NULL OR motor_current IS NULL OR tp3 IS NULL) AS null_rule_inputs,
 count(*) FILTER(WHERE motor_current>=6) AS current_proxy_loaded_observations,
 count(*) FILTER(WHERE dv_electric=1) AS valve_loaded_observations,
 count(*) FILTER(WHERE motor_current>=6 AND dv_electric=1) AS agreeing_loaded_observations,
 count(*) FILTER(WHERE motor_current>=6 AND dv_electric=0) AS proxy_only_observations,
 count(*) FILTER(WHERE motor_current<6 AND dv_electric=1) AS valve_only_observations,
 count(*) FILTER(WHERE motor_current>=6 AND tp3<7) AS rule_low_pressure_observations
FROM readings;
