from fastapi.testclient import TestClient

from cli_agent_proxy.main import create_app


def test_healthz_returns_ok():
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_get_session():
    client = TestClient(create_app())

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


def test_stream_message_returns_sse_events():
    client = TestClient(create_app())
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
    client = TestClient(create_app())
    session = client.post(
        "/v1/sessions",
        json={"provider": "claude-code", "conversation_id": "conv-003"},
    ).json()

    close_response = client.delete(f"/v1/sessions/{session['session_id']}")

    assert close_response.status_code == 200
    assert close_response.json()["status"] == "closed"
    assert client.get(f"/v1/sessions/{session['session_id']}").status_code == 404
