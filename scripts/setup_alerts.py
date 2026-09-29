"""Install local alert configuration without recreating the existing Superset."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run(args, data=None):
    result = subprocess.run(args, input=data, capture_output=True, cwd=ROOT)
    if result.returncode:
        raise RuntimeError("Alert setup command failed (output withheld): " + " ".join(args[:3]))
    return result.stdout

def main():
    # Credential stays inside its existing named volume, never in CLI arguments.
    code = '''import os, pathlib, sqlite3, datetime
p=pathlib.Path('/app/superset_home/.assetpulse_secret_key')
key=os.environ['SUPERSET_SECRET_KEY']
if p.exists():
    assert p.read_text()==key, 'Refusing secret key change'
else:
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f: f.write(key)
source=sqlite3.connect('/app/superset_home/superset.db')
destination=sqlite3.connect('/app/superset_home/pre_alerts_'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')+'.db')
source.backup(destination)
destination.close()
source.close()
'''
    run(['docker','exec','-i','assetpulse-superset','python','-'], code.encode())
    run(['docker','cp','infra/alerts/superset_config.py','assetpulse-superset:/app/superset_home/assetpulse_alert_config.py'])
    # Preserve any unexpected preexisting configuration by refusing to overwrite it.
    install = '''from pathlib import Path
p=Path('/app/pythonpath/superset_config.py')
loader="exec(compile(open('/app/superset_home/assetpulse_alert_config.py').read(), '/app/superset_home/assetpulse_alert_config.py', 'exec'))\\n"
assert not p.exists() or p.read_text()==loader, 'Existing custom config requires review'
p.write_text(loader)
'''
    run(['docker','exec','-i','--user','root','assetpulse-superset','python','-'], install.encode())
    run(['docker','restart','assetpulse-superset'])
    subprocess.run(['docker','compose','-f','compose.alerts.yaml','up','-d'],cwd=ROOT,check=True)
    subprocess.run(['docker','compose','-f','compose.alerts.yaml','restart','worker','beat'],cwd=ROOT,check=True)
    print('Local alert services started. Existing Superset metadata and secret key retained.')

if __name__ == '__main__':
    main()
