"""AssetPulse · Historical compressor investigation, backed by checked SQL exports."""
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from src.dashboard_data import read_snapshot,filter_period,metrics

ROOT=Path(__file__).resolve().parent
st.set_page_config(page_title='AssetPulse | Equipment intelligence',page_icon='◉',layout='wide')
st.markdown('''<style>
.block-container{padding-top:2rem;max-width:1440px} h1{letter-spacing:-1.5px}
[data-testid="stMetric"]{background:#f3f6f8;border:1px solid #e0e7ed;border-radius:12px;padding:18px}
[data-testid="stMetricLabel"]{color:#51627a} [data-testid="stMetricValue"]{color:#152a42}
.stTabs [data-baseweb="tab-list"]{gap:24px}.stTabs [data-baseweb="tab"]{font-weight:600}
</style>''',unsafe_allow_html=True)

@st.cache_data
def load(snapshot_id):
    return read_snapshot(ROOT/'data'/'export')

st.title('AssetPulse')
st.caption('EQUIPMENT INTELLIGENCE  /  COMPRESSOR OPERATIONS')
try:
    pointer=(ROOT/'data'/'export'/'CURRENT').read_text().strip()
    frames,meta=load(pointer)
except (OSError,ValueError,KeyError,pd.errors.ParserError) as exc:
    st.error(f'A verified data snapshot is required: {exc}')
    st.code('python -m src.download\npython -m src.pipeline\npython -m src.export')
    st.stop()

all_days=frames['daily_metrics']
first=all_days.reading_date.min().date(); last=all_days.reading_date.max().date()
st.sidebar.title('Investigation scope')
period=st.sidebar.date_input('Recorded period',(first,last),min_value=first,max_value=last)
if len(period)!=2:
    st.info('Choose a start and end date.');st.stop()
lo,hi=period
selection=filter_period(frames,lo,hi)
kpi=metrics(selection)
days=selection['daily'];hours=selection['hourly'];incidents=selection['incidents'];reports=selection['reports']
st.sidebar.caption('Source timestamps are preserved. Their timezone is unspecified.')
st.sidebar.divider()
st.sidebar.markdown('**MetroPT-3**  \nHistorical railway compressor telemetry  \n1 source dataset · 15 signals')
st.sidebar.markdown('[Dataset and attribution](https://archive.ics.uci.edu/dataset/791/metropt+3+dataset)')
st.sidebar.caption(f"Snapshot exported {meta['exported_at'][:10]}. This is historical analysis, not a live plant feed.")
if days.empty:
    st.warning('No observations exist in this period. Choose a different range.');st.stop()

st.markdown('Investigate sustained low pressure under load, with sensor context and traceable review rules.')
cols=st.columns(4)
cols[0].metric('Recorded observations',f"{kpi['readings']:,}")
cols[1].metric('Low pressure under load',f"{kpi['low_pressure_share']:.1%}" if kpi['low_pressure_share'] is not None else '—')
cols[2].metric('Review incidents',f"{kpi['incidents']:,}")
cols[3].metric('Candidate hours',f"{kpi['candidate_hours']:,}")
st.caption('Low-pressure share = readings below 7 bar ÷ readings with current ≥6 A. Consecutive candidate hours form one review incident; neither measure is confirmed downtime.')

THEME=dict(template='plotly_white',font=dict(family='Arial',color='#233952'),margin=dict(l=10,r=15,t=40,b=20),height=320,legend=dict(orientation='h',y=-.18),hovermode='x unified')
def line(data,x,series,title,unit=None,pct=False,overlays=False):
    fig=go.Figure()
    for name,label,color in series:
        fig.add_trace(go.Scatter(x=data[x],y=data[name],name=label,mode='lines',line=dict(color=color,width=2),connectgaps=False))
    fig.update_layout(**THEME,title=dict(text=title,font=dict(size=16)))
    if unit:fig.update_yaxes(title=unit)
    if pct:fig.update_yaxes(tickformat='.0%')
    if overlays:
        for _,r in reports.iterrows():
            fig.add_vrect(x0=max(r.starts_at,pd.Timestamp(lo)),x1=min(r.ends_at,pd.Timestamp(hi)+pd.Timedelta(days=1)),fillcolor='#f59e0b',opacity=.13,line_width=0)
    return fig

