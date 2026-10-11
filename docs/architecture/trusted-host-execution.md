# 4B.4C.3 — Trusted Host Execution

Jace treats a paired Device Agent as a trusted execution host. Execution scopes
select the expected working context and locally approved shell; they are not
filesystem sandboxes.

The Device Agent remains the final local authority: process execution must be
locally enabled, the scope root must be present in local host policy, the shell
must be locally allowed, and the process backend is chosen only by local Device
Agent configuration.

`native` is the default mode. Commands use the existing host process runtime,
process-tree lifecycle, output replay and timeout handling.

`sandbox` remains an optional local mode for deliberately untrusted code and
continues to require the 4B.4C.2 Windows Sandbox verification. Core cannot
switch execution mode over WSS.

Interactive terminals remain fail-closed until the native-terminal phase.
