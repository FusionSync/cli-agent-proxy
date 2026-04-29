from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from aviary.providers.base import AgentProvider
from aviary.providers.claude_code import ClaudeCodeProvider
from aviary.sandbox.base import SandboxDriver
from aviary.sandbox.docker import DockerSandboxDriver, DockerSandboxProfile
from aviary.sandbox.docker_cli import DockerCliRuntimeClient
from aviary.sandbox.local_unsafe import LocalUnsafeSandboxDriver
from aviary.sandbox.workspace import LocalWorkspaceAllocator


class SandboxMode(str, Enum):
    LOCAL_UNSAFE = "local-unsafe"
    DOCKER_CLI = "docker-cli"


@dataclass(frozen=True)
class AviarySettings:
    sandbox_mode: SandboxMode = SandboxMode.LOCAL_UNSAFE
    workspace_base_path: Path | None = None
    docker_binary: str = "docker"
    docker_container_prefix: str = "aviary"
    docker_runtime_image: str = "ghcr.io/fusionsync/aviary-claude-code-runtime:latest"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AviarySettings":
        source = environ if environ is not None else os.environ
        mode_value = source.get("AVIARY_SANDBOX_MODE", SandboxMode.LOCAL_UNSAFE.value)
        try:
            sandbox_mode = SandboxMode(mode_value)
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


def default_provider_registry() -> dict[str, AgentProvider]:
    return {ClaudeCodeProvider.name: ClaudeCodeProvider()}


def build_sandbox_driver(
    settings: AviarySettings,
    *,
    providers: dict[str, AgentProvider],
) -> SandboxDriver:
    if settings.sandbox_mode == SandboxMode.LOCAL_UNSAFE:
        return LocalUnsafeSandboxDriver(providers=providers)

    if settings.sandbox_mode == SandboxMode.DOCKER_CLI:
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

    raise ValueError(f"unsupported sandbox mode: {settings.sandbox_mode}")
