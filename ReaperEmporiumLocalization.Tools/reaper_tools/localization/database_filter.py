from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from re import Pattern
from typing import Any

from reaper_tools.app_context import AppContext


DEFAULT_EXCLUDED_ASSET_NAMES = (
    "db_Direct",
    "db_VoiceChara",
    "db_ResourceSoundBgmUse",
    "db_ResourceSoundSeUse",
)

DEFAULT_EXCLUDED_ASSET_NAME_REGEX = (
    "^db_Image",
)

CONFIG_RELATIVE_PATH = Path("localization") / "config" / "database_dump_filter.json"


@dataclass(frozen=True, slots=True)
class DatabaseDumpFilter:
    excluded_asset_names: frozenset[str]
    excluded_asset_name_regex: tuple[str, ...]
    compiled_regex: tuple[Pattern[str], ...] = field(repr=False)
    invalid_regex: tuple[str, ...] = ()
    source_path: Path | None = None

    def matches(self, asset_name: str) -> bool:
        if asset_name in self.excluded_asset_names:
            return True
        return any(pattern.search(asset_name) for pattern in self.compiled_regex)


def default_database_dump_filter_payload() -> dict[str, list[str]]:
    return {
        "excluded_asset_names": list(DEFAULT_EXCLUDED_ASSET_NAMES),
        "excluded_asset_name_regex": list(DEFAULT_EXCLUDED_ASSET_NAME_REGEX),
    }


def load_database_dump_filter(
    config_path: Path | None = None,
    *,
    context: AppContext | None = None,
) -> DatabaseDumpFilter:
    resolved_path = resolve_database_dump_filter_path(config_path, context=context)
    payload: dict[str, Any]
    if resolved_path is not None and resolved_path.is_file():
        payload = json.loads(resolved_path.read_text(encoding="utf-8-sig"))
    elif config_path is not None:
        raise FileNotFoundError(f"database_dump_filter.json 不存在：{resolved_path}")
    else:
        payload = default_database_dump_filter_payload()

    names = _string_list(payload.get("excluded_asset_names"))
    regexes = _string_list(payload.get("excluded_asset_name_regex"))
    compiled: list[Pattern[str]] = []
    invalid: list[str] = []
    for pattern in regexes:
        if not pattern.strip():
            continue
        try:
            compiled.append(re.compile(pattern))
        except re.error:
            invalid.append(pattern)

    return DatabaseDumpFilter(
        excluded_asset_names=frozenset(names),
        excluded_asset_name_regex=tuple(regexes),
        compiled_regex=tuple(compiled),
        invalid_regex=tuple(invalid),
        source_path=resolved_path,
    )


def resolve_database_dump_filter_path(config_path: Path | None, *, context: AppContext | None = None) -> Path | None:
    if config_path is not None:
        return Path(config_path)

    if context is None:
        return None

    game_root = context.paths.game_root
    if game_root is not None:
        candidate = game_root / CONFIG_RELATIVE_PATH
        if candidate.is_file():
            return candidate

    repo_candidate = context.paths.root.parent / "ReaperEmporium.GameRoot" / CONFIG_RELATIVE_PATH
    if repo_candidate.is_file():
        return repo_candidate

    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


__all__ = [
    "CONFIG_RELATIVE_PATH",
    "DEFAULT_EXCLUDED_ASSET_NAMES",
    "DEFAULT_EXCLUDED_ASSET_NAME_REGEX",
    "DatabaseDumpFilter",
    "default_database_dump_filter_payload",
    "load_database_dump_filter",
    "resolve_database_dump_filter_path",
]
