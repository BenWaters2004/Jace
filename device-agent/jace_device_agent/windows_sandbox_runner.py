from __future__ import annotations

import argparse
import contextlib
import html
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from jace_device_agent.config import data_directory


RUNNER_VERSION = 1
SUPPORTED_PROCESS_SHELLS = {"powershell", "cmd"}
DEFAULT_COMMAND_TIMEOUT_SECONDS = 3600
STARTUP_ALLOWANCE_SECONDS = 120


def state_directory() -> Path:
    return data_directory() / "windows-sandbox"


def verification_path() -> Path:
    return state_directory() / "verification.json"


def sandbox_executable() -> Path:
    root = Path(os.environ.get("WINDIR", r"C:\Windows"))
    return root / "System32" / "WindowsSandbox.exe"


def windows_build() -> str:
    return platform.version()


def is_verified() -> bool:
    if os.name != "nt" or not sandbox_executable().is_file():
        return False

    marker = verification_path()
    if not marker.is_file():
        return False

    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    return (
        data.get("verified") is True
        and data.get("runner_version") == RUNNER_VERSION
        and data.get("windows_build") == windows_build()
    )


def probe() -> dict[str, Any]:
    exe = sandbox_executable()
    return {
        "platform": platform.system(),
        "windows_build": windows_build(),
        "sandbox_executable": str(exe),
        "sandbox_executable_present": exe.is_file(),
        "runner_version": RUNNER_VERSION,
        "verified": is_verified(),
        "supported_process_shells": sorted(SUPPORTED_PROCESS_SHELLS),
    }


