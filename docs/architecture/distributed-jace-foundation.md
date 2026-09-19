# Distributed Jace Foundation

## Status

Architecture contract for Phase 4B.S.

This document describes the boundaries that future Jace development must preserve as Jace evolves from a local desktop assistant into a distributed assistant platform.

## Core Principle

Jace is not the desktop application.

Jace is a persistent assistant platform.

Desktop, web, mobile and voice interfaces are clients of Jace.

Language models are reasoning providers used by Jace.

Computers are devices connected to Jace.

## Primary Components

### Jace Core

Jace Core owns persistent assistant state and orchestration.

Responsibilities include:

* users and authentication;
* conversations;
* projects;
* memory;
* working context;
* knowledge graph;
* agents;
* Agent Director workflows;
* tasks;
* automations;
* notifications;
* permissions;
* audit history;
* model routing;
* privacy policy;
* integrations;
* device registry.

Jace Core must not assume that it is running on the same machine as the computer being controlled.

### Jace Client

A Jace Client is a user interface connected to Jace Core.

Initial client:

* Windows desktop application.

Future clients:

* web;
* mobile;
* voice-specific interfaces.

Clients display state and submit user requests.

Clients are not the authoritative source of persistent Jace state.

### Jace Device Agent

A Jace Device Agent represents an authorised computer.

It exposes approved capabilities such as:

* filesystem access;
* PowerShell;
* CMD;
* Bash;
* WSL;
* applications;
* processes;
* screenshots;
* desktop interaction;
* microphone;
* speakers;
* local model providers.

The Device Agent establishes an outbound authenticated connection to Jace Core.

Jace Core must not require a publicly exposed remote-control port on a user's computer.

### Capability Broker

The Capability Broker routes a capability request to the correct execution environment.

A request conceptually contains:

* request ID;
* user ID;
* agent ID;
* task/workflow ID;
* project ID;
* device ID;
* requested capability;
* parameters;
* permission state;
* timeout;
* idempotency information.

Example:

User requests a build.

Jace determines:

* project: Jace;
* device: BEN-DESKTOP;
* capability: terminal.execute;
* working directory: the Jace project mount.

The capability is then executed on BEN-DESKTOP rather than on whichever server happens to host Jace Core.

### Model Gateway

Jace must not directly depend on a single inference provider.

The Model Gateway exposes provider-independent operations such as:

* streaming chat;
* non-streaming generation;
* structured generation;
* tool-aware generation;
* embeddings;
* vision.

Provider adapters may include:

* Ollama;
* OpenAI;
* Anthropic;
* Gemini;
* self-hosted model servers;
* future providers.

Agents should request capability classes such as:

* conversation.fast;
* reasoning.high;
* coding.high;
* research.high;
* local.private;
* vision;
* memory.extract;

rather than permanently hardcoding model names.

### Privacy Gateway

External inference must pass through Jace's privacy policy.

Possible processing includes:

* secret redaction;
* PII detection;
* pseudonymisation;
* generalisation;
* project-specific restrictions;
* provider restrictions;
* local-only enforcement.

The language model itself must never be allowed to override privacy policy.

### Event Protocol

Jace clients, Jace Core and Device Agents should converge on a shared event model.

Examples include:

* chat.token;
* chat.completed;
* tool.started;
* tool.output;
* tool.completed;
* tool.failed;
* permission.requested;
* permission.approved;
* agent.started;
* agent.progress;
* agent.completed;
* workflow.completed;
* terminal.output;
* terminal.command.completed;
* device.online;
* device.offline;
* notification.created.

Events should have stable IDs and timestamps and should be attributable to their originating user, workflow, agent, project and device where applicable.

## Deployment Modes

### Local

The desktop connects to a local Jace Core.

Typical endpoint:

http://127.0.0.1:8000

This remains the default development mode.

### Server

Clients connect to a centrally hosted Jace Core using HTTPS/WSS.

Example:

https://jace.example.com

A remote Jace Core may then communicate with connected Device Agents.

## Project Principle

A Project is not a filesystem directory.

A Project is a logical Jace object.

A single Project may have different mounts:

BEN-DESKTOP:

C:\Users\Ben\jace

LAPTOP:

C:\Development\Jace

SERVER:

/srv/projects/jace

All mounts represent the same logical Project.

## State Ownership

Jace Core owns:

* users;
* projects;
* conversations;
* memories;
* tasks;
* agents;
* workflows;
* automation definitions;
* notification history;
* permissions;
* audit records.

Device Agents own or expose:

* local files;
* local shell sessions;
* processes;
* applications;
* GUI state;
* local audio devices;
* local model runtimes.

## Security Rule

The following services must not normally be exposed publicly:

* PostgreSQL;
* Redis;
* Ollama;
* Device Agent control APIs;
* local shells;
* worker administration APIs.

Normal public access should occur through Jace Core over HTTPS/WSS.

## Migration Rule

Existing working Jace capabilities should be migrated behind these abstractions incrementally.

Do not rewrite working agents, tools or UI features solely for architectural purity.

The transition should preserve local mode throughout development.

## Phase 4B.S1

The first implementation establishes:

* configurable Jace Core location;
* local/server deployment terminology;
* HTTP/WebSocket endpoint abstraction;
* this architecture contract.

It does not yet introduce:

* remote authentication;
* Device Agent pairing;
* PostgreSQL;
* remote shell execution;
* cloud model routing.

Those follow as separate tested milestones.
