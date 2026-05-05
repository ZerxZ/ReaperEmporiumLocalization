from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from reaper_tools.app_context import AppContext, build_app_context, get_app_context
from reaper_tools.models import ParatranzData

from .diff_helpers import (
    DATABASE_DIR,
    DLL_STRINGS_FILE,
    DLC_GAME_DIR,
    MAIN_GAME_DIR,
    DatabaseEntryMatcher as _DatabaseEntryMatcher,
    build_database_match_pairs,
    diff_entries_by_patch as _diff_entries_by_patch,
    entries_differ_by_patch as _entries_differ_by_patch,
    format_readable_json_diff as _format_readable_json_diff,
    json_files as _json_files,
    next_database_key_counter as _next_database_key_counter,
    normalized_paratranz_json_text as _normalized_paratranz_json_text,
    write_paratranz_file as _write_paratranz_file,
)
from .installer import read_paratranz_file

DIFF_DIR = "diff"
_DEFAULT_CONTEXT = get_app_context()
paths = _DEFAULT_CONTEXT.paths
logger = _DEFAULT_CONTEXT.logger


@dataclass(slots=True)
class DumpBuildStats:
    """构建 MainGame/DLCGame 转储差异时的统计信息。"""

    main_database_files: int = 0
    main_database_entries: int = 0
    main_dll_entries: int = 0
    dlc_database_files_read: int = 0
    dlc_database_files_written: int = 0
    dlc_database_entries_read: int = 0
    dlc_database_entries_written: int = 0
    dlc_dll_entries_read: int = 0
    dlc_dll_entries_written: int = 0
    diff_database_files_written: int = 0
    diff_dll_files_written: int = 0


@dataclass(slots=True)
class _EntryDiff:
    """保存一条 DLC 差异及其匹配到的 MainGame 候选。"""

    main_entry: ParatranzData | None
    dlc_entry: ParatranzData
    output_entry: ParatranzData


def build_dump_diff(*, show_progress: bool = False, context: AppContext | None = None) -> DumpBuildStats:
    """构建可上传到 ParaTranz 的转储输出。

    MainGame 完整复制，DLCGame 只输出相对 MainGame 新增或不同的词条。
    diff 目录额外保存同一份新增/修改词条，方便单独查看两个转储目录的差异。
    这样能避免 DLC 项目重复承载本体已有文本，也能减少后续人工翻译量。
    """

    ctx = context or build_app_context(project_paths=paths, app_logger=logger)
    input_root = ctx.paths.root / "data" / "0-DumpData"
    build_root = ctx.paths.root / "build"
    output_root = build_root / "dump"
    main_source = input_root / MAIN_GAME_DIR
    dlc_source = input_root / DLC_GAME_DIR
    main_output = output_root / MAIN_GAME_DIR
    dlc_output = output_root / DLC_GAME_DIR
    diff_output = output_root / DIFF_DIR

    _require_dump_package(main_source, MAIN_GAME_DIR)
    _require_dump_package(dlc_source, DLC_GAME_DIR)
    _reset_build_dir(build_root, context=ctx)
    _prepare_output_dir(main_output, output_root, context=ctx)
    _prepare_output_dir(dlc_output, output_root, context=ctx)
    _prepare_output_dir(diff_output, output_root, context=ctx)

    stats = DumpBuildStats()
    stats.main_database_files, stats.main_database_entries = _copy_database_tree(
        main_source / DATABASE_DIR,
        main_output / DATABASE_DIR,
        show_progress=show_progress,
        context=ctx,
    )
    stats.main_dll_entries = _copy_dll_strings(main_source, main_output)

    stats.dlc_database_files_read, stats.dlc_database_entries_read = _write_dlc_database_diff(
        main_source / DATABASE_DIR,
        dlc_source / DATABASE_DIR,
        dlc_output / DATABASE_DIR,
        diff_output / DATABASE_DIR,
        stats=stats,
        show_progress=show_progress,
        context=ctx,
    )
    stats.dlc_dll_entries_read, stats.dlc_dll_entries_written, stats.diff_dll_files_written = _write_dlc_dll_diff(
        main_source / DLL_STRINGS_FILE,
        dlc_source / DLL_STRINGS_FILE,
        dlc_output / DLL_STRINGS_FILE,
        diff_output / f"{DLL_STRINGS_FILE}.diff",
    )

    ctx.logger.info("已构建转储差异到 {}", output_root)
    return stats

