# Sandbox Runtime Architecture

Status: draft  
Last updated: 2026-04-29

This document defines the core architectural direction for Aviary:
container and sandbox lifecycle management is the runtime boundary of the
product.

## 1. Boundary Model

```text
Control Plane
  owns API, sessions, policy, events, approvals

Sandbox Manager
  owns sandbox lifecycle, workspaces, secrets, resources, cleanup

Provider Runtime
  owns provider SDK/CLI process and normalized event mapping
```

The Control Plane should be safe to expose to product backends. The Sandbox
Manager is internal infrastructure with stronger privileges. The Provider
Runtime is isolated per session.

## 2. Session To Sandbox Mapping

Recommended production mapping:

```text
session_id
  -> sandbox_id
    -> workspace_id
      -> credential_context_id
```

One session should not share runtime filesystem, process space, provider client
state, or credentials with another session.

## 3. Driver Interface

The codebase now exposes `SandboxDriver` as the runtime boundary:

```text
create_session(session_id, request)
stream_message(session_id, request) -> AgentEvent stream
interrupt(session_id)
close(session_id)
list_providers()
get_provider_capabilities(provider)
```

Current drivers:

- `LocalUnsafeSandboxDriver`: development only, provider runs in the API
  process.
- `DockerSandboxDriver`: implemented as the managed runtime specification
  boundary. It allocates server-owned workspaces, builds hardened container
  specs, validates unsafe managed policies, and delegates execution to a
  `DockerRuntimeClient`.

Future drivers:

- `KubernetesSandboxDriver`: one pod or job per session.
- hardened container runtimes such as gVisor, Kata, or Firecracker-backed
  workers.

## 4. Local Unsafe Driver

`LocalUnsafeSandboxDriver` intentionally keeps the original fast development
path:

```text
FastAPI
  -> SessionManager
    -> LocalUnsafeSandboxDriver
      -> ClaudeCodeProvider
        -> claude-agent-sdk
```

It is named unsafe because it is not an isolation layer. It should not be used
as the managed production runtime.

## 5. Docker Driver Target

The Docker path is split into two layers.

Implemented now:

```text
POST /v1/sessions
  -> validate managed policy guardrails
  -> create server-owned workspace
  -> build DockerContainerSpec
  -> delegate start/query/interrupt/close to DockerRuntimeClient
  -> clean up workspace according to retention policy
```

Still planned:

```text
  -> resolve short-lived secret references
  -> create isolated Docker network
  -> start non-root provider runtime container
  -> mount workspace only
  -> apply CPU/memory/pids/disk limits
  -> stream runtime events back to control plane
```

Required hardening defaults:

- `--read-only` root filesystem where possible.
- non-root user in provider runtime image.
- no `--privileged`.
- drop Linux capabilities.
- no host home mount.
- no host SSH key or Git credential mount.
- no shared `~/.claude`, `~/.codex`, or provider token directory.
- deny-by-default network with explicit allowlist.
- idle timeout and hard timeout.
- kill escalation after failed graceful interrupt.

The Docker socket must not be mounted into the public API container.
The current code does not import or call a Docker SDK directly; the engine
adapter belongs behind `DockerRuntimeClient` so a sandbox manager can own Docker
authority separately from the public API process.

## 6. Runtime Protocol

The provider runtime inside the sandbox should expose an internal protocol to the
Sandbox Manager. The exact transport can evolve, but the contract should remain
stable:

```text
runtime.start(session_spec)
runtime.query(message_spec) -> event stream
runtime.interrupt()
runtime.close()
runtime.health()
```

The Provider Runtime should normalize SDK/CLI events before forwarding them.
Raw provider events are allowed for diagnostics, but product integrations should
not rely on raw event shape.

The current code represents this boundary with `DockerRuntimeClient`:

```text
create_session(DockerContainerSpec)
stream_message(session_id, message_spec) -> AgentEvent stream
interrupt(session_id)
close(session_id)
```

Tests use a fake runtime client so the control-plane contract is verified
without requiring Docker on the developer machine.

## 7. Policy Enforcement

`PolicyConfig` has two enforcement layers:

- Runtime sandbox enforcement: filesystem, network, process, resource, and
  workspace boundaries.
- Provider-native enforcement: permission mode, allowed tools, disallowed tools,
  approval prompts, and provider-specific sandbox flags.

Provider-native enforcement is defense-in-depth. It should never be the only
security boundary in managed deployments.

Current Docker guardrails reject:

- `execution_mode=bypass`
- `filesystem=unrestricted`
- `network=unrestricted`
- `network=allowlist` without `allowed_hosts`

The Docker driver also ignores caller-supplied `runtime.cwd` for workspace
placement. Managed workspaces are allocated server-side.

## 8. Secrets

Public API requests use `runtime.api_key_ref`, not raw API keys.

Production secret flow:

```text
request api_key_ref
  -> control plane validates caller permission
  -> secret resolver creates short-lived credential context
  -> sandbox manager injects credential into provider runtime
  -> credential revoked when session closes
```

Secrets must not be written to normal event logs or metadata fields.

## 9. Workspace Lifecycle

Workspace handling should be server-owned:

- allocate workspace path or volume server-side
- mount only that workspace into the provider runtime
- validate any caller-supplied path in local unsafe mode only
- delete, snapshot, or keep workspace according to `sandbox.workspace_retention`
- keep retention policy independent from provider behavior

`LocalWorkspaceAllocator` now implements the single-node filesystem version of
this contract. It creates one path per `session_id`, rejects unsafe path
segments, and refuses to release paths outside its configured base directory.

## 10. Implementation Phases

### Phase 1: Boundary Refactor

- Introduce `SandboxDriver`.
- Move provider execution behind `LocalUnsafeSandboxDriver`.
- Keep current FastAPI and test flow working.
- Document local unsafe mode clearly.

### Phase 2A: Docker Runtime Spec Boundary

- Add Docker driver.
- Add workspace allocator.
- Add hardened `DockerContainerSpec`.
- Add runtime client protocol.
- Add policy guardrails for unsafe managed modes.

### Phase 2B: Docker Engine Runtime

- Add runtime container image for Claude Code.
- Add Docker Engine adapter behind `DockerRuntimeClient`.
- Add isolated network creation.
- Add secret resolver integration.
- Add cleanup and timeout worker.

### Phase 3: Production Control Plane

- Persist sessions, runs, events, and approvals.
- Add policy validation.
- Add secret resolver interface.
- Add audit log.
- Add rate limits and auth integration hooks.

### Phase 4: Multi-Provider

- Add Codex provider.
- Add provider conformance tests.
- Add Kubernetes driver.
- Stabilize OpenAPI and SDK examples.
