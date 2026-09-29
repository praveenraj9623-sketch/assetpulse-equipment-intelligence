"""Verify the real CSV's unusual headers and fail-closed ingestion behavior."""

import csv
import tempfile
import unittest
from pathlib import Path

from src.pipeline import ANALOG, DIGITAL, csv_positions, parse_csv, parse_record


class UciIngestionTest(unittest.TestCase):
    def setUp(self):
        self.headers = [
            "Unnamed: 0",
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
        self.record = [
            "0",
            "2020-04-18 00:00:01",
            *(["7.1"] * len(ANALOG)),
            *(["0.0"] * len(DIGITAL)),
        ]

    def test_original_header_spellings_and_float_encoded_digital_signals(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "MetroPT3(AirCompressor).csv"
            with path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(self.headers)
                writer.writerow(self.record)
            rows = list(parse_csv(path))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 1)
        self.assertEqual(rows[0][-1], 0.0)
        self.assertEqual(rows[0][3], 7.1)

    def test_missing_or_duplicate_signal_aborts_before_database_load(self):
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            csv_positions(self.headers[:-1])
        with self.assertRaisesRegex(ValueError, "Duplicate CSV column"):
            csv_positions([*self.headers, "TP2"])

    def test_invalid_digital_and_nonfinite_values_fail_with_row_number(self):
        mapping = csv_positions(self.headers)
        invalid_digital = self.record.copy()
        invalid_digital[-len(DIGITAL)] = "2.0"
        with self.assertRaisesRegex(ValueError, "row 52"):
            parse_record(invalid_digital, mapping, 52)
        invalid_analog = self.record.copy()
        invalid_analog[2] = "inf"
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            parse_record(invalid_analog, mapping, 53)


if __name__ == "__main__":
    unittest.main()
