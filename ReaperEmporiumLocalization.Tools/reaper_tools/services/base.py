from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reaper_tools.app_context import AppContext, get_app_context
from reaper_tools.models import Page, ParatranzData, ParatranzTerm, TermWriteRequest, paratranz_data_list_adapter

if TYPE_CHECKING:
    from reaper_tools.services.paratranz_api import ParatranzApiClient


MAIN_GAME_DIR = "MainGame"
DLC_GAME_DIR = "DLCGame"
DLL_STRINGS_FILE = "dll_strings.json"
DATABASE_DIR = "database"
MIGRATION_REPORT_FILE = "migration_report.json"
_CAB_SUFFIX_PATTERN = re.compile(r"-CAB-.*$")
_NUMBER_SUFFIX_PATTERN = re.compile(r"_\d+$")
_ASSET_TEXT_DIR_PATTERN = re.compile(r"^asset_\d+_text(?:_DLC)?$", re.IGNORECASE)


@dataclass(slots=True)
class _LegacyEntryCandidate:
    """旧 ParaTranz 词条候选，保留来源用于择优和报告冲突。"""

    entry: ParatranzData
    source_path: str
    source_priority: int
    order: int


@dataclass(slots=True)
class _LegacyTranslationIndex:
    """旧译文索引，按目标文件优先，同时保留全局兜底池。"""

    database_by_file: dict[str, dict[str, list[_LegacyEntryCandidate]]]
    database_global: dict[str, list[_LegacyEntryCandidate]]
    dll_by_file: dict[str, dict[tuple[str, str, str], list[_LegacyEntryCandidate]]]
    dll_global: dict[tuple[str, str, str], list[_LegacyEntryCandidate]]
    dll_original_by_file: dict[str, dict[str, list[_LegacyEntryCandidate]]]
    dll_original_global: dict[str, list[_LegacyEntryCandidate]]
    file_mappings: list[dict[str, Any]]
    duplicate_files: dict[str, list[str]]
    source_files: int = 0
    source_entries: int = 0


class _TemporaryJsonFile:
    """临时 JSON 文件上下文。"""

    def __init__(self, payload: Any, *, filename: str | None = None):
        self._payload = payload
        self._filename = filename
        self._name: str | None = None
        self._directory: tempfile.TemporaryDirectory | None = None

    def __enter__(self) -> Path:
        if self._filename:
            self._directory = tempfile.TemporaryDirectory()
            target = Path(self._directory.name) / Path(self._filename).name
            self._name = str(target)
            target.write_text(json.dumps(self._payload, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
                self._name = handle.name
                json.dump(self._payload, handle, ensure_ascii=False, indent=2)
        return Path(self._name)

    def __exit__(self, exc_type, exc, traceback):
        if self._directory is not None:
            self._directory.cleanup()
        elif self._name:
            Path(self._name).unlink(missing_ok=True)
        return False


class ParatranzServiceBase:
    """Shared context and file helpers for ParaTranz services."""

    def __init__(self, api: ParatranzApiClient, *, context: AppContext | None = None) -> None:
        self.api = api
        self.context = context or getattr(api, "context", None) or get_app_context()
        self.settings = self.context.settings
        self.paths = self.context.paths
        self.logger = self.context.logger

    def __getattr__(self, name: str) -> Any:
        return getattr(self.api, name)

    def progress(
        self,
        *,
        total: int | None = None,
        enabled: bool = False,
        desc: str = "",
        unit: str = "it",
        unit_scale: bool = False,
    ):
        return self.context.progress(
            total=total,
            enabled=enabled,
            desc=desc,
            unit=unit,
            unit_scale=unit_scale,
        )

    def _temporary_paratranz_file(self, entries: list[ParatranzData], *, filename: str | None = None):
        payload = [entry.model_dump(mode="json") for entry in entries]
        return self._temporary_json_file(payload, filename=filename)

    def _temporary_json_file(self, payload: Any, *, filename: str | None = None):
        return _TemporaryJsonFile(payload, filename=filename)

    def _read_paratranz_file(self, file_path: Path) -> list[ParatranzData]:
        payload = json.loads(file_path.read_text(encoding="utf-8-sig"))
        return paratranz_data_list_adapter.validate_python(payload)

    def _write_paratranz_file(self, target: Path, entries: list[ParatranzData]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = [entry.model_dump(mode="json") for entry in entries]
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    def _report_path(self, path: Path) -> str:
        resolved = path.resolve()
        for base in (self.paths.root, Path.cwd()):
            try:
                return Path(os.path.relpath(resolved, base.resolve())).as_posix()
            except (OSError, ValueError):
                continue
        return path.as_posix()

    def _term_import_payload(self, term: ParatranzTerm) -> dict[str, Any]:
        return TermWriteRequest(
            pos=term.pos,
            term=term.term,
            translation=term.translation,
            note=term.note,
            variants=term.variants,
            case_sensitive=term.case_sensitive,
        ).to_api_payload()

    def _iter_term_pages(self, *, project_id: int) -> Iterable[Page[ParatranzTerm]]:
        page_number = 1
        while True:
            page = self.get_terms(page=page_number, page_size=100, project_id=project_id)
            yield page
            if not page.results or (page.page_count is not None and page_number >= page.page_count):
                break
            page_number += 1

    def _json_files(self, root: Path) -> list[Path]:
        if not root.exists():
            return []
        return sorted(
            (item for item in root.rglob("*.json") if item.name != MIGRATION_REPORT_FILE),
            key=lambda item: item.relative_to(root).as_posix().casefold(),
        )

    def _remote_name(self, source_root: Path, file_path: Path, remote_prefix: str) -> str:
        relative = file_path.relative_to(source_root).as_posix()
        prefix = remote_prefix.strip("/")
        return f"{prefix}/{relative}" if prefix else relative

    def _remote_parent(self, remote_name: str) -> str:
        parent = Path(remote_name).parent.as_posix()
        if parent == ".":
            return ""
        return f"{parent}/"

    def _normalize_remote_name(self, name: str) -> str:
        return name.replace("\\", "/").strip("/")

    def _chunks(self, values: list[int], chunk_size: int) -> list[list[int]]:
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0。")
        return [values[index : index + chunk_size] for index in range(0, len(values), chunk_size)]


__all__ = [
    "DATABASE_DIR",
    "DLL_STRINGS_FILE",
    "DLC_GAME_DIR",
    "MAIN_GAME_DIR",
    "MIGRATION_REPORT_FILE",
    "ParatranzServiceBase",
    "_ASSET_TEXT_DIR_PATTERN",
    "_CAB_SUFFIX_PATTERN",
    "_LegacyEntryCandidate",
    "_LegacyTranslationIndex",
    "_NUMBER_SUFFIX_PATTERN",
]
