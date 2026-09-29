"""Read-only eligibility audit against Compose db; no credentials or host packages."""
import datetime
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = (ROOT / "sql/07_rule_eligibility_audit.sql").read_text()
    parts = re.split(r"-- audit: (\w+)\s*\n", source)
    results = {}
    for name, query in zip(parts[1::2], parts[2::2]):
        statement = "SELECT COALESCE(json_agg(audit), '[]'::json) FROM (" + query.strip().rstrip(';') + ") audit;"
        response = subprocess.run(["docker", "compose", "exec", "-T", "db", "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "assetpulse", "-d", "assetpulse", "-At"], input=statement, capture_output=True, text=True, cwd=ROOT)
        if response.returncode:
            raise RuntimeError("Read-only audit query failed: " + name)
        results[name] = json.loads(response.stdout)
        print("Verified audit query:", name)
    r = results["reconciliation"][0]
    assert r["observed_hours"] == r["eligible_hours"] + r["not_evaluated_hours"]
    assert r["eligible_hours"] == r["evaluated_no_breach"] + r["evaluated_breach"]
    assert r["not_evaluated_hours"] == r["current_only"] + r["baseline_only"] + r["both"]
    assert r["eligible_null_rate"] == 0
    independent = results["independent_raw_window_reconciliation"][0]
    assert independent["compared_hours"] == r["observed_hours"]
    assert independent["mismatched_hours"] == independent["mismatched_eligibility"] == 0
    results["verified_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    results["source_sql"] = "sql/07_rule_eligibility_audit.sql"
    (ROOT / "evidence/rule_eligibility_audit.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(r))


if __name__ == "__main__":
    main()
