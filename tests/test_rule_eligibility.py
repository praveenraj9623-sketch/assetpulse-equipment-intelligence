"""Focused PostgreSQL regressions using session-local temporary objects only.

Enable ASSET_TEST_RULE_ELIGIBILITY=1, then run the focused unittest module.
Requires the existing Compose db service; never calls ingestion or changes public data.
"""
from pathlib import Path
import json
import os
import subprocess
import shutil
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv('ASSET_TEST_RULE_ELIGIBILITY') == '1' and shutil.which('docker'), 'requires opt-in ASSET_TEST_RULE_ELIGIBILITY=1 and host Docker CLI')
class RuleEligibilityTest(unittest.TestCase):
    def query(self, values, target):
        models = (ROOT / "sql/02_models.sql").read_text()
        candidate = models.split("CREATE VIEW mart_candidate_hours AS", 1)[1].split("CREATE VIEW mart_hourly_investigation AS", 1)[0]
        eligibility = (ROOT / "sql/06_rule_eligibility.sql").read_text().replace("CREATE OR REPLACE VIEW mart_hourly_investigation", "CREATE TEMP VIEW mart_hourly_investigation")
        # Explicit temporary tables/views shadow public relations for this session.
        statement = """BEGIN;
CREATE TEMP TABLE mart_hourly AS SELECT * FROM public.mart_hourly WITH NO DATA;
CREATE TEMP TABLE failure_reports AS SELECT * FROM public.failure_reports WITH NO DATA;
INSERT INTO pg_temp.mart_hourly(hour_ts,readings,loaded_readings,low_pressure_loaded_readings) VALUES """ + values + ";\nCREATE TEMP VIEW mart_candidate_hours AS" + candidate + eligibility + f"\nSELECT row_to_json(t) FROM (SELECT * FROM pg_temp.mart_hourly_investigation WHERE hour_ts='{target}') t;\nROLLBACK;"
        result = subprocess.run(["docker", "compose", "exec", "-T", "db", "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-U", "assetpulse", "-d", "assetpulse"], input=statement, text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_current_only_is_not_missing_baseline(self):
        r = self.query("('2020-01-01',300,300,0),('2020-01-02',360,29,0)", "2020-01-02")
        self.assertEqual(r['exclusion_reason'], 'Current only: loaded observations <30')
        self.assertEqual(r['evaluation_status'], 'Not evaluated')

    def test_baseline_only_and_current_not_included(self):
        r = self.query("('2020-01-01',299,299,0),('2020-01-02',360,30,0)", "2020-01-02")
        self.assertEqual(r['prior_loaded_readings'], 299)
        self.assertEqual(r['exclusion_reason'], 'Baseline only: prior loaded observations <300')
        self.assertFalse(r['rule_eligible'])

    def test_both_and_null_rates_are_not_no_breach(self):
        r = self.query("('2020-01-01',360,0,0)", "2020-01-01")
        self.assertIsNone(r['prior_loaded_readings'])
        self.assertIsNone(r['prior_low_fraction'])
        self.assertIsNone(r['current_low_fraction'])
        self.assertEqual(r['exclusion_reason'], 'Both: current <30 and prior <300')
        self.assertEqual(r['evaluation_status'], 'Not evaluated')

    def test_inclusive_minima_and_valid_zero_baseline(self):
        r = self.query("('2020-01-01',300,300,0),('2020-01-02',360,30,0)", "2020-01-02")
        self.assertTrue(r['rule_eligible'])
        self.assertEqual(r['prior_low_fraction'], 0)
        self.assertEqual(r['evaluation_status'], 'Evaluated: no breach')

    def test_exact_seven_day_boundary_gaps_and_future_exclusion(self):
        r = self.query("('2019-12-31 23:00',300,300,300),('2020-01-01',300,300,0),('2020-01-08',360,40,6),('2020-01-09',300,300,300)", "2020-01-08")
        self.assertEqual(r['prior_loaded_readings'], 300)
        self.assertEqual(r['prior_low_readings'], 0)
        self.assertEqual(r['prior_observed_hours'], 1)
        self.assertEqual(r['evaluation_status'], 'Evaluated: breach')

    def test_calendar_window_not_previous_168_rows(self):
        r = self.query("('2020-01-01',300,300,0),('2020-01-09',360,40,6)", "2020-01-09")
        self.assertIsNone(r['prior_loaded_readings'])
        self.assertEqual(r['evaluation_status'], 'Not evaluated')

    def test_both_breach_thresholds_required(self):
        r = self.query("('2020-01-01',300,300,30),('2020-01-02',360,40,6)", "2020-01-02")
        self.assertTrue(r['rule_eligible'])
        self.assertEqual(r['evaluation_status'], 'Evaluated: no breach')

    def test_missing_rate_defensive_exclusion(self):
        r = self.query("('2020-01-01',300,300,NULL),('2020-01-02',360,40,6)", "2020-01-02")
        self.assertFalse(r['rule_eligible'])
        self.assertEqual(r['exclusion_reason'], 'Missing rate despite sufficient counts')
        self.assertEqual(r['evaluation_status'], 'Not evaluated')


if __name__ == '__main__':
    unittest.main()
