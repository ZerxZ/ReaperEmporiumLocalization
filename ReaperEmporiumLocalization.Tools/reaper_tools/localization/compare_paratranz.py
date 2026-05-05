from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from thefuzz import fuzz

from reaper_tools.app_context import AppContext, build_app_context, get_app_context
from reaper_tools.models import ParatranzData, StageEnum, StringWriteRequest
from reaper_tools.services.base import _ASSET_TEXT_DIR_PATTERN

from .diff_helpers import (
    DATABASE_DIR,
    DATABASE_ORIGINAL_FUZZY_THRESHOLD,
    DLL_STRINGS_FILE,
    DLC_GAME_DIR,
    MAIN_GAME_DIR,
    DatabaseEntryMatcher,
    DatabaseMatchPair,
    build_database_match_pairs,
    database_original_for_match,
    json_files,
    next_database_key_counter,
    write_paratranz_file,
    write_readable_json_diff,
)
from .installer import clean_category_name, read_paratranz_file
from .paratranz import Paratranz

DIFF_DIR = "diff"
DELTA_DIR = "delta"
REVIEW_DIR = "review"
SOURCE_UPDATES_DIR = "source_updates"
NEW_ENTRIES_DIR = "new_entries"
TRANSLATION_UPDATES_DIR = "translation_updates"
ENTRY_UPDATES_DIR = "entry_updates"
REMOTE_ONLY_DIR = "remote_only"
_UPLOAD_DELTA_CATEGORIES = (
    SOURCE_UPDATES_DIR,
    ENTRY_UPDATES_DIR,
    TRANSLATION_UPDATES_DIR,
    NEW_ENTRIES_DIR,
)
_DEFAULT_CONTEXT = get_app_context()
paths = _DEFAULT_CONTEXT.paths
logger = _DEFAULT_CONTEXT.logger
_SCOPE_DIRECTORY_BY_KEY = {"main": MAIN_GAME_DIR, "dlc": DLC_GAME_DIR}


@dataclass(slots=True)
class CompareParatranzSummary:
    scanned_files: int = 0
    remote_only_files: int = 0
    local_only_files: int = 0
    remote_only_entries: int = 0
    local_only_entries: int = 0
    source_changed_entries: int = 0
    translation_changed_entries: int = 0
    entry_changed_entries: int = 0


@dataclass(slots=True)
class CompareParatranzFileReport:
    relative_path: str
    file_type: str
    only_in: str | None = None
    remote_entries: int = 0
    local_entries: int = 0
    remote_only: int = 0
    local_only: int = 0
    source_changed: int = 0
    translation_changed: int = 0
    entry_changed: int = 0
    delta_paths: dict[str, str] = field(default_factory=dict)
    review_paths: dict[str, str] = field(default_factory=dict)
    diff_path: str | None = None

    @property
    def has_delta(self) -> bool:
        return bool(self.delta_paths)

    @property
    def has_source_diff(self) -> bool:
        return any(
            (
                self.source_changed,
                self.entry_changed,
            )
        )


@dataclass(slots=True)
class CompareParatranzResult:
    scope: str
    scope_dir: str
    remote_root: Path
    local_root: Path
    output_root: Path
    report_path: Path
    local_mode: str = "translation_package"
    summary: CompareParatranzSummary = field(default_factory=CompareParatranzSummary)
    files: list[CompareParatranzFileReport] = field(default_factory=list)

    def to_report_payload(self) -> dict:
        return {
            "report_version": 2,
            "scope": self.scope,
            "local_mode": self.local_mode,
            "remote_root": self.remote_root.as_posix(),
            "local_root": self.local_root.as_posix(),
            "output_root": self.output_root.as_posix(),
            "summary": asdict(self.summary),
            "files": [asdict(item) for item in self.files],
        }


@dataclass(slots=True)
class UploadCompareChangeAction:
    category: str
    relative_path: str
    entry_key: str
    operation: str = "save_string"
    remote_name: str | None = None
    file_id: int | None = None
    string_id: int | None = None
    will_write: bool = True
    reason: str | None = None


@dataclass(slots=True)
class UploadCompareChangesSummary:
    scanned_files: int = 0
    source_changed_entries: int = 0
    entry_changed_entries: int = 0
    translation_changed_entries: int = 0
    new_entries: int = 0
    planned_entries: int = 0
    succeeded_entries: int = 0
    failed_entries: int = 0
    skipped_entries: int = 0


