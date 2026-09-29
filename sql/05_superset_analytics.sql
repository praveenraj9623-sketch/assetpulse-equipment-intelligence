-- Additive BI helpers. Never reload readings or replace existing rule models.
CREATE OR REPLACE VIEW analytics_operating_states AS
SELECT h.hour_ts, state.operating_state, state.observations
FROM mart_hourly h
CROSS JOIN LATERAL (VALUES
 ('Loaded (current >= 6 A)', h.loaded_readings),
 ('Unloaded (1 <= current < 6 A)', h.unloaded_readings),
 ('Idle (current < 1 A)', h.idle_readings)
) AS state(operating_state, observations);

-- Full-source quality context intentionally does not follow dashboard time filters.
CREATE OR REPLACE VIEW analytics_data_quality AS
WITH raw AS (
 SELECT COUNT(*) AS raw_observations, MIN(observed_at) AS first_observation,
        MAX(observed_at) AS last_observation,
        COUNT(*) - COUNT(DISTINCT observed_at) AS duplicate_timestamps,
        COUNT(*) FILTER (WHERE tp3 IS NULL OR oil_temperature IS NULL
                         OR motor_current IS NULL) AS missing_core_sensor_rows
 FROM readings
), hourly AS (
 SELECT COUNT(*) AS observed_hours, COUNT(DISTINCT hour_ts::date) AS observed_dates,
        SUM(readings) AS hourly_observations,
        SUM(loaded_readings + unloaded_readings + idle_readings) AS state_observations
 FROM mart_hourly
)
SELECT raw.*, hourly.*,
 (EXTRACT(EPOCH FROM (date_trunc('hour', last_observation) - first_observation)) / 3600 + 1)::BIGINT
   - observed_hours AS unobserved_hour_windows,
 raw_observations - hourly_observations AS reconciliation_difference,
 state_observations - hourly_observations AS state_reconciliation_difference,
 s.original_rows, s.is_complete_source, s.loaded_at AS pipeline_loaded_at,
 s.source_name, s.source_sha256,
 'Historical source; timestamp timezone unspecified'::TEXT AS timestamp_context
FROM raw CROSS JOIN hourly CROSS JOIN dataset_state s;
