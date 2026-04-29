from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from aviary.runtime.protocol import RuntimeCommand, decode_event_line, encode_command
from aviary.sandbox.docker import DockerContainerSpec, DockerRuntimeClient
from aviary.schemas import AgentEvent, NetworkPolicy, StreamMessageRequest


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class DockerCommandError(RuntimeError):
    pass


class DockerCommandRunner:
    async def run(self, args: Sequence[str], *, input_text: str | None = None) -> CommandResult:
        raise NotImplementedError

    async def stream(self, args: Sequence[str], *, input_text: str | None = None) -> AsyncIterator[str]:
        raise NotImplementedError
        yield


class SubprocessDockerCommandRunner(DockerCommandRunner):
    async def run(self, args: Sequence[str], *, input_text: str | None = None) -> CommandResult:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if input_text is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(input_text.encode() if input_text is not None else None)
        return CommandResult(
            returncode=process.returncode or 0,
            stdout=stdout.decode(),
            stderr=stderr.decode(),
        )

    async def stream(self, args: Sequence[str], *, input_text: str | None = None) -> AsyncIterator[str]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if input_text is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if input_text is not None and process.stdin is not None:
            process.stdin.write(input_text.encode())
            await process.stdin.drain()
            process.stdin.close()

        if process.stdout is not None:
            while line := await process.stdout.readline():
                yield line.decode()

        stderr = b""
        if process.stderr is not None:
            stderr = await process.stderr.read()
        returncode = await process.wait()
        if returncode != 0:
            raise DockerCommandError(stderr.decode() or f"docker command failed: {returncode}")


class DockerCliRuntimeClient(DockerRuntimeClient):
    """Docker CLI backed runtime client using JSONL commands over docker exec.

    The adapter never invokes a shell. All Docker commands are argv lists so
    session ids, paths, and env values cannot become shell fragments.
    """

    def __init__(
        self,
        *,
        runner: DockerCommandRunner | None = None,
        docker_binary: str = "docker",
        container_prefix: str = "aviary",
    ) -> None:
        self._runner = runner or SubprocessDockerCommandRunner()
        self._docker_binary = docker_binary
        self._container_prefix = container_prefix
        self._containers: dict[str, str] = {}
        self._specs: dict[str, DockerContainerSpec] = {}

    async def create_session(self, spec: DockerContainerSpec) -> None:
        container_name = self._container_name(spec.session_id)
        args = self._build_run_args(spec, container_name)
        result = await self._runner.run(args)
        self._check_result(result)
        self._containers = {**self._containers, spec.session_id: container_name}
        self._specs = {**self._specs, spec.session_id: spec}

    async def stream_message(
        self,
        session_id: str,
        request: StreamMessageRequest,
    ) -> AsyncIterator[AgentEvent]:
        container_name = self._get_container(session_id)
        command = RuntimeCommand(
            type="query",
            session_id=session_id,
            payload={
                "message": request.message,
                "inputs": request.inputs,
                "files": request.files,
            },
        )
        args = [self._docker_binary, "exec", "-i", container_name, "aviary-runtime", "query"]
        async for line in self._runner.stream(args, input_text=encode_command(command)):
            event = decode_event_line(line)
            if event.session_id != session_id:
                raise ValueError("runtime event session_id does not match active session")
            yield event

    async def interrupt(self, session_id: str) -> None:
        await self._run_runtime_command(session_id, "interrupt")

    async def close(self, session_id: str) -> None:
        container_name = self._get_container(session_id)
        try:
            await self._run_runtime_command(session_id, "close")
        finally:
            result = await self._runner.run([self._docker_binary, "rm", "-f", container_name])
            self._check_result(result)
            self._containers = {key: value for key, value in self._containers.items() if key != session_id}
            self._specs = {key: value for key, value in self._specs.items() if key != session_id}

    async def _run_runtime_command(
        self,
        session_id: str,
        command_type: str,
    ) -> None:
        container_name = self._get_container(session_id)
        command = RuntimeCommand(type=command_type, session_id=session_id)
        result = await self._runner.run(
            [self._docker_binary, "exec", "-i", container_name, "aviary-runtime", command_type],
            input_text=encode_command(command),
        )
        self._check_result(result)

    def _build_run_args(self, spec: DockerContainerSpec, container_name: str) -> list[str]:
        if spec.privileged:
            raise ValueError("privileged containers are not allowed")
        args = [
            self._docker_binary,
            "run",
            "-d",
            "--name",
            container_name,
            "--user",
            spec.user,
            "--workdir",
            spec.container_workspace_path,
            "--pids-limit",
            str(spec.resource_limits.pids_limit),
            "--cpus",
            str(spec.resource_limits.cpu_count),
            "--memory",
            f"{spec.resource_limits.memory_mb}m",
            "--volume",
            f"{spec.workspace.path}:{spec.container_workspace_path}:rw",
            "--network",
            self._network_mode(spec),
        ]

        if spec.read_only_rootfs:
            args.append("--read-only")
        for capability in spec.cap_drop:
            args.extend(["--cap-drop", capability])
        if spec.no_new_privileges:
            args.extend(["--security-opt", "no-new-privileges"])
        for key, value in sorted(spec.env.items()):
            self._validate_env_name(key)
            args.extend(["--env", f"{key}={value}"])
        if spec.network_policy == NetworkPolicy.ALLOWLIST:
            args.extend(["--env", f"AVIARY_ALLOWED_HOSTS={','.join(spec.allowed_hosts)}"])
        for key, value in sorted(spec.labels.items()):
            args.extend(["--label", f"{key}={value}"])

        args.append(spec.image)
        args.extend(spec.command)
        return args

    def _network_mode(self, spec: DockerContainerSpec) -> str:
        if spec.network_policy == NetworkPolicy.DENY_BY_DEFAULT:
            return "none"
        if spec.network_policy == NetworkPolicy.ALLOWLIST:
            return "bridge"
        raise ValueError(f"unsupported Docker network policy: {spec.network_policy}")

    def _container_name(self, session_id: str) -> str:
        if not session_id:
            raise ValueError("session_id cannot be empty")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
        if any(character not in allowed for character in session_id):
            raise ValueError("session_id contains unsafe Docker name characters")
        if session_id in {".", ".."}:
            raise ValueError("session_id cannot be a relative path segment")
        return f"{self._container_prefix}-{session_id}"

    def _get_container(self, session_id: str) -> str:
        container_name = self._containers.get(session_id)
        if container_name is None:
            raise KeyError(session_id)
        return container_name

    def _validate_env_name(self, key: str) -> None:
        if not key or not key.replace("_", "A").isalnum() or key[0].isdigit():
            raise ValueError(f"unsafe environment variable name: {key}")

    def _check_result(self, result: CommandResult) -> None:
        if result.returncode != 0:
            raise DockerCommandError(result.stderr or f"docker command failed: {result.returncode}")
