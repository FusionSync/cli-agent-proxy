import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from aviary.approvals import ApprovalBroker
from aviary.providers.base import AgentProvider
from aviary.sandbox.base import SandboxDriver
from aviary.schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    CreateSessionRequest,
    ProviderCapabilities,
    SessionResponse,
    StreamMessageRequest,
)
from aviary.session_manager import SessionManager
from aviary.settings import AviarySettings, build_sandbox_driver, default_provider_registry


def create_app(
    providers: dict[str, AgentProvider] | None = None,
    sandbox_driver: SandboxDriver | None = None,
    settings: AviarySettings | None = None,
) -> FastAPI:
    app_settings = settings or AviarySettings.from_env()
    approval_broker = ApprovalBroker()
    provider_registry = providers or default_provider_registry(approval_broker=approval_broker)
    driver = sandbox_driver or build_sandbox_driver(app_settings, providers=provider_registry)
    manager = SessionManager(sandbox_driver=driver)

    app = FastAPI(title="Aviary", version="0.1.0")
    app.state.session_manager = manager
    app.state.sandbox_driver = driver
    app.state.settings = app_settings
    app.state.approval_broker = approval_broker

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

    @app.get("/v1/sessions/{session_id}/approvals", response_model=list[ApprovalResponse])
    async def list_session_approvals(session_id: str) -> list[ApprovalResponse]:
        session = await manager.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return await approval_broker.list_session_approvals(session_id)

    @app.post(
        "/v1/sessions/{session_id}/approvals/{approval_id}:decide",
        response_model=ApprovalResponse,
    )
    async def decide_session_approval(
        session_id: str,
        approval_id: str,
        request: ApprovalDecisionRequest,
    ) -> ApprovalResponse:
        try:
            return await approval_broker.decide(
                session_id=session_id,
                approval_id=approval_id,
                decision=request.decision,
                reason=request.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval not found") from exc

    @app.delete("/v1/sessions/{session_id}", response_model=SessionResponse)
    async def close_session(session_id: str) -> SessionResponse:
        try:
            response = await manager.close(session_id)
            await approval_broker.cancel_session(session_id)
            return response
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    return app


app = create_app()
