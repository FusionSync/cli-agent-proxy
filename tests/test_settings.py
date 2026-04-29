from pathlib import Path

import pytest

from aviary.main import create_app
from aviary.sandbox.docker import DockerSandboxDriver
from aviary.sandbox.docker_cli import DockerCliRuntimeClient
from aviary.sandbox.embedded import EmbeddedSandboxDriver
from aviary.settings import AviarySettings, SandboxMode, build_sandbox_driver


def test_settings_default_to_embedded_mode():
    settings = AviarySettings.from_env({})

    assert settings.sandbox_mode == SandboxMode.EMBEDDED
    assert settings.workspace_base_path is None
    assert settings.docker_binary == "docker"
    assert settings.docker_container_prefix == "aviary"


def test_settings_accepts_legacy_local_unsafe_mode_as_embedded():
    settings = AviarySettings.from_env({"AVIARY_SANDBOX_MODE": "local-unsafe"})

    assert settings.sandbox_mode == SandboxMode.EMBEDDED


def test_settings_normalize_direct_legacy_mode_values():
    settings = AviarySettings(sandbox_mode="local-unsafe")

    assert settings.sandbox_mode == SandboxMode.EMBEDDED


def test_settings_parse_managed_container_mode(tmp_path: Path):
    settings = AviarySettings.from_env(
        {
            "AVIARY_SANDBOX_MODE": "managed-container",
            "AVIARY_WORKSPACE_BASE_PATH": str(tmp_path),
            "AVIARY_DOCKER_BINARY": "/usr/bin/docker",
            "AVIARY_DOCKER_CONTAINER_PREFIX": "test-aviary",
            "AVIARY_DOCKER_RUNTIME_IMAGE": "aviary-runtime:test",
        }
    )

    assert settings.sandbox_mode == SandboxMode.MANAGED_CONTAINER
    assert settings.workspace_base_path == tmp_path
    assert settings.docker_binary == "/usr/bin/docker"
    assert settings.docker_container_prefix == "test-aviary"
    assert settings.docker_runtime_image == "aviary-runtime:test"


def test_settings_accepts_legacy_docker_cli_mode_as_managed_container():
    settings = AviarySettings.from_env({"AVIARY_SANDBOX_MODE": "docker-cli"})

    assert settings.sandbox_mode == SandboxMode.MANAGED_CONTAINER


def test_settings_reject_unknown_sandbox_mode():
    with pytest.raises(ValueError):
        AviarySettings.from_env({"AVIARY_SANDBOX_MODE": "docker-socket-in-api"})


def test_build_sandbox_driver_defaults_to_embedded():
    driver = build_sandbox_driver(AviarySettings.from_env({}), providers={})

    assert isinstance(driver, EmbeddedSandboxDriver)


def test_build_sandbox_driver_can_build_managed_container(tmp_path: Path):
    settings = AviarySettings.from_env(
        {
            "AVIARY_SANDBOX_MODE": "managed-container",
            "AVIARY_WORKSPACE_BASE_PATH": str(tmp_path),
            "AVIARY_DOCKER_BINARY": "docker",
            "AVIARY_DOCKER_CONTAINER_PREFIX": "aviary-test",
            "AVIARY_DOCKER_RUNTIME_IMAGE": "aviary-runtime:test",
        }
    )

    driver = build_sandbox_driver(settings, providers={"claude-code": object()})

    assert isinstance(driver, DockerSandboxDriver)
    assert isinstance(driver.runtime_client, DockerCliRuntimeClient)
    assert driver.get_provider_capabilities("claude-code") is not None


def test_create_app_uses_settings_when_no_driver_is_injected(tmp_path: Path):
    app = create_app(
        settings=AviarySettings.from_env(
            {
                "AVIARY_SANDBOX_MODE": "managed-container",
                "AVIARY_WORKSPACE_BASE_PATH": str(tmp_path),
                "AVIARY_DOCKER_RUNTIME_IMAGE": "aviary-runtime:test",
            }
        )
    )

    assert isinstance(app.state.sandbox_driver, DockerSandboxDriver)
    assert app.state.settings.sandbox_mode == SandboxMode.MANAGED_CONTAINER
