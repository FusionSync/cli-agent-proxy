<h1 align="center">CLI Agent Proxy</h1>

<p align="center">
  <strong>Sandbox-first runtime gateway for CLI coding agents.</strong>
</p>

<p align="center">
  Turn Claude Code, Codex, Gemini CLI, OpenCode, ACP-compatible agents, and future CLI agents
  into isolated backend runtimes behind one HTTP/SSE API.
</p>

<p align="center">
  <a href="README.zh-CN.md">Read in Simplified Chinese</a>
  |
  <a href="docs/product-design.md">Product Design</a>
  |
  <a href="docs/sandbox-architecture.md">Sandbox Architecture</a>
  |
  <a href="docs/api-schema.md">API Schema</a>
</p>

<p align="center">
  <a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue"></a>
  <a href="https://docs.astral.sh/uv/"><img alt="uv" src="https://img.shields.io/badge/runtime-uv-2f80ed"></a>
  <a href="#api-preview"><img alt="HTTP SSE API" src="https://img.shields.io/badge/API-HTTP%20%2B%20SSE-0f766e"></a>
  <a href="docs/sandbox-architecture.md"><img alt="Sandbox First" src="https://img.shields.io/badge/architecture-sandbox--first-black"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>

```text
Application backend
  -> CLI Agent Proxy control API
    -> Sandbox Manager
      -> per-session runtime sandbox
        -> Claude Code / Codex / Gemini CLI / OpenCode / ACP / future agents
```

## The Short Version

Most "agent server" integrations do one thing: start a CLI process and stream
the output.

CLI Agent Proxy takes a different stance:

```text
one session -> one sandbox -> one workspace -> one credential context
```

The runtime is the product. Provider SDKs and CLIs are plugins inside that
runtime.

That distinction matters when an upper-layer product needs to serve many users,
run inside a private network, isolate workspaces, route private model gateways,
record audit events, enforce approval policy, and shut everything down cleanly.

## Why This Exists

Coding agents are becoming infrastructure. They are no longer only local
developer tools.

Product teams want to embed Claude Code, Codex, Gemini CLI, OpenCode, and
protocol-based agents inside their own systems. But every provider has a
different process model, permission model, config surface, event stream, and
session lifecycle.

CLI Agent Proxy is the missing runtime layer between application backends and
agent providers.

| Problem | CLI Agent Proxy direction |
| --- | --- |
| Every agent has a different API | One Session, Message, Event, Policy, and Sandbox contract |
| Provider sessions are hard to host safely | One managed runtime environment per session |
| SaaS users must not share files or secrets | Workspace, credential, process, and network isolation |
| Private deployments need model gateways | `runtime.base_url` and server-side secret references |
| UI needs more than final text | Normalized SSE events for streaming, audit, replay, and approvals |
| Providers evolve independently | Capability discovery instead of false feature parity |

## Architecture Doctrine

The project is built around three boundaries.

| Boundary | Owns | Must not own |
| --- | --- | --- |
| Control Plane | Public API, sessions, policy validation, provider routing, event persistence, approvals | Provider SDK processes, Docker socket access, raw secret injection |
| Sandbox Manager | Sandbox lifecycle, workspace allocation, resource limits, secret delivery, cleanup, interrupt escalation | Public product API semantics |
| Provider Runtime | Provider SDK or CLI process, provider-native option mapping, normalized event mapping | Host workspace allocation, authorization, long-lived secrets |

Production shape:

```text
Client / product backend / ChatOps adapter
        |
        | HTTP API / SSE
        v
Control Plane
  - OpenAPI surface
  - session and run registry
  - policy validation
  - provider routing
  - event and audit persistence
        |
        | internal runtime protocol
        v
Sandbox Manager
  - Docker or Kubernetes driver
  - workspace allocator
  - secret resolver
  - resource and timeout enforcement
  - graceful interrupt, then kill escalation
        |
        | per-session sandbox
        v
Provider Runtime
  - Claude Agent SDK / Codex CLI / Gemini CLI / OpenCode / ACP
  - normalized event stream
  - provider-native permissions as defense-in-depth
```

Provider-native permission modes are useful. They are not the primary security
boundary. In managed deployments, filesystem, network, process, and credential
boundaries belong to the sandbox layer.

## What Is Implemented Today

This repository is early, but the architectural seam is already in place.

| Area | Status |
| --- | --- |
| FastAPI HTTP/SSE service | Implemented |
| Claude Code provider via `claude-agent-sdk` | Implemented |
| Session create/get/delete | Implemented |
| Message streaming over SSE | Implemented |
| Provider capabilities endpoint | Implemented |
| DTO schema for model/runtime/generation/policy/sandbox/provider options | Implemented |
| `SandboxDriver` boundary | Implemented |
| `LocalUnsafeSandboxDriver` for development | Implemented |
| Docker one-container-per-session driver | Planned |
| Persistent sessions, runs, events, approvals, audit | Planned |
| Secret resolver and workspace allocator | Planned |
| Codex provider | Planned |
| Kubernetes pod/job driver | Planned |

