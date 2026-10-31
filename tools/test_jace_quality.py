"""Offline, dependency-free contract checks for Phase 0A quality runner."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import jace_quality as q


class QualityRunnerTests(unittest.TestCase):
    def test_outcome_never_treats_skips_as_success(self):
        self.assertEqual(q.calculate_outcome([q.Check("live", "BLOCKED", "staging unavailable")]), ("INCOMPLETE", 2))
        self.assertEqual(q.calculate_outcome([q.Check("x", "NOT_CONFIGURED", "missing")]), ("INCOMPLETE", 2))

    def test_fail_takes_precedence(self):
        self.assertEqual(q.calculate_outcome([q.Check("a", "BLOCKED", ""), q.Check("b", "FAIL", "")]), ("FAIL", 1))

    def test_warning_can_be_visible_without_breaking_baseline(self):
        self.assertEqual(q.calculate_outcome([q.Check("a", "WARN", "tracked db")]), ("PASS_WITH_WARNINGS", 0))

    def test_syntax_detects_failure_without_importing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            src = root / "backend/jace"
            src.mkdir(parents=True)
            (src / "bad.py").write_text("def broken(: pass", encoding="utf-8")
            result = q.python_syntax([src], root)
            self.assertEqual(result.status, "FAIL")
            self.assertIn("bad.py", result.detail)
            self.assertNotIn("def broken", result.detail)

    def test_report_has_no_raw_test_output(self):
        with tempfile.TemporaryDirectory() as folder:
            dst = Path(folder)
            report = {"profile": "quick", "timestamp_utc": "2026-10-18T00:00:00Z", "outcome": "PASS",
                      "checks": [{"name": "syntax", "status": "PASS", "detail": "ok", "repair": ""}]}
            q.write_reports(dst, report)
            self.assertIn('"profile": "quick"', (dst / "last-run.json").read_text())
            self.assertIn("| syntax | PASS | ok |", (dst / "last-run.md").read_text())

    def test_track_hygiene_warn_and_strict_fail(self):
        class Fake:
            returncode = 0
            stdout = b"backend/.venv/foo\0data/jace.db\0README.md\0"
        with tempfile.TemporaryDirectory() as folder, patch.object(q.subprocess, "run", return_value=Fake()):
            self.assertEqual(q.tracked_hygiene(Path(folder), False).status, "WARN")
            result = q.tracked_hygiene(Path(folder), True)
            self.assertEqual(result.status, "FAIL")
            self.assertIn("virtualenv=1", result.detail)
            self.assertIn("private_data=1", result.detail)

    def test_report_profiles_define_unimplemented_harnesses(self):
        for profile in ("integration", "live-provider", "device", "recovery", "production-smoke"):
            self.assertIn(profile, q.SKIPPED_PROFILES)

    def test_command_output_is_not_saved(self):
        class Fake:
            returncode = 1
            stdout = "MY_SUPER_SECRET_PROVIDER_KEY"
        with tempfile.TemporaryDirectory() as folder, patch.object(q.subprocess, "run", return_value=Fake()):
            result = q.run_command("test", ["python", "x"], Path(folder), 5)
            self.assertEqual(result.status, "FAIL")
            self.assertNotIn("SECRET", result.detail)


if __name__ == "__main__":
    unittest.main()
