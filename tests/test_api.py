from fastapi.testclient import TestClient

from cli_agent_proxy.main import create_app
from cli_agent_proxy.providers.base import AgentProvider
from cli_agent_proxy.schemas import AgentEvent, CreateSessionRequest, ProviderCapabilities, ProviderName


class StubProvider(AgentProvider):
    name = "claude-code"

    async def create_session(self, session_id: str, request: CreateSessionRequest) -> None:
        self.request = request

    async def stream_message(self, session_id: str, message: str):
        conversation_id = self.request.conversation_id or session_id
        yield AgentEvent(type="start", session_id=session_id, conversation_id=conversation_id)
        yield AgentEvent(
            type="ai_chunk",
            session_id=session_id,
            conversation_id=conversation_id,
            data={"content": message},
        )
        yield AgentEvent(type="end", session_id=session_id, conversation_id=conversation_id)

    async def interrupt(self, session_id: str) -> None:
        return None

    async def close(self, session_id: str) -> None:
        return None

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=ProviderName.CLAUDE_CODE,
            supports_streaming=True,
            supports_resume=True,
            session_config_fields=["model"],
        )


def create_test_app():
    return create_app(providers={StubProvider.name: StubProvider()})


def test_healthz_returns_ok():
    client = TestClient(create_test_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_get_session():
    client = TestClient(create_test_app())

    create_response = client.post(
        "/v1/sessions",
        json={
            "provider": "claude-code",
            "conversation_id": "conv-001",
            "model": "private-sonnet",
            "allowed_tools": ["Read"],
        },
    )

    assert create_response.status_code == 200
    session = create_response.json()
    assert session["provider"] == "claude-code"
    assert session["conversation_id"] == "conv-001"
    assert session["status"] == "ready"

    get_response = client.get(f"/v1/sessions/{session['session_id']}")
    assert get_response.status_code == 200
    assert get_response.json()["session_id"] == session["session_id"]


def test_provider_capabilities_endpoints():
    client = TestClient(create_test_app())

    providers_response = client.get("/v1/providers")
    capabilities_response = client.get("/v1/providers/claude-code/capabilities")

    assert providers_response.status_code == 200
    assert providers_response.json() == {"providers": ["claude-code"]}
    assert capabilities_response.status_code == 200
    capabilities = capabilities_response.json()
    assert capabilities["provider"] == "claude-code"
    assert capabilities["supports_streaming"] is True
    assert capabilities["supports_resume"] is True
    assert "model" in capabilities["session_config_fields"]


def test_stream_message_returns_sse_events():
    client = TestClient(create_test_app())
    session = client.post(
        "/v1/sessions",
        json={"provider": "claude-code", "conversation_id": "conv-002"},
    ).json()

    with client.stream(
        "POST",
        f"/v1/sessions/{session['session_id']}/messages:stream",
        json={"message": "hello"},
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert "event: start" in body
    assert "event: ai_chunk" in body
    assert "event: end" in body


def test_close_session_removes_it():
    client = TestClient(create_test_app())
    session = client.post(
        "/v1/sessions",
        json={"provider": "claude-code", "conversation_id": "conv-003"},
    ).json()

    close_response = client.delete(f"/v1/sessions/{session['session_id']}")

    assert close_response.status_code == 200
    assert close_response.json()["status"] == "closed"
    assert client.get(f"/v1/sessions/{session['session_id']}").status_code == 404
