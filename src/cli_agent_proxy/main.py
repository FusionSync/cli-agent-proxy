import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from cli_agent_proxy.providers.claude_code import ClaudeCodeProvider
from cli_agent_proxy.schemas import CreateSessionRequest, ProviderCapabilities, SessionResponse, StreamMessageRequest
from cli_agent_proxy.session_manager import SessionManager


def create_app() -> FastAPI:
    manager = SessionManager(
        providers={
            ClaudeCodeProvider.name: ClaudeCodeProvider(),
        }
    )

    app = FastAPI(title="CLI Agent Proxy", version="0.1.0")
    app.state.session_manager = manager

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/providers")
    async def list_providers() -> dict[str, list[str]]:
        return {"providers": manager.list_providers()}

    @app.get("/v1/providers/{provider_name}/capabilities", response_model=ProviderCapabilities)
    async def get_provider_capabilities(provider_name: str) -> ProviderCapabilities:
        capabilities = manager.get_provider_capabilities(provider_name)
        if capabilities is None:
            raise HTTPException(status_code=404, detail="provider not found")
        return capabilities

    @app.post("/v1/sessions", response_model=SessionResponse)
    async def create_session(request: CreateSessionRequest) -> SessionResponse:
        try:
            return await manager.create_session(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(session_id: str) -> SessionResponse:
        session = await manager.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return session

    @app.post("/v1/sessions/{session_id}/messages:stream")
    async def stream_message(session_id: str, request: StreamMessageRequest) -> StreamingResponse:
        async def event_stream():
            try:
                async for event in manager.stream_message(session_id, request):
                    payload = event.model_dump(mode="json")
                    yield f"event: {event.type}\n"
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except KeyError:
                payload = {"type": "error", "session_id": session_id, "data": {"detail": "session not found"}}
                yield "event: error\n"
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/v1/sessions/{session_id}/interrupt", response_model=SessionResponse)
    async def interrupt_session(session_id: str) -> SessionResponse:
        try:
            return await manager.interrupt(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    @app.delete("/v1/sessions/{session_id}", response_model=SessionResponse)
    async def close_session(session_id: str) -> SessionResponse:
        try:
            return await manager.close(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    return app


app = create_app()
