from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from aviary.sandbox.docker import DockerContainerSpec, DockerSandboxDriver
from aviary.sandbox.workspace import LocalWorkspaceAllocator
from aviary.schemas import AgentEvent, CreateSessionRequest, StreamMessageRequest


class FakeRuntimeClient:
    def __init__(self) -> None:
        self.created_specs: list[DockerContainerSpec] = []
        self.interrupted: list[str] = []
        self.closed: list[str] = []
        self.events: list[AgentEvent] = []

    async def create_session(self, spec: DockerContainerSpec) -> None:
        self.created_specs.append(spec)

    async def stream_message(
        self,
        session_id: str,
        request: StreamMessageRequest,
    ) -> AsyncIterator[AgentEvent]:
        for event in self.events:
            yield event

    async def interrupt(self, session_id: str) -> None:
        self.interrupted.append(session_id)

    async def close(self, session_id: str) -> None:
        self.closed.append(session_id)


@pytest.mark.asyncio
async def test_docker_sandbox_allocates_server_owned_workspace_and_hardened_spec(tmp_path: Path):
    runtime = FakeRuntimeClient()
    driver = DockerSandboxDriver(
        runtime_client=runtime,
        workspace_allocator=LocalWorkspaceAllocator(tmp_path),
    )
    request = CreateSessionRequest(
        provider="claude-code",
        model={"name": "private-sonnet"},
        runtime={
            "base_url": "http://model-gateway.internal",
            "api_key_ref": "project-a/anthropic",
            "cwd": "/caller/must/not/control",
            "env": {"ANTHROPIC_API_KEY": "raw-key", "DEBUG": "1"},
        },
        env={"SHOULD_NOT_PASS": "1"},
        sandbox={"timeout_seconds": 120},
    )

    await driver.create_session("session-1", request)

    assert len(runtime.created_specs) == 1
    spec = runtime.created_specs[0]
    assert spec.session_id == "session-1"
    assert spec.provider == "claude-code"
    assert spec.workspace.path == tmp_path.resolve() / "session-1"
    assert str(spec.workspace.path) != "/caller/must/not/control"
    assert spec.container_workspace_path == "/workspace"
    assert spec.read_only_rootfs is True
    assert spec.privileged is False
    assert spec.cap_drop == ("ALL",)
    assert spec.no_new_privileges is True
    assert spec.user == "1000:1000"
    assert spec.resource_limits.memory_mb == 1024
    assert spec.resource_limits.pids_limit == 256
    assert spec.resource_limits.timeout_seconds == 120
    assert spec.env == {
        "AVIARY_SESSION_ID": "session-1",
        "AVIARY_PROVIDER": "claude-code",
        "AVIARY_WORKSPACE": "/workspace",
        "AVIARY_MODEL": "private-sonnet",
        "ANTHROPIC_BASE_URL": "http://model-gateway.internal",
        "AVIARY_API_KEY_REF": "project-a/anthropic",
    }


@pytest.mark.asyncio
async def test_docker_sandbox_streams_runtime_events_and_interrupts(tmp_path: Path):
    runtime = FakeRuntimeClient()
    runtime.events = [
        AgentEvent(
            type="ai_chunk",
            session_id="session-2",
            conversation_id="session-2",
            data={"content": "hello"},
        )
    ]
    driver = DockerSandboxDriver(
        runtime_client=runtime,
        workspace_allocator=LocalWorkspaceAllocator(tmp_path),
    )
    await driver.create_session("session-2", CreateSessionRequest(provider="claude-code"))

    events = [
        event async for event in driver.stream_message("session-2", StreamMessageRequest(message="hello"))
    ]
    await driver.interrupt("session-2")

    assert events == runtime.events
    assert runtime.interrupted == ["session-2"]


@pytest.mark.asyncio
async def test_docker_sandbox_close_stops_runtime_and_deletes_workspace(tmp_path: Path):
    runtime = FakeRuntimeClient()
    driver = DockerSandboxDriver(
        runtime_client=runtime,
        workspace_allocator=LocalWorkspaceAllocator(tmp_path),
    )
    await driver.create_session("session-3", CreateSessionRequest(provider="claude-code"))
    workspace_path = runtime.created_specs[0].workspace.path

    await driver.close("session-3")

    assert runtime.closed == ["session-3"]
    assert not workspace_path.exists()
    with pytest.raises(KeyError):
        driver.get_container_spec("session-3")


@pytest.mark.asyncio
async def test_docker_sandbox_close_honors_keep_retention(tmp_path: Path):
    runtime = FakeRuntimeClient()
    driver = DockerSandboxDriver(
        runtime_client=runtime,
        workspace_allocator=LocalWorkspaceAllocator(tmp_path),
    )
    await driver.create_session(
        "session-4",
        CreateSessionRequest(provider="claude-code", sandbox={"workspace_retention": "keep"}),
    )
    workspace_path = runtime.created_specs[0].workspace.path

    await driver.close("session-4")

    assert workspace_path.exists()


@pytest.mark.asyncio
async def test_docker_sandbox_releases_workspace_when_spec_build_fails(tmp_path: Path):
    driver = DockerSandboxDriver(
        runtime_client=FakeRuntimeClient(),
        workspace_allocator=LocalWorkspaceAllocator(tmp_path),
    )

    with pytest.raises(ValueError):
        await driver.create_session(
            "session-bad-profile",
            CreateSessionRequest(provider="claude-code", sandbox={"profile": "missing"}),
        )

    assert not (tmp_path / "session-bad-profile").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session_request",
    [
        CreateSessionRequest(policy={"execution_mode": "bypass"}),
        CreateSessionRequest(policy={"filesystem": "unrestricted"}),
        CreateSessionRequest(policy={"network": "unrestricted"}),
        CreateSessionRequest(policy={"network": "allowlist"}),
    ],
)
async def test_docker_sandbox_rejects_unsafe_managed_policies(
    tmp_path: Path,
    session_request: CreateSessionRequest,
):
    driver = DockerSandboxDriver(
        runtime_client=FakeRuntimeClient(),
        workspace_allocator=LocalWorkspaceAllocator(tmp_path),
    )

    with pytest.raises(ValueError):
        await driver.create_session("session-policy", session_request)
