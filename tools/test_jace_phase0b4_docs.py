"""Phase 0B.4 focused tests: synthetic data; no live repository changes."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase0b4_fix_docs import DOC, REPLACEMENTS, UnsafeDocumentError, apply_to_repo, patched


class DocumentationFixTests(unittest.TestCase):
    def fixture(self, root: Path, *, newline: bytes = b"\n") -> Path:
        (root / ".git").mkdir()
        (root / "backend" / "jace").mkdir(parents=True)
        target = root / DOC
        target.parent.mkdir(parents=True)
        target.write_bytes(b"# Test" + newline + b"```dotenv" + newline +
                           REPLACEMENTS[0][0] + newline + REPLACEMENTS[1][0] + newline +
                           b"```" + newline + b"Additional notes" + newline)
        return target

    def test_only_two_example_values_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = self.fixture(root)
            before = doc.read_bytes()
            result = apply_to_repo(root, apply=True, backups=root.parent / (root.name + "-backups"))
            self.assertTrue(result.startswith("APPLIED:"))
            after = doc.read_bytes()
            expected, changed = patched(before)
            self.assertTrue(changed)
            self.assertEqual(after, expected)
            self.assertIn(b"Additional notes", after)
            shutil.rmtree(root.parent / (root.name + "-backups"))

    def test_default_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = self.fixture(root)
            before = doc.read_bytes()
            self.assertTrue(apply_to_repo(root).startswith("DRY_RUN:"))
            self.assertEqual(doc.read_bytes(), before)

    def test_idempotent_and_crlf_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = self.fixture(root, newline=b"\r\n")
            backup = Path(tmp).parent / (Path(tmp).name + "-backups")
            apply_to_repo(root, apply=True, backups=backup)
            result = doc.read_bytes()
            self.assertIn(b"\r\n", result)
            self.assertNotIn(b"\n", result.replace(b"\r\n", b""))
            self.assertTrue(apply_to_repo(root, apply=True, backups=backup).startswith("ALREADY_FIXED:"))
            shutil.rmtree(backup)

    def test_unknown_or_partial_example_block_fails_closed(self):
        with self.assertRaises(UnsafeDocumentError):
            patched(REPLACEMENTS[0][0] + b"\n" + REPLACEMENTS[1][1])
        with self.assertRaises(UnsafeDocumentError):
            patched(b"different model routes")
        with self.assertRaises(UnsafeDocumentError):
            patched(REPLACEMENTS[0][0] * 2 + REPLACEMENTS[1][0])

    def test_backups_outside_repo_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            with self.assertRaises(UnsafeDocumentError):
                apply_to_repo(root, apply=True, backups=root / "backups")


if __name__ == "__main__":
    unittest.main()
