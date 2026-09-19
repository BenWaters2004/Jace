# 4B.3B.2 — Interactive Terminal Runtime

## Purpose

4B.3B.1 added durable non-interactive processes. This phase adds real
pseudo-terminal sessions so Jace can drive an interactive shell without
pretending pipes are a terminal.

## Backends

Windows uses ConPTY through `pywinpty`.

Jace pins `pywinpty==2.0.15` for the first implementation. The 3.x line has a
reported read/write regression, while 2.0.15 provides Windows x64 wheels for
modern CPython versions.

POSIX hosts use the standard `pty` module.

## Local opt-in

Interactive terminals are disabled by default on every Device Agent.

Enable locally:

`.\terminal-runtime.ps1 -Action Enable`

Then restart the Device Agent. It advertises `terminal.runtime` only when the
local opt-in is enabled.

This permission is separate from `process.runtime`.

## Session behaviour

A session owns one PTY/ConPTY and therefore naturally retains:

- current working directory;
- shell variables;
- environment mutations made inside the shell;
- interactive application state.

Core does not attempt to reconstruct this state from commands.

## Input privacy

Terminal input is never persisted by Core.

Core records only an event containing input byte count. This avoids creating a
second command/keystroke history which could contain passwords or tokens.

## Output

Terminal output is:

- streamed live as transient `terminal.output` runtime events;
- persisted in bounded `terminal_output_chunks`;
- sequenced per session for reconnect replay.

Default retained Core scrollback is 4 MiB per terminal.

The Device Agent also keeps a bounded in-memory replay window. On Core
reconnect, the Agent sends `terminal.snapshot`; Core requests any missing
output sequence range.

## Lifecycle

Durable lifecycle events include:

- `terminal.created`
- `terminal.started`
- `terminal.resized`
- `terminal.close_requested`
- `terminal.closed`
- `terminal.failed`
- `terminal.lost`

## API

- `POST /terminals`
- `GET /terminals`
- `GET /terminals/{terminal_id}`
- `GET /terminals/{terminal_id}/output`
- `POST /terminals/{terminal_id}/input`
- `POST /terminals/{terminal_id}/resize`
- `POST /terminals/{terminal_id}/close`

## Security

This phase exposes terminal transport APIs but does not register unrestricted
interactive terminal control as an autonomous LLM tool.

Agent/tool access must still go through Jace's capability and approval policy
before autonomous terminal use is enabled.

## Restart boundary

Terminal sessions survive frontend and Core/WebSocket reconnects while the
Device Agent process stays alive.

If the Device Agent itself restarts, the OS PTY handles are lost and Core marks
those terminal sessions `lost` after the reconnect snapshot.
