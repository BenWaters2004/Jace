# 4B.3B.1 — Persistent Process Runtime

## Why this is separate from the interactive terminal

One-shot commands, background jobs and PTY/ConPTY terminal sessions have
different lifecycle requirements.

4B.3B.1 implements durable non-interactive processes. 4B.3B.2 adds true
interactive terminal sessions (stdin, resize, terminal emulation and prompt
semantics) on top.

## Trust boundary

Raw commands travel from authenticated Jace Core to a paired Device Agent over
the existing outbound Device Agent WebSocket.

The full command is not stored in Core. Core stores:

- a SHA-256 command fingerprint;
- a short privacy-transformed preview;
- shell/cwd/mode/status metadata.

The Device Agent process runtime is disabled by default. The device owner must
explicitly opt in locally:

`.\process-runtime.ps1 -Action Enable`

Restart the Device Agent after changing this setting. Only then does the device
advertise `process.runtime`.

This phase does not expose process execution as an autonomous LLM tool. Later
tool integration must still pass through Jace's permission/approval layer.

## Process shapes

Supported:

- foreground process;
- background process.

Supported shells when installed:

- PowerShell;
- cmd.exe;
- WSL bash;
- bash.

Interactive stdin and PTY/ConPTY are deliberately deferred to 4B.3B.2.

## Core state

`process_runs` persists:

- identity/device/owner;
- shell/mode/cwd;
- redacted command preview + SHA-256;
- PID/status/exit code;
- timeout;
- bounded-output metadata;
- project/task/agent/conversation scope;
- lifecycle timestamps.

`process_output_chunks` persists bounded stdout/stderr chunks.

Default Core retained output limit is 2 MiB per process. Once reached, the row
is marked `output_truncated` and further output is not persisted. Live output
may still be delivered while connected.

## Device Agent state

The Device Agent owns the actual subprocess.

It captures stdout/stderr, assigns monotonically increasing per-process
sequences and keeps an in-memory replay window. Processes continue to be
tracked across Core/WebSocket reconnects while the Device Agent itself remains
running.

On reconnect:

1. Device Agent sends `process.snapshot`.
2. Core compares each process's last persisted agent sequence.
3. Core requests any missing output with `process.replay.request`.
4. Device Agent replays retained chunks.
5. A Core row still marked running but absent from the Agent snapshot is marked
   `lost`.

If the Device Agent process itself restarts, managed child state is not
recovered in 4B.3B.1. Normal Device Agent shutdown attempts to terminate its
managed process trees for safety.

## Termination

Termination uses `psutil` to terminate the complete process tree and escalates
to kill when necessary.

Timeouts are enforced by the Device Agent, not by the frontend.

## Shared runtime events

Lifecycle transitions are durable:

- `process.created`
- `process.started`
- `process.completed`
- `process.failed`
- `process.cancel_requested`
- `process.cancelled`
- `process.timed_out`
- `process.lost`

High-volume `process.output` events are live/transient. Durable output belongs
in `process_output_chunks`, preventing the shared event ledger from becoming an
unbounded terminal log.

## API

- `POST /processes`
- `GET /processes`
- `GET /processes/{process_id}`
- `GET /processes/{process_id}/output`
- `POST /processes/{process_id}/terminate`

## Next

4B.3B.2 adds true interactive terminal sessions with PTY/ConPTY, stdin, resize,
working-directory continuity and terminal replay.
