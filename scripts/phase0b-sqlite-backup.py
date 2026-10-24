#!/usr/bin/env python3
"""Create a consistent, verified SQLite backup without modifying the source.

The shell script stages Git changes ONLY when this program succeeds.  Uses a
separate .py script rather than `python -c` to avoid Windows PowerShell 5.1
quote-stripping for native executable arguments.

Usage:
    python phase0b-sqlite-backup.py SOURCE_DB DESTINATION_DB

No database rows or identifying data are printed to stdout.
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def snapshot(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    destination = destination.resolve(strict=False)
    if not source.is_file():
        raise ValueError("SQLite source must be an existing file")
    if source == destination:
        raise ValueError("Refusing to overwrite the source database")
    if destination.exists():
        raise FileExistsError("Refusing to replace an existing backup")
    if not destination.parent.is_dir():
        raise FileNotFoundError("Backup directory does not exist")

    # SQLite online-backup API includes committed WAL transactions, unlike a
    # plain file copy, and does not require stopping a running Jace service.
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=20)) as current:
            with closing(sqlite3.connect(str(destination), timeout=20)) as backup:
                current.backup(backup, pages=256, sleep=0.05)
                backup.commit()

        # Reopen independently to validate the snapshot persisted on disk.
        with closing(sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True, timeout=20)) as verified:
            result = verified.execute("PRAGMA quick_check").fetchall()
            if result != [("ok",)]:
                raise RuntimeError("Backup failed SQLite quick_check")
        if not destination.is_file() or destination.stat().st_size < 512:
            raise RuntimeError("Backup was not written correctly")
    except Exception:
        # Only a destination created by this invocation may be removed.
        if destination.exists():
            destination.unlink()
        raise


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("ERROR: Expected SOURCE_DB DESTINATION_DB", file=sys.stderr)
        return 2
    try:
        snapshot(Path(argv[0]), Path(argv[1]))
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
        print(f"ERROR: SQLite snapshot validation failed ({type(error).__name__}).", file=sys.stderr)
        return 1
    print("SQLite snapshot integrity verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
