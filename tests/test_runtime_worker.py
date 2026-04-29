from collections.abc import AsyncIterator

import pytest

from aviary.providers.base import AgentProvider
from aviary.runtime.protocol import RuntimeCommand, encode_event
from aviary.runtime.worker import RuntimeEnvironment, RuntimeWorker
from aviary.schemas import AgentEvent, CreateSessionRequest, ProviderCapabilities, ProviderName


class RecordingProvider(AgentProvider):
    name = ProviderName.CLAUDE_CODE.value

    def __init__(self, events: list[AgentEvent] | None = None, error: Exception | None = None) -> None:
        self.events = events or []
        self.error = error
        self.created: list[tuple[str, CreateSessionRequest]] = []
        self.messages: list[tuple[str, str]] = []
        self.interrupted: list[str] = []
        self.closed: list[str] = []

    async def create_session(self, session_id: str, request: CreateSessionRequest) -> None:
        self.created.append((session_id, request))

    async def stream_message(self, session_id: str, message: str) -> AsyncIterator[AgentEvent]:
        self.messages.append((session_id, message))
        if self.error is not None:
            raise self.error
        for event in self.events:
            yield event

    async def interrupt(self, session_id: str) -> None:
        self.interrupted.append(session_id)

    async def close(self, session_id: str) -> None:
        self.closed.append(session_id)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider=ProviderName.CLAUDE_CODE)


@pytest.mark.asyncio
async def test_runtime_worker_query_builds_managed_request_from_environment():
    provider = RecordingProvider(
        events=[
            AgentEvent(
                type="ai_chunk",
                session_id="session-1",
                conversation_id="session-1",
                data={"content": "hello"},
            )
        ]
    )
    worker = RuntimeWorker(
        provider_factory=lambda provider_name: provider,
        environment=RuntimeEnvironment(
            session_id="session-1",
            provider="claude-code",
            workspace="/workspace",
            model="private-sonnet",
            base_url="http://model-gateway.internal",
            api_key_ref="project-a/anthropic",
        ),
    )
    command = RuntimeCommand(type="query", session_id="session-1", payload={"message": "inspect"})

    events = [event async for event in worker.handle(command)]

    assert events == provider.events
    assert provider.messages == [("session-1", "inspect")]
    created_request = provider.created[0][1]
    assert created_request.provider == "claude-code"
    assert created_request.conversation_id == "session-1"
    assert created_request.model.name == "private-sonnet"
    assert created_request.runtime.cwd == "/workspace"
    assert created_request.runtime.base_url == "http://model-gateway.internal"
    assert created_request.runtime.api_key_ref == "project-a/anthropic"
    assert created_request.runtime.env == {}


@pytest.mark.asyncio
async def test_runtime_worker_rejects_cross_session_command():
    worker = RuntimeWorker(
        provider_factory=lambda provider_name: RecordingProvider(),
        environment=RuntimeEnvironment(session_id="session-1", provider="claude-code"),
    )
    command = RuntimeCommand(type="query", session_id="other-session", payload={"message": "inspect"})

    events = [event async for event in worker.handle(command)]

    assert [event.type for event in events] == ["error"]
    assert events[0].session_id == "session-1"
    assert "session mismatch" in events[0].data["detail"]


@pytest.mark.asyncio
async def test_runtime_worker_redacts_secret_like_provider_output():
    provider = RecordingProvider(
        events=[
            AgentEvent(
                type="raw",
                session_id="session-1",
                conversation_id="session-1",
                data={
                    "ANTHROPIC_API_KEY": "sk-ant-secret",
                    "nested": {"token": "secret-token", "safe": "visible"},
                },
            )
        ]
    )
    worker = RuntimeWorker(
        provider_factory=lambda provider_name: provider,
        environment=RuntimeEnvironment(session_id="session-1", provider="claude-code"),
    )

    events = [
        event async for event in worker.handle(RuntimeCommand(type="query", session_id="session-1", payload={"message": "x"}))
    ]

    assert events[0].data == {
        "ANTHROPIC_API_KEY": "[REDACTED]",
        "nested": {"token": "[REDACTED]", "safe": "visible"},
    }


@pytest.mark.asyncio
async def test_runtime_worker_rejects_cross_session_provider_events():
    provider = RecordingProvider(
        events=[
            AgentEvent(
                type="ai_chunk",
                session_id="other-session",
                conversation_id="other-session",
                data={"content": "wrong"},
            )
        ]
    )
    worker = RuntimeWorker(
        provider_factory=lambda provider_name: provider,
        environment=RuntimeEnvironment(session_id="session-1", provider="claude-code"),
    )

    events = [
        event async for event in worker.handle(RuntimeCommand(type="query", session_id="session-1", payload={"message": "x"}))
    ]

    assert [event.type for event in events] == ["error"]
    assert events[0].session_id == "session-1"
    assert "provider emitted event for another session" in events[0].data["detail"]


@pytest.mark.asyncio
async def test_runtime_worker_turns_provider_failure_into_redacted_error_event():
    provider = RecordingProvider(error=RuntimeError("failed with ANTHROPIC_API_KEY=sk-ant-secret"))
    worker = RuntimeWorker(
        provider_factory=lambda provider_name: provider,
        environment=RuntimeEnvironment(session_id="session-1", provider="claude-code"),
    )

    events = [
        event async for event in worker.handle(RuntimeCommand(type="query", session_id="session-1", payload={"message": "x"}))
    ]

    assert [event.type for event in events] == ["error"]
    assert events[0].data["detail"] == "failed with ANTHROPIC_API_KEY=[REDACTED]"


@pytest.mark.asyncio
async def test_runtime_worker_interrupt_and_close_delegate_to_provider():
    provider = RecordingProvider()
    worker = RuntimeWorker(
        provider_factory=lambda provider_name: provider,
        environment=RuntimeEnvironment(session_id="session-1", provider="claude-code"),
    )

    interrupt_events = [
        event async for event in worker.handle(RuntimeCommand(type="interrupt", session_id="session-1"))
    ]
    close_events = [
        event async for event in worker.handle(RuntimeCommand(type="close", session_id="session-1"))
    ]

    assert provider.interrupted == ["session-1"]
    assert provider.closed == ["session-1"]
    assert [event.type for event in interrupt_events] == ["end"]
    assert [event.type for event in close_events] == ["end"]


def test_encode_event_outputs_single_json_line():
    event = AgentEvent(
        type="end",
        session_id="session-1",
        conversation_id="session-1",
        data={"ok": True},
    )

    encoded = encode_event(event)

    assert encoded.endswith("\n")
    assert "\n" not in encoded[:-1]
    assert '"type":"end"' in encoded
