-- The CSV row order is retained with a 1-based source_row identifier.
-- Timestamps are naive because UCI does not specify a time zone for this CSV.
CREATE TABLE IF NOT EXISTS readings (
    source_row BIGINT PRIMARY KEY,
    observed_at TIMESTAMP NOT NULL,
    tp2 DOUBLE PRECISION NOT NULL,
    tp3 DOUBLE PRECISION NOT NULL,
    h1 DOUBLE PRECISION NOT NULL,
    dv_pressure DOUBLE PRECISION NOT NULL,
    reservoirs DOUBLE PRECISION NOT NULL,
    oil_temperature DOUBLE PRECISION NOT NULL,
    motor_current DOUBLE PRECISION NOT NULL,
    comp SMALLINT NOT NULL CHECK (comp IN (0, 1)),
    dv_electric SMALLINT NOT NULL CHECK (dv_electric IN (0, 1)),
    towers SMALLINT NOT NULL CHECK (towers IN (0, 1)),
    mpg SMALLINT NOT NULL CHECK (mpg IN (0, 1)),
    lps SMALLINT NOT NULL CHECK (lps IN (0, 1)),
    pressure_switch SMALLINT NOT NULL CHECK (pressure_switch IN (0, 1)),
    oil_level SMALLINT NOT NULL CHECK (oil_level IN (0, 1)),
    caudal_impulse DOUBLE PRECISION NOT NULL CHECK (caudal_impulse >= 0)
);

CREATE TABLE IF NOT EXISTS failure_reports (
    report_id INTEGER PRIMARY KEY,
    starts_at TIMESTAMP NOT NULL,
    ends_at TIMESTAMP NOT NULL,
    report_type TEXT NOT NULL,
    CHECK (ends_at > starts_at)
);

-- UCI's public maintenance intervals are context overlays, never model inputs.
INSERT INTO failure_reports (report_id, starts_at, ends_at, report_type) VALUES
    (1, '2020-04-18 00:00', '2020-04-18 23:59', 'Reported air leak'),
    (2, '2020-05-29 23:30', '2020-05-30 06:00', 'Reported air leak'),
    (3, '2020-06-05 10:00', '2020-06-07 14:30', 'Reported air leak'),
    (4, '2020-07-15 14:30', '2020-07-15 19:00', 'Reported air leak')
ON CONFLICT (report_id) DO UPDATE SET
    starts_at = EXCLUDED.starts_at,
    ends_at = EXCLUDED.ends_at,
    report_type = EXCLUDED.report_type;

-- Replaced inside the same transaction as a successful full rebuild.
CREATE TABLE IF NOT EXISTS dataset_state (
 singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
 run_id TEXT NOT NULL,
 source_sha256 TEXT NOT NULL,
 original_rows BIGINT NOT NULL,
 loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 source_name TEXT NOT NULL,
 is_complete_source BOOLEAN NOT NULL
);
