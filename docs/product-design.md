# Aviary Product Design

Status: draft  
Last updated: 2026-04-29

Chinese product name: Aviary
Engineering name: `aviary`

## 1. Product Definition

Aviary is an offline-first runtime gateway for CLI agents.

It gives application backends one stable API for creating, streaming,
interrupting, auditing, and destroying agent sessions while each session runs in
its own managed runtime environment.

The name intentionally points to a collection of isolated habitats rather than
one generic proxy: different providers can run in different managed enclosures
under a shared backend contract.

```text
Application backend
  -> Aviary control API
    -> sandbox manager
      -> per-session runtime sandbox
        -> Claude Code / Codex / Gemini CLI / OpenCode / ACP / future agents
```

The first provider is Claude Code. The product must not become a Claude-only
wrapper.

## 2. Core Positioning

Aviary is:

- A runtime control plane for CLI agents.
- A sandbox lifecycle manager for agent sessions.
- A provider-neutral API for upper-layer Agent products.
- A self-hosted component that can run inside private networks.
- An event-first interface for audit, replay, approvals, and UI streaming.

Aviary is not:

- A model gateway.
- A chat bridge like cc-connect.
- A local config switcher like CC Switch.
- A single-user desktop wrapper.
- A replacement for provider-native SDKs.

## 3. Design Principles

### Sandbox First

The primary security boundary is the runtime sandbox, not the provider's own
permission mode.

```text
one session
  -> one sandbox
    -> one workspace
      -> one short-lived credential context
```

Provider-native sandboxing and permission modes are defense-in-depth. They are
useful, but they cannot be the only isolation layer for SaaS or multi-user
platform scenarios.

### Offline First

The system must run without a public control plane:

- local Docker Compose
- private cloud VM
- private Kubernetes cluster
- enterprise intranet

Telemetry is absent or disabled by default. Production dependencies must have
self-hosted alternatives.

### Provider Neutral

Each provider advertises capabilities instead of pretending every agent supports
the same features.

Examples:

- Claude Code supports session resume, tools, permission modes, and file edits.
- Codex may expose different sandbox flags and CLI lifecycle behavior.
- ACP-compatible agents may expose a protocol but not all CLI-specific features.

### Event First

Agent output is a stream of normalized events, not just final text. Upper-layer
products need to persist, audit, replay, interrupt, and render the whole run.

## 4. Reference Architecture

```text
Client / bamboo / product backend / ChatOps adapter
        |
        | HTTP API / SSE
        v
Control Plane
  - public API and OpenAPI schema
  - auth integration hooks
  - session registry
  - policy validation
  - provider routing
  - event and audit persistence
  - approval state
        |
        | internal runtime protocol
        v
Sandbox Manager
  - sandbox driver selection
  - workspace allocation
  - secret injection
  - resource limits
  - timeout cleanup
  - interrupt and kill escalation
  - event forwarding
        |
        | Docker / Kubernetes / local unsafe
        v
Provider Runtime Sandbox
  - one runtime per session
  - provider adapter process
  - provider SDK or CLI
  - normalized event mapping
        |
        v
Agent Provider
  - claude-code
  - codex
  - gemini-cli
  - opencode
  - acp
```

The Control Plane must not run untrusted provider SDKs in production. It should
own policy and routing, while the Sandbox Manager owns process and container
lifecycle.

## 5. Runtime Modes

### Local Unsafe

Current implementation mode:

```text
FastAPI process
  -> SessionManager
    -> LocalUnsafeSandboxDriver
      -> provider adapter in the same process
```

This mode is useful for development and provider integration tests. It is not a
security boundary and must not be described as production isolation.

The default `AVIARY_SANDBOX_MODE` is `local-unsafe` so contributors can run the
project without Docker. Managed deployments must opt into a sandbox mode
explicitly.

### Single-Node Production

Target first production deployment:

```text
api container
  -> sandbox manager container
    -> Docker Engine
      -> one provider runtime container per session
```

Only the Sandbox Manager should have Docker authority. The public API container
must not mount the Docker socket.

The current code has started this path by implementing the Docker runtime
specification boundary: server-owned workspace allocation, hardened
`DockerContainerSpec`, managed policy guardrails, and a `DockerRuntimeClient`
protocol. It also includes a Docker CLI runtime client with an injectable
command runner plus a short-lived `aviary-runtime` CLI worker. The actual
Claude Code runtime image and full production deployment wiring are still
planned.

The first managed mode is `AVIARY_SANDBOX_MODE=docker-cli`. It wires the control
plane to `DockerSandboxDriver` and `DockerCliRuntimeClient`; Docker authority
should belong to a sandbox manager context, not a public API container.

### Kubernetes Production

Target large deployment:

```text
control plane deployment
  -> sandbox manager/controller
    -> one pod or job per session
```

Kubernetes deployments should use NetworkPolicies, Pod Security Admission,
resource quotas, secret manager integration, and ephemeral or PVC-backed
workspaces.

## 6. Session Lifecycle

```text
create session
  -> validate provider and policy
  -> allocate server-owned workspace
  -> resolve short-lived credentials
  -> create sandbox
  -> start provider runtime
  -> report session ready
  -> stream message runs
  -> interrupt or complete
  -> close session
  -> revoke credentials
  -> stop sandbox
  -> delete or snapshot workspace
```

The lifecycle is the core product. Provider adapters are plugins inside that
lifecycle.

## 7. Code Boundaries

Current code has these initial boundaries:

