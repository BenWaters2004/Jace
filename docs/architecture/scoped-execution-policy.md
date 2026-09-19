# 4B.3D — Scoped Execution Policy & Approval Memory

## Purpose

4B.3C made device execution permission-aware.

4B.3D adds two missing boundaries:

1. commands/terminals must run inside an explicitly configured device/workspace
   execution scope;
2. a human can approve one exact safe command shape for the current conversation
   without changing the global tool permission.

## Execution scopes

An execution scope binds:

- a paired Device Agent;
- an existing `ComputerWorkspace`;
- a root path on that target device;
- allowed shells;
- process-runtime permission;
- terminal-runtime permission;
- active/inactive state.

The workspace remains the logical user-approved project/workspace object. The
execution scope supplies the device-specific mount path required by distributed
Jace.

Example:

```text
Computer Workspace
  Jace repository
        |
        +-- BEN-DESKTOP mount
             C:\Users\Ben\jace
```

A future VPS Core could bind the same logical workspace to another Device Agent
with a different device-local path.

## Double path enforcement

The model never supplies an arbitrary absolute CWD through the execution tool.

It supplies:

- `scope_id`
- `relative_cwd`

Core rejects absolute paths and `..` traversal, combines the relative directory
with the configured device root, and sends both `cwd` and `scope_root` to the
Device Agent.

The Device Agent independently resolves both paths on the host and checks the
resolved **launch CWD** remains beneath the real resolved scope root.

That second check is important because Core cannot resolve symlinks, junctions
or device-local filesystem aliases on another machine.

### Scope is not an OS filesystem sandbox

An arbitrary shell running as the Device Agent OS user can still explicitly
address paths outside the scope after launch (for example an absolute
`C:\Windows` path), and an interactive shell can later `cd` elsewhere. The
execution scope is therefore a **working-directory / approval boundary**, not a
kernel-enforced filesystem sandbox.

Jace mitigates this by:

- keeping arbitrary commands approval-controlled;
- fingerprinting the exact command in any conversation grant;
- requiring fresh approval for dangerous/compound commands;
- always requiring approval for terminal input;
- rejecting obvious absolute-path and parent-traversal forms in the
  auto-allowed read-only inspection tool.

A future stronger isolation layer could use OS/container sandboxing where
required.

## Workspace permissions

Read-only inspection requires an active readable Computer Workspace.

Arbitrary process execution and interactive terminals require the bound
Computer Workspace to be write-enabled because those interfaces can mutate
files even if a specific request appears harmless.

Direct `/processes` and `/terminals` APIs remain separate administrative
primitives. The scoped boundary applies to agent/tool execution.

## Session approval memory

The approval API gains:

```text
allow_session
```

The desktop approval modal renders this as:

```text
Allow for chat
```

A session grant is:

- memory-only;
- bound to one conversation ID;
- bound to one tool;
- bound to one exact grant fingerprint;
- cleared by Core restart;
- never promoted to global tool permission.

For `run_device_command`, the fingerprint contains:

- scope ID;
- shell;
- exact command;
- relative CWD;
- foreground/background mode.

Only commands classified `standard_execute` can receive a session grant.

The following are deliberately not eligible for remembered command approval:

- destructive commands;
- privilege elevation;
- pipes/chaining/redirection;
- command substitution;
- encoded PowerShell;
- common inline-eval forms.

`open_device_terminal` can receive an exact conversation-scoped grant for the
same scope + shell + relative CWD.

Raw `send_device_terminal_input` always asks. Terminal keystrokes are never
covered by a remembered grant.

## Policy order

Global/configured policy still has the final deny authority.

Conceptually:

```text
global deny
    |
    v
DENY

otherwise:
configured permission
    |
dynamic risk floor
    |
exact session grant (only when eligible)
    |
allow / ask
```

A session grant can satisfy an `ask` for its exact approved shape, but it never
overrides `deny`.

## Compound-shell analysis

4B.3D extends the 4B.3C classifier. Even if `run_device_command` is globally set
to `allow`, the following force human approval:

- `|`, `||`, `&&`, `;`
- redirection (`>`, `<`)
- command substitution (`$(...)`, backticks)
- encoded PowerShell
- common `python -c`, `node -e`, `ruby -e`, `perl -e` forms

This is deliberately conservative.

## New management API

```text
GET    /execution/scopes
POST   /execution/scopes
PATCH  /execution/scopes/{scope_id}
DELETE /execution/scopes/{scope_id}
```

## Agent tools

Adds:

```text
list_execution_scopes
```

and changes these tools to require a scope instead of arbitrary device/CWD
selection:

```text
inspect_device_command
run_device_command
open_device_terminal
```

## Server mode

As in 4B.3C, agent-driven execution remains fail-closed in server mode until
authenticated actor identity is part of `ToolContext`.

Execution scopes are designed to survive that later transition because they
already bind device + workspace rather than trusting a model-provided host path.


## Existing database compatibility

4B.3D deliberately does not add columns to the existing `process_runs` or
`terminal_sessions` tables. SQLAlchemy `create_all()` creates new tables but
does not migrate existing SQLite table columns.

Scope provenance for agent-driven execution remains in the existing tool audit,
whose arguments retain `scope_id` while sensitive command/input content is
redacted. The only database schema addition in this phase is the new
`execution_scopes` table.
