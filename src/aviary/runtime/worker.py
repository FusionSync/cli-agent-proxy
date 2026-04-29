from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from aviary.providers.base import AgentProvider
from aviary.providers.claude_code import ClaudeCodeProvider
from aviary.runtime.protocol import RuntimeCommand
from aviary.schemas import AgentEvent, CreateSessionRequest, ProviderName


ProviderFactory = Callable[[str], AgentProvider]

SECRET_KEY_PATTERN = re.compile(r"(api[_-]?key|token|password|secret|authorization)", re.IGNORECASE)
SECRET_VALUE_PATTERN = re.compile(
    r"(?P<prefix>(?:api[_-]?key|token|password|secret|authorization)[A-Za-z0-9_.-]*=)(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RuntimeEnvironment:
    session_id: str
    provider: str
    workspace: str = "/workspace"
    model: str | None = None
    base_url: str | None = None
    api_key_ref: str | None = None

    @classmethod
    def from_mapping(cls, environ: dict[str, str]) -> "RuntimeEnvironment":
        session_id = environ.get("AVIARY_SESSION_ID")
        if not session_id:
            raise ValueError("runtime environment is missing AVIARY_SESSION_ID")
        provider = environ.get("AVIARY_PROVIDER")
        if not provider:
            raise ValueError("runtime environment is missing AVIARY_PROVIDER")
        return cls(
            session_id=session_id,
            provider=provider,
            workspace=environ.get("AVIARY_WORKSPACE", "/workspace"),
            model=environ.get("AVIARY_MODEL"),
            base_url=environ.get("ANTHROPIC_BASE_URL"),
            api_key_ref=environ.get("AVIARY_API_KEY_REF"),
        )


def default_provider_factory(provider_name: str) -> AgentProvider:
    if provider_name == ProviderName.CLAUDE_CODE.value:
        return ClaudeCodeProvider()
    raise ValueError(f"unsupported provider: {provider_name}")


class RuntimeWorker:
    def __init__(
        self,
        *,
        provider_factory: ProviderFactory = default_provider_factory,
        environment: RuntimeEnvironment,
    ) -> None:
        self._provider_factory = provider_factory
        self._environment = environment
        self._provider = provider_factory(environment.provider)

    async def handle(self, command: RuntimeCommand) -> AsyncIterator[AgentEvent]:
        if command.session_id != self._environment.session_id:
            yield self._error_event(f"session mismatch: {command.session_id}")
            return

        if command.type == "query":
            async for event in self._handle_query(command):
                yield event
            return
        if command.type == "interrupt":
            await self._provider.interrupt(command.session_id)
            yield self._end_event({"interrupted": True})
            return
        if command.type == "close":
            await self._provider.close(command.session_id)
            yield self._end_event({"closed": True})
            return
        if command.type == "health":
            yield self._end_event({"healthy": True})
            return

        yield self._error_event(f"unsupported runtime command: {command.type}")

    async def _handle_query(self, command: RuntimeCommand) -> AsyncIterator[AgentEvent]:
        message = command.payload.get("message")
        if not isinstance(message, str) or not message.strip():
            yield self._error_event("query command requires a non-empty message")
            return

        request = self._build_request()
        try:
            await self._provider.create_session(command.session_id, request)
            async for event in self._provider.stream_message(command.session_id, message):
                if event.session_id != self._environment.session_id:
                    yield self._error_event("provider emitted event for another session")
                    return
                yield self._redact_event(event)
        except Exception as exc:
            yield self._error_event(redact_secrets(str(exc)))

    def _build_request(self) -> CreateSessionRequest:
        return CreateSessionRequest(
            provider=self._environment.provider,
            conversation_id=self._environment.session_id,
            model={"name": self._environment.model} if self._environment.model else {},
            runtime={
                "cwd": self._environment.workspace,
                "base_url": self._environment.base_url,
                "api_key_ref": self._environment.api_key_ref,
                "env": {},
            },
        )

    def _redact_event(self, event: AgentEvent) -> AgentEvent:
        return AgentEvent(
            type=event.type,
            session_id=event.session_id,
            conversation_id=event.conversation_id,
            data=redact_mapping(event.data),
        )

    def _error_event(self, detail: str) -> AgentEvent:
        return AgentEvent(
            type="error",
            session_id=self._environment.session_id,
            conversation_id=self._environment.session_id,
            data={"detail": redact_secrets(detail)},
        )

    def _end_event(self, data: dict[str, Any]) -> AgentEvent:
        return AgentEvent(
            type="end",
            session_id=self._environment.session_id,
            conversation_id=self._environment.session_id,
            data=data,
        )


def redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SECRET_KEY_PATTERN.search(str(key)) else redact_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def redact_secrets(value: str) -> str:
    return SECRET_VALUE_PATTERN.sub(lambda match: f"{match.group('prefix')}[REDACTED]", value)
