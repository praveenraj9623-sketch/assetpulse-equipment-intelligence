"""Smoke test the real bundled snapshot and maintenance report navigation."""
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest

class ApplicationTest(unittest.TestCase):
    def test_snapshot_and_all_report_views(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=30).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual([tab.label for tab in app.tabs], [
            'Operations overview', 'Incident investigation', 'Maintenance review',
            'Data & definitions', 'Apache Superset 3.0 Analytics',
            'Dashboard overview', 'Rule eligibility', 'Exclusion reasons',
            'Sensor context', 'Alert delivery',
        ])
        for report_id in (2, 3, 4):
            app.selectbox[0].select(report_id).run()
            self.assertEqual(len(app.exception), 0)
