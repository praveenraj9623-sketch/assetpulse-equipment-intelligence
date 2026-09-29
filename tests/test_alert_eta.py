"""Focused regression for Superset 3.0 scheduled ETA / SQLite compatibility."""
import ast
from datetime import datetime
from pathlib import Path
import unittest

source=Path(__file__).resolve().parents[1]/'infra/alerts/superset_config.py'
tree=ast.parse(source.read_text())
function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='normalize_scheduled_time')
namespace={}
exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),namespace)
normalize=namespace['normalize_scheduled_time']

class ScheduledEtaTest(unittest.TestCase):
    def test_celery_iso_eta(self):
        self.assertEqual(normalize('2026-09-29T02:17:00+00:00'),datetime(2026,9,29,2,17))
    def test_offset_is_converted_to_utc(self):
        self.assertEqual(normalize('2026-09-29T07:47:00+05:30'),datetime(2026,9,29,2,17))
    def test_native_datetime_preserved(self):
        value=datetime(2026,9,29,2,17)
        self.assertEqual(normalize(value),value)
    def test_invalid_timestamp_fails(self):
        with self.assertRaises(ValueError): normalize('invalid')