def _require_dump_package(package_root: Path, name: str) -> None:
    """检查转储包是否包含构建差异所需的目录和文件。"""
    if not package_root.is_dir():
        raise FileNotFoundError(f"{name} 转储目录不存在：{package_root}")
    if not (package_root / DATABASE_DIR).is_dir():
        raise FileNotFoundError(f"{name} 数据库目录不存在：{package_root / DATABASE_DIR}")
    if not (package_root / DLL_STRINGS_FILE).is_file():
        raise FileNotFoundError(f"{name} DLL 字符串文件不存在：{package_root / DLL_STRINGS_FILE}")


def _reset_build_dir(build_root: Path, *, context: AppContext) -> None:
    """每次构建前重建整个 build 目录，避免旧产物残留。"""
    if build_root.exists():
        context.paths.ensure_inside(build_root, context.paths.root)
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True, exist_ok=True)


def _prepare_output_dir(target: Path, output_root: Path, *, context: AppContext) -> None:
    """准备输出目录；清理旧目录前做双重路径保护。"""
    if target.exists():
        context.paths.ensure_inside(target, output_root)
        context.paths.ensure_inside(target, context.paths.root)
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def _copy_database_tree(
    source_root: Path,
    output_root: Path,
    *,
    show_progress: bool,
    context: AppContext,
) -> tuple[int, int]:
    """完整复制 MainGame 数据库树，并返回文件/词条数量。"""
    files = _json_files(source_root)
    entry_count = 0
    with context.progress(total=len(files), enabled=show_progress, desc="复制 MainGame 数据库", unit="文件") as progress:
        for source_file in files:
            relative = source_file.relative_to(source_root)
            entries = read_paratranz_file(source_file)
            entry_count += len(entries)
            _write_paratranz_file(output_root / relative, entries)
            progress.set_postfix_str(relative.as_posix())
            progress.update()
    return len(files), entry_count


def _copy_dll_strings(source_root: Path, output_root: Path) -> int:
    """完整复制 MainGame 的 DLL 字符串文件。"""
    entries = read_paratranz_file(source_root / DLL_STRINGS_FILE)
    _write_paratranz_file(output_root / DLL_STRINGS_FILE, entries)
    return len(entries)


def _write_dlc_database_diff(
    main_database_root: Path,
    dlc_database_root: Path,
    output_root: Path,
    diff_output_root: Path,
    *,
    stats: DumpBuildStats,
    show_progress: bool,
    context: AppContext | None = None,
) -> tuple[int, int]:
    """写出 DLC 数据库差异文件。

    每个 DLC 数据库文件只保留 MainGame 同路径文件中不存在的完整词条身份；
    同一份差异会同时写入 DLCGame 输出和独立 diff 输出。
    没有差异时跳过输出，避免产生空文件。
    """

    dlc_files = _json_files(dlc_database_root)
    read_entries = 0
    ctx = context or build_app_context(project_paths=paths, app_logger=logger)
    with ctx.progress(total=len(dlc_files), enabled=show_progress, desc="对比 DLCGame 数据库", unit="文件") as progress:
        for dlc_file in dlc_files:
            relative = dlc_file.relative_to(dlc_database_root)
            dlc_entries = read_paratranz_file(dlc_file)
            read_entries += len(dlc_entries)
            main_file = main_database_root / relative
            main_entries = read_paratranz_file(main_file) if main_file.exists() else []
            diff_pairs = _diff_entry_pairs(main_entries, dlc_entries)
            diff_entries = [pair.output_entry for pair in diff_pairs]
            if diff_entries:
                _write_paratranz_file(output_root / relative, diff_entries)
                if _write_readable_database_diff(
                    diff_pairs,
                    _diff_file_path(diff_output_root, relative),
                    f"{MAIN_GAME_DIR}/{DATABASE_DIR}/{relative.as_posix()}",
                    f"{DLC_GAME_DIR}/{DATABASE_DIR}/{relative.as_posix()}",
                ):
                    stats.diff_database_files_written += 1
                stats.dlc_database_files_written += 1
                stats.dlc_database_entries_written += len(diff_entries)
            progress.set_postfix_str(relative.as_posix())
            progress.update()
    return len(dlc_files), read_entries


