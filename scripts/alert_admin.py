"""Run inside existing Superset container; authenticated local REST administration."""
import datetime as dt
import json
import logging
import os
import sqlite3
import sys
import warnings
from pathlib import Path

logging.disable(logging.CRITICAL)
warnings.filterwarnings('ignore')
from superset.app import create_app
from superset import db, security_manager
from superset_assets import API

TEST = 'AssetPulse TEST ONLY - local deterministic fixture'
HISTORY = 'AssetPulse HISTORICAL ONLY - candidate rule (disabled)'
OLD_DISCLOSURE = 'Alert delivery has not been configured or tested.'
NEW_DISCLOSURE = 'Local TEST ONLY SMTP delivery is verified through Mailpit. Both alert schedules are disabled. External email and live equipment monitoring are not configured.'
def fixture(value):
    return f'WITH test_only_fixture(value) AS (VALUES ({value})) SELECT value FROM test_only_fixture'

def main():
    app = create_app()
    with app.app_context():
        from superset.reports.models import ReportSchedule, ReportExecutionLog
        user = security_manager.find_user(username='admin')
        api = API(app, user)
        action = sys.argv[1]
        validation = None
        if action == 'validate':
            from superset.models.core import Database
            database=db.session.query(Database).get(1)
            frame=database.get_df(sql="SELECT COUNT(*) AS observed, COUNT(*) FILTER (WHERE rule_eligible) AS eligible, COUNT(*) FILTER (WHERE evaluation_status = 'Evaluated: breach') AS breaches FROM mart_hourly_investigation")
            counts={key:int(value) for key,value in frame.iloc[0].items()}
            assert counts=={'observed':4416,'eligible':186,'breaches':0}
            assert app.config['SECRET_KEY']==os.environ['SUPERSET_SECRET_KEY']==Path('/app/superset_home/.assetpulse_secret_key').read_text()
            backups=sorted(Path('/app/superset_home').glob('pre_alerts_*.db'))
            before=sqlite3.connect(str(backups[0]))
            after=sqlite3.connect('/app/superset_home/superset.db')
            preserved={}
            for table in ('dashboards','slices','tables','dbs','ab_user'):
                cols=[r[1] for r in before.execute(f'PRAGMA table_info({table})')]
                if table=='dashboards':
                    cols=[c for c in cols if c not in ('changed_on','changed_by_fk')]
                columns=','.join('"'+c+'"' for c in cols)
                old=before.execute(f'SELECT {columns} FROM {table} ORDER BY id').fetchall()
                new=after.execute(f'SELECT {columns} FROM {table} ORDER BY id').fetchall()
                if table=='dashboards':
                    new=[tuple(v.replace(NEW_DISCLOSURE,OLD_DISCLOSURE) if isinstance(v,str) else v for v in row) for row in new]
                preserved[table]=old==new
            before.close()
            after.close()
            assert all(preserved.values()), 'Existing metadata changed'
            validation={'historical_counts':counts,'eligibility_percent':100*186/4416,
                'secret_key_unchanged':True,'metadata_rows_unchanged':preserved,
                'alerts_enabled':app.config['FEATURE_FLAGS']['ALERT_REPORTS'],
                'smtp_host':app.config['SMTP_HOST'],'smtp_port':app.config['SMTP_PORT'],
                'dry_run':app.config['ALERT_REPORTS_NOTIFICATION_DRY_RUN']}
        if action == 'disclosure':
            result=api.call('GET','dashboard/1')['result']
            position=result['position_json']
            assert OLD_DISCLOSURE in position or NEW_DISCLOSURE in position
            api.call('PUT','dashboard/1',{'position_json':position.replace(OLD_DISCLOSURE,NEW_DISCLOSURE)})
        if action == 'setup':
            base = dict(type='Alert', active=False, crontab='* * * * *', timezone='UTC',
                        database=1, dashboard=1, owners=[user.id],
                        creation_method='alerts_reports', validator_type='operator',
                        validator_config_json={'op': '>', 'threshold': 0},
                        grace_period=120, working_timeout=30, log_retention=90,
                        report_format='PNG', force_screenshot=False,
                        recipients=[{'type':'Email','recipient_config_json':{'target':'assetpulse-test@local.test'}}])
            test = dict(base, name=TEST, sql=fixture(0), description='TEST ONLY: isolated constant SQL fixture. No telemetry or equipment diagnosis. Local Mailpit delivery only.')
            historical = dict(base, name=HISTORY, crontab='0 9 * * *', grace_period=86400,
                sql="SELECT COUNT(*) FROM mart_hourly_investigation WHERE rule_eligible AND evaluation_status = 'Evaluated: breach' AND hour_ts >= TIMESTAMP '2020-02-01' AND hour_ts < TIMESTAMP '2020-09-02'",
                description='DISABLED historical 2020 rule review, not live equipment monitoring. Only 186/4416 observed hours eligible (4.21%). The >=6 A loaded proxy needs domain validation. Repeated queries of static history do not detect new equipment events. Local capture recipient only.')
            definitions = []
            for body in (test, historical):
                identity = api.upsert('report', body, 'name', body['name'])
                definitions.append(dict(body, id=identity))
            Path('/tmp/assetpulse-alert-definitions.json').write_text(json.dumps(definitions,indent=2))
        elif action in ('negative','positive','disable'):
            test = db.session.query(ReportSchedule).filter_by(name=TEST).one()
            api.call('PUT',f'report/{test.id}', {'active':action!='disable', 'sql':fixture(1 if action=='positive' else 0)})
            if action=='disable':
                historical = db.session.query(ReportSchedule).filter_by(name=HISTORY).one()
                api.call('PUT',f'report/{historical.id}',{'active':False})
        reports=[]
        for report in db.session.query(ReportSchedule).filter(ReportSchedule.name.in_([TEST,HISTORY])).all():
            db.session.refresh(report)
            logs=db.session.query(ReportExecutionLog).filter_by(report_schedule_id=report.id).order_by(ReportExecutionLog.id.desc()).limit(30).all()
            reports.append({'id':report.id,'name':report.name,'active':report.active,'last_state':report.last_state,'last_value':report.last_value,'grace_period':report.grace_period,
                            'logs':[{'id':log.id,'scheduled':str(log.scheduled_dttm),'start':str(log.start_dttm),'end':str(log.end_dttm),'state':log.state,'value':log.value,'error':log.error_message} for log in reversed(logs)]})
        print('ASSET_RESULT='+json.dumps({'time':dt.datetime.now(dt.timezone.utc).isoformat(),'reports':reports,'validation':validation}))

if __name__=='__main__':
    main()
