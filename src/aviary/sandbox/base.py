from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from aviary.schemas import (
    AgentEvent,
    CreateSessionRequest,
    ProviderCapabilities,
    StreamMessageRequest,
)


class SandboxDriver(ABC):
    """Owns the runtime boundary for a session.

    Production drivers should map one proxy session to one isolated runtime
    environment such as a Docker container or Kubernetes pod.
    """

    @abstractmethod
    async def create_session(self, session_id: str, request: CreateSessionRequest) -> None: ...

    @abstractmethod
    async def stream_message(
        self,
        session_id: str,
        request: StreamMessageRequest,
    ) -> AsyncIterator[AgentEvent]: ...

    @abstractmethod
    async def interrupt(self, session_id: str) -> None: ...

    @abstractmethod
    async def close(self, session_id: str) -> None: ...

    @abstractmethod
    def list_providers(self) -> list[str]: ...

    @abstractmethod
    def get_provider_capabilities(self, provider_name: str) -> ProviderCapabilities | None: ...
