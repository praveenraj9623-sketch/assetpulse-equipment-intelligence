-- Historical context: check whether the candidate rule fires near each
-- externally reported failure. Do not treat non-reported periods as healthy.
WITH candidates AS (
    SELECT hour_ts FROM mart_candidate_hours
    WHERE candidate_status = 'REVIEW_PRESSURE'
)
SELECT f.report_id, f.report_type, f.starts_at, f.ends_at,
       COUNT(c.hour_ts) FILTER (
           WHERE c.hour_ts >= f.starts_at - INTERVAL '24 hours'
             AND c.hour_ts < f.starts_at
       ) AS candidate_hours_in_prior_24h,
       COUNT(c.hour_ts) FILTER (
           WHERE c.hour_ts >= f.starts_at AND c.hour_ts < f.ends_at
       ) AS candidate_hours_during_report
FROM failure_reports f
LEFT JOIN candidates c
       ON c.hour_ts >= f.starts_at - INTERVAL '24 hours'
      AND c.hour_ts < f.ends_at
GROUP BY f.report_id, f.report_type, f.starts_at, f.ends_at
ORDER BY f.starts_at;

SELECT COUNT(*) FILTER (WHERE candidate_status = 'REVIEW_PRESSURE') AS review_candidate_hours,
       COUNT(*) FILTER (WHERE candidate_status = 'REVIEW_PRESSURE'
                              AND overlaps_reported_failure) AS candidates_overlapping_reports
FROM mart_hourly_investigation;

-- These are descriptive counts. Unmatched hours are NOT known false alarms,
-- and report overlap is NOT evidence of predictive lead time.
