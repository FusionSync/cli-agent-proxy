from pathlib import Path

import pytest

from aviary.sandbox.workspace import LocalWorkspaceAllocator, Workspace
from aviary.schemas import CreateSessionRequest, WorkspaceRetention


def test_local_workspace_allocator_creates_server_owned_isolated_workspaces(tmp_path: Path):
    allocator = LocalWorkspaceAllocator(tmp_path)

    first = allocator.allocate("session-1", CreateSessionRequest())
    second = allocator.allocate("session-2", CreateSessionRequest())

    assert first.path.exists()
    assert second.path.exists()
    assert first.path != second.path
    assert first.path.parent == tmp_path.resolve()
    assert second.path.parent == tmp_path.resolve()

    allocator.release(first)
    allocator.release(second)

    assert not first.path.exists()
    assert not second.path.exists()


def test_local_workspace_allocator_rejects_path_traversal_ids(tmp_path: Path):
    allocator = LocalWorkspaceAllocator(tmp_path)

    for unsafe_id in ("../escape", "nested/path", "", "."):
        with pytest.raises(ValueError):
            allocator.allocate(unsafe_id, CreateSessionRequest())


def test_local_workspace_allocator_only_releases_owned_paths(tmp_path: Path):
    allocator = LocalWorkspaceAllocator(tmp_path / "owned")
    outside = tmp_path / "outside"
    outside.mkdir()

    workspace = Workspace(
        workspace_id="outside",
        path=outside,
        retention=WorkspaceRetention.DELETE,
    )

    with pytest.raises(ValueError):
        allocator.release(workspace)

    assert outside.exists()


def test_local_workspace_allocator_honors_keep_retention(tmp_path: Path):
    allocator = LocalWorkspaceAllocator(tmp_path)
    workspace = allocator.allocate(
        "session-keep",
        CreateSessionRequest(sandbox={"workspace_retention": "keep"}),
    )

    allocator.release(workspace)

    assert workspace.path.exists()
