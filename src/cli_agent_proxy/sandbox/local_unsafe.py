from collections.abc import AsyncIterator

from cli_agent_proxy.providers.base import AgentProvider
from cli_agent_proxy.sandbox.base import SandboxDriver
from cli_agent_proxy.schemas import (
    AgentEvent,
    CreateSessionRequest,
    ProviderCapabilities,
    StreamMessageRequest,
)


class LocalUnsafeSandboxDriver(SandboxDriver):
    """Development-only driver that runs provider adapters in the API process.

    This preserves the current developer experience while keeping production
    architecture honest: this class is not an isolation boundary.
    """

    def __init__(self, providers: dict[str, AgentProvider]) -> None:
        self._providers = providers
        self._session_providers: dict[str, AgentProvider] = {}

    async def create_session(self, session_id: str, request: CreateSessionRequest) -> None:
        provider = self._providers.get(request.provider.value)
        if provider is None:
            raise ValueError(f"unsupported provider: {request.provider}")

        self._session_providers = {**self._session_providers, session_id: provider}
        try:
            await provider.create_session(session_id, request)
        except Exception:
            self._session_providers = {
                key: value for key, value in self._session_providers.items() if key != session_id
            }
            raise

    async def stream_message(
        self,
        session_id: str,
        request: StreamMessageRequest,
    ) -> AsyncIterator[AgentEvent]:
        provider = self._get_required_provider(session_id)
        async for event in provider.stream_message(session_id, request.message):
            yield event

    async def interrupt(self, session_id: str) -> None:
        provider = self._get_required_provider(session_id)
        await provider.interrupt(session_id)

    async def close(self, session_id: str) -> None:
        provider = self._get_required_provider(session_id)
        await provider.close(session_id)
        self._session_providers = {
            key: value for key, value in self._session_providers.items() if key != session_id
        }

    def list_providers(self) -> list[str]:
        return sorted(self._providers.keys())

    def get_provider_capabilities(self, provider_name: str) -> ProviderCapabilities | None:
        provider = self._providers.get(provider_name)
        if provider is None:
            return None
        return provider.capabilities()

    def _get_required_provider(self, session_id: str) -> AgentProvider:
        provider = self._session_providers.get(session_id)
        if provider is None:
            raise KeyError(session_id)
        return provider
