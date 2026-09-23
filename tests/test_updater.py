import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.updater.checker import UpdateChecker, UpdateError, UpdateInfo


class Response:
    def __init__(self, content): self.content = content; self.offset = 0
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, size=-1):
        if size == -1: return self.content
        data = self.content[self.offset:self.offset + size]; self.offset += len(data); return data


class UpdaterTests(unittest.TestCase):
    @patch("core.updater.checker.urlopen")
    def test_detects_new_version(self, mocked):
        manifest = {"version": "2.1.0", "installer_url": "https://x/setup.exe",
                    "sha256": "a" * 64, "size": 10}
        mocked.return_value = Response(json.dumps(manifest).encode())
        self.assertEqual("2.1.0", UpdateChecker("https://x/manifest.json", "2.0.0").check().version)

    def test_rejects_insecure_manifest(self):
        with self.assertRaises(UpdateError):
            UpdateChecker("http://x/manifest.json", "2.0.0").check()

    @patch("core.updater.checker.urlopen")
    def test_download_validates_hash(self, mocked):
        content = b"installer"
        mocked.return_value = Response(content)
        info = UpdateInfo("2.1.0", "https://x/setup.exe", hashlib.sha256(content).hexdigest(), len(content))
        target = UpdateChecker("https://x/m.json", "2.0.0").download(info)
        self.assertEqual(content, target.read_bytes())


if __name__ == "__main__":
    unittest.main()
