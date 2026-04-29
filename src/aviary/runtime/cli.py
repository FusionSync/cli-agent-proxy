from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence

from aviary.runtime.protocol import RuntimeCommand, decode_command_line, encode_event
from aviary.runtime.worker import RuntimeEnvironment, RuntimeWorker, redact_secrets
from aviary.schemas import AgentEvent


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aviary-runtime")
    parser.add_argument("command", choices=["serve", "query", "interrupt", "close", "health"])
    parser.add_argument("--once", action="store_true", help="Run one readiness cycle and exit.")
    args = parser.parse_args(argv)
    return asyncio.run(_main_async(args.command, serve_once=args.once))


async def _main_async(command_name: str, *, serve_once: bool = False) -> int:
    if command_name == "serve":
        await _write_event(_control_event("end", {"ready": True}))
        if serve_once:
            return 0
        await asyncio.Event().wait()
        return 0

    try:
        command = _read_command(command_name)
        environment = RuntimeEnvironment.from_mapping(dict(os.environ))
        worker = RuntimeWorker(environment=environment)
        async for event in worker.handle(command):
            await _write_event(event)
        return 0
    except Exception as exc:
        session_id = os.environ.get("AVIARY_SESSION_ID", "unknown")
        await _write_event(
            AgentEvent(
                type="error",
                session_id=session_id,
                conversation_id=session_id,
                data={"detail": redact_secrets(str(exc))},
            )
        )
        return 1


def _read_command(expected_name: str) -> RuntimeCommand:
    line = sys.stdin.readline()
    if not line:
        raise ValueError("runtime command input is empty")
    try:
        command = decode_command_line(line)
    except ValueError as exc:
        raise ValueError("runtime command input is invalid") from exc
    if command.type != expected_name:
        raise ValueError(f"runtime command mismatch: expected {expected_name}, got {command.type}")
    return command


async def _write_event(event: AgentEvent) -> None:
    sys.stdout.write(encode_event(event))
    sys.stdout.flush()


def _control_event(event_type: str, data: dict[str, object]) -> AgentEvent:
    session_id = os.environ.get("AVIARY_SESSION_ID", "runtime")
    return AgentEvent(
        type=event_type,  # type: ignore[arg-type]
        session_id=session_id,
        conversation_id=session_id,
        data=data,
    )


if __name__ == "__main__":
    raise SystemExit(main())
