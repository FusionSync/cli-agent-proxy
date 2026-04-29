from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ProviderName(str, Enum):
    CLAUDE_CODE = "claude-code"


class SessionStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    CLOSED = "closed"
    ERROR = "error"


class CreateSessionRequest(BaseModel):
    provider: ProviderName = Field(default=ProviderName.CLAUDE_CODE)
    conversation_id: str = Field(..., min_length=1)
    model: str | None = None
    cwd: str | None = None
    system_prompt: str | None = None
    permission_mode: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    disallowed_tools: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("conversation_id cannot be empty")
        return stripped


class SessionResponse(BaseModel):
    session_id: str
    provider: ProviderName
    conversation_id: str
    status: SessionStatus
    provider_session_id: str | None = None


class StreamMessageRequest(BaseModel):
    message: str = Field(..., min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
    files: list[str] = Field(default_factory=list)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message cannot be empty")
        return stripped


class AgentEvent(BaseModel):
    type: Literal[
        "start",
        "ai_chunk",
        "tool_call",
        "tool_result",
        "error",
        "end",
        "raw",
    ]
    session_id: str
    conversation_id: str
    data: dict[str, Any] = Field(default_factory=dict)