@dataclass(slots=True)
class UploadCompareChangesResult:
    scope: str
    scope_dir: str
    compare_root: Path
    report_path: Path
    project_id: int
    dry_run: bool = True
    summary: UploadCompareChangesSummary = field(default_factory=UploadCompareChangesSummary)
    actions: list[UploadCompareChangeAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _ScopePackage:
    root: Path
    database_entries_by_relative: dict[Path, list[ParatranzData]]
    dll_entries: list[ParatranzData]
    label: str
    scope_dir: str
    database_key_seed_entries_by_relative: dict[Path, list[ParatranzData]] = field(default_factory=dict)


@dataclass(slots=True)
class _ComparisonOptions:
    ignore_untranslated_local_translation_diffs: bool = False
    local_mode: str = "translation_package"


def download_and_compare_paratranz(
    *,
    scope: str,
    local_root: Path | str | None = None,
    output_root: Path | str | None = None,
    force: bool = False,
    show_progress: bool = False,
    context: AppContext | None = None,
    api: Paratranz | None = None,
) -> CompareParatranzResult:
    ctx = context or build_app_context(project_paths=paths, app_logger=logger)
    paratranz = api or Paratranz(context=ctx)
    remote_root = paratranz.download(force=force, show_progress=show_progress)
    return compare_downloaded_paratranz_scope(
        remote_root=remote_root,
        scope=scope,
        local_root=local_root,
        output_root=output_root,
        context=ctx,
        show_progress=show_progress,
    )


def compare_downloaded_paratranz_scope(
    *,
    remote_root: Path | str,
    scope: str,
    local_root: Path | str | None = None,
    output_root: Path | str | None = None,
    context: AppContext | None = None,
    show_progress: bool = False,
) -> CompareParatranzResult:
    ctx = context or build_app_context(project_paths=paths, app_logger=logger)
    scope_dir = _resolve_scope_dir(scope)
    remote_base = Path(remote_root).resolve()
    local_base = (Path(local_root) if local_root is not None else ctx.paths.root / "build" / "dump").resolve()
    output_base = (Path(output_root) if output_root is not None else ctx.paths.root / "build" / "compare_paratranz").resolve()
    scope_output_root = output_base / scope_dir

    _reset_scope_output(scope_output_root, output_base, context=ctx)
    local_scope_package = _build_local_scope_package(local_base, scope_dir)
    remote_scope_package = _build_remote_scope_package(remote_base, scope_dir)
    comparison_options = _build_comparison_options(local_base, local_scope_package)

    result = CompareParatranzResult(
        scope=scope,
        scope_dir=scope_dir,
        remote_root=remote_scope_package.root,
        local_root=local_scope_package.root,
        output_root=scope_output_root,
        report_path=scope_output_root / "report.json",
        local_mode=comparison_options.local_mode,
    )

    remote_database_files = set(remote_scope_package.database_entries_by_relative)
    local_database_files = set(local_scope_package.database_entries_by_relative)

    all_database_relatives = sorted(remote_database_files | local_database_files, key=lambda item: item.as_posix().casefold())
    with ctx.progress(total=len(all_database_relatives) + 1, enabled=show_progress, desc="对比 ParaTranz", unit="文件") as progress:
        for relative in all_database_relatives:
            report = _compare_database_file(
                remote_entries=remote_scope_package.database_entries_by_relative.get(relative),
                local_entries=local_scope_package.database_entries_by_relative.get(relative),
                relative=Path(DATABASE_DIR) / relative,
                remote_label=remote_scope_package.label,
                local_label=local_scope_package.label,
                scope_dir=scope_dir,
                delta_root=scope_output_root / DELTA_DIR,
                review_root=scope_output_root / REVIEW_DIR,
                diff_root=scope_output_root / DIFF_DIR,
                key_seed_entries=_database_key_seed_entries(
                    remote_scope_package,
                    relative,
                    scope_dir=scope_dir,
                ),
                options=comparison_options,
            )
            _record_file_report(result, report)
            progress.update()

        dll_report = _compare_dll_file(
            remote_entries=remote_scope_package.dll_entries,
            local_entries=local_scope_package.dll_entries,
            relative=Path(DLL_STRINGS_FILE),
            remote_label=remote_scope_package.label,
            local_label=local_scope_package.label,
            scope_dir=scope_dir,
            delta_root=scope_output_root / DELTA_DIR,
            review_root=scope_output_root / REVIEW_DIR,
            diff_root=scope_output_root / DIFF_DIR,
            options=comparison_options,
        )
        _record_file_report(result, dll_report)
        progress.update()

    result.report_path.parent.mkdir(parents=True, exist_ok=True)
    result.report_path.write_text(
        json.dumps(result.to_report_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    ctx.logger.info("已生成 ParaTranz 对比报告：{}", result.report_path)
    return result


def upload_compare_source_changes(
    *,
    scope: str,
    compare_root: Path | str | None = None,
    project_id: int | None = None,
    dry_run: bool = True,
    show_progress: bool = False,
    context: AppContext | None = None,
    api: Any | None = None,
) -> UploadCompareChangesResult:
    ctx = context or build_app_context(project_paths=paths, app_logger=logger)
    scope_dir = _resolve_scope_dir(scope)
    compare_base = (Path(compare_root) if compare_root is not None else ctx.paths.root / "build" / "compare_paratranz").resolve()
    scope_output_root = compare_base / scope_dir
    report_path = scope_output_root / "report.json"
    delta_root = scope_output_root / DELTA_DIR
    if not delta_root.is_dir():
        raise FileNotFoundError(f"ParaTranz 对比 delta 目录不存在：{delta_root}")

    paratranz = api or Paratranz(context=ctx)
    resolved_project_id = project_id if project_id is not None else int(paratranz.project_id)
    result = UploadCompareChangesResult(
        scope=scope,
        scope_dir=scope_dir,
        compare_root=scope_output_root,
        report_path=report_path,
        project_id=resolved_project_id,
        dry_run=dry_run,
    )

    remote_files = list(paratranz.get_files(project_id=resolved_project_id))
    remote_file_index = _remote_files_by_name(remote_files)
    string_cache: dict[int, list[Any]] = {}
    work_items: list[tuple[UploadCompareChangeAction, ParatranzData]] = []

    for category, delta_file in _iter_upload_delta_files(delta_root):
        relative = delta_file.relative_to(delta_root / category)
        entries = read_paratranz_file(delta_file)
        result.summary.scanned_files += 1
        _record_upload_category_count(result.summary, category, len(entries))
        for entry in entries:
            action = _build_upload_compare_change_action(
                paratranz,
                remote_files=remote_files,
                remote_file_index=remote_file_index,
                string_cache=string_cache,
                scope_dir=scope_dir,
                relative=relative,
                category=category,
                entry=entry,
                project_id=resolved_project_id,
            )
            result.actions.append(action)
            if action.will_write:
                result.summary.planned_entries += 1
                work_items.append((action, entry))
            else:
                result.summary.skipped_entries += 1

    if dry_run:
        return result

    with ctx.progress(total=len(work_items), enabled=show_progress, desc="上传对比 delta", unit="条") as progress:
        for action, entry in work_items:
            try:
                request = _string_write_request_for_upload(action, entry)
                if action.operation == "create_string":
                    paratranz.create_string(request, project_id=resolved_project_id)
                else:
                    paratranz.save_string(action.string_id or 0, request, project_id=resolved_project_id)
                result.summary.succeeded_entries += 1
            except Exception as exc:  # noqa: BLE001
                result.summary.failed_entries += 1
                result.errors.append(f"{action.remote_name or action.relative_path}#{action.entry_key}: {exc}")
            progress.set_postfix_str(f"{action.remote_name or action.relative_path}#{action.entry_key}")
            progress.update()

    return result


def _iter_upload_delta_files(delta_root: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for category in _UPLOAD_DELTA_CATEGORIES:
        category_root = delta_root / category
        if not category_root.is_dir():
            continue
        for delta_file in json_files(category_root):
            files.append((category, delta_file))
    category_order = {category: index for index, category in enumerate(_UPLOAD_DELTA_CATEGORIES)}
    return sorted(files, key=lambda item: (category_order[item[0]], item[1].as_posix().casefold()))


def _record_upload_category_count(summary: UploadCompareChangesSummary, category: str, count: int) -> None:
    if category == SOURCE_UPDATES_DIR:
        summary.source_changed_entries += count
    elif category == ENTRY_UPDATES_DIR:
        summary.entry_changed_entries += count
    elif category == TRANSLATION_UPDATES_DIR:
        summary.translation_changed_entries += count
    elif category == NEW_ENTRIES_DIR:
        summary.new_entries += count


def _string_write_request_for_upload(action: UploadCompareChangeAction, entry: ParatranzData) -> StringWriteRequest:
    stage: int | StageEnum | None = entry.stage
    if action.category in {SOURCE_UPDATES_DIR, ENTRY_UPDATES_DIR, NEW_ENTRIES_DIR}:
        stage = int(StageEnum.untranslated)
    return StringWriteRequest(
        key=entry.key,
        original=entry.original,
        translation=entry.translation,
        file=action.file_id if action.operation == "create_string" else None,
        stage=stage,
        context=entry.context,
    )


def _build_upload_compare_change_action(
    api: Any,
    *,
    remote_files: list[Any],
    remote_file_index: dict[str, Any],
    string_cache: dict[int, list[Any]],
    scope_dir: str,
    relative: Path,
    category: str,
    entry: ParatranzData,
    project_id: int,
) -> UploadCompareChangeAction:
    operation = "create_string" if category == NEW_ENTRIES_DIR else "save_string"
    action = UploadCompareChangeAction(
        category=category,
        relative_path=relative.as_posix(),
        entry_key=entry.key,
        operation=operation,
    )
    remote_file, remote_string = _find_upload_compare_target(
        api,
        remote_files=remote_files,
        remote_file_index=remote_file_index,
        string_cache=string_cache,
        scope_dir=scope_dir,
        relative=relative,
        entry=entry,
        project_id=project_id,
    )
    if remote_file is None:
        action.will_write = False
        action.reason = "远端文件不存在"
        return action

    action.remote_name = _remote_file_name(remote_file)
    action.file_id = _remote_file_id(remote_file)
    if action.file_id is None:
        action.will_write = False
        action.reason = "远端文件缺少 file id"
        return action

    if category == NEW_ENTRIES_DIR:
        if remote_string is not None:
            action.will_write = False
            action.reason = "远端词条 key 已存在，跳过以避免覆盖"
            action.string_id = _remote_string_id(remote_string)
        return action

    if remote_string is None:
        action.will_write = False
        action.reason = "远端词条不存在"
        return action

    action.string_id = _remote_string_id(remote_string)
    if action.string_id is None:
        action.will_write = False
        action.reason = "远端词条缺少 string id"
    return action


def _find_upload_compare_target(
    api: Any,
    *,
    remote_files: list[Any],
    remote_file_index: dict[str, Any],
    string_cache: dict[int, list[Any]],
    scope_dir: str,
    relative: Path,
    entry: ParatranzData,
    project_id: int,
) -> tuple[Any | None, Any | None]:
    for remote_file in _remote_file_candidates(remote_files, remote_file_index, scope_dir, relative):
        file_id = _remote_file_id(remote_file)
        if file_id is None:
            continue
        strings = _cached_file_strings(api, file_id, string_cache, project_id=project_id)
        remote_string = _select_remote_string(strings, entry)
        if remote_string is not None:
            return remote_file, remote_string
    candidates = _remote_file_candidates(remote_files, remote_file_index, scope_dir, relative)
    return (candidates[0], None) if candidates else (None, None)


def _remote_files_by_name(remote_files: list[Any]) -> dict[str, Any]:
    return {
        _normalize_remote_file_name(_remote_file_name(remote_file)): remote_file
        for remote_file in remote_files
        if _remote_file_name(remote_file)
    }


def _remote_file_candidates(
    remote_files: list[Any],
    remote_file_index: dict[str, Any],
    scope_dir: str,
    relative: Path,
) -> list[Any]:
    relative_name = _normalize_remote_file_name(relative.as_posix())
    names = [f"{scope_dir}/{relative_name}"]
    if scope_dir == DLC_GAME_DIR:
        names.append(f"{MAIN_GAME_DIR}/{relative_name}")
    names.append(relative_name)

    candidates: list[Any] = []
    seen_ids: set[int] = set()
    for name in names:
        remote_file = remote_file_index.get(_normalize_remote_file_name(name))
        if remote_file is not None:
            _append_unique_remote_file(candidates, seen_ids, remote_file)

    for remote_file in remote_files:
        remote_name = _normalize_remote_file_name(_remote_file_name(remote_file))
        if remote_name == relative_name or remote_name.endswith(f"/{relative_name}"):
            _append_unique_remote_file(candidates, seen_ids, remote_file)
    return candidates


def _append_unique_remote_file(candidates: list[Any], seen_ids: set[int], remote_file: Any) -> None:
    identity = id(remote_file)
    if identity in seen_ids:
        return
    seen_ids.add(identity)
    candidates.append(remote_file)


def _cached_file_strings(api: Any, file_id: int, cache: dict[int, list[Any]], *, project_id: int) -> list[Any]:
    if file_id in cache:
        return cache[file_id]
    page_number = 1
    strings: list[Any] = []
    while True:
        page = api.get_strings(
            file=file_id,
            detailed=True,
            page=page_number,
            page_size=500,
            project_id=project_id,
        )
        results = list(getattr(page, "results", []) or [])
        strings.extend(results)
        page_count = getattr(page, "page_count", None)
        if not results or (page_count is not None and page_number >= page_count):
            break
        page_number += 1
    cache[file_id] = strings
    return strings


def _select_remote_string(strings: list[Any], entry: ParatranzData) -> Any | None:
    matches = [remote_string for remote_string in strings if str(getattr(remote_string, "key", "")) == entry.key]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    return max(matches, key=lambda remote_string: fuzz.ratio(str(getattr(remote_string, "original", "")), entry.original))


def _normalize_remote_file_name(name: str) -> str:
    return name.replace("\\", "/").strip("/")


def _remote_file_name(remote_file: Any) -> str:
    return str(getattr(remote_file, "name", "") or "")


def _remote_file_id(remote_file: Any) -> int | None:
    value = getattr(remote_file, "id", None)
    return int(value) if value is not None else None


def _remote_string_id(remote_string: Any) -> int | None:
    value = getattr(remote_string, "id", None)
    return int(value) if value is not None else None


def _compare_database_file(
    remote_entries: list[ParatranzData] | None,
    local_entries: list[ParatranzData] | None,
    *,
    relative: Path,
    remote_label: str,
    local_label: str,
    scope_dir: str,
    delta_root: Path,
    review_root: Path,
    diff_root: Path,
    key_seed_entries: list[ParatranzData],
    options: _ComparisonOptions,
) -> CompareParatranzFileReport:
    remote_entries = list(remote_entries or [])
    local_entries = list(local_entries or [])
    report = CompareParatranzFileReport(
        relative_path=relative.as_posix(),
        file_type="database",
        only_in=_only_in_label(remote_entries, local_entries),
        remote_entries=len(remote_entries),
        local_entries=len(local_entries),
    )

    source_update_entries: list[ParatranzData] = []
    translation_update_entries: list[ParatranzData] = []
    entry_update_entries: list[ParatranzData] = []
    new_entries: list[ParatranzData] = []
    rejected_remote_entries: list[ParatranzData] = []
    remote_source_diff_entries: list[ParatranzData] = []
    local_source_diff_entries: list[ParatranzData] = []
    next_new_key = next_database_key_counter(key_seed_entries)

    if not remote_entries or not local_entries:
        report.remote_only = len(remote_entries)
        report.local_only = len(local_entries)
        for local_entry in local_entries:
            output_entry, next_new_key = _database_output_entry(None, local_entry, next_new_key, None, options)
            new_entries.append(output_entry)
        _write_report_entries(report.delta_paths, NEW_ENTRIES_DIR, new_entries, delta_root / NEW_ENTRIES_DIR / relative)
        _write_report_entries(report.review_paths, REMOTE_ONLY_DIR, remote_entries, review_root / REMOTE_ONLY_DIR / relative)
        return report

    pairs, unmatched_remote_entries = build_database_match_pairs(remote_entries, local_entries)
    unmatched_local_entries: list[ParatranzData] = []
    for pair in pairs:
        if pair.base_entry is None:
            unmatched_local_entries.append(pair.compare_entry)
            continue
        classification = _classify_entry_change(pair.base_entry, pair.compare_entry, options=options)
        if classification == "source_changed":
            report.source_changed += 1
        elif classification == "translation_changed":
            report.translation_changed += 1
        elif classification == "entry_changed":
            report.entry_changed += 1
        else:
            continue
        if not _is_fuzzy_confirmed_source_pair(pair.base_entry, pair.compare_entry, classification):
            unmatched_remote_entries.append(pair.base_entry)
            unmatched_local_entries.append(pair.compare_entry)
            if classification == "source_changed":
                report.source_changed -= 1
            elif classification == "entry_changed":
                report.entry_changed -= 1
            continue
        output_entry, next_new_key = _database_output_entry(
            pair.base_entry,
            pair.compare_entry,
            next_new_key,
            classification,
            options,
        )
        if classification == "source_changed":
            source_update_entries.append(output_entry)
        elif classification == "translation_changed":
            translation_update_entries.append(output_entry)
        elif classification == "entry_changed":
            entry_update_entries.append(output_entry)
        if classification in {"source_changed", "entry_changed"}:
            remote_source_diff_entries.append(pair.base_entry)
            local_source_diff_entries.append(output_entry)

    reconciled_pairs, unmatched_remote_entries, unmatched_local_entries = _reconcile_unmatched_database_pairs(
        unmatched_remote_entries,
        unmatched_local_entries,
    )
    rejected_remote_entries: list[ParatranzData] = []
    rejected_local_entries: list[ParatranzData] = []
    for pair in reconciled_pairs:
        classification = _classify_entry_change(pair.base_entry, pair.compare_entry, options=options)
        if classification == "source_changed":
            report.source_changed += 1
        elif classification == "translation_changed":
            report.translation_changed += 1
        elif classification == "entry_changed":
            report.entry_changed += 1
        else:
            continue
        if not _is_fuzzy_confirmed_source_pair(pair.base_entry, pair.compare_entry, classification):
            rejected_remote_entries.append(pair.base_entry)
            rejected_local_entries.append(pair.compare_entry)
            if classification == "source_changed":
                report.source_changed -= 1
            elif classification == "entry_changed":
                report.entry_changed -= 1
            continue
        output_entry, next_new_key = _database_output_entry(
            pair.base_entry,
            pair.compare_entry,
            next_new_key,
            classification,
            options,
        )
        if classification == "source_changed":
            source_update_entries.append(output_entry)
        elif classification == "translation_changed":
            translation_update_entries.append(output_entry)
        elif classification == "entry_changed":
            entry_update_entries.append(output_entry)
        if classification in {"source_changed", "entry_changed"}:
            remote_source_diff_entries.append(pair.base_entry)
            local_source_diff_entries.append(output_entry)

    unmatched_remote_entries.extend(rejected_remote_entries)
    unmatched_local_entries.extend(rejected_local_entries)
    report.remote_only = len(unmatched_remote_entries)
    report.local_only = len(unmatched_local_entries)
    for local_entry in unmatched_local_entries:
        output_entry, next_new_key = _database_output_entry(None, local_entry, next_new_key, None, options)
        new_entries.append(output_entry)

    _write_report_entries(report.delta_paths, SOURCE_UPDATES_DIR, source_update_entries, delta_root / SOURCE_UPDATES_DIR / relative)
    _write_report_entries(report.delta_paths, TRANSLATION_UPDATES_DIR, translation_update_entries, delta_root / TRANSLATION_UPDATES_DIR / relative)
    _write_report_entries(report.delta_paths, ENTRY_UPDATES_DIR, entry_update_entries, delta_root / ENTRY_UPDATES_DIR / relative)
    _write_report_entries(report.delta_paths, NEW_ENTRIES_DIR, new_entries, delta_root / NEW_ENTRIES_DIR / relative)
    _write_report_entries(report.review_paths, REMOTE_ONLY_DIR, unmatched_remote_entries, review_root / REMOTE_ONLY_DIR / relative)
    if report.has_source_diff:
        report.diff_path = _write_diff_file(
            remote_source_diff_entries,
            local_source_diff_entries,
            diff_root / relative.with_name(f"{relative.name}.diff"),
            from_label=f"{remote_label}/{scope_dir}/{relative.as_posix()}",
            to_label=f"{local_label}/{scope_dir}/{relative.as_posix()}",
        )
    return report


def _compare_dll_file(
    remote_entries: list[ParatranzData],
    local_entries: list[ParatranzData],
    *,
    relative: Path,
    remote_label: str,
    local_label: str,
    scope_dir: str,
    delta_root: Path,
    review_root: Path,
    diff_root: Path,
    options: _ComparisonOptions,
) -> CompareParatranzFileReport:
    report = CompareParatranzFileReport(
        relative_path=relative.as_posix(),
        file_type="dll",
        remote_entries=len(remote_entries),
        local_entries=len(local_entries),
    )

    remote_exact: dict[tuple[str, str], list[ParatranzData]] = {}
    remote_by_key: dict[str, list[ParatranzData]] = {}
    used_remote_ids: set[int] = set()
    source_update_entries: list[ParatranzData] = []
    translation_update_entries: list[ParatranzData] = []
    entry_update_entries: list[ParatranzData] = []
    new_entries: list[ParatranzData] = []
    rejected_remote_entries: list[ParatranzData] = []
    remote_source_diff_entries: list[ParatranzData] = []
    local_source_diff_entries: list[ParatranzData] = []
    for entry in remote_entries:
        remote_exact.setdefault((entry.key, entry.original), []).append(entry)
        remote_by_key.setdefault(entry.key, []).append(entry)

    for local_entry in local_entries:
        exact_candidate = _take_first_unused(remote_exact.get((local_entry.key, local_entry.original), []), used_remote_ids)
        if exact_candidate is not None:
            classification = _classify_translation_side_change(exact_candidate, local_entry, options=options)
            if classification == "translation_changed":
                report.translation_changed += 1
                translation_update_entries.append(local_entry)
            continue

        key_candidate = _take_first_unused(remote_by_key.get(local_entry.key, []), used_remote_ids)
        if key_candidate is not None:
            classification = _classify_entry_change(key_candidate, local_entry, options=options)
            if classification == "entry_changed":
                report.entry_changed += 1
                if not _is_fuzzy_confirmed_source_pair(key_candidate, local_entry, classification):
                    report.entry_changed -= 1
                    rejected_remote_entries.append(key_candidate)
                    new_entries.append(local_entry)
                    continue
                output_entry = _dll_output_entry(key_candidate, local_entry, classification, options)
                entry_update_entries.append(output_entry)
            elif classification == "source_changed":
                report.source_changed += 1
                if not _is_fuzzy_confirmed_source_pair(key_candidate, local_entry, classification):
                    report.source_changed -= 1
                    rejected_remote_entries.append(key_candidate)
                    new_entries.append(local_entry)
                    continue
                output_entry = _dll_output_entry(key_candidate, local_entry, classification, options)
                source_update_entries.append(output_entry)
            elif classification == "translation_changed":
                report.translation_changed += 1
                output_entry = _dll_output_entry(key_candidate, local_entry, classification, options)
                translation_update_entries.append(output_entry)
            else:
                continue
            if classification in {"source_changed", "entry_changed"}:
                remote_source_diff_entries.append(key_candidate)
                local_source_diff_entries.append(output_entry)
            continue

        report.local_only += 1
        new_entries.append(local_entry)

    unmatched_remote_entries = [entry for entry in remote_entries if id(entry) not in used_remote_ids]
    unmatched_remote_entries.extend(rejected_remote_entries)
    report.remote_only = len(unmatched_remote_entries)

    _write_report_entries(report.delta_paths, SOURCE_UPDATES_DIR, source_update_entries, delta_root / SOURCE_UPDATES_DIR / relative)
    _write_report_entries(report.delta_paths, TRANSLATION_UPDATES_DIR, translation_update_entries, delta_root / TRANSLATION_UPDATES_DIR / relative)
    _write_report_entries(report.delta_paths, ENTRY_UPDATES_DIR, entry_update_entries, delta_root / ENTRY_UPDATES_DIR / relative)
    _write_report_entries(report.delta_paths, NEW_ENTRIES_DIR, new_entries, delta_root / NEW_ENTRIES_DIR / relative)
    _write_report_entries(report.review_paths, REMOTE_ONLY_DIR, unmatched_remote_entries, review_root / REMOTE_ONLY_DIR / relative)
    if report.has_source_diff:
        report.diff_path = _write_diff_file(
            remote_source_diff_entries,
            local_source_diff_entries,
            diff_root / relative.with_name(f"{relative.name}.diff"),
            from_label=f"{remote_label}/{scope_dir}/{relative.as_posix()}",
            to_label=f"{local_label}/{scope_dir}/{relative.as_posix()}",
        )
    return report


def _record_file_report(result: CompareParatranzResult, report: CompareParatranzFileReport) -> None:
    result.files.append(report)
    result.summary.scanned_files += 1
    result.summary.remote_only_entries += report.remote_only
    result.summary.local_only_entries += report.local_only
    result.summary.source_changed_entries += report.source_changed
    result.summary.translation_changed_entries += report.translation_changed
    result.summary.entry_changed_entries += report.entry_changed
    if report.only_in == "remote":
        result.summary.remote_only_files += 1
    elif report.only_in == "local":
        result.summary.local_only_files += 1


def _classify_entry_change(
    remote_entry: ParatranzData,
    local_entry: ParatranzData,
    *,
    options: _ComparisonOptions,
) -> str | None:
    source_changed = _source_signature(remote_entry) != _source_signature(local_entry)
    translation_changed = _should_compare_translation_side(local_entry, options) and (
        _translation_signature(remote_entry) != _translation_signature(local_entry)
    )
    if source_changed and translation_changed:
        return "entry_changed"
    if source_changed:
        return "source_changed"
    if translation_changed:
        return "translation_changed"
    return None


def _classify_translation_side_change(
    remote_entry: ParatranzData,
    local_entry: ParatranzData,
    *,
    options: _ComparisonOptions,
) -> str | None:
    if not _should_compare_translation_side(local_entry, options):
        return None
    return "translation_changed" if _translation_signature(remote_entry) != _translation_signature(local_entry) else None


def _source_signature(entry: ParatranzData) -> tuple[str, str]:
    return entry.original, entry.context


def _translation_signature(entry: ParatranzData) -> tuple[str, int]:
    return entry.translation, int(entry.stage)


def _is_fuzzy_confirmed_source_pair(
    remote_entry: ParatranzData,
    local_entry: ParatranzData,
    classification: str | None,
) -> bool:
    if classification not in {"source_changed", "entry_changed"}:
        return True
    remote_original = database_original_for_match(remote_entry)
    local_original = database_original_for_match(local_entry)
    if remote_original == local_original:
        return True
    if not remote_original or not local_original:
        return False
    return fuzz.ratio(remote_original, local_original) >= DATABASE_ORIGINAL_FUZZY_THRESHOLD


def _should_compare_translation_side(local_entry: ParatranzData, options: _ComparisonOptions) -> bool:
    if not options.ignore_untranslated_local_translation_diffs:
        return True
    return _has_meaningful_translation(local_entry)


def _has_meaningful_translation(entry: ParatranzData) -> bool:
    return bool(entry.translation.strip()) or int(entry.stage) > 0


def _database_output_entry(
    remote_entry: ParatranzData | None,
    local_entry: ParatranzData,
    next_new_key: int,
    classification: str | None,
    options: _ComparisonOptions,
) -> tuple[ParatranzData, int]:
    if remote_entry is not None:
        if classification in {"source_changed", "entry_changed"}:
            return _source_retranslation_entry(remote_entry, local_entry), next_new_key
        return local_entry.model_copy(update={"key": remote_entry.key}), next_new_key
    return local_entry.model_copy(update={"key": str(next_new_key)}), next_new_key + 1


def _dll_output_entry(
    remote_entry: ParatranzData,
    local_entry: ParatranzData,
    classification: str | None,
    options: _ComparisonOptions,
) -> ParatranzData:
    if classification in {"source_changed", "entry_changed"}:
        return _source_retranslation_entry(remote_entry, local_entry)
    return local_entry


def _source_retranslation_entry(remote_entry: ParatranzData, local_entry: ParatranzData) -> ParatranzData:
    return remote_entry.model_copy(
        update={
            "original": local_entry.original,
            "stage": StageEnum.untranslated,
            "context": local_entry.context,
        }
    )


def _reconcile_unmatched_database_pairs(
    remote_entries: list[ParatranzData],
    local_entries: list[ParatranzData],
) -> tuple[list[DatabaseMatchPair], list[ParatranzData], list[ParatranzData]]:
    if not remote_entries or not local_entries:
        return [], list(remote_entries), list(local_entries)

    matcher = DatabaseEntryMatcher(
        remote_entries,
        enable_fuzzy_search=len(remote_entries) <= 2000,
    )
    reconciled_pairs: list[DatabaseMatchPair] = []
    still_local_entries: list[ParatranzData] = []
    for local_entry in local_entries:
        candidate = matcher.find(local_entry, index=None, use_index=False)
        if candidate is None:
            still_local_entries.append(local_entry)
            continue
        reconciled_pairs.append(DatabaseMatchPair(candidate, local_entry))
    return reconciled_pairs, matcher.unmatched_entries(), still_local_entries


def _take_first_unused(entries: list[ParatranzData], used_ids: set[int]) -> ParatranzData | None:
    for entry in entries:
        entry_id = id(entry)
        if entry_id in used_ids:
            continue
        used_ids.add(entry_id)
        return entry
    return None


def _write_diff_file(
    remote_entries: list[ParatranzData],
    local_entries: list[ParatranzData],
    target_file: Path,
    *,
    from_label: str,
    to_label: str,
) -> str | None:
    wrote = write_readable_json_diff(
        remote_entries,
        local_entries,
        target_file,
        from_label=from_label,
        to_label=to_label,
    )
    return target_file.as_posix() if wrote else None


def _write_report_entries(
    paths: dict[str, str],
    category: str,
    entries: list[ParatranzData],
    target_file: Path,
) -> None:
    path = _write_entries_file(entries, target_file)
    if path is not None:
        paths[category] = path


def _write_entries_file(entries: list[ParatranzData], target_file: Path) -> str | None:
    if not entries:
        return None
    write_paratranz_file(target_file, entries)
    return target_file.as_posix()


def _resolve_scope_dir(scope: str) -> str:
    try:
        return _SCOPE_DIRECTORY_BY_KEY[scope.casefold()]
    except KeyError as exc:
        raise ValueError(f"不支持的 scope：{scope}") from exc


def _build_comparison_options(local_base: Path, local_scope_package: _ScopePackage) -> _ComparisonOptions:
    if _looks_like_raw_dump_root(local_base) or _scope_package_has_no_meaningful_translations(local_scope_package):
        return _ComparisonOptions(
            ignore_untranslated_local_translation_diffs=True,
            local_mode="source_text",
        )
    return _ComparisonOptions()


def _looks_like_raw_dump_root(local_base: Path) -> bool:
    return any(part.casefold() == "0-dumpdata" for part in local_base.parts)


def _scope_package_has_no_meaningful_translations(scope_package: _ScopePackage) -> bool:
    for entries in scope_package.database_entries_by_relative.values():
        for entry in entries:
            if _has_meaningful_translation(entry):
                return False
    for entry in scope_package.dll_entries:
        if _has_meaningful_translation(entry):
            return False
    return True


def _database_key_seed_entries(
    remote_scope_package: _ScopePackage,
    relative: Path,
    *,
    scope_dir: str,
) -> list[ParatranzData]:
    if scope_dir == DLC_GAME_DIR:
        return remote_scope_package.database_key_seed_entries_by_relative.get(relative, [])
    return remote_scope_package.database_entries_by_relative.get(relative, [])


def _build_local_scope_package(local_base: Path, scope_dir: str) -> _ScopePackage:
    main_root = local_base / MAIN_GAME_DIR
    dlc_root = local_base / DLC_GAME_DIR
    if scope_dir == MAIN_GAME_DIR:
        return _read_standard_scope_package(main_root, MAIN_GAME_DIR, label="Local")

    _require_scope_package(dlc_root, f"本地 {DLC_GAME_DIR}")
    main_package = (
        _read_standard_scope_package(main_root, MAIN_GAME_DIR, label="Local")
        if main_root.is_dir()
        else _empty_scope_package(local_base, MAIN_GAME_DIR, label="Local")
    )
    dlc_package = _read_standard_scope_package(dlc_root, DLC_GAME_DIR, label="Local")
    return _merge_scope_packages(local_base, main_package, dlc_package, label="LocalMerged")


def _build_remote_scope_package(remote_base: Path, scope_dir: str) -> _ScopePackage:
    standardized_main_root = remote_base / MAIN_GAME_DIR
    standardized_dlc_root = remote_base / DLC_GAME_DIR
    if standardized_main_root.is_dir() or standardized_dlc_root.is_dir():
        main_package = _read_standard_scope_package(standardized_main_root, MAIN_GAME_DIR, label="ParaTranz") if standardized_main_root.is_dir() else _empty_scope_package(remote_base, MAIN_GAME_DIR, label="ParaTranz")
        dlc_package = _read_standard_scope_package(standardized_dlc_root, DLC_GAME_DIR, label="ParaTranz") if standardized_dlc_root.is_dir() else _empty_scope_package(remote_base, DLC_GAME_DIR, label="ParaTranz")
    else:
        main_package, dlc_package = _read_legacy_remote_packages(remote_base)

    if scope_dir == MAIN_GAME_DIR:
        if not main_package.database_entries_by_relative and not main_package.dll_entries:
            raise FileNotFoundError(f"ParaTranz {MAIN_GAME_DIR} 目录不存在：{remote_base}")
        return main_package

    merged_package = _merge_scope_packages(remote_base, main_package, dlc_package, label="ParaTranzMerged")
    if not merged_package.database_entries_by_relative and not merged_package.dll_entries:
        raise FileNotFoundError(f"ParaTranz {DLC_GAME_DIR} 可比较基线不存在：{remote_base}")
    return merged_package


def _read_standard_scope_package(scope_root: Path, scope_dir: str, *, label: str) -> _ScopePackage:
    _require_scope_package(scope_root, f"{label} {scope_dir}")
    database_root = scope_root / DATABASE_DIR
    database_entries_by_relative = {
        file.relative_to(database_root): read_paratranz_file(file)
        for file in json_files(database_root)
    }
    return _ScopePackage(
        root=scope_root,
        database_entries_by_relative=database_entries_by_relative,
        dll_entries=read_paratranz_file(scope_root / DLL_STRINGS_FILE),
        label=label,
        scope_dir=scope_dir,
        database_key_seed_entries_by_relative=database_entries_by_relative,
    )


def _read_legacy_remote_packages(remote_base: Path) -> tuple[_ScopePackage, _ScopePackage]:
    main_database: dict[Path, list[ParatranzData]] = {}
    dlc_database: dict[Path, list[ParatranzData]] = {}
    main_dll_entries: list[ParatranzData] = []
    dlc_dll_entries: list[ParatranzData] = []

    for file_path in json_files(remote_base):
        logical_path = _legacy_logical_dump_path(file_path, remote_base)
        if logical_path is None:
            continue
        entries = read_paratranz_file(file_path)
        if logical_path.parts[0] == MAIN_GAME_DIR:
            if logical_path.name == DLL_STRINGS_FILE:
                main_dll_entries = entries
            else:
                main_database[logical_path.relative_to(Path(MAIN_GAME_DIR) / DATABASE_DIR)] = entries
        elif logical_path.parts[0] == DLC_GAME_DIR:
            if logical_path.name == DLL_STRINGS_FILE:
                dlc_dll_entries = entries
            else:
                dlc_database[logical_path.relative_to(Path(DLC_GAME_DIR) / DATABASE_DIR)] = entries

    return (
        _ScopePackage(
            root=remote_base,
            database_entries_by_relative=main_database,
            dll_entries=main_dll_entries,
            label="ParaTranz",
            scope_dir=MAIN_GAME_DIR,
            database_key_seed_entries_by_relative=main_database,
        ),
        _ScopePackage(
            root=remote_base,
            database_entries_by_relative=dlc_database,
            dll_entries=dlc_dll_entries,
            label="ParaTranz",
            scope_dir=DLC_GAME_DIR,
            database_key_seed_entries_by_relative=dlc_database,
        ),
    )


def _merge_scope_packages(remote_base: Path, main_package: _ScopePackage, dlc_package: _ScopePackage, *, label: str) -> _ScopePackage:
    relative_files = sorted(
        set(main_package.database_entries_by_relative) | set(dlc_package.database_entries_by_relative),
        key=lambda item: item.as_posix().casefold(),
    )
    merged_database = {
        relative: _merge_database_entries(
            main_package.database_entries_by_relative.get(relative, []),
            dlc_package.database_entries_by_relative.get(relative, []),
        )
        for relative in relative_files
    }
    key_seed_database = {
        relative: (
            dlc_package.database_entries_by_relative.get(relative)
            or main_package.database_entries_by_relative.get(relative, [])
        )
        for relative in relative_files
    }
    return _ScopePackage(
        root=remote_base,
        database_entries_by_relative=merged_database,
        dll_entries=_merge_dll_entries(main_package.dll_entries, dlc_package.dll_entries),
        label=label,
        scope_dir=DLC_GAME_DIR,
        database_key_seed_entries_by_relative=key_seed_database,
    )


def _empty_scope_package(remote_base: Path, scope_dir: str, *, label: str) -> _ScopePackage:
    return _ScopePackage(
        root=remote_base / scope_dir,
        database_entries_by_relative={},
        dll_entries=[],
        label=label,
        scope_dir=scope_dir,
        database_key_seed_entries_by_relative={},
    )


def _require_scope_package(scope_root: Path, label: str) -> None:
    if not scope_root.is_dir():
        raise FileNotFoundError(f"{label} 目录不存在：{scope_root}")
    if not (scope_root / DATABASE_DIR).is_dir():
        raise FileNotFoundError(f"{label} 数据库目录不存在：{scope_root / DATABASE_DIR}")
    if not (scope_root / DLL_STRINGS_FILE).is_file():
        raise FileNotFoundError(f"{label} DLL 字符串文件不存在：{scope_root / DLL_STRINGS_FILE}")


def _reset_scope_output(scope_output_root: Path, output_root: Path, *, context: AppContext) -> None:
    if scope_output_root.exists():
        context.paths.ensure_inside(scope_output_root, output_root)
        context.paths.ensure_inside(scope_output_root, context.paths.root)
        shutil.rmtree(scope_output_root)
    scope_output_root.mkdir(parents=True, exist_ok=True)


def _only_in_label(remote_entries: list[ParatranzData], local_entries: list[ParatranzData]) -> str | None:
    if remote_entries and not local_entries:
        return "remote"
    if not remote_entries and local_entries:
        return "local"
    return None


def _legacy_logical_dump_path(file_path: Path, remote_base: Path) -> Path | None:
    parts = [part for part in file_path.relative_to(remote_base).parts if part not in {"", "."}]
    if not parts:
        return None
    if parts[0].casefold() == "utf8":
        parts = parts[1:]
    if not parts:
        return None
    if _is_legacy_dll_source(parts):
        return _legacy_dll_logical_path(parts)
    if parts[0] in {MAIN_GAME_DIR, DLC_GAME_DIR}:
        return _legacy_existing_dump_path(parts)
    if parts[0] == DATABASE_DIR:
        return _legacy_database_path_from_parts(parts[1:])
    asset_index = next((index for index, part in enumerate(parts) if _ASSET_TEXT_DIR_PATTERN.match(part)), None)
    if asset_index is not None:
        return _legacy_database_path_from_parts(parts[asset_index:])
    if parts[-1] == DLL_STRINGS_FILE and parts[0] in {MAIN_GAME_DIR, DLC_GAME_DIR}:
        return Path(parts[0]) / DLL_STRINGS_FILE
    return None


def _is_legacy_dll_source(parts: list[str]) -> bool:
    filename = Path(parts[-1]).name if parts else ""
    lowered = [part.casefold() for part in parts]
    return filename == DLL_STRINGS_FILE or "dll" in lowered or "dll_strings" in lowered


def _legacy_dll_logical_path(parts: list[str]) -> Path:
    lowered = [part.casefold() for part in parts]
    filename = Path(parts[-1]).stem.casefold() if parts else ""
    if any(part in {DLC_GAME_DIR.casefold(), "dlc"} or part.endswith("_dlc") for part in lowered) or "dlc" in filename:
        return Path(DLC_GAME_DIR) / DLL_STRINGS_FILE
    return Path(MAIN_GAME_DIR) / DLL_STRINGS_FILE


def _legacy_existing_dump_path(parts: list[str]) -> Path | None:
    game_dir = parts[0]
    if len(parts) >= 2 and parts[1] == DLL_STRINGS_FILE:
        return Path(game_dir) / DLL_STRINGS_FILE
    if len(parts) >= 3 and parts[1] == DATABASE_DIR:
        clean_parts = [*parts[2:-1], f"{clean_category_name(Path(parts[-1]))}.json"]
        return Path(game_dir) / DATABASE_DIR / Path(*clean_parts)
    return None


def _legacy_database_path_from_parts(parts: list[str]) -> Path | None:
    if len(parts) < 2 or not _ASSET_TEXT_DIR_PATTERN.match(parts[0]):
        return None
    asset_dir = parts[0]
    game_dir = DLC_GAME_DIR if asset_dir.casefold().endswith("_dlc") else MAIN_GAME_DIR
    target_asset_dir = asset_dir[:-4] if game_dir == DLC_GAME_DIR and asset_dir.casefold().endswith("_dlc") else asset_dir
    clean_parts = [target_asset_dir, *parts[1:-1], f"{clean_category_name(Path(parts[-1]))}.json"]
    return Path(game_dir) / DATABASE_DIR / Path(*clean_parts)


def _merge_database_entries(main_entries: list[ParatranzData], dlc_entries: list[ParatranzData]) -> list[ParatranzData]:
    merged: dict[str, ParatranzData] = {}
    for entry in main_entries:
        merged.setdefault(entry.runtime_original, entry)
    for entry in dlc_entries:
        merged[entry.runtime_original] = entry
    return list(merged.values())


def _merge_dll_entries(main_entries: list[ParatranzData], dlc_entries: list[ParatranzData]) -> list[ParatranzData]:
    candidates: dict[str, ParatranzData] = {}
    source_priority: dict[str, int] = {}
    for priority, entries in ((0, main_entries), (1, dlc_entries)):
        for entry in entries:
            original = entry.runtime_original
            current = candidates.get(original)
            current_priority = source_priority.get(original, -1)
            if current is None or (priority, entry.quality_rank()) > (current_priority, current.quality_rank()):
                candidates[original] = entry
                source_priority[original] = priority
    return list(candidates.values())


__all__ = [
    "CompareParatranzFileReport",
    "CompareParatranzResult",
    "CompareParatranzSummary",
    "UploadCompareChangeAction",
    "UploadCompareChangesResult",
    "UploadCompareChangesSummary",
    "compare_downloaded_paratranz_scope",
    "download_and_compare_paratranz",
    "upload_compare_source_changes",
]
