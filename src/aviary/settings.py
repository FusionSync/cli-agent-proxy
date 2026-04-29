from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from aviary.approvals import ApprovalBroker
from aviary.providers.base import AgentProvider
from aviary.providers.claude_code import ClaudeCodeProvider
from aviary.sandbox.base import SandboxDriver
from aviary.sandbox.docker import DockerSandboxDriver, DockerSandboxProfile
from aviary.sandbox.docker_cli import DockerCliRuntimeClient
from aviary.sandbox.embedded import EmbeddedSandboxDriver
from aviary.sandbox.workspace import LocalWorkspaceAllocator


class SandboxMode(str, Enum):
    EMBEDDED = "embedded"
    MANAGED_CONTAINER = "managed-container"
    LOCAL_UNSAFE = "local-unsafe"
    DOCKER_CLI = "docker-cli"


_SANDBOX_MODE_ALIASES = {
    SandboxMode.LOCAL_UNSAFE: SandboxMode.EMBEDDED,
    SandboxMode.DOCKER_CLI: SandboxMode.MANAGED_CONTAINER,
}


@dataclass(frozen=True)
class AviarySettings:
    sandbox_mode: SandboxMode | str = SandboxMode.EMBEDDED
    workspace_base_path: Path | None = None
    docker_binary: str = "docker"
    docker_container_prefix: str = "aviary"
    docker_runtime_image: str = "ghcr.io/fusionsync/aviary-claude-code-runtime:latest"

    def __post_init__(self) -> None:
        object.__setattr__(self, "sandbox_mode", normalize_sandbox_mode(self.sandbox_mode))

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AviarySettings":
        source = environ if environ is not None else os.environ
        mode_value = source.get("AVIARY_SANDBOX_MODE", SandboxMode.EMBEDDED.value)
        try:
            sandbox_mode = normalize_sandbox_mode(SandboxMode(mode_value))
        except ValueError as exc:
            raise ValueError(f"unsupported AVIARY_SANDBOX_MODE: {mode_value}") from exc

        workspace_base_path = source.get("AVIARY_WORKSPACE_BASE_PATH")
        return cls(
            sandbox_mode=sandbox_mode,
            workspace_base_path=Path(workspace_base_path).expanduser() if workspace_base_path else None,
            docker_binary=source.get("AVIARY_DOCKER_BINARY", "docker"),
            docker_container_prefix=source.get("AVIARY_DOCKER_CONTAINER_PREFIX", "aviary"),
            docker_runtime_image=source.get(
                "AVIARY_DOCKER_RUNTIME_IMAGE",
                "ghcr.io/fusionsync/aviary-claude-code-runtime:latest",
            ),
        )


def default_provider_registry(approval_broker: ApprovalBroker | None = None) -> dict[str, AgentProvider]:
    return {ClaudeCodeProvider.name: ClaudeCodeProvider(approval_broker=approval_broker)}


def normalize_sandbox_mode(mode: SandboxMode | str) -> SandboxMode:
    parsed_mode = mode if isinstance(mode, SandboxMode) else SandboxMode(mode)
    return _SANDBOX_MODE_ALIASES.get(parsed_mode, parsed_mode)


def build_sandbox_driver(
    settings: AviarySettings,
    *,
    providers: dict[str, AgentProvider],
) -> SandboxDriver:
    sandbox_mode = normalize_sandbox_mode(settings.sandbox_mode)
    if sandbox_mode == SandboxMode.EMBEDDED:
        return EmbeddedSandboxDriver(providers=providers)

    if sandbox_mode == SandboxMode.MANAGED_CONTAINER:
        runtime_client = DockerCliRuntimeClient(
            docker_binary=settings.docker_binary,
            container_prefix=settings.docker_container_prefix,
        )
        workspace_allocator = LocalWorkspaceAllocator(settings.workspace_base_path)
        profile = DockerSandboxProfile(image=settings.docker_runtime_image)
        return DockerSandboxDriver(
            providers=providers.keys(),
            runtime_client=runtime_client,
            workspace_allocator=workspace_allocator,
            profiles={"default": profile},
        )

    raise ValueError(f"unsupported sandbox mode: {sandbox_mode}")
