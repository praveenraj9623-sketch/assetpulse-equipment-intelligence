"""Stream original UCI readings into PostgreSQL; build reproducible SQL marts."""

import argparse
import csv
import hashlib
import math
import os
import re
import uuid
from itertools import islice
from datetime import datetime
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "data" / "raw" / "MetroPT3(AirCompressor).csv"
EXPECTED_FULL_ROWS = 1_516_948
ANALOG = (
    "tp2",
    "tp3",
    "h1",
    "dv_pressure",
    "reservoirs",
    "oil_temperature",
    "motor_current",
)
DIGITAL = (
    "comp",
    "dv_electric",
    "towers",
    "mpg",
    "lps",
    "pressure_switch",
    "oil_level",
    "caudal_impulse",
)
FIELDS = ("timestamp", *ANALOG, *DIGITAL)
DB_COLUMNS = ("source_row", "observed_at", *ANALOG, *DIGITAL)


def dsn():
    if os.getenv('ASSET_DATABASE_URL'):
        return os.environ['ASSET_DATABASE_URL']
    return psycopg.conninfo.make_conninfo(
        host=os.getenv('ASSET_DB_HOST', 'localhost'),
        port=os.getenv('ASSET_DB_PORT', '5434'),
        dbname=os.getenv('ASSET_DB_NAME', 'assetpulse'),
        user=os.getenv('ASSET_DB_USER', 'assetpulse'),
        password=os.getenv('ASSET_DB_PASSWORD', 'assetpulse_local_dev'),
        connect_timeout=15,
    )


def canonical_header(header):
    normalized = re.sub(r"[^a-z0-9]", "", header.strip().lower().lstrip("\ufeff"))
    if normalized in ("dveletric", "dvelectric"):
        return "dv_electric"
    if normalized == "caudalimpulses":
        return "caudal_impulse"
    return {re.sub(r"[^a-z0-9]", "", name): name for name in FIELDS}.get(normalized)


def csv_positions(headers):
    positions = {}
    for pos, header in enumerate(headers):
        name = canonical_header(header)
        if name in FIELDS:
            if name in positions:
                raise ValueError(f"Duplicate CSV column: {name}")
            positions[name] = pos
    missing = set(FIELDS) - positions.keys()
    if missing:
        raise ValueError(
            f"UCI CSV is missing required columns: {sorted(missing)}. Found {headers}"
        )
    return positions


def parse_record(values, positions, row_number):
    try:
        stamp = datetime.fromisoformat(values[positions["timestamp"]].strip())
        if stamp.tzinfo is not None:
            raise ValueError("Unexpected timezone in UCI timestamp")
        analog = tuple(float(values[positions[name]]) for name in ANALOG)
        if not all(math.isfinite(value) for value in analog):
            raise ValueError("Non-finite analog reading")
        # The UCI CSV commonly stores digital signals as strings such as "0.0".
        digital = tuple(float(values[positions[name]]) for name in DIGITAL[:-1])
        impulse = float(values[positions["caudal_impulse"]])
        if any(value not in (0, 1) for value in digital):
            raise ValueError("Digital reading outside 0 or 1")
        if not math.isfinite(impulse) or impulse < 0:
            raise ValueError("Invalid nonnegative caudal pulse reading")
        return (row_number, stamp, *analog, *(int(value) for value in digital), impulse)
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Invalid UCI CSV row {row_number}: {exc}") from exc


def parse_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        headers = next(reader, None)
        if headers is None:
            raise ValueError('CSV is empty')
        positions = csv_positions(headers)
        for number, values in enumerate(reader, start=1):
            if not values or all(not value.strip() for value in values):
                raise ValueError(f'Blank CSV row {number}')
            yield parse_record(values, positions, number)


def run(path=DEFAULT_CSV, allow_subset=False):
    if not Path(path).is_file():
        raise FileNotFoundError(
            f"Place the official UCI CSV here, or run python src/download.py: {path}"
        )
    columns = ", ".join(DB_COLUMNS)
    with Path(path).open('rb') as source:
        source_sha256 = hashlib.file_digest(source, 'sha256').hexdigest()
    run_id = str(uuid.uuid4())
    with psycopg.connect(dsn()) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(20260927)")
        cursor.execute((ROOT / "sql" / "01_schema.sql").read_text(encoding="utf-8"))
        cursor.execute("TRUNCATE TABLE readings")
        count = 0
        if os.getenv('ASSET_INSERT_MODE') == '1':
            # Compatibility mode for embedded PostgreSQL engines whose wire
            # server lacks COPY support. Production PostgreSQL uses COPY below.
            records=iter(parse_csv(Path(path)))
            while batch:=list(islice(records,500)):
                placeholders=','.join(['('+','.join(['%s']*len(DB_COLUMNS))+')']*len(batch))
                cursor.execute(f'INSERT INTO readings ({columns}) VALUES {placeholders}',
                               [v for row in batch for v in row],prepare=False)
                count+=len(batch)
                if count%250_000==0: print(f'Loaded {count:,} readings ...',flush=True)
        else:
            with cursor.copy(f"COPY readings ({columns}) FROM STDIN") as copy:
                for row in parse_csv(Path(path)):
                    copy.write_row(row)
                    count += 1
                    if count % 250_000 == 0:
                        print(f"Loaded {count:,} original sensor readings ...", flush=True)
        if not count or (not allow_subset and count != EXPECTED_FULL_ROWS):
            raise ValueError(
                f"Imported {count:,} rows; expected {EXPECTED_FULL_ROWS:,}. "
                "Rerun with the complete official CSV. For test fixtures, use --allow-subset."
            )
        cursor.execute((ROOT / "sql" / "02_models.sql").read_text(encoding="utf-8"))
        cursor.execute((ROOT / "sql" / "06_rule_eligibility.sql").read_text(encoding="utf-8"))
        cursor.execute("SELECT COALESCE(SUM(readings), 0) FROM mart_hourly")
        aggregated = cursor.fetchone()[0]
        if aggregated != count:
            raise ValueError(
                f"Hour aggregation lost rows: source={count}, hourly={aggregated}"
            )
        cursor.execute("SELECT COUNT(*) FROM mart_hourly")
        hours = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO dataset_state(singleton,run_id,source_sha256,original_rows,source_name,is_complete_source) "
            "VALUES(TRUE,%s,%s,%s,%s,%s) ON CONFLICT(singleton) DO UPDATE SET "
            "run_id=EXCLUDED.run_id,source_sha256=EXCLUDED.source_sha256,original_rows=EXCLUDED.original_rows,"
            "loaded_at=CURRENT_TIMESTAMP,source_name=EXCLUDED.source_name,is_complete_source=EXCLUDED.is_complete_source",
            (run_id,source_sha256,count,Path(path).name,not allow_subset),
        )
        cursor.execute('ANALYZE readings; ANALYZE mart_hourly; ANALYZE mart_daily')
    print(f"Committed {count:,} original rows, {hours:,} hourly groups. Run {run_id}",flush=True)
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument(
        "--allow-subset", action="store_true", help="For integration tests only"
    )
    args = parser.parse_args()
    run(args.csv, allow_subset=args.allow_subset)
