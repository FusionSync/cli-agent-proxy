from collections.abc import AsyncIterator
import os
from typing import Any

from cli_agent_proxy.providers.base import AgentProvider
from cli_agent_proxy.schemas import AgentEvent, CreateSessionRequest, ProviderName


class ClaudeCodeProvider(AgentProvider):
    name = ProviderName.CLAUDE_CODE.value

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}
        self._requests: dict[str, CreateSessionRequest] = {}

    async def create_session(self, session_id: str, request: CreateSessionRequest) -> None:
        self._requests[session_id] = request

    async def stream_message(self, session_id: str, message: str) -> AsyncIterator[AgentEvent]:
        request = self._requests[session_id]
        yield AgentEvent(
            type="start",
            session_id=session_id,
            conversation_id=request.conversation_id,
            data={"provider": self.name, "model": request.model},
        )

        client = await self._get_client(session_id, request)
        if client is None:
            # Development fallback keeps the API testable without a live Claude Code binary.
            yield AgentEvent(
                type="ai_chunk",
                session_id=session_id,
                conversation_id=request.conversation_id,
                data={"content": f"[mock claude-code] {message}"},
            )
            yield AgentEvent(
                type="end",
                session_id=session_id,
                conversation_id=request.conversation_id,
                data={"provider_session_id": None},
            )
            return

        await client.query(message, session_id=session_id)
        async for sdk_message in client.receive_messages():
            yield self._map_sdk_message(session_id, request.conversation_id, sdk_message)

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

        if os.getenv("CLI_AGENT_PROXY_ENABLE_REAL_CLAUDE") != "1":
            return None

        try:
            from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        except Exception:
            return None

        options_kwargs: dict[str, Any] = {}
        if request.cwd:
            options_kwargs["cwd"] = request.cwd
        if request.model:
            options_kwargs["model"] = request.model
        if request.system_prompt:
            options_kwargs["system_prompt"] = request.system_prompt
        if request.permission_mode:
            options_kwargs["permission_mode"] = request.permission_mode
        if request.allowed_tools:
            options_kwargs["allowed_tools"] = request.allowed_tools
        if request.disallowed_tools:
            options_kwargs["disallowed_tools"] = request.disallowed_tools
        if request.env:
            options_kwargs["env"] = request.env

        try:
            client = ClaudeSDKClient(options=ClaudeAgentOptions(**options_kwargs))
            await client.connect()
        except Exception:
            return None

        self._clients[session_id] = client
        return client

    def _map_sdk_message(self, session_id: str, conversation_id: str, sdk_message: Any) -> AgentEvent:
        message_type = getattr(sdk_message, "type", sdk_message.__class__.__name__)
        if message_type == "assistant" and hasattr(sdk_message, "content"):
            return AgentEvent(
                type="ai_chunk",
                session_id=session_id,
                conversation_id=conversation_id,
                data={"content": str(sdk_message.content)},
            )
        if message_type == "result":
            return AgentEvent(
                type="end",
                session_id=session_id,
                conversation_id=conversation_id,
                data=self._serialize_message(sdk_message),
            )
        return AgentEvent(
            type="raw",
            session_id=session_id,
            conversation_id=conversation_id,
            data={"message": self._serialize_message(sdk_message)},
        )

    def _serialize_message(self, message: Any) -> dict[str, Any]:
        if hasattr(message, "__dict__"):
            return {key: str(value) for key, value in message.__dict__.items() if not key.startswith("_")}
        return {"value": str(message)}
