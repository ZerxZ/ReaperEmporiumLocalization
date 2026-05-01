from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from .configuration import settings
from .exceptions import ConfigurationError, SafePathError


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    root: Path
    data: Path
    cache: Path
    paratranz: Path
    logs: Path
    game_root: Path | None

    @classmethod
    def from_settings(cls) -> "ProjectPaths":
        root = settings.filepath.root.resolve()
        data = _resolve_under(root, settings.filepath.data)
        cache = _resolve_under(root, settings.filepath.cache)
        paratranz = _resolve_under(root, settings.filepath.paratranz)
        game_root = _resolve_game_root(root, settings.filepath.game_root)
        return cls(
            root=root,
            data=data,
            cache=cache,
            paratranz=paratranz,
            logs=data / "logs",
            game_root=game_root,
        )

    @property
    def artifact_zip(self) -> Path:
        return self.cache / "paratranz_export.zip"

    def ensure_base_dirs(self) -> None:
        for path in (self.data, self.cache, self.paratranz, self.logs):
            path.mkdir(parents=True, exist_ok=True)

    def require_game_root(self, override: Path | str | None = None) -> Path:
        candidate = _resolve_game_root(self.root, Path(override) if override else self.game_root)
        if candidate is None:
            raise ConfigurationError("Game root is not configured. Set PATH_GAME_ROOT or pass --game-root.")
        return candidate

    def ensure_inside(self, path: Path, root: Path) -> Path:
        target = path.resolve()
        anchor = root.resolve()
        if target == anchor or anchor not in target.parents:
            raise SafePathError(f"Refusing to modify path outside {anchor}: {target}")
        return target


def _resolve_under(root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _resolve_game_root(tool_root: Path, value: Path | None) -> Path | None:
    if value is not None:
        return value.resolve() if value.is_absolute() else (tool_root / value).resolve()
    try:
        return tool_root.parents[2].resolve()
    except IndexError:
        return None


def safe_extract_zip(archive: ZipFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != destination and destination not in target.parents:
            raise RuntimeError(f"Archive member escapes extraction root: {member.filename}")
    archive.extractall(destination)


paths = ProjectPaths.from_settings()


__all__ = ["ProjectPaths", "paths", "safe_extract_zip"]
