"""Exercise real beat schedules and Mailpit capture, never manually enqueue tasks.

Run after setup_alerts.py. All test alerts are disabled in finally, even on failure.
"""
import datetime as dt
import json
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
def admin(action):
    p=subprocess.run(['docker','exec','assetpulse-superset','python','/tmp/alert_admin.py',action],capture_output=True,cwd=ROOT)
    lines=[s for s in p.stdout.decode().splitlines() if s.startswith('ASSET_RESULT=')]
    if p.returncode or not lines:
        raise RuntimeError('Alert administration failed; inspect locally (output withheld)')
    return json.loads(lines[-1].split('=',1)[1])
def messages():
    with urllib.request.urlopen('http://localhost:8026/api/v1/messages') as r:
        return json.load(r)['messages']
def main():
    for file in ('superset_assets.py','alert_admin.py'):
        subprocess.run(['docker','cp',str(ROOT/'scripts'/file),'assetpulse-superset:/tmp/'+file],check=True,capture_output=True)
    evidence={'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'manual_task_dispatch':False}
    initial={m['ID'] for m in messages()}
    admin('setup')
    subprocess.run(['docker','cp','assetpulse-superset:/tmp/assetpulse-alert-definitions.json',str(ROOT/'superset/alert_definitions.json')],check=True,capture_output=True)
    status=admin('status')
    prior=max([log['id'] for report in status['reports'] for log in report['logs']]+[0])
    def new_logs(status):
        test=next(r for r in status['reports'] if 'TEST ONLY' in r['name'])
        return [l for l in test['logs'] if l['id']>prior]
    def captured():
        return [m for m in messages() if m['ID'] not in initial and 'TEST ONLY' in m['Subject']]
    def wait_for(predicate, phase, timeout=300):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            status=admin('status')
            if any(l['state']=='Error' for l in new_logs(status)):
                evidence['failed_status']=status
                raise AssertionError('Superset recorded an execution error')
            if predicate(status):
                print(phase+' passed',flush=True)
                return status
            time.sleep(10)
        raise TimeoutError(phase)
    try:
        admin('negative')
        status=wait_for(lambda s:any(l['state']=='Not triggered' and l['value']==0 for l in new_logs(s)),'Scheduled false condition')
        assert not captured()
        evidence['negative_condition']=status
        admin('positive')
        status=wait_for(lambda s:any(l['state']=='Success' for l in new_logs(s)) and len(captured())==1,'Scheduled true condition and SMTP capture')
        evidence['first_delivery']=status
        status=wait_for(lambda s:any(l['state']=='On Grace' for l in new_logs(s)),'Repeat suppressed during 120-second grace')
        assert len(captured())==1
        evidence['grace_suppression']=status
        status=wait_for(lambda s:len(captured())>=2,'Repeat notification after grace')
        successes=[l for l in new_logs(status) if l['state']=='Success']
        assert len(successes)>=2
        elapsed=(dt.datetime.fromisoformat(successes[-1]['end'])-dt.datetime.fromisoformat(successes[0]['end'])).total_seconds()
        assert elapsed>=120
        evidence['repeat_elapsed_seconds']=elapsed
        evidence['repeat_delivery']=status
        evidence['messages']=[{k:m[k] for k in ('ID','Subject','Created','To')} for m in captured()]
        evidence['passed']=True
    finally:
        evidence['disabled_status']=admin('disable')
        assert all(not r['active'] for r in evidence['disabled_status']['reports'])
        evidence['preservation']=admin('validate')['validation']
        evidence['external_email_delivery']='Not configured or tested'
        (ROOT/'evidence/alert_delivery_verification.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('Both alerts disabled. Evidence saved.',flush=True)

if __name__=='__main__':
    main()
