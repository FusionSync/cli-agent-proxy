from pathlib import Path

import pytest

from aviary.schemas import CreateSessionRequest


def test_skill_source_accepts_absolute_local_path(tmp_path: Path):
    request = CreateSessionRequest(
        skills={
            "sources": [{"type": "local_path", "path": str(tmp_path)}],
            "names": "all",
        }
    )

    assert request.skills.sources[0].path == str(tmp_path)
    assert request.skills.names == "all"


def test_skill_source_rejects_relative_local_path():
    with pytest.raises(ValueError):
        CreateSessionRequest(skills={"sources": [{"type": "local_path", "path": "relative/skills"}]})


def test_skill_source_accepts_s3_uri():
    request = CreateSessionRequest(
        skills={
            "sources": [{"type": "s3_uri", "uri": "s3://company-agent-skills/claude"}],
            "names": ["reviewer"],
        }
    )

    assert request.skills.sources[0].uri == "s3://company-agent-skills/claude"


def test_skill_source_rejects_non_s3_uri():
    with pytest.raises(ValueError):
        CreateSessionRequest(skills={"sources": [{"type": "s3_uri", "uri": "https://example.com/skills"}]})
