# 4B.3C — Permission-Aware Execution Bridge

## Goal

Expose the durable process and interactive terminal runtimes to Jace's tool
system without bypassing the existing `allow / ask / deny` permission engine,
approval UI or tool audit.

## Tool split

### Read-only / automatic

- `list_execution_devices`
- `inspect_device_command`
- `get_device_process`
- `read_device_process_output`
- `read_device_terminal_output`
- `resize_device_terminal`

`inspect_device_command` is intentionally not arbitrary shell execution. It
accepts a small read-only allowlist and rejects shell chaining, pipes and
redirection.

### Arbitrary execution

`run_device_command` executes PowerShell, cmd, WSL or bash through the durable
4B.3B.1 process runtime.

Its normal default is `ask`.

If the user later changes its configured permission to `allow`, a dynamic
policy floor still forces commands classified as destructive or elevated back
to `ask`.

A configured global `deny` always wins.

### Interactive terminal

Opening a terminal, sending terminal input and closing a terminal have an
`ask` policy floor. They therefore cannot become silent agent actions merely
because a tool permission was relaxed.

Terminal output reads remain read-only.

## Dynamic policy decisions

`ToolDefinition` gains an optional policy resolver. It may only make a tool
call more restrictive.

Order:

`allow < ask < deny`

The resolver returns:

- minimum permission;
- policy classification;
- effective risk;
- human-readable policy reason.

The primary agent adds this policy result to live tool/approval events and to
the redacted audit metadata.

## Command classification

The initial classifier intentionally targets high-confidence dangerous forms:

### Elevated

Examples include:

- `sudo`
- `su -`
- `runas`
- PowerShell `Start-Process ... -Verb RunAs`

### Destructive / system-changing

Examples include:

- file/directory deletion commands;
- disk formatting/initialisation;
- shutdown/restart;
- registry writes/deletes;
- service deletion/disable;
- user/group administration;
- permission/ownership changes;
- process termination.

This classifier is a permission escalation control, not a sandbox. The Device
Agent still executes commands with the same OS privileges as its own process.

## Audit privacy

Approval events may contain the proposed command/input so the human can make a
decision.

Persistent `ToolAuditLog.arguments_json` does not keep:

- raw `run_device_command.command`;
- raw `inspect_device_command.command`;
- raw `send_device_terminal_input.data`.

Commands are replaced with SHA-256/length metadata. Terminal input is replaced
with character/byte counts.

## Server mode

The agent execution bridge is fail-closed in `JACE_MODE=server` until the
authenticated actor identity is explicitly threaded into `ToolContext`.

The authenticated process/terminal HTTP APIs remain separate. This prevents a
server-mode model/tool call from accidentally acting as an unscoped local
owner.

## Future extension

The next execution-security layer can add:

- authenticated actor/device ownership in server mode;
- project mount restrictions;
- remembered one-session approvals;
- richer structured command parsing;
- per-device/per-project execution policy;
- terminal rendering in the desktop UI.
