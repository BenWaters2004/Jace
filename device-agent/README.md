# Jace Device Agent

The Device Agent runs on an authorised Windows computer and connects **outward** to Jace Core. It advertises allowed host capabilities and provides the trusted local execution boundary for paired device requests.

**Important:** the original 4B.S5 document said the agent could pair but could not execute remote shell/process operations. That described its *initial phase*. The repository now includes later process, terminal, scoped execution, host policy and sandbox-related implementations. Those capabilities are subject to separate local enablement, Jace Core permissions and environment-specific readiness; their presence does **not** imply unrestricted remote shell access.

## Install on Windows

From `device-agent` in PowerShell:

```powershell
.\install.ps1
```

Requires Python 3. The installer creates `device-agent/.venv` and installs `device-agent/requirements.txt`.

## Pair with Jace Core

First create a pairing code in Jace Core. Then, from `device-agent`:

```powershell
.\pair.ps1 -PairingCode "jace_pair_..."
```

For a remote VPS:

```powershell
.\pair.ps1 `
  -Server https://jace.example.com `
  -PairingCode "jace_pair_..." `
  -Name BEN-DESKTOP
```

Use your real HTTPS server address. Do not expose host-control ports publicly or use insecure remote transport as a workaround.

## Run and inspect

```powershell
.\run.ps1
.\status.ps1
```

The agent is a separate process from the desktop client. Closing the Jace desktop window does not automatically stop an independently running Device Agent. An always-on Windows service/tray launcher is a **future packaging/operations milestone**, not guaranteed by this command.

## Approvals and execution modes

Host operations must satisfy **both** Core-side tool/permission policy and applicable Device Agent local policy. Configured execution scopes and terminal sessions are not equivalent to a kernel-level sandbox. High-impact actions must require approval; a remote model cannot redefine host permissions.

The relevant implementation contracts are:

- [Device Agent foundation](../docs/architecture/device-agent.md)
- [Device Capability Broker](../docs/architecture/device-capability-broker.md)
- [Persistent process runtime](../docs/architecture/persistent-process-runtime.md)
- [Interactive terminal runtime](../docs/architecture/interactive-terminal-runtime.md)
- [Scoped execution policy](../docs/architecture/scoped-execution-policy.md)
- [Trusted host execution](../docs/architecture/trusted-host-execution.md)

## Cloud-first migration

The VPS runs Jace Core and provider orchestration. Device Agents continue to execute permitted *on-device* actions. Cloud models should receive only policy-approved context and never gain direct device credentials.

See [master roadmap](../docs/roadmap/cloud-first-master-roadmap.md).
