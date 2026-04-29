# API Schema

Status: draft

Aviary uses DTO-style request schemas so providers can expose different
support levels while clients keep one stable integration shape.

The public session creation schema is split into standard DTO groups plus
provider-specific options:

```json
{
  "provider": "claude-code",
  "conversation_id": "conv_001",
  "model": {},
  "runtime": {},
  "generation": {},
  "policy": {},
  "sandbox": {},
  "skills": {},
  "provider_options": {},
  "metadata": {}
}
```

`metadata` is non-authoritative caller metadata for correlation only. It must
not be used as a security boundary, authorization source, quota key, or secret
lookup key.

## ModelConfig

```json
{
  "name": "private-sonnet",
  "fallback": "private-haiku"
}
```

Fields:

- `name`: logical or provider model name.
- `fallback`: fallback model when the provider supports it.

## RuntimeConfig

```json
{
  "base_url": "http://model-gateway.internal",
  "api_key_ref": "project_001/anthropic",
  "cwd": "/workspaces/project_001/conv_001",
  "env": {}
}
```

Fields:

- `base_url`: model gateway or provider base URL.
- `api_key_ref`: reference to a server-side secret. It is not a raw API key.
- `cwd`: working directory allocated by the runtime.
- `env`: additional provider environment variables.

Managed deployments should resolve `api_key_ref` server-side and should not
accept raw provider API keys from end users.

In managed Docker mode, `runtime.cwd` is not used as a host path. The sandbox
driver allocates a server-owned workspace and mounts it into the provider
runtime as `/workspace`.

In managed Docker mode, arbitrary caller `env` is not copied into the container
spec. The current driver only emits managed keys such as `AVIARY_SESSION_ID`,
`AVIARY_PROVIDER`, `AVIARY_WORKSPACE`, `AVIARY_MODEL`, `ANTHROPIC_BASE_URL`,
and `AVIARY_API_KEY_REF`.

## GenerationConfig

```json
{
  "temperature": 0.2,
  "top_p": 0.9,
  "max_tokens": 4096,
  "stop": []
}
```

Fields:

- `temperature`
- `top_p`
- `max_tokens`
- `stop`

Providers may not support these controls. Clients must inspect provider
capabilities before assuming they take effect.

## PolicyConfig

```json
{
  "execution_mode": "approve_edits",
  "approval_mode": "broker",
  "approval_timeout_seconds": 300,
  "allowed_tools": ["Read", "Write"],
  "disallowed_tools": ["Bash"],
  "filesystem": "workspace_only",
  "network": "deny_by_default",
  "allowed_hosts": ["model-gateway.internal"]
}
```

Fields:

- `execution_mode`: one of `default`, `read_only`, `approve_edits`, `auto`, `bypass`.
- `approval_mode`: one of `provider_native`, `broker`, `auto_deny`.
- `approval_timeout_seconds`: max time a brokered tool permission request waits
  before Aviary denies it.
- `allowed_tools`: normalized or provider tool names.
- `disallowed_tools`: normalized or provider tool names.
- `filesystem`: one of `workspace_only`, `read_only`, `unrestricted`.
- `network`: one of `deny_by_default`, `allowlist`, `unrestricted`.
- `allowed_hosts`: network allowlist entries.

Sandbox enforcement is required before filesystem and network policy can be
considered production-safe.

Current Docker guardrails reject `bypass`, `filesystem=unrestricted`,
`network=unrestricted`, and `network=allowlist` without `allowed_hosts`.
Provider-native permission modes remain defense-in-depth; they are not the
primary security boundary.

With `approval_mode=broker`, provider-native permission requests are routed to
Aviary instead of blocking on a CLI prompt. The backend exposes pending requests
through:

```http
GET  /v1/sessions/{session_id}/approvals
POST /v1/sessions/{session_id}/approvals/{approval_id}:decide
```

Decision payload:

```json
{
  "decision": "approve",
  "reason": "User approved this file edit."
}
```

## SandboxConfig

```json
{
  "profile": "default",
  "workspace_retention": "delete",
  "timeout_seconds": 1800
}
```

Fields:

- `profile`: server-defined runtime profile. The server maps it to Docker,
  Kubernetes, or other sandbox settings.
- `workspace_retention`: one of `delete`, `snapshot`, `keep`.
- `timeout_seconds`: hard upper bound for the session runtime when supported.

The public schema intentionally avoids exposing Docker socket, host path, or
privileged container controls. Managed deployments should keep those decisions
server-side.

`profile` is resolved by the server into a sandbox profile. For Docker this
maps to image, non-root user, resource limits, read-only rootfs, dropped
capabilities, and network policy defaults.

## SkillConfig

```json
{
  "names": ["reviewer"],
  "sources": [
    {
      "type": "local_path",
      "path": "/mnt/aviary-skills/team-a"
    },
    {
      "type": "s3_uri",
      "uri": "s3://company-agent-skills/claude"
    }
  ],
  "auto_allow_skill_tool": true
}
```

Fields:

- `names`: optional list of Claude Code skill names, or `"all"` to expose all
  discovered skills.
- `sources`: skill sources that Aviary materializes into a local
  `.claude/skills` directory before starting the provider.
- `auto_allow_skill_tool`: when true, Aviary adds the Claude Code `Skill` tool
  to `allowed_tools` for the session.

Supported source types:

- `local_path`: absolute path already visible inside the Aviary service
  container. The path may be a single skill directory containing `SKILL.md`, a
  root containing multiple skill directories, or a project directory containing
  `.claude/skills/`.
- `s3_uri`: S3 prefix such as `s3://bucket/path/to/skills`. This requires
  optional S3 materialization dependencies or an equivalent server-side
  materializer. If S3 is mounted into the container with tools such as
  Mountpoint for Amazon S3 or `s3fs-fuse`, use `local_path` instead.

Skill sources are standard DTOs. Clients should not use
`provider_options.setting_sources` or raw provider settings to load arbitrary
filesystem configuration.

## Provider Options

`provider_options` contains provider-specific fields. For Claude Code, examples
include:

```json
{
  "resume": "previous-claude-session-id",
  "max_turns": 5,
  "mcp_servers": {}
}
```

Provider-specific fields should not become cross-provider public contract unless
they are promoted into one of the standard DTO groups.

Do not put provider-specific control fields in `metadata`; metadata is only for
caller-side correlation.

## Capability Support Levels

Providers expose support levels through:

```http
GET /v1/providers/{provider}/capabilities
```

Support levels:

- `supported`: provider natively supports the DTO group.
- `partial`: provider supports some fields or requires additional runtime layers.
- `unsupported`: provider does not support the DTO group.
- `provider_specific`: fields are available only under `provider_options`.

Example:

```json
{
  "provider": "claude-code",
  "config_schema": {
    "model": {
      "level": "supported",
      "fields": ["name", "fallback"]
    },
    "generation": {
      "level": "unsupported",
      "fields": ["temperature", "top_p", "max_tokens", "stop"],
      "notes": "Claude Agent SDK options do not currently expose these generation controls directly."
    }
  }
}
```
