from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from aviary.sandbox.base import SandboxDriver
from aviary.sandbox.workspace import LocalWorkspaceAllocator, Workspace, WorkspaceAllocator
from aviary.schemas import (
    AgentEvent,
    CreateSessionRequest,
    ExecutionMode,
    FilesystemPolicy,
    NetworkPolicy,
    ProviderCapabilities,
    ProviderName,
    StreamMessageRequest,
)


@dataclass(frozen=True)
class ResourceLimits:
    cpu_count: float = 1.0
    memory_mb: int = 1024
    pids_limit: int = 256
    timeout_seconds: int | None = None


@dataclass(frozen=True)
class DockerSandboxProfile:
    name: str = "default"
    image: str = "ghcr.io/fusionsync/aviary-claude-code-runtime:latest"
    user: str = "1000:1000"
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)


@dataclass(frozen=True)
class DockerContainerSpec:
    session_id: str
    provider: str
    image: str
    workspace: Workspace
    container_workspace_path: str = "/workspace"
    command: tuple[str, ...] = ("aviary-runtime", "serve")
    user: str = "1000:1000"
    env: Mapping[str, str] = field(default_factory=dict)
    labels: Mapping[str, str] = field(default_factory=dict)
    read_only_rootfs: bool = True
    privileged: bool = False
    cap_drop: tuple[str, ...] = ("ALL",)
    no_new_privileges: bool = True
    network_policy: NetworkPolicy = NetworkPolicy.DENY_BY_DEFAULT
    allowed_hosts: tuple[str, ...] = ()
    filesystem_policy: FilesystemPolicy = FilesystemPolicy.WORKSPACE_ONLY
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)


class DockerRuntimeClient(Protocol):
    async def create_session(self, spec: DockerContainerSpec) -> None: ...

    async def stream_message(
        self,
        session_id: str,
        request: StreamMessageRequest,
    ) -> AsyncIterator[AgentEvent]: ...

    async def interrupt(self, session_id: str) -> None: ...

    async def close(self, session_id: str) -> None: ...


class NotConfiguredDockerRuntimeClient:
    async def create_session(self, spec: DockerContainerSpec) -> None:
        raise NotImplementedError("Docker runtime client is not configured.")

    async def stream_message(
        self,
        session_id: str,
        request: StreamMessageRequest,
    ) -> AsyncIterator[AgentEvent]:
        raise NotImplementedError("Docker runtime client is not configured.")
        yield

    async def interrupt(self, session_id: str) -> None:
        raise NotImplementedError("Docker runtime client is not configured.")

    async def close(self, session_id: str) -> None:
        raise NotImplementedError("Docker runtime client is not configured.")


@dataclass(frozen=True)
class DockerManagedSession:
    request: CreateSessionRequest
    spec: DockerContainerSpec


