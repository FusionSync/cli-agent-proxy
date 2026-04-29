# CLI Agent Proxy Product Design

Status: draft  
Last updated: 2026-04-29

## 1. Product Definition

CLI Agent Proxy is an offline-first, self-hosted runtime gateway for agent and
CLI-agent systems.

It provides one secure API for SaaS products and private deployments to run
Claude Code first, then Codex, Gemini CLI, OpenCode, ACP-compatible agents, and
future coding agents through a consistent session, message, event, approval, and
workspace interface.

Chinese product name: CLI Agent 代理

Engineering name: `cli-agent-proxy`

Positioning:

```text
Upper-layer Agent products / SaaS platforms
  -> CLI Agent Proxy unified runtime API
    -> provider adapters
      -> Claude Code / Codex / Gemini CLI / OpenCode / ACP / future agents
```

## 2. Non-Goals

CLI Agent Proxy is not:

- A model gateway. It may call a model gateway, but does not primarily provide
  LLM completion APIs.
- A chat platform bridge like cc-connect. ChatOps adapters can be built on top,
  but the core API is for SaaS/backend integration.
- A config switcher like CC Switch. Provider configuration is part of runtime
  execution, not the main product.
- A single-user local desktop helper.

## 3. Core Principles

### Offline-First and Self-Hosted

The product must run in customer-controlled environments:

- local Docker Compose
- private cloud VM
- private Kubernetes cluster
- enterprise intranet

No public control plane is required. Telemetry must be disabled by default or
absent. All dependencies required for production operation must have offline or
self-hosted alternatives.

### SaaS-Safe Multi-Tenancy

The primary use case is SaaS vendors embedding third-party agent runtimes into
their own upper-layer Agent products.

`tenant_id`, `user_id`, `session_id`, and `workspace_id` are first-class
concepts. A session must not access another tenant's files, credentials,
processes, model tokens, or network resources.

Default security boundary:

```text
session = security boundary
```

Higher-security deployments should use:

```text
one session -> one sandbox -> one workspace -> one short-lived credential set
```

### Provider Abstraction

The API must not be shaped only around Claude Code. Each provider implements the
same high-level contract and advertises capabilities.

Examples:

- Claude Code may support resume, tool use, file edits, and permission modes.
- Codex may support a different session model.
- ACP-compatible agents may expose a standard protocol but not all CLI-specific
  features.

The system should expose capabilities instead of pretending every provider has
identical behavior.

### Event-First Runtime

The runtime output is a durable event stream, not only final text.

Upper-layer SaaS products need to observe, persist, audit, interrupt, replay,
and display the run process. Provider-specific messages must be normalized into
a stable event schema.

## 4. Reference Architecture

```text
Client / bamboo / SaaS backend / ChatOps adapter
        |
        | HTTP API / SSE / WebSocket
        v
Control Plane
  - OpenAPI
  - auth integration hooks
  - session registry
  - tenant policy
  - provider routing
  - workspace allocation
  - audit log
  - worker scheduling
        |
        | internal RPC / HTTP
        v
Worker Plane
  - provider adapter process lifecycle
  - sandbox lifecycle
  - workspace mount
  - resource limits
  - event streaming
  - interrupt / approval handling
        |
        v
Sandbox Layer
  - local process driver for development only
  - per-session Docker container
  - Kubernetes pod or job
  - future: gVisor, Kata, Firecracker
        |
        v
Provider Adapter
  - claude-code
  - codex
  - gemini-cli
  - opencode
  - acp
```

Control Plane should not directly run untrusted agents in production. It manages
sessions, policies, storage, and worker routing. Worker Plane runs provider
adapters inside an enforceable sandbox.

## 5. First Provider: Claude Code

Claude Code is the first supported provider.

Initial implementation path:

```text
worker
  -> claude-agent-sdk
    -> ClaudeSDKClient
      -> Claude Code process
        -> ANTHROPIC_BASE_URL / private model gateway
```

Important boundary:

Claude Code / Claude Agent SDK does not provide an official standalone HTTP
daemon. CLI Agent Proxy must provide the HTTP/SSE runtime service and use the
SDK inside the worker.

Claude Code provider must support:

- session creation
- streaming messages
- interrupt
- optional resume
- model selection
- workspace cwd
- allowed/disallowed tools where supported
- permission mode where supported
- normalized event mapping

Initial SDK support is documented in
[claude-code-provider.md](claude-code-provider.md).

## 6. Unified Provider Contract

Each provider adapter must implement:

```text
PrepareSession(ctx, spec) -> provider_session
StartRun(ctx, message) -> event stream
Interrupt(ctx)
Close(ctx)
GetCapabilities(ctx) -> capabilities
```

Provider capabilities should include:

```json
{
  "provider": "claude-code",
  "supports_streaming": true,
  "supports_resume": true,
  "supports_tools": true,
  "supports_file_watch": true,
  "supports_approval": true,
  "supports_model_switch": true
}
```

Provider adapters must not expose raw provider-specific behavior directly to
upper-layer products unless wrapped in a namespaced `raw` extension.

## 7. Public API Draft

Initial stable API surface:

```http
GET    /healthz
GET    /v1/providers
GET    /v1/providers/{provider}/capabilities
POST   /v1/sessions
GET    /v1/sessions/{session_id}
POST   /v1/sessions/{session_id}/messages:stream
POST   /v1/sessions/{session_id}/interrupt
POST   /v1/sessions/{session_id}/approvals/{approval_id}
DELETE /v1/sessions/{session_id}
GET    /v1/sessions/{session_id}/events
```

