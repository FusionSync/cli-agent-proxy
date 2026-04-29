# Claude Code Provider

Status: initial SDK support

The `claude-code` provider is the first provider implemented by CLI Agent
Proxy. It uses the Python `claude-agent-sdk` package and `ClaudeSDKClient`
inside the worker process.

## Runtime Path

```text
CLI Agent Proxy worker
  -> claude-agent-sdk
    -> ClaudeSDKClient
      -> Claude Code process
        -> ANTHROPIC_BASE_URL / private model gateway
```

Claude Code / Claude Agent SDK does not provide an official standalone HTTP
daemon. CLI Agent Proxy provides the HTTP/SSE API and uses the SDK internally.

## Development Fallback

By default, the provider uses a mock fallback. This keeps unit tests and local
API exploration independent from a live Claude Code runtime.

Enable real SDK execution explicitly:

```bash
export CLI_AGENT_PROXY_ENABLE_REAL_CLAUDE=1
```

Then start the API:

```bash
uv run uvicorn cli_agent_proxy.main:app --host 0.0.0.0 --port 9000
```

## Session Configuration

`POST /v1/sessions` accepts the common session fields and maps them to
`ClaudeAgentOptions`.

Direct fields:

- `model`
- `cwd`
- `system_prompt`
- `permission_mode`
- `allowed_tools`
- `disallowed_tools`
- `env`

Claude-specific metadata fields:

- `metadata.resume`
- `metadata.continue_conversation`
- `metadata.max_turns`
- `metadata.max_budget_usd`
- `metadata.fallback_model`
- `metadata.mcp_servers`
- `metadata.cli_path`
- `metadata.settings`
- `metadata.add_dirs`
- `metadata.extra_args`
- `metadata.max_buffer_size`
- `metadata.permission_prompt_tool_name`
- `metadata.user`
- `metadata.include_partial_messages`
- `metadata.fork_session`
- `metadata.setting_sources`
- `metadata.skills`
- `metadata.max_thinking_tokens`
- `metadata.effort`
- `metadata.output_format`
- `metadata.enable_file_checkpointing`
- `metadata.load_timeout_ms`

Example:

```json
{
  "provider": "claude-code",
  "conversation_id": "conv_001",
  "model": "private-sonnet",
  "cwd": "/workspaces/tenant-a/conv_001",
  "system_prompt": "You are an isolated coding agent.",
  "permission_mode": "acceptEdits",
  "allowed_tools": ["Read", "Write"],
  "disallowed_tools": ["Bash"],
  "env": {
    "ANTHROPIC_BASE_URL": "http://model-gateway.internal",
    "ANTHROPIC_API_KEY": "placeholder"
  },
  "metadata": {
    "max_turns": 5,
    "resume": "previous-claude-session-id"
  }
}
```

Production deployments should not accept arbitrary `cwd` or user-supplied API
keys. The control plane should allocate workspace paths and inject credentials
through secrets or an internal model gateway.

## Normalized Events

The provider maps Claude Agent SDK messages into common CLI Agent Proxy events:

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
SaaS production use.
