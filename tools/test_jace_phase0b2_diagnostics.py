"""Phase 0B.2 diagnostics contract tests. No credentials or external services."""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import jace_quality as q


class DiagnosticsTests(unittest.TestCase):
    def test_failed_subprocess_output_is_suppressed_by_default(self):
        class Fake:
            returncode = 1
            stdout = 'SYNTHETIC_PRIVATE_CANARY\nFAIL\n'
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(q.subprocess, 'run', return_value=Fake()), \
             contextlib.redirect_stdout(output):
            result = q.run_command('Runner contracts', ['python', '-m', 'unittest'], Path(directory), 10)
        self.assertEqual(result.status, 'FAIL')
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', output.getvalue())
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', repr(result))

    def test_failed_subprocess_output_can_be_shown_locally_without_report_storage(self):
        class Fake:
            returncode = 1
            stdout = 'SYNTHETIC_PRIVATE_CANARY\nFAIL\n'
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(q.subprocess, 'run', return_value=Fake()), \
             contextlib.redirect_stdout(output):
            result = q.run_command('Runner contracts', ['python', '-m', 'unittest'],
                                   Path(directory), 10, show_test_output=True)
            report = {'profile': 'quick', 'timestamp_utc': 'synthetic', 'outcome': 'FAIL',
                      'checks': [q.asdict(result)]}
            q.write_reports(Path(directory), report)
            json_content = (Path(directory) / 'last-run.json').read_text(encoding='utf-8')
            markdown_content = (Path(directory) / 'last-run.md').read_text(encoding='utf-8')
        self.assertIn('SYNTHETIC_PRIVATE_CANARY', output.getvalue())
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json_content)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', markdown_content)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', repr(result))


if __name__ == '__main__':
    unittest.main()
