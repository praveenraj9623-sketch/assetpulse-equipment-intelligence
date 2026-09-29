"""Verify that the official archive layout is extracted without extra files."""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from src import download as source


class ArchiveTest(unittest.TestCase):
    def test_only_named_csv_is_extracted_and_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "official.zip"
            with zipfile.ZipFile(archive, "w") as file:
                file.writestr(
                    "folder/" + source.CSV_NAME,
                    b"timestamp,TP2\n2020-02-01 00:00:00,1\n",
                )
                file.writestr("folder/description.pdf", b"reference only")
            with (
                patch.object(source, "ROOT", root),
                patch.object(source, "URL", archive.as_uri()),
            ):
                extracted = source.download(root / "data" / "raw")
            self.assertEqual(extracted.name, source.CSV_NAME)
            self.assertFalse((root / "data" / "raw" / "description.pdf").exists())
            manifest = json.loads(
                (root / "data" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
