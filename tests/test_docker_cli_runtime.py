from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from aviary.sandbox.docker import DockerContainerSpec, ResourceLimits
from aviary.sandbox.docker_cli import CommandResult, DockerCliRuntimeClient
from aviary.sandbox.workspace import Workspace
from aviary.schemas import AgentEvent, NetworkPolicy, StreamMessageRequest, WorkspaceRetention


class RecordingDockerRunner:
    def __init__(self) -> None:
        self.run_calls: list[tuple[list[str], str | None]] = []
        self.stream_calls: list[tuple[list[str], str | None]] = []
        self.stream_lines: list[str] = []

    async def run(self, args: Sequence[str], *, input_text: str | None = None) -> CommandResult:
        self.run_calls.append((list(args), input_text))
        return CommandResult(returncode=0, stdout="ok", stderr="")

    async def stream(self, args: Sequence[str], *, input_text: str | None = None) -> AsyncIterator[str]:
        self.stream_calls.append((list(args), input_text))
        for line in self.stream_lines:
            yield line


def make_spec(tmp_path: Path, session_id: str = "session-1") -> DockerContainerSpec:
    return DockerContainerSpec(
        session_id=session_id,
        provider="claude-code",
        image="aviary-runtime:test",
        workspace=Workspace(
            workspace_id=session_id,
            path=tmp_path / session_id,
            retention=WorkspaceRetention.DELETE,
        ),
        env={
            "AVIARY_SESSION_ID": session_id,
            "AVIARY_PROVIDER": "claude-code",
            "AVIARY_WORKSPACE": "/workspace",
            "ANTHROPIC_BASE_URL": "http://model-gateway.internal",
            "AVIARY_API_KEY_REF": "project-a/anthropic",
        },
        labels={"aviary.session_id": session_id, "aviary.provider": "claude-code"},
        resource_limits=ResourceLimits(memory_mb=2048, pids_limit=128, timeout_seconds=60),
    )


@pytest.mark.asyncio
async def test_docker_cli_runtime_builds_hardened_run_command(tmp_path: Path):
    runner = RecordingDockerRunner()
    client = DockerCliRuntimeClient(runner=runner, docker_binary="docker")
    spec = make_spec(tmp_path)

    await client.create_session(spec)

    args, input_text = runner.run_calls[0]
    assert input_text is None
    assert args[:3] == ["docker", "run", "-d"]
    assert "--privileged" not in args
    assert "--read-only" in args
    assert "--cap-drop" in args
    assert "ALL" in args
    assert "--security-opt" in args
    assert "no-new-privileges" in args
    assert "--network" in args
    assert "none" in args
    assert "--user" in args
    assert "1000:1000" in args
    assert "--memory" in args
    assert "2048m" in args
    assert "--pids-limit" in args
    assert "128" in args
    assert f"{tmp_path / 'session-1'}:/workspace:rw" in args
    assert "aviary-runtime:test" in args
    assert "ANTHROPIC_API_KEY" not in " ".join(args)


@pytest.mark.asyncio
async def test_docker_cli_runtime_uses_allowlist_network_metadata(tmp_path: Path):
    runner = RecordingDockerRunner()
    client = DockerCliRuntimeClient(runner=runner)
    spec = make_spec(tmp_path)
    spec = DockerContainerSpec(
        **{
            **spec.__dict__,
            "network_policy": NetworkPolicy.ALLOWLIST,
            "allowed_hosts": ("model-gateway.internal",),
        }
    )

    await client.create_session(spec)

    args, _ = runner.run_calls[0]
    assert "bridge" in args
    assert "AVIARY_ALLOWED_HOSTS=model-gateway.internal" in args


@pytest.mark.asyncio
async def test_docker_cli_runtime_streams_jsonl_events(tmp_path: Path):
    runner = RecordingDockerRunner()
    runner.stream_lines = [
        '{"type":"ai_chunk","session_id":"session-2","conversation_id":"session-2","data":{"content":"hello"}}\n'
    ]
    client = DockerCliRuntimeClient(runner=runner)
    await client.create_session(make_spec(tmp_path, session_id="session-2"))

    events = [
        event async for event in client.stream_message("session-2", StreamMessageRequest(message="hello"))
    ]

    assert events == [
        AgentEvent(
            type="ai_chunk",
            session_id="session-2",
            conversation_id="session-2",
            data={"content": "hello"},
        )
    ]
    args, input_text = runner.stream_calls[0]
    assert args == ["docker", "exec", "-i", "aviary-session-2", "aviary-runtime", "query"]
    assert input_text is not None
    assert '"message":"hello"' in input_text


@pytest.mark.asyncio
async def test_docker_cli_runtime_rejects_cross_session_events(tmp_path: Path):
    runner = RecordingDockerRunner()
    runner.stream_lines = [
        '{"type":"ai_chunk","session_id":"other-session","conversation_id":"other-session","data":{}}\n'
    ]
    client = DockerCliRuntimeClient(runner=runner)
    await client.create_session(make_spec(tmp_path, session_id="session-2"))

    with pytest.raises(ValueError):
        _ = [
            event async for event in client.stream_message("session-2", StreamMessageRequest(message="hello"))
        ]


@pytest.mark.asyncio
async def test_docker_cli_runtime_interrupts_and_removes_container(tmp_path: Path):
    runner = RecordingDockerRunner()
    client = DockerCliRuntimeClient(runner=runner)
    await client.create_session(make_spec(tmp_path, session_id="session-3"))

    await client.interrupt("session-3")
    await client.close("session-3")

    run_args = [call[0] for call in runner.run_calls]
    assert ["docker", "exec", "-i", "aviary-session-3", "aviary-runtime", "interrupt"] in run_args
    assert ["docker", "exec", "-i", "aviary-session-3", "aviary-runtime", "close"] in run_args
    assert ["docker", "rm", "-f", "aviary-session-3"] in run_args


@pytest.mark.asyncio
async def test_docker_cli_runtime_rejects_unsafe_session_ids(tmp_path: Path):
    client = DockerCliRuntimeClient(runner=RecordingDockerRunner())
    spec = make_spec(tmp_path, session_id="../escape")

    with pytest.raises(ValueError):
        await client.create_session(spec)
