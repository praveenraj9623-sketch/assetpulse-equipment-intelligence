"""Fetch the original MetroPT-3 CSV from the official UCI archive.

No packaged reading data are manufactured or copied from another project.
"""

import argparse
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://archive.ics.uci.edu/static/public/791/metropt%2B3%2Bdataset.zip"
CSV_NAME = "MetroPT3(AirCompressor).csv"


def download(destination: Path = ROOT / "data" / "raw") -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "metropt_3_dataset.zip"
    csv_path = destination / CSV_NAME
    if not csv_path.exists():
        if not archive.exists():
            partial = archive.with_suffix(".zip.part")
            try:
                with (
                    urllib.request.urlopen(URL, timeout=120) as response,
                    partial.open("wb") as out,
                ):
                    shutil.copyfileobj(response, out, length=1024 * 1024)
                partial.replace(archive)
            finally:
                partial.unlink(missing_ok=True)
        with zipfile.ZipFile(archive) as source:
            matches = [
                name for name in source.namelist() if Path(name).name == CSV_NAME
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"Expected one {CSV_NAME} in the UCI archive; found {len(matches)}"
                )
            partial_csv = csv_path.with_suffix(".csv.part")
            try:
                with (
                    source.open(matches[0]) as incoming,
                    partial_csv.open("wb") as outgoing,
                ):
                    shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
                partial_csv.replace(csv_path)
            finally:
                partial_csv.unlink(missing_ok=True)
    else:
        print(f"Using existing CSV: {csv_path}")
    with csv_path.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    manifest = {
        "source": URL,
        "file": CSV_NAME,
        "bytes": csv_path.stat().st_size,
        "sha256": digest,
        "dataset_doi": "10.24432/C5VW3R",
    }
    (ROOT / "data" / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(
        f"Downloaded official MetroPT-3 CSV: {csv_path} ({manifest['bytes']:,} bytes)"
    )
    return csv_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "data" / "raw")
    args = parser.parse_args()
    download(args.directory)
