"""Phase 0B secret scanner tests: local disposable Git repositories, no real secrets/network."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import jace_secret_scan as ss


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jace_scan_contract_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        # Git for Windows commonly enables autocrlf and global ignore rules.
        # Keep fixtures deterministic regardless of user/system Git defaults.
        self.git("config", "core.autocrlf", "false")
        (self.root / "safe.py").write_text("print('no secrets here')\n", encoding="utf-8")
        self.git("add", "safe.py")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def test_missing_gitleaks_not_reported_pass(self):
        with patch.object(ss.shutil, "which", return_value=None):
            self.assertEqual(ss.scan_index_snapshot(self.root).status, "NOT_CONFIGURED")

    def test_private_db_blocks_before_any_scanner(self):
        (self.root / "data").mkdir()
        (self.root / "data/jace.db").write_bytes(b"synthetic-not-actually-sqlite")
        self.git("add", "-f", "data/jace.db")
        with patch.object(ss.subprocess, "run", wraps=subprocess.run) as calls:
            result = ss.scan_index_snapshot(self.root, executable="fake-gitleaks")
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("tracked private/generated", result.detail)
        self.assertFalse(any(x.args[0][0] == "fake-gitleaks" for x in calls.call_args_list))

    def test_scan_uses_staged_contents_not_dirty_working_file(self):
        (self.root / "safe.py").write_text("changed working copy is not staged", encoding="utf-8")
        original = ss.subprocess.run
        observed = []

        def stub(cmd, *args, **kwargs):
            if cmd[0] == "fake-gitleaks":
                snapshot = Path(cmd[-1]) / "safe.py"
                observed.append(snapshot.read_text(encoding="utf-8"))
                return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
            return original(cmd, *args, **kwargs)

        with patch.object(ss.subprocess, "run", side_effect=stub):
            result = ss.scan_index_snapshot(self.root, executable="fake-gitleaks")
        self.assertEqual(result.status, "PASS")
        self.assertEqual(observed, ["print('no secrets here')\n"])

    def test_findings_count_without_leaking_finding(self):
        original = ss.subprocess.run
        def stub(cmd, *args, **kwargs):
            if cmd[0] == "fake-gitleaks":
                report = Path(cmd[cmd.index("--report-path") + 1])
                report.write_text(json.dumps([{"Secret": "SYNTHETIC_CANARY_NEVER_REPORT"}]), encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 1, stdout=b"SYNTHETIC_CANARY_NEVER_REPORT", stderr=b"")
            return original(cmd, *args, **kwargs)
        with patch.object(ss.subprocess, "run", side_effect=stub):
            result = ss.scan_index_snapshot(self.root, executable="fake-gitleaks")
        self.assertEqual(result.status, "FAIL")
        self.assertIn("1 potential", result.detail)
        self.assertNotIn("SYNTHETIC_CANARY", repr(result))

    def test_gitkeep_is_safe_and_scanned(self):
        self.assertFalse(ss._possibly_private("data/.gitkeep"))
        self.assertTrue(ss._possibly_private("data/jace.db"))
        self.assertTrue(ss._possibly_private("data/quality/last-run.json"))
        self.assertTrue(ss._possibly_private("backend/.venv/Lib/test.py"))
        (self.root / "data").mkdir()
        (self.root / "data/.gitkeep").write_bytes(b"")
        self.git("add", "data/.gitkeep")
        original = ss.subprocess.run
        observed = []

        def stub(cmd, *args, **kwargs):
            if cmd[0] == "fake-gitleaks":
                observed.append((Path(cmd[-1]) / "data/.gitkeep").exists())
                return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
            return original(cmd, *args, **kwargs)

        with patch.object(ss.subprocess, "run", side_effect=stub):
            result = ss.scan_index_snapshot(self.root, executable="fake-gitleaks")
        self.assertEqual(result.status, "PASS")
        self.assertEqual(observed, [True])

    def test_large_checked_in_audio_asset_fits_bound(self):
        # Current Jace thinking audio is 6,350,444 bytes. The old 4 MiB
        # limit blocked a complete index scan even after Git cleanup.
        self.assertGreaterEqual(ss.MAX_BLOB_BYTES, 6_350_444)
        self.assertLessEqual(ss.MAX_BLOB_BYTES, ss.MAX_TOTAL_BYTES)

    def test_path_rejection(self):
        for value in ("../outside", "a/../outside", "/root/hidden", r"C:\\secrets", ""):
            self.assertFalse(ss._valid_path(value), value)


if __name__ == "__main__":
    unittest.main()
