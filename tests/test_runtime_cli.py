import io
import json
import sys
import tomllib
from pathlib import Path

from aviary.runtime import cli
from aviary.runtime.protocol import RuntimeCommand, encode_command
from aviary.schemas import AgentEvent


class FakeRuntimeWorker:
    instances: list["FakeRuntimeWorker"] = []

    def __init__(self, *, environment):
        self.environment = environment
        self.commands: list[RuntimeCommand] = []
        FakeRuntimeWorker.instances.append(self)

    async def handle(self, command: RuntimeCommand):
        self.commands.append(command)
        yield AgentEvent(
            type="ai_chunk",
            session_id=command.session_id,
            conversation_id=command.session_id,
            data={"content": "ok"},
        )


def run_cli(monkeypatch, argv, stdin: str, environ: dict[str, str]):
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(cli.os, "environ", environ)
    return_code = cli.main(argv)
    return return_code, stdout.getvalue(), stderr.getvalue()


def test_runtime_cli_query_reads_stdin_and_writes_jsonl(monkeypatch):
    FakeRuntimeWorker.instances = []
    monkeypatch.setattr(cli, "RuntimeWorker", FakeRuntimeWorker)
    command = RuntimeCommand(type="query", session_id="session-1", payload={"message": "hello"})

    return_code, stdout, stderr = run_cli(
        monkeypatch,
        ["query"],
        encode_command(command),
        {
            "AVIARY_SESSION_ID": "session-1",
            "AVIARY_PROVIDER": "claude-code",
            "AVIARY_WORKSPACE": "/workspace",
        },
    )

    assert return_code == 0
    assert stderr == ""
    lines = stdout.splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["type"] == "ai_chunk"
    assert payload["session_id"] == "session-1"
    assert FakeRuntimeWorker.instances[0].environment.workspace == "/workspace"
    assert FakeRuntimeWorker.instances[0].commands == [command]


def test_runtime_cli_interrupt_reads_stdin_and_writes_jsonl(monkeypatch):
    FakeRuntimeWorker.instances = []
    monkeypatch.setattr(cli, "RuntimeWorker", FakeRuntimeWorker)
    command = RuntimeCommand(type="interrupt", session_id="session-1")

    return_code, stdout, stderr = run_cli(
        monkeypatch,
        ["interrupt"],
        encode_command(command),
        {"AVIARY_SESSION_ID": "session-1", "AVIARY_PROVIDER": "claude-code"},
    )

    assert return_code == 0
    assert stderr == ""
    assert json.loads(stdout)["type"] == "ai_chunk"
    assert FakeRuntimeWorker.instances[0].commands == [command]


def test_runtime_cli_serve_once_writes_readiness_event(monkeypatch):
    return_code, stdout, stderr = run_cli(monkeypatch, ["serve", "--once"], "", {})

    assert return_code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["type"] == "end"
    assert payload["data"] == {"ready": True}


def test_runtime_cli_rejects_invalid_json_as_error_event(monkeypatch):
    return_code, stdout, stderr = run_cli(
        monkeypatch,
        ["query"],
        "not-json\n",
        {"AVIARY_SESSION_ID": "session-1", "AVIARY_PROVIDER": "claude-code"},
    )

    assert return_code == 1
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["type"] == "error"
    assert payload["session_id"] == "session-1"
    assert payload["data"]["detail"] == "runtime command input is invalid"


def test_runtime_cli_rejects_missing_environment_as_error_event(monkeypatch):
    command = RuntimeCommand(type="query", session_id="session-1", payload={"message": "hello"})

    return_code, stdout, stderr = run_cli(monkeypatch, ["query"], encode_command(command), {})

    assert return_code == 1
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["type"] == "error"
    assert payload["session_id"] == "unknown"
    assert "AVIARY_SESSION_ID" in payload["data"]["detail"]


def test_runtime_cli_redacts_secret_like_errors(monkeypatch):
    command = RuntimeCommand(type="query", session_id="session-1", payload={"message": "hello"})
    monkeypatch.setattr(
        cli,
        "RuntimeWorker",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("failed ANTHROPIC_API_KEY=sk-ant-secret")),
    )

    return_code, stdout, stderr = run_cli(
        monkeypatch,
        ["query"],
        encode_command(command),
        {"AVIARY_SESSION_ID": "session-1", "AVIARY_PROVIDER": "claude-code"},
    )

    assert return_code == 1
    assert stderr == ""
    assert "sk-ant-secret" not in stdout
    assert "ANTHROPIC_API_KEY=[REDACTED]" in stdout


def test_pyproject_exposes_aviary_runtime_console_script():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    assert pyproject["project"]["scripts"]["aviary-runtime"] == "aviary.runtime.cli:main"