overview,investigate,maintenance,quality=st.tabs(['Operations overview','Incident investigation','Maintenance review','Data & definitions'])
with overview:
    # Explicit gaps prevent interpolation across missing calendar days.
    continuous=days.set_index('reading_date').reindex(pd.date_range(lo,hi,freq='D')).rename_axis('reading_date').reset_index()
    a,b=st.columns([1.55,1])
    with a:
        st.plotly_chart(line(continuous,'reading_date',[('low_pressure_loaded_fraction','Low-pressure share','#0d9488')],'Low pressure while loaded',pct=True,overlays=True),width='stretch')
        st.caption(f'Amber shading: {len(reports)} published failure interval(s) intersect this view. Reports are context, not inputs to the rule.')
    with b:
        st.plotly_chart(line(continuous,'reading_date',[('avg_panel_pressure_bar','Panel pressure','#315ea8'),('avg_pressure_gap_bar','Panel–reservoir gap','#0d9488')],'Pressure context',unit='bar'),width='stretch')
    c,d=st.columns([1.55,1])
    with c:
        st.plotly_chart(line(continuous,'reading_date',[('avg_oil_temperature_c','Oil temperature','#d97706')],'Oil temperature',unit='°C'),width='stretch')
    with d:
        states=['Idle proxy','Unloaded proxy','Loaded proxy']
        counts=[int(days.idle_readings.sum()),int(days.unloaded_readings.sum()),int(days.loaded_readings.sum())]
        fig=go.Figure(go.Bar(x=states,y=counts,marker_color=['#b6c6d6','#6689ac','#0d9488']))
        fig.update_layout(**THEME,title=dict(text='Observations by current-based state',font=dict(size=16)))
        st.plotly_chart(fig,width='stretch')
        st.caption('Current-based proxies: <1 A, 1–<6 A, ≥6 A. Counts represent observations, not elapsed operating time.')
    st.download_button('Download selected hourly evidence',hours.to_csv(index=False).encode(),file_name=f'assetpulse-hours-{lo}-{hi}.csv',mime='text/csv')

with investigate:
    st.subheader('Review queue')
    st.caption('Incidents intersecting the selected dates are shown with their full boundaries. Sensor context may extend before the selected dates to explain the baseline.')
    if incidents.empty:
        st.info('No incident satisfies pressure-v1 in this period. No substitute or simulated incidents are shown.')
    else:
        queue=incidents.sort_values('starts_at',ascending=False)
        st.dataframe(queue[['incident_id','starts_at','ends_at','candidate_hours','low_pressure_share','overlaps_reported_failure']],hide_index=True,width='stretch',column_config={'low_pressure_share':st.column_config.NumberColumn('Loaded low-pressure share',format='percent'),'overlaps_reported_failure':'Overlaps published report'})
        chosen=st.selectbox('Inspect incident',queue.incident_id.tolist())
        incident=queue.loc[queue.incident_id==chosen].iloc[0]
        full=frames['hourly_investigation']
        scope=full[(full.hour_ts>=incident.starts_at-pd.Timedelta(days=7))&(full.hour_ts<incident.ends_at)].copy()
        scope=scope.set_index('hour_ts').reindex(pd.date_range(incident.starts_at-pd.Timedelta(days=7),incident.ends_at-pd.Timedelta(hours=1),freq='h')).rename_axis('hour_ts').reset_index()
        fig=line(scope,'hour_ts',[('current_low_fraction','Observed hourly share','#0d9488'),('prior_low_fraction','Earlier seven-day share','#7c86a3')],'Evidence leading into the incident',pct=True)
        fig.add_vrect(x0=incident.starts_at,x1=incident.ends_at,fillcolor='#f59e0b',opacity=.15,line_width=0)
        st.plotly_chart(fig,width='stretch')
        a,b=st.columns(2)
        with a:st.plotly_chart(line(scope,'hour_ts',[('avg_panel_pressure_bar','Panel pressure','#315ea8')],'Panel pressure',unit='bar'),width='stretch')
        with b:st.plotly_chart(line(scope,'hour_ts',[('avg_oil_temperature_c','Oil temperature','#d97706')],'Oil temperature',unit='°C'),width='stretch')
        st.markdown(f'**Evidence:** {int(incident.candidate_hours)} qualifying hourly window(s), {int(incident.loaded_readings):,} loaded readings, {incident.low_pressure_share:.1%} below 7 bar. **Rule:** {incident.rule_version}.')
        st.caption('Investigate equipment context before acting. Sparse published reports cannot establish precision, recall, or whether unmatched periods were healthy.')
        st.download_button('Download this incident evidence',scope.dropna(subset=['readings']).to_csv(index=False).encode(),file_name=f'{chosen}.csv',mime='text/csv')
    with st.expander('Exact review rule'):
        st.markdown('An hour needs **≥30 loaded readings**, **≥300 loaded readings in the earlier seven days**, a low-pressure share **≥15%**, and a share **≥2× the earlier baseline**. The current hour is excluded from its baseline. An unobserved or non-candidate hour breaks an incident. Thresholds are exploratory analytical choices, not calibrated equipment specifications.')

