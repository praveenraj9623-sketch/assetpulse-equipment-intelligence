"""Run ingestion then publish a verified export; any failure stops publication."""
import subprocess
import sys
import psycopg
from .pipeline import ROOT, dsn


def main():
    # A distinct session lock covers download through export publication.
    with psycopg.connect(dsn(), autocommit=True) as guard:
        if not guard.execute("SELECT pg_try_advisory_lock(20260928)").fetchone()[0]:
            raise RuntimeError("Another AssetPulse refresh is already running")
        try:
            for module in ("src.download", "src.pipeline", "src.export"):
                subprocess.run([sys.executable, "-m", module], cwd=ROOT, check=True)
        finally:
            guard.execute("SELECT pg_advisory_unlock(20260928)")


if __name__ == "__main__":
    main()
