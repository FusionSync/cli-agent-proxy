from collections.abc import AsyncIterator

import pytest
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)

from cli_agent_proxy.providers.claude_code import ClaudeCodeProvider
from cli_agent_proxy.schemas import CreateSessionRequest, ExecutionMode


class StubClaudeClient:
    def __init__(self, messages: list[object]) -> None:
        self.messages = messages
        self.connected = False
        self.disconnected = False
        self.interrupted = False
        self.queries: list[tuple[str, str]] = []

    async def connect(self) -> None:
        self.connected = True

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.queries.append((prompt, session_id))

    async def receive_messages(self) -> AsyncIterator[object]:
        for message in self.messages:
            yield message

    async def interrupt(self) -> None:
        self.interrupted = True

    async def disconnect(self) -> None:
        self.disconnected = True


@pytest.mark.asyncio
async def test_claude_code_provider_builds_sdk_options_and_streams_normalized_events():
    captured_options = []
    stub_client = StubClaudeClient(
        [
            AssistantMessage(
                model="claude-test",
                content=[
                    TextBlock(text="hello"),
                    ThinkingBlock(thinking="considering", signature="sig"),
                    ToolUseBlock(id="tool-1", name="Read", input={"file_path": "README.md"}),
                    ToolResultBlock(tool_use_id="tool-1", content="ok", is_error=False),
                ],
                session_id="claude-session-1",
            ),
            ResultMessage(
                subtype="success",
                duration_ms=120,
                duration_api_ms=100,
                is_error=False,
                num_turns=1,
                session_id="claude-session-1",
                total_cost_usd=0.01,
                usage={"input_tokens": 10, "output_tokens": 5},
            ),
        ]
    )

    async def fake_factory(options):
        captured_options.append(options)
        await stub_client.connect()
        return stub_client

    provider = ClaudeCodeProvider(client_factory=fake_factory)
    request = CreateSessionRequest(
        provider="claude-code",
        conversation_id="conv-1",
        model="private-sonnet",
        cwd="/tmp/workspace",
        system_prompt="system",
        permission_mode="acceptEdits",
        allowed_tools=["Read"],
        disallowed_tools=["Bash"],
        env={"ANTHROPIC_BASE_URL": "http://model-gateway"},
        metadata={
            "resume": "resume-session",
            "max_turns": 3,
            "fallback_model": "fallback-model",
            "mcp_servers": {"local": {"type": "stdio", "command": "server"}},
        },
    )
    await provider.create_session("session-1", request)

    events = [event async for event in provider.stream_message("session-1", "inspect repo")]

    assert stub_client.connected is True
    assert stub_client.queries == [("inspect repo", "session-1")]
    assert len(captured_options) == 1
    options = captured_options[0]
    assert options.model == "private-sonnet"
    assert str(options.cwd) == "/tmp/workspace"
    assert options.system_prompt == "system"
    assert options.permission_mode == "acceptEdits"
    assert options.allowed_tools == ["Read"]
    assert options.disallowed_tools == ["Bash"]
    assert options.env["ANTHROPIC_BASE_URL"] == "http://model-gateway"
    assert options.resume == "resume-session"
    assert options.max_turns == 3
    assert options.fallback_model == "fallback-model"
    assert options.mcp_servers == {"local": {"type": "stdio", "command": "server"}}

    assert [event.type for event in events] == [
        "start",
        "ai_chunk",
        "reasoning_delta",
        "tool_call",
        "tool_result",
        "end",
    ]
    assert events[1].data == {"content": "hello", "model": "claude-test"}
    assert events[2].data == {"content": "considering"}
    assert events[3].data == {
        "tool_call_id": "tool-1",
        "name": "Read",
        "args": {"file_path": "README.md"},
    }
    assert events[4].data == {
        "tool_call_id": "tool-1",
        "result": "ok",
        "status": "success",
    }
    assert events[5].data["provider_session_id"] == "claude-session-1"
    assert events[5].data["usage"] == {"input_tokens": 10, "output_tokens": 5}


@pytest.mark.asyncio
async def test_claude_code_provider_interrupts_and_closes_active_client():
    stub_client = StubClaudeClient([])

    async def fake_factory(options):
        await stub_client.connect()
        return stub_client

    provider = ClaudeCodeProvider(client_factory=fake_factory)
    await provider.create_session("session-1", CreateSessionRequest(conversation_id="conv-1"))
    _ = [event async for event in provider.stream_message("session-1", "hello")]

    await provider.interrupt("session-1")
    await provider.close("session-1")

    assert stub_client.interrupted is True
    assert stub_client.disconnected is True


def test_claude_code_provider_capabilities():
    capabilities = ClaudeCodeProvider().capabilities()

    assert capabilities.provider == "claude-code"
    assert capabilities.supports_streaming is True
    assert capabilities.supports_resume is True
    assert "model" in capabilities.session_config_fields
    assert capabilities.config_schema["model"].level == "supported"
    assert capabilities.config_schema["generation"].level == "unsupported"


@pytest.mark.asyncio
async def test_claude_code_provider_maps_structured_session_dtos_to_sdk_options():
    captured_options = []
    stub_client = StubClaudeClient([])

    async def fake_factory(options):
        captured_options.append(options)
        await stub_client.connect()
        return stub_client

    provider = ClaudeCodeProvider(client_factory=fake_factory)
    request = CreateSessionRequest(
        provider="claude-code",
        conversation_id="conv-structured",
        model={"name": "private-sonnet", "fallback": "private-haiku"},
        runtime={
            "base_url": "http://model-gateway",
            "api_key_ref": "project/anthropic",
            "cwd": "/tmp/structured",
            "env": {"EXTRA": "1"},
        },
        policy={
            "execution_mode": ExecutionMode.APPROVE_EDITS,
            "allowed_tools": ["Read", "Write"],
            "disallowed_tools": ["Bash"],
            "filesystem": "workspace_only",
            "network": "deny_by_default",
            "allowed_hosts": ["model-gateway"],
        },
        generation={"temperature": 0.2, "top_p": 0.9, "max_tokens": 4096},
        provider_options={"resume": "resume-id", "max_turns": 4},
    )

    await provider.create_session("session-structured", request)
    _ = [event async for event in provider.stream_message("session-structured", "hello")]

    options = captured_options[0]
    assert options.model == "private-sonnet"
    assert options.fallback_model == "private-haiku"
    assert str(options.cwd) == "/tmp/structured"
    assert options.permission_mode == "acceptEdits"
    assert options.allowed_tools == ["Read", "Write"]
    assert options.disallowed_tools == ["Bash"]
    assert options.env == {
        "ANTHROPIC_BASE_URL": "http://model-gateway",
        "CLI_AGENT_PROXY_API_KEY_REF": "project/anthropic",
        "EXTRA": "1",
    }
    assert options.resume == "resume-id"
    assert options.max_turns == 4


@pytest.mark.asyncio
async def test_real_sdk_mode_returns_error_event_when_client_creation_fails():
    async def failing_factory(options):
        raise RuntimeError("sdk unavailable")

    provider = ClaudeCodeProvider(client_factory=failing_factory)
    await provider.create_session("session-1", CreateSessionRequest(conversation_id="conv-1"))

    events = [event async for event in provider.stream_message("session-1", "hello")]

    assert [event.type for event in events] == ["start", "error"]
    assert events[1].data["detail"] == "sdk unavailable"
