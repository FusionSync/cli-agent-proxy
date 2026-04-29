import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from cli_agent_proxy.sandbox.base import SandboxDriver
from cli_agent_proxy.schemas import (
    AgentEvent,
    CreateSessionRequest,
    ProviderCapabilities,
    SessionResponse,
    SessionStatus,
    StreamMessageRequest,
)


@dataclass(frozen=True)
class ManagedSession:
    session_id: str
    request: CreateSessionRequest
    status: SessionStatus = SessionStatus.READY
    provider_session_id: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, compare=False)


class SessionManager:
    def __init__(self, sandbox_driver: SandboxDriver) -> None:
        self._sandbox_driver = sandbox_driver
        self._sessions: dict[str, ManagedSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(self, request: CreateSessionRequest) -> SessionResponse:
        if self._sandbox_driver.get_provider_capabilities(request.provider.value) is None:
            raise ValueError(f"unsupported provider: {request.provider}")

        session_id = str(uuid.uuid4())
        managed = ManagedSession(session_id=session_id, request=request)
        async with self._lock:
            self._sessions = {**self._sessions, session_id: managed}

        try:
            await self._sandbox_driver.create_session(session_id, request)
        except Exception:
            async with self._lock:
                self._sessions = {key: value for key, value in self._sessions.items() if key != session_id}
            raise
        return self._to_response(managed)

    async def get_session(self, session_id: str) -> SessionResponse | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return self._to_response(session)

    def list_providers(self) -> list[str]:
        return self._sandbox_driver.list_providers()

    def get_provider_capabilities(self, provider_name: str) -> ProviderCapabilities | None:
        return self._sandbox_driver.get_provider_capabilities(provider_name)

    async def stream_message(self, session_id: str, request: StreamMessageRequest) -> AsyncIterator[AgentEvent]:
        session = self._get_required_session(session_id)

        async with session.lock:
            self._replace_session(session_id, SessionStatus.RUNNING)
            try:
                async for event in self._sandbox_driver.stream_message(session_id, request):
                    yield event
            finally:
                if session_id in self._sessions:
                    self._replace_session(session_id, SessionStatus.READY)

    async def interrupt(self, session_id: str) -> SessionResponse:
        session = self._get_required_session(session_id)
        await self._sandbox_driver.interrupt(session_id)
        return self._to_response(session)

    async def close(self, session_id: str) -> SessionResponse:
        session = self._get_required_session(session_id)
        await self._sandbox_driver.close(session_id)
        async with self._lock:
            self._sessions = {key: value for key, value in self._sessions.items() if key != session_id}
        return self._to_response(ManagedSession(session_id=session_id, request=session.request, status=SessionStatus.CLOSED))

    def _get_required_session(self, session_id: str) -> ManagedSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def _replace_session(self, session_id: str, status: SessionStatus) -> None:
        current = self._sessions[session_id]
        self._sessions = {
            **self._sessions,
            session_id: ManagedSession(
                session_id=current.session_id,
                request=current.request,
                status=status,
                provider_session_id=current.provider_session_id,
                lock=current.lock,
            ),
        }

    def _to_response(self, session: ManagedSession) -> SessionResponse:
        return SessionResponse(
            session_id=session.session_id,
            provider=session.request.provider,
            conversation_id=session.request.conversation_id or session.session_id,
            status=session.status,
            provider_session_id=session.provider_session_id,
        )