def _write_dlc_dll_diff(main_file: Path, dlc_file: Path, output_file: Path, diff_output_file: Path) -> tuple[int, int, int]:
    """写出 DLC DLL 字符串差异文件，并同步写入独立 diff 输出。"""
    main_entries = read_paratranz_file(main_file) if main_file.exists() else []
    dlc_entries = read_paratranz_file(dlc_file)
    diff_entries = _diff_dll_entries(main_entries, dlc_entries)
    diff_files_written = 0
    if diff_entries:
        _write_paratranz_file(output_file, diff_entries)
        diff_files_written = int(
            _write_readable_json_diff(
                main_file,
                dlc_file,
                diff_output_file,
                from_label=f"{MAIN_GAME_DIR}/{DLL_STRINGS_FILE}",
                to_label=f"{DLC_GAME_DIR}/{DLL_STRINGS_FILE}",
            )
        )
    return len(dlc_entries), len(diff_entries), diff_files_written


def _diff_file_path(root: Path, relative: Path) -> Path:
    """把原始 JSON 相对路径映射为 diff 输出路径，例如 db.json -> db.json.diff。"""
    return root / relative.with_name(f"{relative.name}.diff")


def _write_readable_json_diff(
    main_file: Path,
    dlc_file: Path,
    target_file: Path,
    *,
    from_label: str | None = None,
    to_label: str | None = None,
) -> bool:
    """使用 diff-match-patch 写出可直接阅读的规范化 JSON 行级差异。"""
    main_text = _normalized_paratranz_json_text(read_paratranz_file(main_file) if main_file.exists() else [])
    dlc_text = _normalized_paratranz_json_text(read_paratranz_file(dlc_file))
    diff_text = _format_readable_json_diff(
        main_text,
        dlc_text,
        from_label or main_file.as_posix(),
        to_label or dlc_file.as_posix(),
    )
    if not diff_text:
        return False
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(diff_text, encoding="utf-8", newline="\n")
    return True


def _write_readable_database_diff(diff_pairs: list[_EntryDiff], target_file: Path, from_label: str, to_label: str) -> bool:
    """按数据库匹配结果写出差异文件，避免完整数组重排造成大段误导性 diff。"""
    main_entries = [pair.main_entry for pair in diff_pairs if pair.main_entry is not None]
    dlc_entries = [pair.output_entry for pair in diff_pairs]
    main_text = _normalized_paratranz_json_text(main_entries)
    dlc_text = _normalized_paratranz_json_text(dlc_entries)
    diff_text = _format_readable_json_diff(main_text, dlc_text, from_label, to_label)
    if not diff_text:
        return False
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(diff_text, encoding="utf-8", newline="\n")
    return True


def _database_output_entry(pair: _EntryDiff, next_new_key: int) -> tuple[ParatranzData, int]:
    """已匹配词条改用 MainGame key；新增 DLC 词条按 MainGame 文件 key 顺序继续编号。"""
    if pair.main_entry is not None:
        return pair.dlc_entry.model_copy(update={"key": pair.main_entry.key}), next_new_key
    return pair.dlc_entry.model_copy(update={"key": str(next_new_key)}), next_new_key + 1


def _diff_entries(main_entries: list[ParatranzData], dlc_entries: list[ParatranzData]) -> list[ParatranzData]:
    """计算普通数据库词条差异。"""
    return [pair.output_entry for pair in _diff_entry_pairs(main_entries, dlc_entries)]


def _diff_entry_pairs(main_entries: list[ParatranzData], dlc_entries: list[ParatranzData]) -> list[_EntryDiff]:
    """计算普通数据库词条差异，并保留 MainGame 候选用于生成人类可读 diff。"""
    changed_pairs: list[_EntryDiff] = []
    next_new_key = _next_database_key_counter(main_entries)
    matched_pairs, _unmatched_main_entries = build_database_match_pairs(main_entries, dlc_entries)
    for matched_pair in matched_pairs:
        candidate = matched_pair.base_entry
        dlc_entry = matched_pair.compare_entry
        if candidate is None or _entries_differ_by_patch(candidate, dlc_entry, ignore_key=True):
            pending_pair = _EntryDiff(candidate, dlc_entry, dlc_entry)
            output_entry, next_new_key = _database_output_entry(pending_pair, next_new_key)
            changed_pairs.append(_EntryDiff(candidate, dlc_entry, output_entry))
    return changed_pairs


def _diff_dll_entries(main_entries: list[ParatranzData], dlc_entries: list[ParatranzData]) -> list[ParatranzData]:
    """计算 DLL 字符串差异。"""
    return _diff_entries_by_patch(
        main_entries,
        dlc_entries,
        match_key=lambda entry: (entry.key, entry.original),
    )


__all__ = ["DumpBuildStats", "build_dump_diff"]