def create_request_file(
    *,
    shell: str,
    command: str,
    scope_root: str,
    cwd: str,
    timeout_seconds: int | None,
) -> Path:
    directory = state_directory() / "requests"
    directory.mkdir(parents=True, exist_ok=True)

    path = directory / f"{uuid.uuid4().hex}.json"
    path.write_text(
        json.dumps(
            {
                "shell": shell,
                "command": command,
                "scope_root": scope_root,
                "cwd": cwd,
                "timeout_seconds": (
                    int(timeout_seconds)
                    if timeout_seconds is not None
                    else DEFAULT_COMMAND_TIMEOUT_SECONDS
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def sandbox_command_argv(request_file: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "jace_device_agent.windows_sandbox_runner",
        "exec",
        "--request",
        str(request_file),
    ]


def _resolved_directory(value: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Sandbox path cannot be empty.")

    path = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    if not path.is_dir():
        raise ValueError(f"Sandbox directory does not exist: {path}")
    return path


def _validate_request(data: dict[str, Any]) -> dict[str, Any]:
    shell = str(data.get("shell") or "").strip().lower()
    command = str(data.get("command") or "")
    root = _resolved_directory(str(data.get("scope_root") or ""))
    cwd = _resolved_directory(str(data.get("cwd") or ""))

    if shell not in SUPPORTED_PROCESS_SHELLS:
        raise PermissionError(
            f"Shell {shell!r} is not supported by the Windows Sandbox process backend."
        )
    if not command.strip():
        raise ValueError("Sandbox command cannot be empty.")

    try:
        common = os.path.commonpath(
            [os.path.normcase(str(root)), os.path.normcase(str(cwd))]
        )
    except ValueError as exc:
        raise PermissionError(
            "Sandbox working directory is outside the approved root."
        ) from exc

    if common != os.path.normcase(str(root)):
        raise PermissionError("Sandbox working directory escaped the approved root.")

    relative = cwd.relative_to(root)

    try:
        timeout = int(
            data.get("timeout_seconds") or DEFAULT_COMMAND_TIMEOUT_SECONDS
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid sandbox timeout.") from exc

    return {
        "shell": shell,
        "command": command,
        "scope_root": str(root),
        "relative_cwd": "." if str(relative) in {"", "."} else str(relative),
        "timeout_seconds": max(1, min(timeout, 86400)),
    }


class RunnerLock:
    def __init__(self) -> None:
        self.path = state_directory() / "runner.lock"
        self.owned = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if self.path.exists():
            stale = True
            try:
                pid = int(self.path.read_text(encoding="utf-8").strip())
                stale = not psutil.pid_exists(pid)
            except Exception:
                stale = True
            if stale:
                try:
                    self.path.unlink()
                except OSError:
                    pass

        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise RuntimeError(
                "Another Jace isolated Windows command is already running."
            ) from exc

        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))

        self.owned = True
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.owned:
            try:
                self.path.unlink()
            except OSError:
                pass


def _guest_runner_text() -> str:
    return r'''$ErrorActionPreference = "Stop"

$InputRoot = "C:\JaceControlIn"
$OutputRoot = "C:\JaceControlOut"
$Workspace = "C:\JaceWorkspace"

$RequestPath = Join-Path $InputRoot "request.json"
$StdoutPath = Join-Path $OutputRoot "stdout.txt"
$StderrPath = Join-Path $OutputRoot "stderr.txt"
$ResultPath = Join-Path $OutputRoot "result.json"

function Write-JsonAtomic {
    param([string]$Path, [hashtable]$Value)
    $Temp = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 8 -Compress |
        Set-Content -LiteralPath $Temp -Encoding UTF8
    Move-Item -LiteralPath $Temp -Destination $Path -Force
}

try {
    $Request = Get-Content -LiteralPath $RequestPath -Raw | ConvertFrom-Json
    $Relative = [string]$Request.relative_cwd
    if ([string]::IsNullOrWhiteSpace($Relative)) { $Relative = "." }

    if ([System.IO.Path]::IsPathRooted($Relative)) {
        throw "Sandbox working directory must be relative."
    }
    if (($Relative -split '[\\/]') -contains "..") {
        throw "Sandbox working directory cannot traverse to a parent."
    }

    $RootFull = [System.IO.Path]::GetFullPath($Workspace).TrimEnd('\\')
    $CwdFull = [System.IO.Path]::GetFullPath((Join-Path $Workspace $Relative)).TrimEnd('\\')

    if ($CwdFull -ne $RootFull -and -not $CwdFull.StartsWith(
        $RootFull + '\\',
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Sandbox working directory escaped the mapped workspace."
    }

    if (-not (Test-Path -LiteralPath $CwdFull -PathType Container)) {
        throw "Sandbox working directory does not exist: $CwdFull"
    }

    "" | Set-Content -LiteralPath $StdoutPath -Encoding UTF8
    "" | Set-Content -LiteralPath $StderrPath -Encoding UTF8

    $Shell = ([string]$Request.shell).ToLowerInvariant()
    if ($Shell -eq "powershell") {
        $Executable = "powershell.exe"
        $Arguments = @(
            "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-File", "C:\JaceControlIn\command.ps1"
        )
    }
    elseif ($Shell -eq "cmd") {
        $Executable = "cmd.exe"
        $Arguments = @("/d", "/s", "/c", "C:\JaceControlIn\command.cmd")
    }
    else {
        throw "Unsupported sandbox shell: $Shell"
    }

    $Process = Start-Process `
        -FilePath $Executable `
        -ArgumentList $Arguments `
        -WorkingDirectory $CwdFull `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath `
        -NoNewWindow `
        -PassThru

    $TimeoutSeconds = [Math]::Max(1, [Math]::Min(86400, [int]$Request.timeout_seconds))
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $TimedOut = $false

    while (-not $Process.HasExited) {
        if ([DateTime]::UtcNow -ge $Deadline) {
            $TimedOut = $true
            & taskkill.exe /PID $Process.Id /T /F *> $null
            break
        }
        Start-Sleep -Milliseconds 100
        $Process.Refresh()
    }

    if (-not $Process.HasExited) {
        $Process.WaitForExit(5000) | Out-Null
    }

    $ExitCode = if ($Process.HasExited) { [int]$Process.ExitCode } else { 1 }

    Write-JsonAtomic -Path $ResultPath -Value @{
        state = $(if ($TimedOut) { "timed_out" } elseif ($ExitCode -eq 0) { "completed" } else { "failed" })
        exit_code = $(if ($TimedOut) { 124 } else { $ExitCode })
        timed_out = $TimedOut
        sandbox_user = [Environment]::UserName
        sandbox_machine = [Environment]::MachineName
    }
}
catch {
    $_.Exception.ToString() | Set-Content -LiteralPath $StderrPath -Encoding UTF8
    Write-JsonAtomic -Path $ResultPath -Value @{
        state = "failed"
        exit_code = 1
        timed_out = $false
        error = $_.Exception.Message
        sandbox_user = [Environment]::UserName
        sandbox_machine = [Environment]::MachineName
    }
}
finally {
    Start-Sleep -Milliseconds 500
    Start-Process -FilePath "shutdown.exe" -ArgumentList @("/s", "/t", "0", "/f") -WindowStyle Hidden
}
'''


def _write_configuration(
    path: Path,
    *,
    workspace: Path,
    control_in: Path,
    control_out: Path,
) -> None:
    workspace_xml = html.escape(str(workspace), quote=True)
    input_xml = html.escape(str(control_in), quote=True)
    output_xml = html.escape(str(control_out), quote=True)

    config = f'''<Configuration>
  <VGpu>Disable</VGpu>
  <Networking>Disable</Networking>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <PrinterRedirection>Disable</PrinterRedirection>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <MemoryInMB>4096</MemoryInMB>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>{workspace_xml}</HostFolder>
      <SandboxFolder>C:\\JaceWorkspace</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>{input_xml}</HostFolder>
      <SandboxFolder>C:\\JaceControlIn</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>{output_xml}</HostFolder>
      <SandboxFolder>C:\\JaceControlOut</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\\JaceControlIn\\guest-runner.ps1</Command>
  </LogonCommand>
</Configuration>
'''
    path.write_text(config, encoding="utf-8", newline="\r\n")


def _tail(path: Path, *, offset: int, target) -> int:
    if not path.is_file():
        return offset

    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        handle.seek(offset)
        value = handle.read()
        next_offset = handle.tell()

    if value:
        target.write(value)
        target.flush()
    return next_offset


def _kill_tree(pid: int) -> None:
    try:
        root = psutil.Process(pid)
    except psutil.Error:
        return

    for process in root.children(recursive=True):
        try:
            process.kill()
        except psutil.Error:
            pass
    try:
        root.kill()
    except psutil.Error:
        pass


def execute(data: dict[str, Any], *, require_verification: bool) -> int:
    if os.name != "nt":
        raise RuntimeError("Windows Sandbox isolation is available only on Windows.")

    executable = sandbox_executable()
    if not executable.is_file():
        raise RuntimeError("Windows Sandbox executable was not found.")
    if require_verification and not is_verified():
        raise RuntimeError(
            "Windows Sandbox runner has not passed the Jace local isolation verification."
        )

    request = _validate_request(data)
    session = state_directory() / "sessions" / uuid.uuid4().hex
    control_in = session / "input"
    control_out = session / "output"
    control_in.mkdir(parents=True, exist_ok=True)
    control_out.mkdir(parents=True, exist_ok=True)

    workspace = Path(request["scope_root"]).resolve()

    (control_in / "request.json").write_text(
        json.dumps(
            {
                "shell": request["shell"],
                "relative_cwd": request["relative_cwd"],
                "timeout_seconds": request["timeout_seconds"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    if request["shell"] == "powershell":
        (control_in / "command.ps1").write_text(
            request["command"] + "\n", encoding="utf-8", newline="\r\n"
        )
        (control_in / "command.cmd").write_text(
            "@echo off\r\nexit /b 1\r\n", encoding="utf-8"
        )
    else:
        (control_in / "command.cmd").write_text(
            "@echo off\r\n" + request["command"] + "\r\n",
            encoding="utf-8",
            newline="",
        )
        (control_in / "command.ps1").write_text(
            "exit 1\n", encoding="utf-8"
        )

    (control_in / "guest-runner.ps1").write_text(
        _guest_runner_text(), encoding="utf-8", newline="\r\n"
    )

    config = session / "jace-command.wsb"
    _write_configuration(
        config,
        workspace=workspace,
        control_in=control_in,
        control_out=control_out,
    )

    stdout_path = control_out / "stdout.txt"
    stderr_path = control_out / "stderr.txt"
    result_path = control_out / "result.json"
    stdout_offset = 0
    stderr_offset = 0
    deadline = (
        time.monotonic()
        + STARTUP_ALLOWANCE_SECONDS
        + int(request["timeout_seconds"])
        + 30
    )

    sandbox_process: subprocess.Popen | None = None

    try:
        sandbox_process = subprocess.Popen(
            [str(executable), str(config)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        while True:
            stdout_offset = _tail(
                stdout_path, offset=stdout_offset, target=sys.stdout
            )
            stderr_offset = _tail(
                stderr_path, offset=stderr_offset, target=sys.stderr
            )

            if result_path.is_file():
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Windows Sandbox did not return a command result before the host-side deadline."
                )
            if sandbox_process.poll() is not None and not result_path.is_file():
                raise RuntimeError(
                    "Windows Sandbox exited before producing a command result."
                )
            time.sleep(0.10)

        time.sleep(0.20)
        _tail(stdout_path, offset=stdout_offset, target=sys.stdout)
        _tail(stderr_path, offset=stderr_offset, target=sys.stderr)

        result = json.loads(result_path.read_text(encoding="utf-8-sig"))
        error = str(result.get("error") or "").strip()
        if error:
            print(error, file=sys.stderr)
        if result.get("timed_out") is True:
            return 124
        return int(result.get("exit_code", 1))

    finally:
        if sandbox_process is not None and sandbox_process.poll() is None:
            try:
                sandbox_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _kill_tree(sandbox_process.pid)


def _write_verification_marker(proof: dict[str, Any]) -> None:
    path = verification_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(
            {
                "verified": True,
                "runner_version": RUNNER_VERSION,
                "windows_build": windows_build(),
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "proof": proof,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    temp.replace(path)


def verify() -> int:
    current = probe()
    print(json.dumps(current, indent=2))

    if not current["sandbox_executable_present"]:
        print("[FAIL] WindowsSandbox.exe was not found.", file=sys.stderr)
        return 1

    workspace = state_directory() / "verification-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    proof_file = workspace / "sandbox-write-proof.txt"
    if proof_file.exists():
        proof_file.unlink()

    secret = state_directory() / f"outside-secret-{uuid.uuid4().hex}.txt"
    secret.write_text(uuid.uuid4().hex, encoding="utf-8")

    command = (
        '$ErrorActionPreference = "Stop"\n'
        'Write-Output ("SANDBOX_USER=" + [Environment]::UserName)\n'
        f'Write-Output ("OUTSIDE_PATH_VISIBLE=" + [int](Test-Path -LiteralPath {json.dumps(str(secret))}))\n'
        '"written-inside-sandbox" | Set-Content -LiteralPath ".\\sandbox-write-proof.txt" -Encoding UTF8\n'
        'Write-Output "WORKSPACE_WRITE=1"\n'
    )

    out = io.StringIO()
    err = io.StringIO()

    try:
        with RunnerLock():
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                exit_code = execute(
                    {
                        "shell": "powershell",
                        "command": command,
                        "scope_root": str(workspace),
                        "cwd": str(workspace),
                        "timeout_seconds": 60,
                    },
                    require_verification=False,
                )
    finally:
        try:
            secret.unlink()
        except OSError:
            pass

    stdout = out.getvalue()
    stderr = err.getvalue()
    print(stdout, end="")
    if stderr:
        print(stderr, file=sys.stderr, end="")

    passed = (
        exit_code == 0
        and "OUTSIDE_PATH_VISIBLE=0" in stdout
        and "WORKSPACE_WRITE=1" in stdout
        and proof_file.is_file()
        and "written-inside-sandbox"
        in proof_file.read_text(encoding="utf-8-sig", errors="replace")
    )

    if not passed:
        print("[FAIL] Windows Sandbox isolation proof failed.", file=sys.stderr)
        return 1

    sandbox_user = "unknown"
    for line in stdout.splitlines():
        if line.startswith("SANDBOX_USER="):
            sandbox_user = line.partition("=")[2].strip()
            break

    _write_verification_marker(
        {
            "outside_host_path_visible": False,
            "mapped_workspace_write_persisted": True,
            "sandbox_user": sandbox_user,
            "networking_configured": "disabled",
            "clipboard_configured": "disabled",
            "vgpu_configured": "disabled",
        }
    )

    print("[PASS] Windows Sandbox isolated process runner verified.")
    print("[PASS] A host path outside the mapped workspace was not visible.")
    print("[PASS] A write inside the mapped workspace persisted to the host.")
    print("[PASS] Jace may now advertise isolated process.runtime.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("probe")
    sub.add_parser("verify")
    run = sub.add_parser("exec")
    run.add_argument("--request", required=True)
    args = parser.parse_args()

    if args.command == "probe":
        print(json.dumps(probe(), indent=2))
        return 0
    if args.command == "verify":
        return verify()

    request_path = Path(args.request).resolve()
    data = json.loads(request_path.read_text(encoding="utf-8"))
    try:
        request_path.unlink()
    except OSError:
        pass

    with RunnerLock():
        return execute(data, require_verification=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[sandbox-runner] {exc}", file=sys.stderr)
        raise SystemExit(1)
