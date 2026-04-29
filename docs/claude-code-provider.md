# Claude Code Provider

Status: initial SDK support

The `claude-code` provider is the first provider implemented by Aviary.
It uses the Python `claude-agent-sdk` package and `ClaudeSDKClient`
inside the provider runtime process.

## Runtime Path

```text
Sandbox runtime
  -> claude-agent-sdk
    -> ClaudeSDKClient
      -> Claude Code process
        -> ANTHROPIC_BASE_URL / private model gateway
```

Claude Code / Claude Agent SDK does not provide an official standalone HTTP
daemon. Aviary provides the HTTP/SSE API and uses the SDK internally.

## Running Locally

The provider always uses the real Claude Agent SDK path. If the SDK, Claude Code
runtime, credentials, model gateway, or workspace configuration is unavailable,
the stream returns an `error` event instead of synthetic agent output.

Start the API:

```bash
uv run uvicorn aviary.main:app --host 0.0.0.0 --port 9000
```

## Session Configuration

`POST /v1/sessions` accepts the common session fields and maps them to
`ClaudeAgentOptions`.

Standard DTO groups:

- `model`
- `runtime`
- `generation`
- `policy`
- `sandbox`
- `provider_options`

Claude Code currently maps:

- `model.name` -> `ClaudeAgentOptions.model`
- `model.fallback` -> `ClaudeAgentOptions.fallback_model`
- `runtime.base_url` -> `env.ANTHROPIC_BASE_URL`
- `runtime.api_key_ref` -> `env.AVIARY_API_KEY_REF`
- `runtime.cwd` -> `ClaudeAgentOptions.cwd`
- `runtime.env` -> `ClaudeAgentOptions.env`
- `policy.execution_mode` -> `ClaudeAgentOptions.permission_mode`
- `policy.allowed_tools` -> `ClaudeAgentOptions.allowed_tools`
- `policy.disallowed_tools` -> `ClaudeAgentOptions.disallowed_tools`

The `generation` DTO is part of the standard API, but Claude Agent SDK does not
currently expose direct `temperature`, `top_p`, `max_tokens`, or `stop` options.
The Claude Code provider declares this as `unsupported` in capabilities.

Backward-compatible flat fields still accepted during early development:

- `model` as a string
- `cwd`
- `system_prompt`
- `permission_mode`
- `allowed_tools`
- `disallowed_tools`
- `env`

Claude-specific provider options:

- `provider_options.resume`
- `provider_options.continue_conversation`
- `provider_options.max_turns`
- `provider_options.max_budget_usd`
- `provider_options.fallback_model`
- `provider_options.mcp_servers`
- `provider_options.cli_path`
- `provider_options.settings`
- `provider_options.add_dirs`
- `provider_options.extra_args`
- `provider_options.max_buffer_size`
- `provider_options.permission_prompt_tool_name`
- `provider_options.user`
- `provider_options.include_partial_messages`
- `provider_options.fork_session`
- `provider_options.setting_sources`
- `provider_options.skills`
- `provider_options.max_thinking_tokens`
- `provider_options.effort`
- `provider_options.output_format`
- `provider_options.enable_file_checkpointing`
- `provider_options.load_timeout_ms`

`metadata` is not forwarded into Claude SDK options. It is only caller-side
correlation data.

Example:

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
    "api_key_ref": "project/anthropic",
    "cwd": "/workspaces/project-a/conv_001",
    "env": {}
  },
  "generation": {
    "temperature": 0.2,
    "top_p": 0.9,
    "max_tokens": 4096
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
    "network": "deny_by_default",
    "allowed_hosts": ["model-gateway.internal"]
  },
  "system_prompt": "You are an isolated coding agent.",
  "provider_options": {
    "max_turns": 5,
    "resume": "previous-claude-session-id"
  }
}
```

Production deployments should not accept arbitrary `cwd` or user-supplied API
keys. The control plane should allocate workspace paths and inject credentials
through secrets or an internal model gateway.

## Normalized Events

The provider maps Claude Agent SDK messages into common Aviary events:

- `TextBlock` -> `ai_chunk`
- `ThinkingBlock` -> `reasoning_delta`
- `ToolUseBlock` / `ServerToolUseBlock` -> `tool_call`
- `ToolResultBlock` / `ServerToolResultBlock` -> `tool_result`
- `ResultMessage` -> `end`
- provider-specific or unknown messages -> `raw`

Example SSE output:

```text
event: ai_chunk
data: {"type":"ai_chunk","data":{"content":"I will inspect the project..."}}

event: tool_call
data: {"type":"tool_call","data":{"tool_call_id":"tool-1","name":"Read","args":{"file_path":"README.md"}}}

event: end
data: {"type":"end","data":{"provider_session_id":"...","duration_ms":120}}
```

## Capabilities

Capabilities are available at:

```http
GET /v1/providers/claude-code/capabilities
```

Current declared capabilities:

- streaming
- resume
- tools
- file watch
- approval
- model switch

Some capabilities require sandbox and policy layers before they are safe for
managed production use.
