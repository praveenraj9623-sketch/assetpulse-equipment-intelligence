"""SQL regression tests use isolated fixtures, never claimed as real telemetry."""
import csv
import os
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
import psycopg
from src.pipeline import run,dsn,ANALOG,DIGITAL
from src.export import run as export

@unittest.skipUnless(os.getenv('ASSET_TEST_INTEGRATION')=='1','requires isolated test database')
class IncidentWorkflowTest(unittest.TestCase):
    def fixture(self,path,extra_future=False,bad=False):
        origin=datetime(2020,4,17)
        with path.open('w',newline='') as f:
            w=csv.writer(f); w.writerow(['timestamp',*ANALOG,*DIGITAL])
            plan=[(i,False) for i in range(10)]+[(10,True),(11,True),(13,True),(14,False),(15,True)]
            if extra_future:plan += [(100,True)]
            for hour,flag in plan:
                for second in range(30):
                    w.writerow([(origin+timedelta(hours=hour,seconds=second)).isoformat(),5,6 if flag and second<15 else 8.5,5,1,8.5,45,7,*([0]*8)])
            if bad:w.writerow(['bad timestamp',*([1]*15)])
    def test_islands_baseline_and_failed_load_rollback(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'fixture.csv';self.fixture(p)
            self.assertEqual(run(p,allow_subset=True),450)
            with psycopg.connect(dsn()) as c:
                incidents=c.execute('SELECT starts_at,candidate_hours FROM mart_incidents ORDER BY starts_at').fetchall()
                self.assertEqual([r[1] for r in incidents],[2,1,1])
                rows=c.execute('SELECT hour_ts,prior_low_fraction,candidate_status FROM mart_candidate_hours ORDER BY hour_ts').fetchall()
                self.assertEqual(rows[9][2],'INSUFFICIENT_HISTORY')
                self.assertEqual(rows[10][2],'REVIEW_PRESSURE')
                self.assertEqual(float(rows[10][1]),0.0)
                columns={d.name for d in c.execute('SELECT * FROM mart_hourly_investigation LIMIT 0').description}
                self.assertTrue({'avg_panel_pressure_bar','avg_oil_temperature_c','avg_motor_current_a','avg_pressure_gap_bar'}.issubset(columns))
                ids=[r[0] for r in c.execute('SELECT incident_id FROM mart_incidents ORDER BY starts_at')]
            run(p,allow_subset=True)
            with psycopg.connect(dsn()) as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM readings').fetchone()[0],450)
                self.assertEqual(ids,[r[0] for r in c.execute('SELECT incident_id FROM mart_incidents ORDER BY starts_at')])
                state=c.execute('SELECT run_id FROM dataset_state').fetchone()[0]
            self.fixture(p,bad=True)
            with self.assertRaises(ValueError):run(p,allow_subset=True)
            with psycopg.connect(dsn()) as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM readings').fetchone()[0],450)
                self.assertEqual(c.execute('SELECT run_id FROM dataset_state').fetchone()[0],state)
            with self.assertRaisesRegex(ValueError,'complete-source'): export(Path(t)/'export')
            self.fixture(p,extra_future=True);run(p,allow_subset=True)
            with psycopg.connect(dsn()) as c:
                prior=c.execute("SELECT prior_low_fraction FROM mart_candidate_hours WHERE hour_ts='2020-04-17 10:00'").fetchone()[0]
                self.assertEqual(float(prior),0.0)

if __name__=='__main__':unittest.main()
