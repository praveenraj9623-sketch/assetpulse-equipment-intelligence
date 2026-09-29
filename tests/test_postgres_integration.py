"""Run against an isolated PostgreSQL CI service when explicitly enabled."""

import csv
import os
import tempfile
import unittest
from pathlib import Path

import psycopg

from src.pipeline import ANALOG, DIGITAL, dsn, run


@unittest.skipUnless(
    os.getenv("ASSET_TEST_INTEGRATION") == "1", "requires dedicated CI Postgres"
)
class PostgresIntegrationTest(unittest.TestCase):
    def test_transactional_load_hour_reconciliation_and_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.csv"
            with path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(
                    [
                        "timestamp",
                        *ANALOG,
                        "COMP",
                        "DV_eletric",
                        "Towers",
                        "MPG",
                        "LPS",
                        "Pressure_switch",
                        "Oil_level",
                        "Caudal_impulses",
                    ]
                )
                for stamp, panel in [
                    ("2020-04-18 00:01:00", "6.2"),
                    ("2020-04-18 00:02:00", "8.0"),
                    ("2020-04-18 01:01:00", "6.0"),
                ]:
                    writer.writerow(
                        [
                            stamp,
                            "5",
                            panel,
                            "5",
                            "1",
                            "7.5",
                            "45",
                            "7",
                            *(["0.0"] * len(DIGITAL)),
                        ]
                    )
            self.assertEqual(run(path, allow_subset=True), 3)
            with psycopg.connect(dsn()) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT (SELECT COUNT(*) FROM readings), "
                    "(SELECT SUM(readings) FROM mart_hourly), "
                    "(SELECT COUNT(*) FROM failure_reports), "
                    "(SELECT COUNT(*) FROM mart_candidate_hours "
                    " WHERE candidate_status = 'REVIEW_PRESSURE')"
                )
                self.assertEqual(cur.fetchone(), (3, 3, 4, 0))
                cur.execute(
                    "SELECT overlaps_reported_failure FROM mart_hourly_investigation "
                    "WHERE hour_ts = '2020-04-18 00:00:00'"
                )
                self.assertTrue(cur.fetchone()[0])
            self.assertEqual(run(path, allow_subset=True), 3)
            with psycopg.connect(dsn()) as conn:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 3
                )


if __name__ == "__main__":
    unittest.main()
