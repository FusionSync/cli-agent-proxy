from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from aviary.schemas import AgentEvent, CreateSessionRequest, ProviderCapabilities


class AgentProvider(ABC):
    name: str

    @abstractmethod
    async def create_session(self, session_id: str, request: CreateSessionRequest) -> None: ...

    @abstractmethod
    async def stream_message(self, session_id: str, message: str) -> AsyncIterator[AgentEvent]: ...

    @abstractmethod
    async def interrupt(self, session_id: str) -> None: ...

    @abstractmethod
    async def close(self, session_id: str) -> None: ...

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...
