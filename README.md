# CLI Agent Proxy

**Sandbox-first runtime gateway for CLI coding agents.**

CLI Agent Proxy turns CLI agents into a managed backend runtime. It gives
application builders one API to create isolated sessions, stream agent events,
interrupt runs, enforce policies, and clean up runtime environments.

First provider: Claude Code.
Next providers: Codex, Gemini CLI, OpenCode, ACP-compatible agents.

中文名：**CLI Agent 代理**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Runtime](https://img.shields.io/badge/runtime-uv-2f80ed)](https://docs.astral.sh/uv/)
[![API](https://img.shields.io/badge/API-HTTP%20%2B%20SSE-0f766e)](#api-preview)
[![Architecture](https://img.shields.io/badge/architecture-sandbox--first-black)](docs/sandbox-architecture.md)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Not Another Claude Wrapper

Most integrations stop at "call the CLI from a server". That is not enough for
SaaS, private deployments, or multi-user products.

CLI Agent Proxy treats the runtime as the product:

```text
Application backend
  -> CLI Agent Proxy control API
    -> sandbox manager
      -> per-session runtime sandbox
        -> Claude Code / Codex / Gemini CLI / OpenCode / ACP
```

The important unit is not only the provider. It is:

```text
one session -> one sandbox -> one workspace -> one credential context
```

Provider-native permissions are useful, but they are defense-in-depth. The real
security boundary should be the container, pod, or hardened sandbox that runs
the agent.

## What It Solves

- **Unified API**: one Session, Message, Event, Policy, and Sandbox contract for
  many CLI agents.
- **Private deployment**: designed for offline, intranet, Docker Compose, and
  Kubernetes environments.
- **Per-session isolation**: every managed session can have its own workspace,
  credentials, network policy, and lifecycle.
- **Provider capability discovery**: clients inspect what each provider supports
  instead of assuming all agents behave the same.
- **Event-first UX**: stream normalized events for UI rendering, audit logs,
  replay, approvals, and observability.

## Current Status

This is an early open-source foundation. It is intentionally honest about what
is implemented today and what is architectural direction.

Implemented:

- FastAPI HTTP/SSE API.
- Claude Code provider through `claude-agent-sdk`.
- Session create/get/delete.
- SSE message streaming.
- Provider capabilities endpoint.
- `SandboxDriver` runtime boundary.
- `LocalUnsafeSandboxDriver` for development.
- Initial DTO schema for model, runtime, generation, policy, sandbox, and
  provider-specific options.

Planned:

- Docker sandbox driver with one container per session.
- Workspace allocator and secret resolver.
- Durable session, run, event, approval, and audit storage.
- Policy engine and approval API.
- Codex provider and provider conformance tests.
- Docker Compose and Helm deployment assets.

## Architecture

```text
Client / bamboo / product backend / ChatOps adapter
        |
        | HTTP API / SSE
        v
Control Plane
  - public API
  - session registry
  - policy validation
  - provider routing
  - event and audit persistence
        |
        | internal runtime protocol
        v
Sandbox Manager
  - sandbox driver
  - workspace allocation
  - secret injection
  - resource limits
  - timeout cleanup
        |
        | Docker / Kubernetes / local unsafe
        v
Provider Runtime Sandbox
  - provider adapter
  - SDK or CLI process
  - normalized event mapping
```

Current local development path:

```text
FastAPI
  -> SessionManager
    -> LocalUnsafeSandboxDriver
      -> ClaudeCodeProvider
        -> claude-agent-sdk
```

`LocalUnsafeSandboxDriver` is not a production isolation boundary. It exists so
provider support can be built quickly while the production Docker/Kubernetes
drivers are implemented behind the same interface.

Design references:

- [Product design](docs/product-design.md)
- [Sandbox architecture](docs/sandbox-architecture.md)
- [API schema](docs/api-schema.md)
- [Claude Code provider](docs/claude-code-provider.md)

## Quick Start

Install dependencies:

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
  -d '{
    "provider": "claude-code",
    "conversation_id": "demo-conv",
    "model": {"name": "private-sonnet"},
    "sandbox": {"profile": "default", "timeout_seconds": 1800},
    "policy": {"execution_mode": "approve_edits"}
  }'
```

Stream a message:

```bash
curl -N -X POST http://localhost:9000/v1/sessions/<session_id>/messages:stream \
  -H 'content-type: application/json' \
  -d '{"message":"Inspect this repository and summarize the architecture."}'
```

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
  "sandbox": {
    "profile": "default",
    "workspace_retention": "delete",
    "timeout_seconds": 1800
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
  },
  "metadata": {
    "external_trace_id": "trace-001"
  }
}
```

Providers have different support levels for each DTO group. Use:

```http
GET /v1/providers/{provider}/capabilities
```

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

### Interrupt And Close

```http
POST   /v1/sessions/{session_id}/interrupt
DELETE /v1/sessions/{session_id}
```

## Docker

Build and run the current API container:

```bash
docker build -t cli-agent-proxy .
docker run --rm -p 9000:9000 cli-agent-proxy
```

This image runs the API service. It does not yet provide per-session Docker
sandboxes. The production Docker sandbox driver is on the roadmap and will run
provider runtimes in separate containers.

## Security Direction

Defaults we intend to preserve:

- Do not mount the Docker socket into the public API container.
- Do not share host home directories, SSH keys, Git credentials, `~/.claude`, or
  `~/.codex` across sessions.
- Do not accept raw provider API keys from end-user payloads.
- Do not use `metadata` for authorization, secret lookup, sandbox policy, or
  provider options.
- Do not default to permission bypass modes.
- Allocate and validate workspaces server-side in managed mode.
- Serialize requests per session to avoid corrupting interactive agent state.
- Persist events and audit records before production use.

## Roadmap

- `v0.1`: Claude Code proof of concept, local unsafe sandbox driver, SSE stream,
  memory storage.
- `v0.2`: durable event schema, persisted sessions/runs/events, policy
  validation.
- `v0.3`: Docker sandbox driver, workspace allocator, secret resolver, audit log.
- `v0.4`: approval API, network/filesystem enforcement, Docker Compose.
- `v0.5`: Codex provider and provider conformance tests.
- `v1.0`: stable OpenAPI, SDK examples, Helm chart, production hardening guide.

## License

MIT
