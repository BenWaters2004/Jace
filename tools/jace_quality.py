#!/usr/bin/env python3
"""Phase 0B: non-destructive Jace quality runner (Python 3.10+, stdlib).

No production API calls, database reads, or shell execution of project tools.
The `full` profile executes only checked-in offline unit tests and a desktop build.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass


PROFILES = (
    "quick", "full", "security", "integration", "live-provider",
    "device", "recovery", "production-smoke", "all",
)
SKIPPED_PROFILES = {
    "integration": "Real API, WebSocket and test-database integration harness not yet implemented.",
    "live-provider": "Live provider checks require a controlled staging fixture, cost budget and explicit opt-in.",
    "device": "Cross-device tests need two approved staging devices and permission fixtures.",
    "recovery": "Restart/queue crash testing requires isolated staging workers and durable test state.",
    "production-smoke": "A non-destructive authenticated VPS smoke harness is not yet implemented.",
}


@dataclass
class Check:
    name: str
    status: str
    detail: str
    duration_seconds: float = 0.0
    repair: str = ""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def safe_detail(s: str, limit: int = 750) -> str:
    """Do not copy test stdout/tracebacks into persistent quality reports."""
    return s[:limit].replace("\x00", "")


def python_syntax(paths: list[Path], repo: Path) -> Check:
    started = time.monotonic()
    count = 0
    problems = []
    for source in paths:
        if not source.is_dir():
            continue
        for path in source.rglob("*.py"):
            if any(part in {".venv", "venv", "node_modules", "__pycache__"} for part in path.parts):
                continue
            count += 1
            try:
                compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
            except (OSError, SyntaxError, UnicodeError) as exc:
                rel = path.relative_to(repo).as_posix()
                problems.append(f"{rel}: {type(exc).__name__}")
    return Check("Python source syntax", "FAIL" if problems else "PASS",
                 safe_detail("; ".join(problems[:8]) if problems else f"Compiled {count} source files in memory (no imports)."),
                 round(time.monotonic() - started, 3),
                 "Correct indicated source files." if problems else "")


def tracked_hygiene(repo: Path, strict: bool) -> Check:
    started = time.monotonic()
    try:
        result = subprocess.run(["git", "ls-files", "-z"], cwd=repo, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=25, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return Check("Tracked file hygiene", "NOT_CONFIGURED", "Git is unavailable.",
                     round(time.monotonic()-started,3), "Install Git and run inside the repository.")
    if result.returncode != 0:
        return Check("Tracked file hygiene", "NOT_CONFIGURED", "Could not obtain Git's tracked file index.",
                     round(time.monotonic()-started,3), "Run this in a Git checkout.")
    paths = [x.decode("utf-8", errors="replace").replace("\\", "/") for x in result.stdout.split(b"\0") if x]
    bad_venv = [p for p in paths if p.startswith("backend/.venv/") or p.startswith("device-agent/.venv/")]
    bad_db = [p for p in paths if p.startswith("data/") and p != "data/.gitkeep"]
    bad_backups = [p for p in paths if p.startswith(".jace-patch-backups/")]
    bad_keys = [p for p in paths if p.lower().endswith((".p12", ".pfx", ".key")) or
                (Path(p).name.startswith(".env") and Path(p).name != ".env.example")]
    counts = {"virtualenv": len(bad_venv), "private_data": len(bad_db),
              "patch_backups": len(bad_backups), "secret_filename_candidates": len(bad_keys)}
    unsafe = sum(counts.values())
    if unsafe:
        summary = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
        status = "FAIL" if strict else "WARN"
        repair = ("Back up local state first; inspect tracked paths privately; untrack generated files "
                  "with git rm --cached, then review Git history and rotate any exposed credentials.")
        return Check("Tracked file hygiene", status, f"Detected tracked sensitive/generated path categories: {summary}. No contents read.",
                     round(time.monotonic()-started,3), repair)
    return Check("Tracked file hygiene", "PASS", f"No tracked private/generated path categories among {len(paths)} indexed files.",
                 round(time.monotonic()-started,3))


def run_command(name: str, command: list[str], repo: Path, timeout: int,
                env: dict[str, str] | None = None,
                show_test_output: bool = False) -> Check:
    started = time.monotonic()
    try:
        proc = subprocess.run(command, cwd=repo, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout, check=False,
                              text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return Check(name, "NOT_CONFIGURED", "Required executable is unavailable.",
                     round(time.monotonic()-started,3), "Install the required tool and retry.")
    except subprocess.TimeoutExpired:
        return Check(name, "FAIL", f"Exceeded timeout of {timeout} seconds.",
                     round(time.monotonic()-started,3), "Run the check interactively to diagnose the hang.")
    except OSError:
        return Check(name, "FAIL", "Could not start the test process.",
                     round(time.monotonic()-started,3), "Check executable access and working directory.")
    status = "PASS" if proc.returncode == 0 else "FAIL"
    # Explicit local diagnostic mode: console only, never persisted to reports.
    # Opt-in because even test tracebacks can contain local paths or fixture data.
    if status == "FAIL" and show_test_output:
        print(f"\n--- LOCAL TEST OUTPUT: {name} (not saved to reports) ---", flush=True)
        print(proc.stdout or "(no output from test command)", flush=True)
        print("--- END LOCAL TEST OUTPUT ---\n", flush=True)
    # Do not persist test output: it may contain environment configuration,
    # fixture text or user-specific filesystem paths.
    return Check(name, status, f"Exit code {proc.returncode}; output intentionally not retained.",
                 round(time.monotonic()-started,3),
                 "Rerun the corresponding command locally for the detailed failure." if proc.returncode else "")


def run_quick(repo: Path, strict_hygiene: bool, show_test_output: bool = False) -> list[Check]:
    required = ["backend/jace", "backend/tests", "apps/desktop/package.json", "device-agent/jace_device_agent"]
    missing = [p for p in required if not (repo / p).exists()]
    checks = [Check("Repository layout", "FAIL" if missing else "PASS",
                    "Missing expected locations: " + ", ".join(missing) if missing else "Required repository locations found.",
                    repair="Point --repo-root to the Jace checkout." if missing else "")]
    if missing:
        return checks
    checks.append(python_syntax([repo / "backend/jace", repo / "backend/tests",
                                 repo / "device-agent/jace_device_agent", repo / "tools"], repo))
    tests = repo / "tools/test_jace_quality.py"
    if tests.is_file():
        checks.append(run_command("Runner self-tests",
                                  [sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_jace_*.py", "-v"],
                                  repo, 90, show_test_output=show_test_output))
    else:
        checks.append(Check("Runner self-tests", "NOT_CONFIGURED", "Self-test file is missing.",
                            repair="Install the complete Phase 0A package."))
    checks.append(tracked_hygiene(repo, strict_hygiene))
    return checks


def run_full(repo: Path, show_test_output: bool = False) -> list[Check]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "backend") + os.pathsep + env.get("PYTHONPATH", "")
    # Avoid accidental provider calls from test helpers that consult env flags.
    # Tests must independently mock providers. A development machine with configured
    # real provider keys must still be treated as trusted during test execution.
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "backend/tests", "-p", "test_*.py", "-v"]
    checks = [run_command("Backend offline unittest suite", cmd, repo, 900, env=env, show_test_output=show_test_output)]
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None:
        checks.append(Check("Desktop TypeScript/Vite build", "NOT_CONFIGURED", "npm not on PATH.",
                            repair="Install Node.js; run npm ci in apps/desktop."))
    elif not (repo / "apps/desktop/node_modules").is_dir():
        checks.append(Check("Desktop TypeScript/Vite build", "NOT_CONFIGURED", "Desktop dependencies not installed.",
                            repair="cd apps/desktop; npm ci; then rerun the full profile."))
    else:
        checks.append(run_command("Desktop TypeScript/Vite build", [npm, "run", "build", "--prefix", "apps/desktop"],
                                  repo, 600, show_test_output=show_test_output))
    return checks


def write_reports(report_dir: Path, report: dict) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_target = report_dir / "last-run.json"
    md_target = report_dir / "last-run.md"
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    json_target.write_text(payload, encoding="utf-8")
    lines = [f"# Jace quality — {report['profile']}", "",
             f"Run (UTC): {report['timestamp_utc']}", f"Outcome: **{report['outcome']}**", "",
             "| Check | Status | Details |", "|---|---|---|"]
    for check in report["checks"]:
        cells = [str(check[k]).replace("|", "\\|").replace("\n", " ") for k in ("name", "status", "detail")]
        lines.append("| " + " | ".join(cells) + " |")
        if check.get("repair"):
            lines.append(f"\n**{check['name']} — next action:** {check['repair']}\n")
    md_target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def calculate_outcome(checks: list[Check]) -> tuple[str, int]:
    states = {c.status for c in checks}
    if "FAIL" in states:
        return "FAIL", 1
    if "NOT_CONFIGURED" in states or "BLOCKED" in states:
        return "INCOMPLETE", 2
    if "WARN" in states:
        return "PASS_WITH_WARNINGS", 0
    return "PASS", 0


def build_checks(repo: Path, profile: str, strict: bool, show_test_output: bool = False) -> list[Check]:
    checks = run_quick(repo, strict or profile == "security", show_test_output)
    if profile in {"full", "all"}:
        checks.extend(run_full(repo, show_test_output))
    if profile in {"security", "all"}:
        if profile == "all":
            checks.append(tracked_hygiene(repo, True))
        from jace_secret_scan import scan_index_snapshot
        verdict = scan_index_snapshot(repo)
        checks.append(Check("Current-index secret scanning", verdict.status, verdict.detail,
                            repair=verdict.repair))
    if profile in SKIPPED_PROFILES:
        checks.append(Check(profile + " acceptance", "BLOCKED", SKIPPED_PROFILES[profile]))
    if profile == "all":
        checks.extend(Check(key + " acceptance", "BLOCKED", reason) for key, reason in SKIPPED_PROFILES.items())
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--profile", choices=PROFILES, default="quick")
    parser.add_argument("--strict-hygiene", action="store_true",
                        help="Fail rather than warn when tracked private/generated paths exist.")
    parser.add_argument("--show-test-output", action="store_true",
                        help="Print failed subprocess test output to the local console only; not to saved reports.")
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    if not root.is_dir():
        print("Repository directory does not exist.", file=sys.stderr)
        return 2
    started = time.monotonic()
    checks = build_checks(root, args.profile, args.strict_hygiene, args.show_test_output)
    outcome, code = calculate_outcome(checks)
    report = {
        "schema_version": 1,
        "timestamp_utc": utc_now(),
        "profile": args.profile,
        "outcome": outcome,
        "counts": {s: sum(c.status == s for c in checks) for s in ("PASS", "WARN", "FAIL", "NOT_CONFIGURED", "BLOCKED")},
        "duration_seconds": round(time.monotonic()-started, 3),
        "checks": [asdict(x) for x in checks],
    }
    dest = (args.report_dir if args.report_dir is not None else root / "data/quality").resolve()
    try:
        write_reports(dest, report)
    except OSError as exc:
        print(f"Could not write reports: {type(exc).__name__}", file=sys.stderr)
        return 2
    for check in checks:
        print(f"[{check.status:14}] {check.name}: {check.detail}")
    print(f"\nOutcome: {outcome} | JSON: {dest / 'last-run.json'} | Markdown: {dest / 'last-run.md'}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