- `main.py`: FastAPI route wiring.
- `session_manager.py`: session state and serialization lock.
- `sandbox/`: runtime boundary abstraction.
- `providers/`: provider-specific SDK/CLI option mapping and event mapping.
- `schemas.py`: public DTOs and event models.

Planned production boundaries:

- `control/`: session service, policy service, approval service.
- `storage/`: session, run, event, approval, and audit repositories.
- `runtime/`: internal JSONL protocol and container-side CLI worker.
- `sandbox/docker.py`: Docker runtime spec driver and future engine adapter.
- `sandbox/kubernetes.py`: Kubernetes driver.

## 8. Public API Draft

Initial API surface:

```http
GET    /healthz
GET    /v1/providers
GET    /v1/providers/{provider}/capabilities
POST   /v1/sessions
GET    /v1/sessions/{session_id}
POST   /v1/sessions/{session_id}/messages:stream
POST   /v1/sessions/{session_id}/interrupt
DELETE /v1/sessions/{session_id}
```

Planned API surface:

```http
POST   /v1/sessions/{session_id}/approvals/{approval_id}
GET    /v1/sessions/{session_id}/events
GET    /v1/sessions/{session_id}/workspace
```

Create session example:

```json
{
  "provider": "claude-code",
  "conversation_id": "conv_001",
  "model": {
    "name": "private-sonnet",
    "fallback": "private-haiku"
  },
  "runtime": {
    "base_url": "http://model-gateway.internal",
    "api_key_ref": "project_001/anthropic",
    "cwd": "/workspaces/project_001/conv_001",
    "env": {}
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
    "allowed_hosts": ["model-gateway.internal"],
    "allowed_tools": ["Read", "Write"],
    "disallowed_tools": ["Bash"]
  },
  "provider_options": {
    "resume": "previous-provider-session-id",
    "max_turns": 5
  },
  "metadata": {
    "external_trace_id": "trace_001"
  }
}
```

`metadata` is non-authoritative correlation data only. It must not control
authorization, secret lookup, workspace allocation, provider options, or sandbox
policy.

## 9. Provider Contract

Each provider adapter implements:

```text
create_session(session_id, request)
stream_message(session_id, message) -> event stream
interrupt(session_id)
close(session_id)
capabilities() -> ProviderCapabilities
```

Provider adapters should only map provider-native options and provider-native
events. They should not allocate host workspaces, read secrets directly from
caller payloads, or decide sandbox lifecycle.

## 10. Security Model

Production minimums:

- No privileged provider runtime containers.
- No host home directory mounts.
- No shared SSH keys, Git credentials, `~/.claude`, `~/.codex`, or model tokens.
- Workspaces are allocated and validated server-side.
- Network is deny-by-default with explicit allowlists.
- Credentials are injected through secret references or model gateways.
- Long-lived provider API keys are not accepted from end-user payloads.
- Sessions have idle and hard timeouts.
- Containers have CPU, memory, pids, disk, and output limits.
- Dangerous actions flow through approvals.
- Every run emits auditable events.

Docker socket access is high risk. If used, it belongs only in an internal
Sandbox Manager process, never in the public API process.

## 11. First Provider: Claude Code

Claude Code runs through the Python `claude-agent-sdk`.

```text
provider runtime
  -> claude-agent-sdk
    -> ClaudeSDKClient
      -> Claude Code process
        -> ANTHROPIC_BASE_URL / private model gateway
```

Claude Code / Claude Agent SDK does not provide an official standalone HTTP
daemon. Aviary provides the HTTP/SSE service and uses the SDK inside a
runtime process.

Details are documented in [claude-code-provider.md](claude-code-provider.md).

## 12. Relationship To Existing Tools

### cc-connect

cc-connect is a useful reference for broad agent support, hooks, commands,
multi-project workflows, and ACP ideas. It is primarily a chat bridge:

```text
IM/chat platform -> local AI coding agent
```

Aviary is a runtime gateway:

```text
application backend -> secure runtime API -> sandboxed agent session
```

Use cc-connect as a source of provider and UX ideas, not as the core
architecture unless it is heavily refactored around strong runtime isolation.

### CC Switch

CC Switch is useful for understanding provider configuration switching. It does
not provide the managed session runtime API required by upper-layer products.

## 13. Roadmap

### v0.1

- FastAPI proof of concept.
- Claude Code provider.
- Local unsafe sandbox driver.
- Session create/get/delete.
- SSE stream endpoint.
- Provider capabilities endpoint.

### v0.2

- Normalized durable event schema.
- Session and event persistence.
- Runtime mode configuration.
- Policy validation.
- Provider session resume metadata.

### v0.3

- Docker sandbox driver.
- Workspace allocator.
- Resource limits.
- Secret resolver.
- Audit log.

### v0.4

- Approval API.
- Network and filesystem enforcement.
- Production hardening guide.
- Docker Compose deployment.

### v0.5

- Codex provider.
- Generic CLI provider conformance tests.
- Provider runtime protocol hardening.

### v1.0

- Stable OpenAPI.
- SDK examples.
- Helm chart.
- Bamboo integration example.

## 14. Decisions To Preserve

- Do not build only a Claude Code wrapper.
- Do not treat provider permission modes as the primary security boundary.
- Do not let raw provider messages become the stable public API.
- Do not let callers choose arbitrary host workspaces in managed mode.
- Do not inject long-lived provider credentials into agent sandboxes.
- Do not default to permission bypass modes.
- Keep deployment offline-first and self-hosted.
- Keep provider support capability-driven.
