-- AssetPulse rule pressure-v1. Historical readings retain the source's naive
-- timestamps: the publisher does not specify a timezone. Never relabel as UTC.
DROP MATERIALIZED VIEW IF EXISTS mart_daily CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mart_hourly CASCADE;

CREATE MATERIALIZED VIEW mart_hourly AS
SELECT date_trunc('hour', observed_at) AS hour_ts,
       COUNT(*)::BIGINT AS readings,
       SUM(tp3) AS panel_pressure_sum,
       SUM(oil_temperature) AS oil_temperature_sum,
       SUM(ABS(tp3 - reservoirs)) AS pressure_gap_sum,
       AVG(tp3) AS avg_panel_pressure_bar,
       AVG(reservoirs) AS avg_reservoir_pressure_bar,
       AVG(motor_current) AS avg_motor_current_a,
       AVG(oil_temperature) AS avg_oil_temperature_c,
       AVG(ABS(tp3 - reservoirs)) AS avg_pressure_gap_bar,
       COUNT(*) FILTER (WHERE motor_current >= 6)::BIGINT AS loaded_readings,
       COUNT(*) FILTER (WHERE motor_current >= 1 AND motor_current < 6)::BIGINT AS unloaded_readings,
       COUNT(*) FILTER (WHERE motor_current < 1)::BIGINT AS idle_readings,
       COUNT(*) FILTER (WHERE motor_current >= 6 AND tp3 < 7)::BIGINT AS low_pressure_loaded_readings,
       COUNT(*) FILTER (WHERE lps = 1)::BIGINT AS lps_active_readings
FROM readings GROUP BY 1;
CREATE UNIQUE INDEX mart_hourly_hour_idx ON mart_hourly (hour_ts);
CREATE INDEX IF NOT EXISTS readings_observed_at_idx ON readings (observed_at);

CREATE MATERIALIZED VIEW mart_daily AS
SELECT hour_ts::DATE AS reading_date,
       SUM(readings)::BIGINT AS readings,
       SUM(loaded_readings)::BIGINT AS loaded_readings,
       SUM(unloaded_readings)::BIGINT AS unloaded_readings,
       SUM(idle_readings)::BIGINT AS idle_readings,
       SUM(low_pressure_loaded_readings)::BIGINT AS low_pressure_loaded_readings,
       SUM(low_pressure_loaded_readings)::NUMERIC / NULLIF(SUM(loaded_readings),0) AS low_pressure_loaded_fraction,
       SUM(panel_pressure_sum) / NULLIF(SUM(readings),0) AS avg_panel_pressure_bar,
       SUM(pressure_gap_sum) / NULLIF(SUM(readings),0) AS avg_pressure_gap_bar,
       SUM(oil_temperature_sum) / NULLIF(SUM(readings),0) AS avg_oil_temperature_c
FROM mart_hourly GROUP BY 1;
CREATE UNIQUE INDEX mart_daily_date_idx ON mart_daily (reading_date);

CREATE VIEW mart_candidate_hours AS
WITH context AS (
 SELECT h.*, SUM(low_pressure_loaded_readings) OVER prior AS prior_low_readings,
        SUM(loaded_readings) OVER prior AS prior_loaded_readings,
        COUNT(*) OVER prior AS prior_observed_hours
 FROM mart_hourly h
 WINDOW prior AS (ORDER BY hour_ts RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 hour' PRECEDING)
), rates AS (
 SELECT *, low_pressure_loaded_readings::NUMERIC / NULLIF(loaded_readings,0) AS current_low_fraction,
           prior_low_readings::NUMERIC / NULLIF(prior_loaded_readings,0) AS prior_low_fraction
 FROM context
)
SELECT *, 'pressure-v1'::TEXT AS rule_version,
 CASE WHEN loaded_readings < 30 OR COALESCE(prior_loaded_readings,0) < 300
      THEN 'INSUFFICIENT_HISTORY'
      WHEN current_low_fraction >= 0.15 AND current_low_fraction >= 2 * prior_low_fraction
      THEN 'REVIEW_PRESSURE' ELSE 'NO_CANDIDATE' END AS candidate_status
FROM rates;

CREATE VIEW mart_hourly_investigation AS
SELECT c.*, EXISTS (
 SELECT 1 FROM failure_reports f
 WHERE c.hour_ts < f.ends_at AND c.hour_ts + INTERVAL '1 hour' > f.starts_at
) AS overlaps_reported_failure
FROM mart_candidate_hours c;

-- Gaps and islands: missing hours and non-candidate hours break an incident.
-- Duration below describes qualifying hour windows, NOT confirmed downtime.
CREATE VIEW mart_incidents AS
WITH flagged AS (
 SELECT *, LAG(hour_ts) OVER (ORDER BY hour_ts) AS previous_candidate
 FROM mart_hourly_investigation WHERE candidate_status='REVIEW_PRESSURE'
), marked AS (
 SELECT *, CASE WHEN previous_candidate = hour_ts - INTERVAL '1 hour' THEN 0 ELSE 1 END AS new_group
 FROM flagged
), grouped AS (
 SELECT *, SUM(new_group) OVER (ORDER BY hour_ts ROWS UNBOUNDED PRECEDING) AS island
 FROM marked
)
SELECT 'AP-' || LEFT(MD5('pressure-v1|' || TO_CHAR(MIN(hour_ts),'YYYY-MM-DD HH24:MI:SS')),12) AS incident_id,
       MIN(hour_ts) AS starts_at, MAX(hour_ts)+INTERVAL '1 hour' AS ends_at,
       COUNT(*)::INTEGER AS candidate_hours,
       SUM(readings)::BIGINT AS readings,
       SUM(loaded_readings)::BIGINT AS loaded_readings,
       SUM(low_pressure_loaded_readings)::BIGINT AS low_pressure_loaded_readings,
       SUM(low_pressure_loaded_readings)::NUMERIC / NULLIF(SUM(loaded_readings),0) AS low_pressure_share,
       MAX(current_low_fraction) AS peak_hour_share,
       BOOL_OR(overlaps_reported_failure) AS overlaps_reported_failure,
       'pressure-v1'::TEXT AS rule_version
FROM grouped GROUP BY island;

CREATE VIEW mart_report_review AS
SELECT f.report_id, f.report_type, f.starts_at, f.ends_at,
       COUNT(c.hour_ts) FILTER (WHERE c.hour_ts + INTERVAL '1 hour' <= f.starts_at) AS candidate_hours_ending_in_prior_24h,
       COUNT(c.hour_ts) FILTER (WHERE c.hour_ts < f.ends_at AND c.hour_ts+INTERVAL '1 hour'>f.starts_at) AS candidate_hours_overlapping_report
FROM failure_reports f
LEFT JOIN mart_candidate_hours c ON c.candidate_status='REVIEW_PRESSURE'
 AND c.hour_ts+INTERVAL '1 hour'>f.starts_at-INTERVAL '24 hours' AND c.hour_ts<f.ends_at
GROUP BY f.report_id,f.report_type,f.starts_at,f.ends_at;
