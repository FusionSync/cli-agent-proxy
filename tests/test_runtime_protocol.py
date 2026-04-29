import pytest
from pydantic import ValidationError

from aviary.runtime.protocol import RuntimeCommand, decode_event_line, encode_command
from aviary.schemas import AgentEvent


def test_runtime_command_encodes_as_single_json_line():
    command = RuntimeCommand(
        type="query",
        session_id="session-1",
        payload={"message": "hello"},
    )

    encoded = encode_command(command)

    assert encoded.endswith("\n")
    assert "\n" not in encoded[:-1]
    assert '"type":"query"' in encoded
    assert '"session_id":"session-1"' in encoded


def test_runtime_protocol_decodes_agent_event_line():
    line = (
        '{"type":"ai_chunk","session_id":"session-1",'
        '"conversation_id":"conv-1","data":{"content":"hello"}}\n'
    )

    event = decode_event_line(line)

    assert event == AgentEvent(
        type="ai_chunk",
        session_id="session-1",
        conversation_id="conv-1",
        data={"content": "hello"},
    )


def test_runtime_protocol_rejects_invalid_event_line():
    with pytest.raises(ValueError):
        decode_event_line("not-json\n")


def test_runtime_protocol_rejects_oversized_event_line():
    oversized = "x" * (1024 * 1024 + 1)

    with pytest.raises(ValueError):
        decode_event_line(oversized)


def test_runtime_command_rejects_unknown_type():
    with pytest.raises(ValidationError):
        RuntimeCommand(type="shell", session_id="session-1")
