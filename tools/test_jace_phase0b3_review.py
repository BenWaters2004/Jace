"""Offline, synthetic-only checks for Phase 0B.3 local secret triage."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import jace_secret_review as review


class SecretReviewTests(unittest.TestCase):
    def test_metadata_never_includes_secret_value(self) -> None:
        items = [{"File": "/tmp/staged/backend/example.py", "StartLine": 15,
                  "RuleID": "generic-api-key", "Secret": "super-secret-TEST-FIXTURE",
                  "Match": "token = super-secret-TEST-FIXTURE"}]
        result = review.safe_metadata(items, {"backend/example.py"})
        self.assertEqual(result, [("backend/example.py", "15", "generic-api-key")])
        self.assertNotIn("super-secret-TEST-FIXTURE", repr(result))

    def test_unknown_path_cannot_be_injected(self) -> None:
        result = review.safe_metadata([{"File": "../private.db", "RuleID": "\x1b[1msecret"}], {"README.md"})
        self.assertEqual(result, [("[unresolved tracked path]", "?", "unknown-rule")])

    def test_invalid_finding_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            review.safe_metadata({"Secret": "X"}, {"README.md"})

    def test_index_snapshot_rejects_tracked_database(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jace_phase0b3_git_") as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True, stdout=subprocess.DEVNULL)
            (repo / "data").mkdir()
            (repo / "data" / "jace.db").write_bytes(b"synthetic-test-only")
            subprocess.run(["git", "add", "-f", "data/jace.db"], cwd=repo, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self.assertRaises(RuntimeError):
                review.index_snapshot(repo, repo / "safe")

    def test_index_snapshot_reads_staged_not_working_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jace_phase0b3_git_") as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True, stdout=subprocess.DEVNULL)
            (repo / "note.txt").write_text("staged-file-content", encoding="utf-8")
            subprocess.run(["git", "add", "note.txt"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
            (repo / "note.txt").write_text("unstaged PRIVATE TEXT", encoding="utf-8")
            target = repo / "tmp"
            target.mkdir()
            paths = review.index_snapshot(repo, target)
            self.assertEqual(paths, {"note.txt"})
            self.assertEqual((target / "note.txt").read_text(), "staged-file-content")


if __name__ == "__main__":
    unittest.main()
