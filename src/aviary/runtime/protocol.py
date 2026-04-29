import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from aviary.schemas import AgentEvent

MAX_EVENT_LINE_BYTES = 1024 * 1024


class RuntimeCommand(BaseModel):
    type: Literal["start", "query", "interrupt", "close", "health"]
    session_id: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


def encode_command(command: RuntimeCommand) -> str:
    payload = command.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def decode_event_line(line: str) -> AgentEvent:
    if len(line.encode()) > MAX_EVENT_LINE_BYTES:
        raise ValueError("runtime event line is too large")
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError("runtime event line is not valid JSON") from exc
    try:
        return AgentEvent.model_validate(payload)
    except Exception as exc:
        raise ValueError("runtime event line is not a valid AgentEvent") from exc
