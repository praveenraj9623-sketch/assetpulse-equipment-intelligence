"""Run idempotent Superset setup in the existing container; no host dependencies.

Requires local Docker administration. Existing database credentials are read into
memory, sent on stdin, and never printed or written to the workspace.
"""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "assetpulse-superset"


def command(args, *, data=None):
    result = subprocess.run(args, cwd=ROOT, input=data, capture_output=True)
    if result.returncode:
        if args[:3] == ["docker", "exec", "-i"]:
            # Worker explicitly suppresses secret-bearing exceptions and logging.
            print(result.stdout.decode(), file=sys.stderr)
            for line in result.stderr.decode().splitlines():
                if line.startswith("Provisioning stopped:"):
                    print(line, file=sys.stderr)
        # Docker/DB exceptions may include a credential-bearing payload.
        raise RuntimeError("Command failed: " + " ".join(args[:3]) + " (output withheld)")
    return result.stdout


def main():
    prior_ids_path = ROOT / "superset/asset_ids.json"
    prior_ids = json.loads(prior_ids_path.read_text()) if prior_ids_path.exists() else None
    db_id = command(["docker", "compose", "ps", "-q", "db"]).decode().strip()
    if not db_id:
        raise RuntimeError("Start the existing Compose db service first")
    details = json.loads(command(["docker", "inspect", db_id]))[0]
    env = dict(item.split("=", 1) for item in details["Config"]["Env"] if "=" in item)
    payload = {"admin_password": env["POSTGRES_PASSWORD"],
               "analytics_sql": (ROOT / "sql/05_superset_analytics.sql").read_text(),
               "eligibility_sql": (ROOT / "sql/06_rule_eligibility.sql").read_text()}
    command(["docker", "cp", "scripts/superset_assets.py", CONTAINER + ":/tmp/assetpulse_assets.py"])
    result = command(["docker", "exec", "-i", CONTAINER, "python", "/tmp/assetpulse_assets.py"],
                     data=json.dumps(payload).encode())
    # Worker stdout contains only a sanitized summary.
    print(result.decode())
    (ROOT / "superset").mkdir(exist_ok=True)
    command(["docker", "cp", CONTAINER + ":/tmp/assetpulse-export/.", str(ROOT / "superset")])
    if prior_ids is not None:
        current_ids = json.loads(prior_ids_path.read_text())
        for key, previous in prior_ids.items():
            if isinstance(previous, dict):
                assert all(current_ids[key].get(name) == identity for name, identity in previous.items()), "Existing asset IDs changed"
            else:
                assert previous == current_ids[key], "Existing asset IDs changed"
        print("Rerun verified: all existing asset IDs retained; any additions have distinct IDs.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
