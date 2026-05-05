from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from reaper_tools.app_context import AppContext, get_app_context
from reaper_tools.models import ParatranzFile

from .database_filter import DatabaseDumpFilter, load_database_dump_filter
from .installer import clean_category_name
from .paratranz import Paratranz


@dataclass(frozen=True, slots=True)
class FilteredRemoteFile:
    file_id: int | None
    remote_name: str
    asset_name: str


@dataclass(slots=True)
class DeleteFilteredFilesSummary:
    scanned_files: int = 0
    database_files: int = 0
    matched_files: int = 0
    planned_files: int = 0
    deleted_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0


@dataclass(slots=True)
class DeleteFilteredFilesResult:
    project_id: int
    dry_run: bool
    filter_config: DatabaseDumpFilter
    summary: DeleteFilteredFilesSummary = field(default_factory=DeleteFilteredFilesSummary)
    actions: list[FilteredRemoteFile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def delete_filtered_database_files(
    *,
    config_path: Path | None = None,
    project_id: int | None = None,
    dry_run: bool = True,
    show_progress: bool = False,
    context: AppContext | None = None,
    api: Any | None = None,
) -> DeleteFilteredFilesResult:
    ctx = context or getattr(api, "context", None) or get_app_context()
    paratranz = api or Paratranz(context=ctx)
    resolved_project_id = project_id or paratranz.project_id
    dump_filter = load_database_dump_filter(config_path, context=ctx)
    remote_files = list(paratranz.get_files(project_id=resolved_project_id))

    result = DeleteFilteredFilesResult(
        project_id=resolved_project_id,
        dry_run=dry_run,
        filter_config=dump_filter,
    )
    result.summary.scanned_files = len(remote_files)

    for remote_file in remote_files:
        match = _match_filtered_database_file(remote_file, dump_filter)
        if match is None:
            continue
        result.summary.database_files += 1
        result.summary.matched_files += 1
        result.actions.append(match)

    result.summary.planned_files = len(result.actions)
    if dry_run:
        return result

    with ctx.progress(total=len(result.actions), enabled=show_progress, desc="删除过滤文件", unit="文件") as progress:
        for action in result.actions:
            progress.set_postfix_str(action.remote_name)
            progress.update()
            if action.file_id is None:
                result.summary.skipped_files += 1
                result.errors.append(f"远端文件缺少 id，已跳过：{action.remote_name}")
                continue
            try:
                paratranz.delete_file(action.file_id, project_id=resolved_project_id)
                result.summary.deleted_files += 1
            except Exception as exc:  # noqa: BLE001 - keep cleanup resilient and report all failures.
                result.summary.failed_files += 1
                result.errors.append(f"{action.remote_name}: {exc}")

    return result


def _match_filtered_database_file(remote_file: ParatranzFile, dump_filter: DatabaseDumpFilter) -> FilteredRemoteFile | None:
    remote_name = _remote_file_name(remote_file)
    if not remote_name:
        return None
    normalized = remote_name.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if path.suffix.lower() != ".json" or "database" not in path.parts:
        return None

    asset_name = clean_category_name(Path(path.name))
    if not dump_filter.matches(asset_name):
        return None

    return FilteredRemoteFile(
        file_id=getattr(remote_file, "id", None),
        remote_name=normalized,
        asset_name=asset_name,
    )


def _remote_file_name(remote_file: Any) -> str:
    if isinstance(remote_file, dict):
        return str(remote_file.get("name") or "")
    return str(getattr(remote_file, "name", "") or "")


__all__ = [
    "DeleteFilteredFilesResult",
    "DeleteFilteredFilesSummary",
    "FilteredRemoteFile",
    "delete_filtered_database_files",
]
