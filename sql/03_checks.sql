-- Expected full source count is 1,516,948, per UCI's record. Running with a
-- deliberately limited source is supported for local validation only.
SELECT (SELECT COUNT(*) FROM readings) AS source_rows,
       (SELECT COUNT(*) FROM mart_hourly) AS hourly_rows,
       (SELECT COUNT(*) FROM mart_daily) AS daily_rows,
       (SELECT COUNT(*) FROM failure_reports) AS public_report_windows;

-- An observation row belongs to exactly one hour. All rows must survive.
SELECT (SELECT COUNT(*) FROM readings)
       - (SELECT COALESCE(SUM(readings), 0) FROM mart_hourly) AS lost_rows;

-- Duplicated timestamps can be legitimate; inspect them, do not delete them.
SELECT COUNT(*) - COUNT(DISTINCT observed_at) AS duplicate_timestamp_count,
       MIN(observed_at) AS first_reading, MAX(observed_at) AS last_reading
FROM readings;

EXPLAIN (ANALYZE, BUFFERS)
SELECT hour_ts, avg_panel_pressure_bar, avg_oil_temperature_c
FROM mart_hourly
WHERE hour_ts >= '2020-04-01' AND hour_ts < '2020-05-01'
ORDER BY hour_ts;
