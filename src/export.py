"""Export a consistent SQL snapshot. Publish CURRENT only after checksums exist."""
import hashlib
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import psycopg
try:
    from .pipeline import ROOT, dsn
except ImportError:
    from pipeline import ROOT, dsn

EXPORTS = {
 'hourly_investigation.csv': ('mart_hourly_investigation','hour_ts'),
 'daily_metrics.csv': ('mart_daily','reading_date'),
 'failure_reports.csv': ('failure_reports','report_id'),
 'incidents.csv': ('mart_incidents','starts_at'),
 'report_review.csv': ('mart_report_review','report_id'),
}

def run(destination=None):
    destination = Path(destination or ROOT/'data'/'export')
    snapshots=destination/'snapshots'
    snapshots.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=snapshots,prefix='.staging-') as temporary:
        staging=Path(temporary)
        with psycopg.connect(dsn()) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            state=conn.execute('SELECT run_id,source_sha256,original_rows,loaded_at,is_complete_source FROM dataset_state WHERE singleton').fetchone()
            if not state or not state[4]:
                raise ValueError('Public export requires a complete-source load; test fixtures cannot be published.')
            run_id,sha,reading_count,loaded_at,_=state
            counts=conn.execute('SELECT (SELECT COUNT(*) FROM readings),(SELECT SUM(readings) FROM mart_daily),(SELECT SUM(readings) FROM mart_hourly)').fetchone()
            if any(int(x or 0)!=reading_count for x in counts):
                raise ValueError('Raw, hourly, daily and provenance row totals must reconcile.')
            files={}
            for filename,(view,order) in EXPORTS.items():
                if os.getenv('ASSET_INSERT_MODE')=='1':
                    cursor=conn.execute(f'SELECT * FROM {view} ORDER BY {order}')
                    with (staging/filename).open('w',newline='',encoding='utf-8') as output:
                        writer=csv.writer(output)
                        writer.writerow([c.name for c in cursor.description])
                        while rows:=cursor.fetchmany(2000): writer.writerows(rows)
                else:
                    with (staging/filename).open('wb') as output,conn.cursor().copy(f'COPY (SELECT * FROM {view} ORDER BY {order}) TO STDOUT WITH (FORMAT CSV,HEADER TRUE)') as copy:
                        for block in copy: output.write(block)
                files[filename]=hashlib.sha256((staging/filename).read_bytes()).hexdigest()
            bounds=conn.execute('SELECT MIN(observed_at),MAX(observed_at),COUNT(*)-COUNT(DISTINCT observed_at) FROM readings').fetchone()
            db_version=conn.execute('SELECT version()').fetchone()[0]
        provenance={
          'schema_version':2,'run_id':run_id,'source':'UCI MetroPT-3',
          'source_url':'https://archive.ics.uci.edu/dataset/791/metropt+3+dataset',
          'doi':'10.24432/C5VW3R','license':'CC BY 4.0','source_sha256':sha,
          'original_reading_count':reading_count,'loaded_at':loaded_at.isoformat(),
          'exported_at':datetime.now(timezone.utc).isoformat(),
          'first_reading':bounds[0].isoformat(),'last_reading':bounds[1].isoformat(),
          'duplicate_timestamps':bounds[2],'database_version':db_version,
          'timestamp_policy':'Original naive timestamps; source timezone unspecified.',
          'kind':'Historical observations; SQL-derived aggregates',
          'rule':{'version':'pressure-v1','loaded_current_a':6,'low_pressure_bar':7,
                  'minimum_loaded_readings':30,'minimum_prior_loaded_readings':300,
                  'minimum_hour_share':0.15,'relative_to_prior':2,'prior_days':7},
          'files':files,
        }
        (staging/'provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
        # A new export id avoids replacing a snapshot readers may have open.
        snapshot_id=run_id+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        final=snapshots/snapshot_id
        os.replace(staging,final)
        pointer=destination/'.CURRENT.tmp'
        pointer.write_text(snapshot_id,encoding='utf-8')
        os.replace(pointer,destination/'CURRENT')
    print(f'Exported verified snapshot {snapshot_id} ({reading_count:,} source rows)')
    return final

if __name__=='__main__': run()
