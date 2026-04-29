# CLI Agent Proxy

**One secure API for sandboxed coding agents.**

CLI Agent Proxy is an offline-first, self-hosted runtime gateway for Agent and
CLI-agent systems. It lets upper-layer products and private deployments run Claude Code
first, then Codex, Gemini CLI, OpenCode, ACP-compatible agents, and future
coding agents through one consistent Session, Message, Event, Approval, and
Workspace API.

中文名：**CLI Agent 代理**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Runtime](https://img.shields.io/badge/runtime-uv-2f80ed)](https://docs.astral.sh/uv/)
[![API](https://img.shields.io/badge/API-HTTP%20%2B%20SSE-0f766e)](#api-preview)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Why

Modern Agent products increasingly want to embed coding agents, but every agent
has a different runtime model:

- Claude Code uses the Claude Agent SDK and its own session/process model.
- Codex, Gemini CLI, OpenCode, and other tools expose different CLI or protocol
  behaviors.
- Platforms need isolation, auditability, policy, quotas, approval
  gates, and private deployment.

CLI Agent Proxy provides a runtime interface layer so upper-layer products do
not need to directly integrate every agent vendor.

```text
Application backend / bamboo / private Agent platform
  -> CLI Agent Proxy unified runtime API
    -> sandboxed provider adapters
      -> Claude Code / Codex / Gemini CLI / OpenCode / ACP / future agents
```

## What It Is

CLI Agent Proxy is:

- **Offline-first**: designed for private cloud, intranet, Docker Compose, and
  Kubernetes deployments.
- **Platform-oriented**: treats `session_id`, runtime config, policy, and
  workspace allocation as first-class concepts.
- **Provider-neutral**: starts with Claude Code, but the contract is designed
  for many Agent and CLI Agent providers.
- **Event-first**: streams normalized events instead of exposing unstable raw
  provider messages as the product API.
- **Security-domain aware**: designed around per-session sandboxing, workspace
  isolation, policy, and audit logs.

It is not:

- a model gateway
- a chat platform bridge
- a local config switcher
- a single-user desktop wrapper

## Current Status

This repository is in early bootstrap stage.

Implemented now:

- FastAPI service skeleton
- Claude Code provider with Claude Agent SDK option construction and event mapping
- session create/get/delete
- SSE message stream endpoint
- provider capabilities endpoint
- in-memory session manager
- initial product design document

Planned next:

- normalized event schema
- persistent storage
- Docker sandbox driver
- production policy and approval model
- production Claude Code process hardening

## Architecture

Production architecture is designed around a Control Plane and Worker Plane:

```text
Client / bamboo / Application backend / ChatOps adapter
        |
        | HTTP API / SSE / WebSocket
        v
Control Plane
  - OpenAPI
  - auth integration hooks
  - session registry
  - runtime policy
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
```

The design source of truth is [docs/product-design.md](docs/product-design.md).
The API DTO schema is documented in [docs/api-schema.md](docs/api-schema.md).
Claude Code provider details are documented in
[docs/claude-code-provider.md](docs/claude-code-provider.md).

## Claude Code First

The first provider is Claude Code:

```text
worker
  -> claude-agent-sdk
    -> ClaudeSDKClient
      -> Claude Code process
        -> ANTHROPIC_BASE_URL / private model gateway
```

Important: Claude Code / Claude Agent SDK does not provide an official
standalone HTTP daemon. CLI Agent Proxy provides the HTTP/SSE runtime service
and uses the SDK inside the worker.

## API Preview

### Create Session

```http
POST /v1/sessions
```

```json
{
  "provider": "claude-code",
  "conversation_id": "bamboo-conv-001",
  "model": {
    "name": "private-sonnet",
    "fallback": "private-haiku"
  },
  "runtime": {
    "base_url": "http://model-gateway:8080",
    "api_key_ref": "project-a/anthropic",
    "cwd": "/workspaces/project-a/bamboo-conv-001",
    "env": {}
  },
  "generation": {
    "temperature": 0.2,
    "top_p": 0.9,
    "max_tokens": 4096
  },
  "policy": {
    "execution_mode": "approve_edits",
    "allowed_tools": ["Read", "Write"],
    "disallowed_tools": ["Bash"],
    "filesystem": "workspace_only",
    "network": "deny_by_default",
    "allowed_hosts": ["model-gateway.internal"]
  },
  "system_prompt": "You are Bamboo's coding agent.",
  "provider_options": {
    "resume": "previous-claude-session-id",
    "max_turns": 5,
    "mcp_servers": {}
  }
}
```

Providers have different support levels for each DTO group. Use
`GET /v1/providers/{provider}/capabilities` to inspect support for `model`,
`runtime`, `generation`, `policy`, and `provider_options`.

### Stream Message

```http
POST /v1/sessions/{session_id}/messages:stream
```

Returns `text/event-stream`:

```text
event: start
data: {"type":"start","session_id":"...","data":{"provider":"claude-code"}}

event: ai_chunk
data: {"type":"ai_chunk","session_id":"...","data":{"content":"I will inspect the project..."}}

event: end
data: {"type":"end","session_id":"...","data":{}}
```

### Interrupt Session

```http
POST /v1/sessions/{session_id}/interrupt
```

### Delete Session

```http
DELETE /v1/sessions/{session_id}
```

## Quick Start

Install dependencies with `uv`:

```bash
uv sync --extra dev
```

Run tests:

```bash
uv run pytest
```

Start the API:

```bash
uv run uvicorn cli_agent_proxy.main:app --reload --host 0.0.0.0 --port 9000
```

Create a session:

```bash
curl -s http://localhost:9000/v1/sessions \
  -H 'content-type: application/json' \
  -d '{"provider":"claude-code","conversation_id":"demo-conv"}'
```

## Docker

```bash
docker build -t cli-agent-proxy .
docker run --rm -p 9000:9000 cli-agent-proxy
```

## Security Defaults We Intend To Preserve

- Do not allow arbitrary `cwd` in managed mode; allocate and validate workspaces
  server-side.
- Do not accept user-supplied provider API keys; inject credentials through
  secrets or an internal model gateway.
- Do not default to permission bypass modes.
- Do not share host home directories, SSH keys, Git credentials, `~/.claude`,
  or `~/.codex` across sessions.
- Serialize requests per session to avoid corrupting interactive agent state.
- Persist session metadata and audit events outside process memory before
  production use.

## Roadmap

- `v0.1`: Claude Code proof of concept, SSE stream, memory storage.
- `v0.2`: normalized event schema, capabilities endpoint, persisted sessions.
- `v0.3`: Docker sandbox driver, workspace allocator, audit log.
- `v0.4`: policy engine, approval API, network/filesystem/tool restrictions.
- `v0.5`: Codex provider and provider conformance tests.
- `v1.0`: stable OpenAPI, SDK examples, Docker Compose, Helm chart, production
  hardening guide.

## License

MIT
