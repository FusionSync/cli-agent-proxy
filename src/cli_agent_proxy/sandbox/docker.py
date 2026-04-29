from collections.abc import AsyncIterator, Iterable

from cli_agent_proxy.sandbox.base import SandboxDriver
from cli_agent_proxy.schemas import (
    AgentEvent,
    CreateSessionRequest,
    ProviderCapabilities,
    ProviderName,
    StreamMessageRequest,
)


class DockerSandboxDriver(SandboxDriver):
    """Planned production driver for one-container-per-session execution."""

    def __init__(self, providers: Iterable[str] | None = None) -> None:
        provider_names = providers or [ProviderName.CLAUDE_CODE.value]
        self._providers = sorted(set(provider_names))

    async def create_session(self, session_id: str, request: CreateSessionRequest) -> None:
        raise NotImplementedError("Docker sandbox driver is planned for the next implementation phase.")

    async def stream_message(
        self,
        session_id: str,
        request: StreamMessageRequest,
    ) -> AsyncIterator[AgentEvent]:
        raise NotImplementedError("Docker sandbox driver is planned for the next implementation phase.")
        yield

    async def interrupt(self, session_id: str) -> None:
        raise NotImplementedError("Docker sandbox driver is planned for the next implementation phase.")

    async def close(self, session_id: str) -> None:
        raise NotImplementedError("Docker sandbox driver is planned for the next implementation phase.")

    def list_providers(self) -> list[str]:
        return self._providers

    def get_provider_capabilities(self, provider_name: str) -> ProviderCapabilities | None:
        if provider_name not in self._providers:
            return None
        try:
            provider = ProviderName(provider_name)
        except ValueError:
            return None
        return ProviderCapabilities(provider=provider)
