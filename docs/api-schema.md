# API Schema

Status: draft

CLI Agent Proxy uses DTO-style request schemas so providers can expose different
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
  "allowed_tools": ["Read", "Write"],
  "disallowed_tools": ["Bash"],
  "filesystem": "workspace_only",
  "network": "deny_by_default",
  "allowed_hosts": ["model-gateway.internal"]
}
```

Fields:

- `execution_mode`: one of `default`, `read_only`, `approve_edits`, `auto`, `bypass`.
- `allowed_tools`: normalized or provider tool names.
- `disallowed_tools`: normalized or provider tool names.
- `filesystem`: one of `workspace_only`, `read_only`, `unrestricted`.
- `network`: one of `deny_by_default`, `allowlist`, `unrestricted`.
- `allowed_hosts`: network allowlist entries.

Sandbox enforcement is required before filesystem and network policy can be
considered production-safe.

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