class DockerSandboxDriver(SandboxDriver):
    """Builds one-container-per-session runtime specs for Docker execution.

    The driver deliberately depends on a runtime client protocol instead of a
    Docker SDK here. That keeps the public API process separate from Docker
    authority and lets a dedicated sandbox manager own the actual engine.
    """

    def __init__(
        self,
        providers: Iterable[str] | None = None,
        *,
        runtime_client: DockerRuntimeClient | None = None,
        workspace_allocator: WorkspaceAllocator | None = None,
        profiles: Mapping[str, DockerSandboxProfile] | None = None,
    ) -> None:
        provider_names = providers or [ProviderName.CLAUDE_CODE.value]
        self._providers = sorted(set(provider_names))
        self._runtime_client = runtime_client or NotConfiguredDockerRuntimeClient()
        self._workspace_allocator = workspace_allocator or LocalWorkspaceAllocator()
        self._profiles = dict(profiles or {"default": DockerSandboxProfile()})
        self._sessions: dict[str, DockerManagedSession] = {}

    @property
    def runtime_client(self) -> DockerRuntimeClient:
        return self._runtime_client

    async def create_session(self, session_id: str, request: CreateSessionRequest) -> None:
        if request.provider.value not in self._providers:
            raise ValueError(f"unsupported provider: {request.provider}")
        self._validate_managed_policy(request)

        workspace = self._workspace_allocator.allocate(session_id, request)
        try:
            spec = self._build_container_spec(session_id, request, workspace)
            await self._runtime_client.create_session(spec)
        except Exception:
            self._workspace_allocator.release(workspace)
            raise
        self._sessions = {
            **self._sessions,
            session_id: DockerManagedSession(request=request, spec=spec),
        }

    async def stream_message(
        self,
        session_id: str,
        request: StreamMessageRequest,
    ) -> AsyncIterator[AgentEvent]:
        self._get_required_session(session_id)
        async for event in self._runtime_client.stream_message(session_id, request):
            yield event

    async def interrupt(self, session_id: str) -> None:
        self._get_required_session(session_id)
        await self._runtime_client.interrupt(session_id)

    async def close(self, session_id: str) -> None:
        session = self._get_required_session(session_id)
        try:
            await self._runtime_client.close(session_id)
        finally:
            self._workspace_allocator.release(session.spec.workspace)
            self._sessions = {
                key: value for key, value in self._sessions.items() if key != session_id
            }

    def list_providers(self) -> list[str]:
        return self._providers

    def get_provider_capabilities(self, provider_name: str) -> ProviderCapabilities | None:
        if provider_name not in self._providers:
            return None
        try:
            provider = ProviderName(provider_name)
        except ValueError:
            return None
        return ProviderCapabilities(provider=provider)

    def get_container_spec(self, session_id: str) -> DockerContainerSpec:
        return self._get_required_session(session_id).spec

    def _get_required_session(self, session_id: str) -> DockerManagedSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def _build_container_spec(
        self,
        session_id: str,
        request: CreateSessionRequest,
        workspace: Workspace,
    ) -> DockerContainerSpec:
        profile = self._get_profile(request)
        env = self._managed_env(session_id, request)
        labels = {
            "aviary.session_id": session_id,
            "aviary.provider": request.provider.value,
            "aviary.workspace_id": workspace.workspace_id,
        }
        return DockerContainerSpec(
            session_id=session_id,
            provider=request.provider.value,
            image=profile.image,
            workspace=workspace,
            user=profile.user,
            env=env,
            labels=labels,
            network_policy=request.policy.network,
            allowed_hosts=tuple(request.policy.allowed_hosts),
            filesystem_policy=request.policy.filesystem,
            resource_limits=ResourceLimits(
                cpu_count=profile.resource_limits.cpu_count,
                memory_mb=profile.resource_limits.memory_mb,
                pids_limit=profile.resource_limits.pids_limit,
                timeout_seconds=request.sandbox.timeout_seconds or profile.resource_limits.timeout_seconds,
            ),
        )

    def _get_profile(self, request: CreateSessionRequest) -> DockerSandboxProfile:
        profile_name = request.sandbox.profile or "default"
        profile = self._profiles.get(profile_name)
        if profile is None:
            raise ValueError(f"unknown sandbox profile: {profile_name}")
        return profile

    def _managed_env(self, session_id: str, request: CreateSessionRequest) -> Mapping[str, str]:
        env: dict[str, str] = {
            "AVIARY_SESSION_ID": session_id,
            "AVIARY_PROVIDER": request.provider.value,
            "AVIARY_WORKSPACE": "/workspace",
        }
        if request.model.name:
            env["AVIARY_MODEL"] = request.model.name
        if request.runtime.base_url:
            env["ANTHROPIC_BASE_URL"] = request.runtime.base_url
        if request.runtime.api_key_ref:
            env["AVIARY_API_KEY_REF"] = request.runtime.api_key_ref
        return env

    def _validate_managed_policy(self, request: CreateSessionRequest) -> None:
        if request.policy.execution_mode == ExecutionMode.BYPASS:
            raise ValueError("bypass execution mode is not allowed in Docker sandbox mode")
        if request.policy.filesystem == FilesystemPolicy.UNRESTRICTED:
            raise ValueError("unrestricted filesystem policy is not allowed in Docker sandbox mode")
        if request.policy.network == NetworkPolicy.UNRESTRICTED:
            raise ValueError("unrestricted network policy is not allowed in Docker sandbox mode")
        if request.policy.network == NetworkPolicy.ALLOWLIST and not request.policy.allowed_hosts:
            raise ValueError("allowlist network policy requires allowed_hosts")