Create session example:

```json
{
  "tenant_id": "tenant_001",
  "user_id": "user_001",
  "provider": "claude-code",
  "conversation_id": "conv_001",
  "model": {
    "name": "private-sonnet",
    "fallback": "private-haiku"
  },
  "runtime": {
    "base_url": "http://model-gateway.internal",
    "api_key_ref": "tenant_001/anthropic",
    "cwd": "/workspaces/tenant_001/conv_001",
    "env": {}
  },
  "generation": {
    "temperature": 0.2,
    "top_p": 0.9,
    "max_tokens": 4096
  },
  "workspace": {
    "mode": "ephemeral"
  },
  "policy": {
    "execution_mode": "approve_edits",
    "filesystem": "workspace_only",
    "network": "deny_by_default",
    "allowed_hosts": ["model-gateway.internal"],
    "allowed_tools": ["read", "write"],
    "disallowed_tools": ["shell"]
  },
  "provider_options": {
    "resume": "previous-provider-session-id",
    "max_turns": 5
  }
}
```

Stream message endpoint returns `text/event-stream`.

## 8. Normalized Event Model

Events must be append-only and sequence-numbered.

Recommended base fields:

```json
{
  "id": "evt_001",
  "type": "message.delta",
  "session_id": "sess_001",
  "run_id": "run_001",
  "tenant_id": "tenant_001",
  "user_id": "user_001",
  "provider": "claude-code",
  "sequence": 12,
  "timestamp": "2026-04-29T08:00:00Z",
  "data": {}
}
```

Initial event types:

- `session.created`
- `session.ready`
- `run.started`
- `message.delta`
- `reasoning.delta`
- `tool.call`
- `tool.result`
- `file.changed`
- `approval.requested`
- `approval.resolved`
- `run.completed`
- `run.failed`
- `session.closed`
- `raw.provider_event`

Raw provider events may be exposed for debugging, but upper-layer integrations
must not depend on raw event shape for stable product behavior.

## 9. SaaS Security Model

Minimum production requirements:

- No privileged worker containers.
- No host home directory mount.
- No shared `~/.claude`, `~/.codex`, SSH keys, git credentials, or model tokens.
- Workspace path is allocated server-side and validated.
- Agent file access is workspace-only by default.
- Network is deny-by-default with explicit allowlist.
- Provider credentials are injected through secrets or model gateway, not
  accepted from end-user request payloads.
- Every shell command, file write, network request, approval, and provider error
  should be auditable.
- Session has idle timeout and hard timeout.
- Worker has CPU, memory, disk, process count, and output size limits.
- Dangerous actions should trigger approval workflow.

Recommended production security boundary:

```text
tenant session
  -> dedicated sandbox
    -> dedicated workspace
      -> short-lived credentials
```

Development mode may support local process execution, but it must be clearly
marked unsafe for SaaS production.

## 10. Deployment Modes

### Local Development

```text
api + worker in one process
memory storage
local process sandbox
```

### Single-Node Private Deployment

```text
Docker Compose
api container
worker container
Postgres or SQLite
Redis optional
per-session Docker sandbox
internal model gateway
```

### Kubernetes Private Deployment

```text
api deployment
worker deployment
Postgres
Redis
per-session pod/job sandbox
network policies
secret manager
persistent volume or ephemeral volume workspaces
```

## 11. Storage Responsibilities

Memory storage is allowed only for local development.

Production storage should persist:

- tenant and user identifiers
- session records
- run records
- provider session ids
- workspace metadata
- event log
- approval records
- audit records
- resource usage

Secrets should not be stored in normal application tables.

## 12. Relationship to Existing Open Source Tools

### cc-connect

cc-connect is a strong reference for:

- broad provider support
- session commands
- hooks
- multi-project concepts
- web admin ideas
- ACP support

But cc-connect is primarily a chat bridge:

```text
IM/chat platform -> local AI coding agent
```

CLI Agent Proxy is a SaaS/runtime gateway:

```text
SaaS backend -> secure runtime API -> sandboxed agent provider
```

Therefore, cc-connect should be used as a reference for provider and UX ideas,
not as the direct product base unless heavily refactored around SaaS tenant
isolation.

### CC Switch

CC Switch is a configuration switcher and desktop management tool. It is useful
for understanding provider configuration patterns, but it does not provide the
runtime session API required by SaaS products.

## 13. Roadmap

### v0.1

- FastAPI proof of concept
- Claude Code provider
- session create/get/delete
- SSE stream endpoint
- memory storage

### v0.2

- normalized event schema
- provider capabilities endpoint
- persisted session/event storage
- interrupt support
- provider session resume metadata

### v0.3

- Docker sandbox driver
- workspace allocator
- per-session resource limits
- audit log

### v0.4

- policy engine
- approval API
- network/filesystem/tool restrictions
- security documentation and threat model

### v0.5

- Codex provider
- generic CLI provider adapter interface
- provider conformance tests

### v1.0

- stable OpenAPI
- SDK examples
- Docker Compose and Helm deployment
- production hardening guide
- bamboo integration example

## 14. Design Decisions to Preserve

- Do not build only a Claude Code wrapper.
- Do not let provider-specific raw messages become the public API.
- Do not treat multi-session as equivalent to multi-tenant security.
- Do not let users pass arbitrary workspace paths in SaaS mode.
- Do not inject long-lived provider credentials into agent sandboxes.
- Do not default to permission bypass modes.
- Do keep deployment offline-first and self-hosted.
- Do keep provider support capability-driven.