with maintenance:
    st.subheader('Published maintenance periods')
    st.caption('Explore reported periods independently of candidate alerts. This view uses all four source reports and its own context window; the sidebar date filter does not apply.')
    all_reports=frames['failure_reports'].sort_values('starts_at')
    report_id=st.selectbox('Maintenance report',all_reports.report_id.tolist(),format_func=lambda value: f'Report {value}')
    report=all_reports.loc[all_reports.report_id==report_id].iloc[0]
    context_days=st.slider('Context before and after report (days)',1,14,3)
    full=frames['hourly_investigation']
    window_start=(report.starts_at-pd.Timedelta(days=context_days)).floor('h')
    window_end=(report.ends_at+pd.Timedelta(days=context_days)).ceil('h')
    evidence=full[(full.hour_ts>=window_start)&(full.hour_ts<window_end)].copy()
    continuous=evidence.set_index('hour_ts').reindex(pd.date_range(window_start,window_end-pd.Timedelta(hours=1),freq='h')).rename_axis('hour_ts').reset_index()
    st.write(f"{report.report_type}: {report.starts_at} to {report.ends_at}")
    expected=int((window_end-window_start)/pd.Timedelta(hours=1))
    a,b,c=st.columns(3)
    a.metric('Observed context hours',len(evidence))
    b.metric('Context hours without observations',expected-len(evidence))
    c.metric('Candidate hours in context',int((evidence.candidate_status=='REVIEW_PRESSURE').sum()))
    for title,series,unit in [
        ('Pressure around the report',[('avg_panel_pressure_bar','Panel pressure','#315ea8')],'bar'),
        ('Oil temperature around the report',[('avg_oil_temperature_c','Oil temperature','#d97706')],'°C'),
        ('Motor current around the report',[('avg_motor_current_a','Motor current','#0d9488')],'A'),
    ]:
        fig=line(continuous,'hour_ts',series,title,unit=unit)
        fig.add_vrect(x0=report.starts_at,x1=report.ends_at,fillcolor='#f59e0b',opacity=.18,line_width=0)
        st.plotly_chart(fig,width='stretch')
    st.caption('Amber shading is the published report interval. Missing hours remain gaps. These plots show historical context and do not establish a cause.')
    st.download_button('Download maintenance context',evidence.to_csv(index=False).encode(),file_name=f'assetpulse-report-{report_id}.csv',mime='text/csv')
    st.subheader('Rule coverage across the full dataset')
    status=full.groupby('candidate_status',dropna=False).size().rename('observed_hours').reset_index()
    st.dataframe(status,hide_index=True,width='stretch')
    review=frames.get('report_review')
    if review is not None:
        st.dataframe(review,hide_index=True,width='stretch')
    st.caption('Counts before/overlapping a report are retrospective comparisons, not precision or recall. Published reports are incomplete ground truth.')

with quality:
    st.subheader('Traceable data, reproducible calculations')
    st.markdown(f"**{meta['original_reading_count']:,} original observations** · source period **{first:%d %b %Y}–{last:%d %b %Y}** · **{meta['duplicate_timestamps']:,} duplicate timestamps** preserved.")
    st.write('The pipeline validates input schema, numeric values, binary flags and source row count. Raw, hourly and daily totals reconcile. Each exported file is checked against its SHA-256 before the application loads.')
    st.code(meta['source_sha256'],language=None)
    st.caption('Original CSV SHA-256. The export also records the input run ID and database engine.')
    st.dataframe(selection['reports'][['report_id','starts_at','ends_at','report_type']],hide_index=True,width='stretch')
    st.caption('Published report intervals intersecting the selected range. Their original boundaries are retained.')
    st.markdown('**Scope:** an operating metro train compressor. Production counts, OEE, manufacturing yield, costs and intervention savings are unavailable. Missing hours remain missing. Baselines use observed prior readings, and rates use summed numerators and denominators.')
    st.markdown('**Delivery:** the app reads an immutable historical SQL snapshot. Native Superset alert delivery is a separate, optional service; its verified status is documented in `docs/VERIFICATION.md`.')
    st.json({k:meta[k] for k in ['run_id','loaded_at','exported_at','database_version','timestamp_policy','license']})
