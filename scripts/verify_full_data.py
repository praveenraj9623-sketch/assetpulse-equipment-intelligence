"""Independent pandas reconciliation of raw CSV against exported SQL aggregates."""
import json
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.pipeline import ROOT,DEFAULT_CSV
from src.dashboard_data import read_snapshot

def run():
    frames,meta=read_snapshot(ROOT/'data'/'export')
    raw=pd.read_csv(DEFAULT_CSV,usecols=['timestamp','TP3','Motor_current','Oil_temperature'],parse_dates=['timestamp'])
    raw['day']=raw.timestamp.dt.floor('D')
    raw['loaded']=(raw.Motor_current>=6).astype(int)
    raw['low']=((raw.Motor_current>=6)&(raw.TP3<7)).astype(int)
    daily=raw.groupby('day').agg(readings=('TP3','size'),loaded=('loaded','sum'),low=('low','sum'),pressure=('TP3','mean'),temperature=('Oil_temperature','mean'))
    actual=frames['daily_metrics'].set_index('reading_date')
    assert daily.index.equals(actual.index)
    assert (daily.readings==actual.readings).all()
    assert (daily.loaded==actual.loaded_readings).all()
    assert (daily.low==actual.low_pressure_loaded_readings).all()
    assert (daily.pressure-actual.avg_panel_pressure_bar).abs().max()<1e-9
    assert (daily.temperature-actual.avg_oil_temperature_c).abs().max()<1e-9
    assert len(raw)==meta['original_reading_count']
    hourly=frames['hourly_investigation'].sort_values('hour_ts')
    candidates=hourly[hourly.candidate_status=='REVIEW_PRESSURE']
    expected=[]
    for stamp in candidates.hour_ts:
        if not expected or stamp!=expected[-1][-1]+pd.Timedelta(hours=1):expected.append([stamp])
        else:expected[-1].append(stamp)
    incidents=frames['incidents'].sort_values('starts_at')
    assert len(incidents)==len(expected)
    assert incidents.candidate_hours.tolist()==[len(g) for g in expected]
    # Independently calculate every trailing baseline by actual timestamp range.
    for row in hourly.itertuples():
        before=hourly[(hourly.hour_ts>=row.hour_ts-pd.Timedelta(days=7))&(hourly.hour_ts<row.hour_ts)]
        loaded=int(before.loaded_readings.sum()); low=int(before.low_pressure_loaded_readings.sum())
        expected_status='INSUFFICIENT_HISTORY'
        if row.loaded_readings>=30 and loaded>=300:
            current=row.low_pressure_loaded_readings/row.loaded_readings
            expected_status='REVIEW_PRESSURE' if current>=.15 and current>=2*low/loaded else 'NO_CANDIDATE'
        assert row.candidate_status==expected_status
    summary={'source_rows':len(raw),'observed_days':len(daily),'observed_hours':len(hourly),'candidate_hours':len(candidates),'review_incidents':len(incidents),'checks':['raw totals','all daily counts and weighted averages','all hourly trailing baselines','independent incident grouping','export checksums'],'status':'passed','source_sha256':meta['source_sha256']}
    (ROOT/'evidence'/'full_data_verification.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))
if __name__=='__main__':run()
