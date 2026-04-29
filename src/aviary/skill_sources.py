from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from aviary.schemas import SkillConfig, SkillSource, SkillSourceType


@dataclass(frozen=True)
class MaterializedSkillContext:
    project_dir: Path

    @property
    def add_dirs(self) -> tuple[str, ...]:
        return (str(self.project_dir),)

    def cleanup(self) -> None:
        shutil.rmtree(self.project_dir, ignore_errors=True)


class SkillMaterializer(Protocol):
    def materialize(self, session_id: str, config: SkillConfig) -> MaterializedSkillContext | None: ...


class FilesystemSkillMaterializer:
    """Materializes skill sources into a Claude-discoverable project directory."""

    def __init__(self, *, temp_root: Path | None = None) -> None:
        self._temp_root = temp_root

    def materialize(self, session_id: str, config: SkillConfig) -> MaterializedSkillContext | None:
        if not config.sources:
            return None

        project_dir = Path(
            tempfile.mkdtemp(
                prefix=f"aviary-skills-{_safe_label(session_id)}-",
                dir=str(self._temp_root) if self._temp_root else None,
            )
        )
        skills_dir = project_dir / ".claude" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        registered: set[str] = set()
        try:
            for source in config.sources:
                source_path = self._resolve_source(source, project_dir)
                for skill_dir in _discover_skill_dirs(source_path):
                    _register_skill_dir(skill_dir, skills_dir, registered)
        except Exception:
            shutil.rmtree(project_dir, ignore_errors=True)
            raise

        if not registered:
            shutil.rmtree(project_dir, ignore_errors=True)
            raise ValueError("skill sources did not contain any SKILL.md files")
        return MaterializedSkillContext(project_dir=project_dir)

    def _resolve_source(self, source: SkillSource, project_dir: Path) -> Path:
        if source.type == SkillSourceType.LOCAL_PATH:
            assert source.path is not None
            source_path = Path(source.path).expanduser().resolve()
            if not source_path.is_dir():
                raise ValueError(f"local skill source is not a directory: {source.path}")
            return source_path

        if source.type == SkillSourceType.S3_URI:
            assert source.uri is not None
            return _materialize_s3_source(source.uri, project_dir / "s3-sources")

        raise ValueError(f"unsupported skill source type: {source.type}")


def _discover_skill_dirs(source_path: Path) -> list[Path]:
    if (source_path / "SKILL.md").is_file():
        return [source_path]

    nested_skills = source_path / ".claude" / "skills"
    root = nested_skills if nested_skills.is_dir() else source_path
    skill_dirs = [
        child
        for child in sorted(root.iterdir())
        if child.is_dir() and (child / "SKILL.md").is_file()
    ]
    if not skill_dirs:
        raise ValueError(f"skill source does not contain skill directories: {source_path}")
    return skill_dirs


def _register_skill_dir(skill_dir: Path, skills_dir: Path, registered: set[str]) -> None:
    skill_name = skill_dir.name
    if skill_name in registered:
        raise ValueError(f"duplicate skill name: {skill_name}")

    target = skills_dir / skill_name
    try:
        target.symlink_to(skill_dir, target_is_directory=True)
    except OSError:
        shutil.copytree(skill_dir, target)
    registered.add(skill_name)


def _materialize_s3_source(uri: str, target_root: Path) -> Path:
    try:
        import fsspec
    except ImportError as exc:
        raise RuntimeError(
            "S3 skill sources require optional dependencies. Install with "
            "`uv sync --extra skill-s3`, or mount S3 as a local directory and "
            "use a local_path skill source."
        ) from exc

    fs, source_prefix = fsspec.core.url_to_fs(uri)
    files = [path for path in fs.find(source_prefix) if not path.endswith("/")]
    if not files:
        raise ValueError(f"S3 skill source is empty: {uri}")

    source_root = source_prefix.rstrip("/")
    target_dir = target_root / "source"
    target_dir.mkdir(parents=True, exist_ok=True)
    for file_path in files:
        normalized = file_path.rstrip("/")
        if normalized == source_root:
            relative = Path(normalized).name
        elif normalized.startswith(f"{source_root}/"):
            relative = normalized[len(source_root) :].lstrip("/")
        else:
            continue
        target_path = target_dir / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with fs.open(file_path, "rb") as source, target_path.open("wb") as target:
            shutil.copyfileobj(source, target)
    return target_dir


def _safe_label(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    sanitized = "".join(character if character in allowed else "-" for character in value)
    return sanitized[:80] or "session"
