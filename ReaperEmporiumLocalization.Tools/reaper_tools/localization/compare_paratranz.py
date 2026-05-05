from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from reaper_tools.app_context import AppContext, build_app_context, get_app_context
from reaper_tools.models import ParatranzData
from reaper_tools.services.base import _ASSET_TEXT_DIR_PATTERN

from .diff_helpers import (
    DATABASE_DIR,
    DLL_STRINGS_FILE,
    DLC_GAME_DIR,
    MAIN_GAME_DIR,
    DatabaseEntryMatcher,
    DatabaseMatchPair,
    build_database_match_pairs,
    is_numeric_database_key,
    json_files,
    write_paratranz_file,
    write_readable_json_diff,
)
from .installer import clean_category_name, read_paratranz_file
from .paratranz import Paratranz

DIFF_DIR = "diff"
DELTA_DIR = "delta"
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
    delta_path: str | None = None
    diff_path: str | None = None

    @property
    def has_delta(self) -> bool:
        return any(
            (
                self.local_only,
                self.source_changed,
                self.translation_changed,
                self.entry_changed,
            )
        )

    @property
    def has_source_diff(self) -> bool:
        return any(
            (
                self.only_in is not None,
                self.remote_only,
                self.local_only,
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
            "scope": self.scope,
            "local_mode": self.local_mode,
            "remote_root": self.remote_root.as_posix(),
            "local_root": self.local_root.as_posix(),
            "output_root": self.output_root.as_posix(),
            "summary": asdict(self.summary),
            "files": [asdict(item) for item in self.files],
        }


@dataclass(slots=True)
class _ScopePackage:
    root: Path
    database_entries_by_relative: dict[Path, list[ParatranzData]]
    dll_entries: list[ParatranzData]
    label: str
    scope_dir: str


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
    local_scope_root = local_base / scope_dir
    scope_output_root = output_base / scope_dir

    _require_scope_package(local_scope_root, f"本地 {scope_dir}")
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

    local_database_root = local_scope_root / DATABASE_DIR
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
                diff_root=scope_output_root / DIFF_DIR,
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


def _compare_database_file(
    remote_entries: list[ParatranzData] | None,
    local_entries: list[ParatranzData] | None,
    *,
    relative: Path,
    remote_label: str,
    local_label: str,
    scope_dir: str,
    delta_root: Path,
    diff_root: Path,
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

    if not remote_entries or not local_entries:
        report.remote_only = len(remote_entries)
        report.local_only = len(local_entries)
        delta_entries = _build_database_delta_entries(remote_entries, local_entries)
        report.delta_path = _write_delta_file(delta_entries, _delta_file_path(delta_root, relative))
        if report.has_source_diff:
            report.diff_path = _write_diff_file(
                remote_entries,
                delta_entries,
                diff_root / relative.with_name(f"{relative.name}.diff"),
                from_label=f"{remote_label}/{scope_dir}/{relative.as_posix()}",
                to_label=f"{local_label}/{scope_dir}/{relative.as_posix()}",
            )
        return report

    pairs, unmatched_remote_entries = build_database_match_pairs(remote_entries, local_entries)
    unmatched_local_entries: list[ParatranzData] = []
    delta_entries: list[ParatranzData] = []
    remote_source_diff_entries: list[ParatranzData] = []
    local_source_diff_entries: list[ParatranzData] = []
    next_new_key = _next_database_key_counter(remote_entries)
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
        output_entry, next_new_key = _database_output_entry(pair.base_entry, pair.compare_entry, next_new_key)
        delta_entries.append(output_entry)
        if classification != "translation_changed":
            remote_source_diff_entries.append(pair.base_entry)
            local_source_diff_entries.append(output_entry)

    reconciled_pairs, unmatched_remote_entries, unmatched_local_entries = _reconcile_unmatched_database_pairs(
        unmatched_remote_entries,
        unmatched_local_entries,
    )
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
        output_entry, next_new_key = _database_output_entry(pair.base_entry, pair.compare_entry, next_new_key)
        delta_entries.append(output_entry)
        if classification != "translation_changed":
            remote_source_diff_entries.append(pair.base_entry)
            local_source_diff_entries.append(output_entry)

    report.remote_only = len(unmatched_remote_entries)
    report.local_only = len(unmatched_local_entries)
    for local_entry in unmatched_local_entries:
        output_entry, next_new_key = _database_output_entry(None, local_entry, next_new_key)
        delta_entries.append(output_entry)
        local_source_diff_entries.append(output_entry)
    remote_source_diff_entries.extend(unmatched_remote_entries)

    report.delta_path = _write_delta_file(delta_entries, _delta_file_path(delta_root, relative))
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
    delta_entries: list[ParatranzData] = []
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
                delta_entries.append(local_entry)
            continue

        key_candidate = _take_first_unused(remote_by_key.get(local_entry.key, []), used_remote_ids)
        if key_candidate is not None:
            classification = _classify_entry_change(key_candidate, local_entry, options=options)
            if classification == "entry_changed":
                report.entry_changed += 1
            else:
                report.source_changed += 1
            delta_entries.append(local_entry)
            remote_source_diff_entries.append(key_candidate)
            local_source_diff_entries.append(local_entry)
            continue

        report.local_only += 1
        delta_entries.append(local_entry)
        local_source_diff_entries.append(local_entry)

    unmatched_remote_entries = [entry for entry in remote_entries if id(entry) not in used_remote_ids]
    report.remote_only = len(unmatched_remote_entries)
    remote_source_diff_entries.extend(unmatched_remote_entries)

    report.delta_path = _write_delta_file(delta_entries, _delta_file_path(delta_root, relative))
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


def _should_compare_translation_side(local_entry: ParatranzData, options: _ComparisonOptions) -> bool:
    if not options.ignore_untranslated_local_translation_diffs:
        return True
    return _has_meaningful_translation(local_entry)


def _has_meaningful_translation(entry: ParatranzData) -> bool:
    return bool(entry.translation.strip()) or int(entry.stage) > 0


def _build_database_delta_entries(remote_entries: list[ParatranzData], local_entries: list[ParatranzData]) -> list[ParatranzData]:
    if not local_entries:
        return []
    next_new_key = _next_database_key_counter(remote_entries)
    delta_entries: list[ParatranzData] = []
    for local_entry in local_entries:
        output_entry, next_new_key = _database_output_entry(None, local_entry, next_new_key)
        delta_entries.append(output_entry)
    return delta_entries


def _database_output_entry(
    remote_entry: ParatranzData | None,
    local_entry: ParatranzData,
    next_new_key: int,
) -> tuple[ParatranzData, int]:
    if remote_entry is not None:
        return local_entry.model_copy(update={"key": remote_entry.key}), next_new_key
    return local_entry.model_copy(update={"key": str(next_new_key)}), next_new_key + 1


def _next_database_key_counter(entries: list[ParatranzData]) -> int:
    for entry in reversed(entries):
        if is_numeric_database_key(entry.key):
            return int(entry.key) + 1
    return 0


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


def _write_delta_file(entries: list[ParatranzData], target_file: Path) -> str | None:
    if not entries:
        return None
    write_paratranz_file(target_file, entries)
    return target_file.as_posix()


def _delta_file_path(root: Path, relative: Path) -> Path:
    return root / relative


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
        ),
        _ScopePackage(
            root=remote_base,
            database_entries_by_relative=dlc_database,
            dll_entries=dlc_dll_entries,
            label="ParaTranz",
            scope_dir=DLC_GAME_DIR,
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
    return _ScopePackage(
        root=remote_base,
        database_entries_by_relative=merged_database,
        dll_entries=_merge_dll_entries(main_package.dll_entries, dlc_package.dll_entries),
        label=label,
        scope_dir=DLC_GAME_DIR,
    )


def _empty_scope_package(remote_base: Path, scope_dir: str, *, label: str) -> _ScopePackage:
    return _ScopePackage(
        root=remote_base / scope_dir,
        database_entries_by_relative={},
        dll_entries=[],
        label=label,
        scope_dir=scope_dir,
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
    "compare_downloaded_paratranz_scope",
    "download_and_compare_paratranz",
]
