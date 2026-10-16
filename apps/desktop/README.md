# Jace desktop client

Jace's desktop interface is built with **Tauri 2, React, TypeScript and Vite**. It is a client of Jace Core, not the authoritative storage for assistant state.

## Current development commands

Run from `apps/desktop`:

```powershell
npm ci
npm run dev       # Vite development server
npm run build     # TypeScript check + production frontend build
npm run tauri dev # Launch Tauri desktop, with native prerequisites installed
```

These commands come from the checked-in `package.json`. The Tauri command additionally requires the Windows Rust/Tauri native development prerequisites.

## Connect to Jace Core

Current endpoint and authentication behaviour is configured in the desktop client and Core. Refer to the actual configuration files and [distributed architecture](../../docs/architecture/distributed-jace-foundation.md) rather than assuming every installation uses localhost.

For remote mode, use HTTPS/WSS, server-mode authentication and an authorised device connection for host actions. Do **not** embed cloud-model API keys in frontend environment variables or a Tauri bundle: provider credentials belong in Jace Core's secret boundary.

## UI areas

The desktop currently has chat, agent/office, settings, calendar, connections and computer-related components. The cloud-first roadmap **proposes** additional provider/model selection, task activity, evidence and cost views; these are not claimed to exist yet.

## Architecture and roadmap

- [Repository overview](../../README.md)
- [Documentation index](../../docs/README.md)
- [Cloud-first roadmap](../../docs/roadmap/cloud-first-master-roadmap.md)
- [Cloud intelligence](../../docs/architecture/cloud-intelligence.md)
