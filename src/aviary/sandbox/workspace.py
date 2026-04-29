from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from aviary.schemas import CreateSessionRequest, WorkspaceRetention


@dataclass(frozen=True)
class Workspace:
    workspace_id: str
    path: Path
    retention: WorkspaceRetention


class WorkspaceAllocator:
    """Allocates server-owned workspaces for sandbox runtimes."""

    def allocate(self, session_id: str, request: CreateSessionRequest) -> Workspace:
        raise NotImplementedError

    def release(self, workspace: Workspace) -> None:
        raise NotImplementedError


class LocalWorkspaceAllocator(WorkspaceAllocator):
    """Filesystem-backed allocator used by single-node sandbox drivers."""

    def __init__(self, base_path: Path | str | None = None) -> None:
        root = base_path or Path(tempfile.gettempdir()) / "aviary-workspaces"
        self._base_path = Path(root).expanduser().resolve()

    @property
    def base_path(self) -> Path:
        return self._base_path

    def allocate(self, session_id: str, request: CreateSessionRequest) -> Workspace:
        workspace_id = self._safe_workspace_id(session_id)
        workspace_path = (self._base_path / workspace_id).resolve()
        self._ensure_inside_base(workspace_path)
        workspace_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        return Workspace(
            workspace_id=workspace_id,
            path=workspace_path,
            retention=request.sandbox.workspace_retention,
        )

    def release(self, workspace: Workspace) -> None:
        self._ensure_inside_base(workspace.path.resolve())
        if workspace.retention == WorkspaceRetention.DELETE:
            shutil.rmtree(workspace.path, ignore_errors=True)

    def _safe_workspace_id(self, session_id: str) -> str:
        if not session_id:
            raise ValueError("session_id cannot be empty")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
        if any(character not in allowed for character in session_id):
            raise ValueError("session_id contains unsafe path characters")
        if session_id in {".", ".."}:
            raise ValueError("session_id cannot be a relative path segment")
        return session_id

    def _ensure_inside_base(self, path: Path) -> None:
        try:
            path.relative_to(self._base_path)
        except ValueError as exc:
            raise ValueError("workspace path escapes allocator base path") from exc
