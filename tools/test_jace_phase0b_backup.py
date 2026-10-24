"""Regression tests for Phase 0B SQLite backup helper; disposable fixtures only."""
from __future__ import annotations

import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "phase0b-sqlite-backup.py"


class SqliteBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="jace_phase0b_backup_test_")
        self.addCleanup(self.tempdir.cleanup)
        self.dir = Path(self.tempdir.name)
        self.source = self.dir / "private.db"
        self.destination = self.dir / "backups" / "copy.db"
        self.destination.parent.mkdir()

    def run_backup(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCRIPT), str(self.source), str(self.destination)],
                              capture_output=True, text=True, check=False, timeout=45)

    def test_snapshot_preserves_source_and_committed_wal(self) -> None:
        con = sqlite3.connect(self.source)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE sample (note TEXT)")
            con.execute("INSERT INTO sample VALUES ('synthetic-only')")
            con.commit()
            result = self.run_backup()
            self.assertEqual(result.returncode, 0, result.stderr)
            # A sqlite3.Connection context manager commits/rolls back but DOES NOT close.
            # An open handle prevents TemporaryDirectory cleanup on Windows (WinError 32).
            with closing(sqlite3.connect(self.destination)) as check:
                self.assertEqual(check.execute("SELECT note FROM sample").fetchone(), ("synthetic-only",))
            self.assertEqual(con.execute("SELECT count(*) FROM sample").fetchone(), (1,))
        finally:
            con.close()

    def test_bad_sqlite_file_fails_without_backup(self) -> None:
        self.source.write_text("not a database", encoding="utf-8")
        result = self.run_backup()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.destination.exists())
        self.assertNotIn("not a database", result.stderr)

    def test_missing_source_fails(self) -> None:
        self.assertNotEqual(self.run_backup().returncode, 0)
        self.assertFalse(self.destination.exists())

    def test_existing_backup_not_overwritten(self) -> None:
        with closing(sqlite3.connect(self.source)) as con:
            con.execute("CREATE TABLE sample (x INTEGER)")
        self.destination.write_bytes(b"sentinel")
        self.assertNotEqual(self.run_backup().returncode, 0)
        self.assertEqual(self.destination.read_bytes(), b"sentinel")


if __name__ == "__main__":
    unittest.main()
