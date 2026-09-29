"""Data contract shared by the Streamlit display and its regression tests."""
import hashlib
import json
from pathlib import Path
import pandas as pd

BOOL_COLUMNS=('overlaps_reported_failure',)

def read_snapshot(root):
    root=Path(root)
    snapshot_id=(root/'CURRENT').read_text(encoding='utf-8').strip()
    if not snapshot_id or Path(snapshot_id).name!=snapshot_id:
        raise ValueError('Invalid snapshot pointer')
    folder=root/'snapshots'/snapshot_id
    meta=json.loads((folder/'provenance.json').read_text())
    frames={}
    for name,digest in meta['files'].items():
        if Path(name).name!=name: raise ValueError('Invalid export filename')
        body=(folder/name).read_bytes()
        if hashlib.sha256(body).hexdigest()!=digest: raise ValueError(f'Export checksum mismatch: {name}')
        df=pd.read_csv(folder/name)
        for c in ['hour_ts','reading_date','starts_at','ends_at']:
            if c in df: df[c]=pd.to_datetime(df[c])
        for c in BOOL_COLUMNS:
            if c in df: df[c]=df[c].astype(str).str.lower().isin(['t','true','1'])
        frames[name.removesuffix('.csv')]=df
    if int(frames['daily_metrics'].readings.sum())!=meta['original_reading_count']:
        raise ValueError('Daily totals do not match source row count')
    if int(frames['hourly_investigation'].readings.sum())!=meta['original_reading_count']:
        raise ValueError('Hourly totals do not match source row count')
    return frames,meta

def filter_period(frames,start,end):
    lo=pd.Timestamp(start); hi=pd.Timestamp(end)+pd.Timedelta(days=1)
    hourly=frames['hourly_investigation']
    daily=frames['daily_metrics']
    incidents=frames['incidents']
    reports=frames['failure_reports']
    return {
      'hourly':hourly[(hourly.hour_ts>=lo)&(hourly.hour_ts<hi)].copy(),
      'daily':daily[(daily.reading_date>=lo)&(daily.reading_date<hi)].copy(),
      'incidents':incidents[(incidents.starts_at<hi)&(incidents.ends_at>lo)].copy(),
      'reports':reports[(reports.starts_at<hi)&(reports.ends_at>lo)].copy(),
    }

def metrics(selection):
    d=selection['daily']; h=selection['hourly']
    loaded=int(d.loaded_readings.sum()); low=int(d.low_pressure_loaded_readings.sum())
    return {'readings':int(d.readings.sum()),'loaded_readings':loaded,
      'low_pressure_share':low/loaded if loaded else None,
      'candidate_hours':int((h.candidate_status=='REVIEW_PRESSURE').sum()),
      'incidents':len(selection['incidents']),'reports':len(selection['reports'])}