Current local development path:

```text
FastAPI
  -> SessionManager
    -> LocalUnsafeSandboxDriver
      -> ClaudeCodeProvider
        -> claude-agent-sdk
```

`LocalUnsafeSandboxDriver` intentionally says "unsafe" because it runs provider
adapters in the API process. It is a development path, not production isolation.

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

Create a Claude Code session:

```bash
curl -s http://localhost:9000/v1/sessions \
  -H 'content-type: application/json' \
  -d '{
    "provider": "claude-code",
    "conversation_id": "demo-conv",
    "model": {"name": "private-sonnet"},
    "runtime": {
      "base_url": "http://model-gateway.internal",
      "api_key_ref": "project-a/anthropic"
    },
    "sandbox": {
      "profile": "default",
      "workspace_retention": "delete",
      "timeout_seconds": 1800
    },
    "policy": {
      "execution_mode": "approve_edits",
      "filesystem": "workspace_only",
      "network": "deny_by_default",
      "allowed_hosts": ["model-gateway.internal"]
    }
  }'
```

Stream a message:

```bash
curl -N -X POST http://localhost:9000/v1/sessions/<session_id>/messages:stream \
  -H 'content-type: application/json' \
  -d '{"message":"Inspect this repository and summarize the architecture."}'
```

## API Preview

### Provider Capabilities

```http
GET /v1/providers
GET /v1/providers/{provider}/capabilities
```

Capabilities let clients discover support levels before assuming a provider can
honor a field such as `generation.temperature`, `policy.execution_mode`, or
`model.fallback`.

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

`metadata` is non-authoritative. It is never a security boundary, secret lookup
key, workspace selector, or provider option source.

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

event: tool_call
data: {"type":"tool_call","session_id":"...","data":{"name":"Read","args":{"file_path":"README.md"}}}

event: end
data: {"type":"end","session_id":"...","data":{"provider_session_id":"..."}}
```

### Interrupt And Close

```http
POST   /v1/sessions/{session_id}/interrupt
DELETE /v1/sessions/{session_id}
```

## Claude Code First

Claude Code currently runs through the Python `claude-agent-sdk`.

```text
Provider Runtime
  -> claude-agent-sdk
    -> ClaudeSDKClient
      -> Claude Code process
        -> ANTHROPIC_BASE_URL / private model gateway
```

Claude Code / Claude Agent SDK does not provide a standalone HTTP daemon. CLI
Agent Proxy provides the HTTP/SSE service and uses the SDK inside the runtime
boundary.

Provider details: [docs/claude-code-provider.md](docs/claude-code-provider.md)

## Deployment Model

Current Docker image:

```bash
docker build -t cli-agent-proxy .
docker run --rm -p 9000:9000 cli-agent-proxy
```

The current image runs the API service as a non-root user. It does not yet
create one Docker container per session.

Target Docker deployment:

```text
api container
  -> internal sandbox manager container
    -> Docker Engine
      -> provider runtime container for session A
      -> provider runtime container for session B
      -> provider runtime container for session C
```

Target Kubernetes deployment:

```text
control plane deployment
  -> sandbox manager/controller
    -> pod or job per session
      -> network policy
      -> secret manager
      -> ephemeral or PVC-backed workspace
```

## Security Posture

Security defaults we intend to preserve:

- The public API container must not mount the Docker socket.
- Provider runtimes should not run privileged.
- Host home directories, SSH keys, Git credentials, `~/.claude`, and `~/.codex`
  must not be shared across sessions.
- Raw provider API keys should not be accepted from end-user payloads.
- `runtime.api_key_ref` should resolve to server-side secret material.
- Workspaces should be allocated and validated server-side in managed mode.
- Network policy should be deny-by-default.
- Permission bypass modes should not be default behavior.
- Events and audit records should be persisted before production use.

## Roadmap

| Milestone | Focus |
| --- | --- |
| `v0.1` | Claude Code proof of concept, local unsafe sandbox driver, SSE stream, memory storage |
| `v0.2` | Durable event schema, persisted sessions/runs/events, policy validation |
| `v0.3` | Docker sandbox driver, workspace allocator, secret resolver, audit log |
| `v0.4` | Approval API, network/filesystem enforcement, Docker Compose |
| `v0.5` | Codex provider and provider conformance tests |
| `v1.0` | Stable OpenAPI, SDK examples, Helm chart, production hardening guide |

## Documentation

| Document | Purpose |
| --- | --- |
| [Product Design](docs/product-design.md) | Product boundaries, principles, roadmap |
| [Sandbox Architecture](docs/sandbox-architecture.md) | Runtime lifecycle, drivers, isolation model |
| [API Schema](docs/api-schema.md) | DTO groups and provider capability model |
| [Claude Code Provider](docs/claude-code-provider.md) | Claude Agent SDK mapping and event normalization |

## License

MIT
