from collections.abc import AsyncIterator
from collections.abc import Awaitable, Callable
from typing import Any

from cli_agent_proxy.providers.base import AgentProvider
from cli_agent_proxy.schemas import (
    AgentEvent,
    CreateSessionRequest,
    ExecutionMode,
    ProviderCapabilities,
    ProviderName,
    ProviderOptionSupport,
    SupportLevel,
)

ClaudeClientFactory = Callable[[Any], Awaitable[Any]]


class ClaudeCodeProvider(AgentProvider):
    name = ProviderName.CLAUDE_CODE.value

    def __init__(self, *, client_factory: ClaudeClientFactory | None = None) -> None:
        self._clients: dict[str, Any] = {}
        self._requests: dict[str, CreateSessionRequest] = {}
        self._client_factory = client_factory

    async def create_session(self, session_id: str, request: CreateSessionRequest) -> None:
        self._requests[session_id] = request

    async def stream_message(self, session_id: str, message: str) -> AsyncIterator[AgentEvent]:
        request = self._requests[session_id]
        conversation_id = request.conversation_id or session_id
        yield AgentEvent(
            type="start",
            session_id=session_id,
            conversation_id=conversation_id,
            data={"provider": self.name, "model": request.model.name},
        )

        try:
            client = await self._get_client(session_id, request)
        except Exception as exc:
            yield AgentEvent(
                type="error",
                session_id=session_id,
                conversation_id=conversation_id,
                data={"detail": str(exc)},
            )
            return
        await client.query(message, session_id=session_id)
        async for sdk_message in client.receive_messages():
            for event in self._map_sdk_message(session_id, conversation_id, sdk_message):
                yield event

    async def interrupt(self, session_id: str) -> None:
        client = self._clients.get(session_id)
        if client and hasattr(client, "interrupt"):
            await client.interrupt()

    async def close(self, session_id: str) -> None:
        client = self._clients.pop(session_id, None)
        self._requests.pop(session_id, None)
        if client and hasattr(client, "disconnect"):
            await client.disconnect()

    async def _get_client(self, session_id: str, request: CreateSessionRequest) -> Any:
        if session_id in self._clients:
            return self._clients[session_id]

        try:
            from claude_agent_sdk import ClaudeSDKClient
        except Exception as exc:
            raise RuntimeError(f"claude-agent-sdk is not available: {exc}") from exc

        options = self._build_options(session_id, request)
        if self._client_factory is not None:
            client = await self._client_factory(options)
        else:
            client = ClaudeSDKClient(options=options)
            await client.connect()

        self._clients[session_id] = client
        return client

    def _build_options(self, session_id: str, request: CreateSessionRequest) -> Any:
        from claude_agent_sdk import ClaudeAgentOptions

        metadata = request.metadata
        provider_options = {**request.provider_options, **metadata}
        env = {
            **request.runtime.env,
            **request.env,
        }
        if request.runtime.base_url:
            env["ANTHROPIC_BASE_URL"] = request.runtime.base_url
        if request.runtime.api_key_ref:
            env["CLI_AGENT_PROXY_API_KEY_REF"] = request.runtime.api_key_ref

        options_kwargs: dict[str, Any] = {"session_id": str(metadata.get("session_id") or session_id)}
        cwd = request.runtime.cwd or request.cwd
        if cwd:
            options_kwargs["cwd"] = cwd
        model = request.model.name
        if model:
            options_kwargs["model"] = model
        if request.model.fallback:
            options_kwargs["fallback_model"] = request.model.fallback
        if request.system_prompt:
            options_kwargs["system_prompt"] = request.system_prompt
        permission_mode = self._map_permission_mode(request)
        if permission_mode:
            options_kwargs["permission_mode"] = permission_mode
        allowed_tools = request.policy.allowed_tools or request.allowed_tools
        if allowed_tools:
            options_kwargs["allowed_tools"] = allowed_tools
        disallowed_tools = request.policy.disallowed_tools or request.disallowed_tools
        if disallowed_tools:
            options_kwargs["disallowed_tools"] = disallowed_tools
        if env:
            options_kwargs["env"] = env

        for key in (
            "resume",
            "continue_conversation",
            "max_turns",
            "max_budget_usd",
            "fallback_model",
            "mcp_servers",
            "cli_path",
            "settings",
            "add_dirs",
            "extra_args",
            "max_buffer_size",
            "permission_prompt_tool_name",
            "user",
            "include_partial_messages",
            "fork_session",
            "setting_sources",
            "skills",
            "max_thinking_tokens",
            "effort",
            "output_format",
            "enable_file_checkpointing",
            "load_timeout_ms",
        ):
            if key in provider_options and provider_options[key] is not None:
                options_kwargs[key] = provider_options[key]

        return ClaudeAgentOptions(**options_kwargs)

    def _map_permission_mode(self, request: CreateSessionRequest) -> str | None:
        if request.permission_mode:
            return request.permission_mode
        return {
            ExecutionMode.DEFAULT: None,
            ExecutionMode.READ_ONLY: "plan",
            ExecutionMode.APPROVE_EDITS: "acceptEdits",
            ExecutionMode.AUTO: "auto",
            ExecutionMode.BYPASS: "bypassPermissions",
        }[request.policy.execution_mode]

    def _map_sdk_message(self, session_id: str, conversation_id: str, sdk_message: Any) -> list[AgentEvent]:
        message_type = getattr(sdk_message, "type", sdk_message.__class__.__name__)
        if sdk_message.__class__.__name__ == "AssistantMessage" and hasattr(sdk_message, "content"):
            return self._map_assistant_message(session_id, conversation_id, sdk_message)
        if message_type == "result" or sdk_message.__class__.__name__ == "ResultMessage":
            if getattr(sdk_message, "is_error", False):
                return [
                    AgentEvent(
                        type="error",
                        session_id=session_id,
                        conversation_id=conversation_id,
                        data=self._serialize_message(sdk_message),
                    )
                ]
            return [AgentEvent(
                type="end",
                session_id=session_id,
                conversation_id=conversation_id,
                data={
                    "provider_session_id": getattr(sdk_message, "session_id", None),
                    "duration_ms": getattr(sdk_message, "duration_ms", None),
                    "duration_api_ms": getattr(sdk_message, "duration_api_ms", None),
                    "num_turns": getattr(sdk_message, "num_turns", None),
                    "stop_reason": getattr(sdk_message, "stop_reason", None),
                    "total_cost_usd": getattr(sdk_message, "total_cost_usd", None),
                    "usage": getattr(sdk_message, "usage", None),
                    "result": getattr(sdk_message, "result", None),
                },
            )]
        return [AgentEvent(
            type="raw",
            session_id=session_id,
            conversation_id=conversation_id,
            data={"message": self._serialize_message(sdk_message)},
        )]

    def _map_assistant_message(self, session_id: str, conversation_id: str, sdk_message: Any) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        model = getattr(sdk_message, "model", None)
        for block in getattr(sdk_message, "content", []) or []:
            block_name = block.__class__.__name__
            if block_name == "TextBlock":
                events.append(
                    AgentEvent(
                        type="ai_chunk",
                        session_id=session_id,
                        conversation_id=conversation_id,
                        data={"content": getattr(block, "text", ""), "model": model},
                    )
                )
            elif block_name == "ThinkingBlock":
                events.append(
                    AgentEvent(
                        type="reasoning_delta",
                        session_id=session_id,
                        conversation_id=conversation_id,
                        data={"content": getattr(block, "thinking", "")},
                    )
                )
            elif block_name in {"ToolUseBlock", "ServerToolUseBlock"}:
                events.append(
                    AgentEvent(
                        type="tool_call",
                        session_id=session_id,
                        conversation_id=conversation_id,
                        data={
                            "tool_call_id": getattr(block, "id", None),
                            "name": getattr(block, "name", None),
                            "args": getattr(block, "input", None),
                        },
                    )
                )
            elif block_name in {"ToolResultBlock", "ServerToolResultBlock"}:
                is_error = bool(getattr(block, "is_error", False))
                events.append(
                    AgentEvent(
                        type="tool_result",
                        session_id=session_id,
                        conversation_id=conversation_id,
                        data={
                            "tool_call_id": getattr(block, "tool_use_id", None),
                            "result": getattr(block, "content", None),
                            "status": "error" if is_error else "success",
                        },
                    )
                )
            else:
                events.append(
                    AgentEvent(
                        type="raw",
                        session_id=session_id,
                        conversation_id=conversation_id,
                        data={"message": self._serialize_message(block)},
                    )
                )
        return events

    def _serialize_message(self, message: Any) -> dict[str, Any]:
        if hasattr(message, "__dict__"):
            return {key: str(value) for key, value in message.__dict__.items() if not key.startswith("_")}
        return {"value": str(message)}

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=ProviderName.CLAUDE_CODE,
            supports_streaming=True,
            supports_resume=True,
            supports_tools=True,
            supports_file_watch=True,
            supports_approval=True,
            supports_model_switch=True,
            session_config_fields=[
                "model",
                "model.name",
                "model.fallback",
                "runtime.base_url",
                "runtime.api_key_ref",
                "runtime.cwd",
                "runtime.env",
                "generation",
                "policy.execution_mode",
                "policy.allowed_tools",
                "policy.disallowed_tools",
                "provider_options",
                "system_prompt",
            ],
            config_schema={
                "model": ProviderOptionSupport(
                    level=SupportLevel.SUPPORTED,
                    fields=["name", "fallback"],
                ),
                "runtime": ProviderOptionSupport(
                    level=SupportLevel.PARTIAL,
                    fields=["base_url", "api_key_ref", "cwd", "env"],
                    notes="base_url maps to ANTHROPIC_BASE_URL. api_key_ref is exposed as CLI_AGENT_PROXY_API_KEY_REF until secret resolution is implemented.",
                ),
                "generation": ProviderOptionSupport(
                    level=SupportLevel.UNSUPPORTED,
                    fields=["temperature", "top_p", "max_tokens", "stop"],
                    notes="Claude Agent SDK options do not currently expose these generation controls directly.",
                ),
                "policy": ProviderOptionSupport(
                    level=SupportLevel.PARTIAL,
                    fields=["execution_mode", "allowed_tools", "disallowed_tools"],
                    notes="execution_mode maps to Claude permission_mode. Filesystem and network policy require sandbox enforcement.",
                ),
                "provider_options": ProviderOptionSupport(
                    level=SupportLevel.PROVIDER_SPECIFIC,
                    fields=[
                        "resume",
                        "continue_conversation",
                        "max_turns",
                        "max_budget_usd",
                        "mcp_servers",
                        "cli_path",
                        "settings",
                        "add_dirs",
                        "extra_args",
                        "max_buffer_size",
                        "permission_prompt_tool_name",
                        "user",
                        "include_partial_messages",
                        "fork_session",
                        "setting_sources",
                        "skills",
                        "max_thinking_tokens",
                        "effort",
                        "output_format",
                        "enable_file_checkpointing",
                        "load_timeout_ms",
                    ],
                ),
            },
            event_types=[
                "start",
                "ai_chunk",
                "reasoning_delta",
                "tool_call",
                "tool_result",
                "error",
                "end",
                "raw",
            ],
        )
