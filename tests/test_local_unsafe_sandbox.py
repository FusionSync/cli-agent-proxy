from collections.abc import AsyncIterator

import pytest

from cli_agent_proxy.providers.base import AgentProvider
from cli_agent_proxy.sandbox.local_unsafe import LocalUnsafeSandboxDriver
from cli_agent_proxy.schemas import (
    AgentEvent,
    CreateSessionRequest,
    ProviderCapabilities,
    ProviderName,
    StreamMessageRequest,
)


class RecordingProvider(AgentProvider):
    name = ProviderName.CLAUDE_CODE.value

    def __init__(self) -> None:
        self.created: list[str] = []
        self.closed: list[str] = []

    async def create_session(self, session_id: str, request: CreateSessionRequest) -> None:
        self.created.append(session_id)

    async def stream_message(self, session_id: str, message: str) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(
            type="ai_chunk",
            session_id=session_id,
            conversation_id=session_id,
            data={"content": message},
        )

    async def interrupt(self, session_id: str) -> None:
        return None

    async def close(self, session_id: str) -> None:
        self.closed.append(session_id)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider=ProviderName.CLAUDE_CODE)


@pytest.mark.asyncio
async def test_local_unsafe_sandbox_delegates_provider_lifecycle():
    provider = RecordingProvider()
    driver = LocalUnsafeSandboxDriver(providers={provider.name: provider})
    request = CreateSessionRequest(provider="claude-code")

    await driver.create_session("session-1", request)
    events = [
        event async for event in driver.stream_message("session-1", StreamMessageRequest(message="hello"))
    ]
    await driver.close("session-1")

    assert provider.created == ["session-1"]
    assert events[0].data == {"content": "hello"}
    assert provider.closed == ["session-1"]

    with pytest.raises(KeyError):
        _ = [event async for event in driver.stream_message("session-1", StreamMessageRequest(message="again"))]
