<h1 align="center">Aviary</h1>

<p align="center">
  <strong>Self-hosted runtime backend for CLI coding agents.</strong>
</p>

<p align="center">
  Run Claude Code today, and Codex, Gemini CLI, OpenCode, ACP-compatible agents, and future providers next,
  behind one HTTP/SSE API with isolated workspaces, policies, streaming events, and private deployment support.
</p>

<p align="center">
  <a href="README.zh-CN.md">Read in Simplified Chinese</a>
  |
  <a href="#quick-start">Quick Start</a>
  |
  <a href="#architecture">Architecture</a>
  |
  <a href="#security-model">Security</a>
  |
  <a href="docs/product-design.md">Design</a>
</p>

<p align="center">
  <a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue"></a>
  <a href="https://docs.astral.sh/uv/"><img alt="uv" src="https://img.shields.io/badge/runtime-uv-2f80ed"></a>
  <a href="#api-preview"><img alt="HTTP SSE API" src="https://img.shields.io/badge/API-HTTP%20%2B%20SSE-0f766e"></a>
  <a href="docs/sandbox-architecture.md"><img alt="Sandbox First" src="https://img.shields.io/badge/architecture-sandbox--first-black"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>

<p align="center">
  <img src="docs/assets/aviary-system-map.svg" alt="Aviary system map">
</p>

## What Is Aviary?

Aviary is a backend runtime layer for teams building their own AI agent
frontends, SaaS products, internal dev tools, or ChatOps workflows.

It does not try to become another model gateway or agent framework. It hosts
CLI-agent providers as managed runtime sessions:

```text
one session -> one sandbox -> one workspace -> one short-lived credential context
```

Think of it as a managed aviary for agent runtimes: different providers,
policies, workspaces, model gateways, and runtime profiles can coexist behind
one backend API without forcing your product to integrate each CLI directly.

## Why Aviary?

| If you are building... | Aviary gives you... |
| --- | --- |
| A coding-agent SaaS backend | Session, stream, interrupt, close, policy, and provider routing APIs |
| A private agent platform | Self-hosted runtime control with private model gateway support |
| A multi-provider agent product | Capability discovery instead of hardcoded provider assumptions |
| A secure workspace runtime | Per-session workspace and credential boundaries as the product direction |
| An observable agent UI | Normalized SSE events for UI streaming, audit, replay, and approvals |

## Current Status

Aviary is early. The core boundary is in place, but production sandbox drivers
are still planned.

| Area | Status |
| --- | --- |
| FastAPI HTTP/SSE service | Implemented |
| Claude Code provider via `claude-agent-sdk` | Implemented |
| Session create/get/delete | Implemented |
| Message streaming over SSE | Implemented |
| Provider capabilities endpoint | Implemented |
| DTO schema for model/runtime/generation/policy/sandbox/provider options | Implemented |
| `SandboxDriver` runtime boundary | Implemented |
| `LocalUnsafeSandboxDriver` | Implemented, development only |
| Docker one-container-per-session driver | Planned |
| Kubernetes pod/job driver | Planned |
| Persistent sessions, runs, events, approvals, audit | Planned |
| Codex, Gemini CLI, OpenCode, ACP providers | Planned |

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
uv run uvicorn aviary.main:app --reload --host 0.0.0.0 --port 9000
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
      "timeout_seconds": 1800
    },
    "policy": {
      "execution_mode": "approve_edits",
      "filesystem": "workspace_only",
      "network": "deny_by_default"
    }
  }'
```

Stream a message:

```bash
curl -N -X POST http://localhost:9000/v1/sessions/<session_id>/messages:stream \
  -H 'content-type: application/json' \
  -d '{"message":"Inspect this repository and summarize the runtime architecture."}'
```

## Architecture

<p align="center">
  <img src="docs/assets/aviary-runtime-layers.svg" alt="Aviary runtime layer boundaries">
</p>

Aviary separates three responsibilities:

| Boundary | Owns | Must not own |
| --- | --- | --- |
| Control Plane | Public API, session registry, policy validation, provider routing, event persistence, approvals | Provider SDK processes, Docker socket access, raw secret injection |
| Sandbox Manager | Sandbox lifecycle, workspace allocation, resource limits, secret delivery, cleanup, interrupt escalation | Public product API semantics |
| Provider Runtime | Provider SDK or CLI process, provider-native option mapping, normalized event mapping | Host workspace allocation, authorization, long-lived secrets |

Current development path:

```text
FastAPI
  -> SessionManager
    -> LocalUnsafeSandboxDriver
      -> ClaudeCodeProvider
        -> claude-agent-sdk
```

`LocalUnsafeSandboxDriver` is intentionally named unsafe. It runs provider
adapters in the API process and is not a production isolation boundary.

## Session Lifecycle

<p align="center">
  <img src="docs/assets/aviary-session-lifecycle.svg" alt="Aviary session lifecycle">
</p>

Aviary is designed around the full session lifecycle, not only prompt
submission. The runtime must be able to validate policy, allocate workspace,
inject short-lived credentials, start the provider runtime, stream normalized
events, interrupt safely, and clean up the sandbox.

## API Preview

### Provider Capabilities

```http
GET /v1/providers
GET /v1/providers/{provider}/capabilities
```

Capabilities tell clients what each provider can actually honor. For example,
Claude Code currently supports model selection and provider-specific options,
but direct generation controls such as `temperature` are declared unsupported.

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
  "policy": {
    "execution_mode": "approve_edits",
    "allowed_tools": ["Read", "Write"],
    "disallowed_tools": ["Bash"],
    "filesystem": "workspace_only",
    "network": "deny_by_default"
  },
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

`metadata` is correlation data only. It is not a security boundary, secret
lookup key, workspace selector, or provider option source.

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

## Security Model

The security model is deliberately stricter than provider-native permission
modes.

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

Provider-native sandbox flags are useful defense-in-depth. The primary security
boundary belongs to the runtime sandbox.

## Deployment Model

Current local/API container:

```bash
docker build -t aviary .
docker run --rm -p 9000:9000 aviary
```

Target single-node deployment:

```text
api container
  -> internal sandbox manager container
    -> Docker Engine
      -> provider runtime container per session
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

## Contributing

Issues and pull requests are welcome. The project is still establishing its
provider runtime boundary, so design discussions are valuable before large
implementation changes.

## License

MIT
