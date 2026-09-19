# Jace Device Agent

The Device Agent runs on an authorised computer and makes an outbound
connection to Jace Core.

Phase 4B.S5 provides:

- device pairing;
- secure OS credential storage;
- machine identity;
- capability advertisement;
- outbound WebSocket connection;
- heartbeat;
- automatic reconnect;
- Core-side live connection tracking.

It deliberately does **not** execute remote shell/filesystem/process actions.
That begins in Phase 4B.S6 through the Capability Broker.

## Install

```powershell
.\install.ps1
```

## Pair

Generate a pairing code through Jace Core, then:

```powershell
.\pair.ps1 -PairingCode "jace_pair_..."
```

For a VPS:

```powershell
.\pair.ps1 `
  -Server https://jace.example.com `
  -PairingCode "jace_pair_..." `
  -Name BEN-DESKTOP
```

Remote non-HTTPS URLs are rejected by default.

## Run

```powershell
.\run.ps1
```

The process is independent of the desktop UI. Closing the Jace desktop window
does not inherently stop this process.

Automatic Windows startup/tray behaviour is intentionally left for the
background/tray integration milestone; this foundation focuses on the trusted
transport itself.
