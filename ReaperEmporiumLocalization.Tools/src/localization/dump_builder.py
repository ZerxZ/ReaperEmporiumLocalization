from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from diff_match_patch import diff_match_patch

from src.config.logging import logger
from src.config.paths import paths
from src.config.progress import ProgressBar
from src.models import ParatranzData

from .installer import read_paratranz_file


MAIN_GAME_DIR = "MainGame"
DLC_GAME_DIR = "DLCGame"
DATABASE_DIR = "database"
DIFF_DIR = "diff"
DLL_STRINGS_FILE = "dll_strings.json"
DMP_EQUAL = 0
DMP_INSERT = 1
DMP_DELETE = -1
_DIFF_MATCH_PATCH = diff_match_patch()


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


def build_dump_diff(*, show_progress: bool = False) -> DumpBuildStats:
    """构建可上传到 ParaTranz 的转储输出。

    MainGame 完整复制，DLCGame 只输出相对 MainGame 新增或不同的词条。
    diff 目录额外保存同一份新增/修改词条，方便单独查看两个转储目录的差异。
    这样能避免 DLC 项目重复承载本体已有文本，也能减少后续人工翻译量。
    """

    input_root = paths.root / "data" / "0-DumpData"
    build_root = paths.root / "build"
    output_root = build_root / "dump"
    main_source = input_root / MAIN_GAME_DIR
    dlc_source = input_root / DLC_GAME_DIR
    main_output = output_root / MAIN_GAME_DIR
    dlc_output = output_root / DLC_GAME_DIR
    diff_output = output_root / DIFF_DIR

    _require_dump_package(main_source, MAIN_GAME_DIR)
    _require_dump_package(dlc_source, DLC_GAME_DIR)
    _reset_build_dir(build_root)
    _prepare_output_dir(main_output, output_root)
    _prepare_output_dir(dlc_output, output_root)
    _prepare_output_dir(diff_output, output_root)

    stats = DumpBuildStats()
    stats.main_database_files, stats.main_database_entries = _copy_database_tree(
        main_source / DATABASE_DIR,
        main_output / DATABASE_DIR,
        show_progress=show_progress,
    )
    stats.main_dll_entries = _copy_dll_strings(main_source, main_output)

    stats.dlc_database_files_read, stats.dlc_database_entries_read = _write_dlc_database_diff(
        main_source / DATABASE_DIR,
        dlc_source / DATABASE_DIR,
        dlc_output / DATABASE_DIR,
        diff_output / DATABASE_DIR,
        stats=stats,
        show_progress=show_progress,
    )
    stats.dlc_dll_entries_read, stats.dlc_dll_entries_written, stats.diff_dll_files_written = _write_dlc_dll_diff(
        main_source / DLL_STRINGS_FILE,
        dlc_source / DLL_STRINGS_FILE,
        dlc_output / DLL_STRINGS_FILE,
        diff_output / f"{DLL_STRINGS_FILE}.diff",
    )

    logger.info("已构建转储差异到 {}", output_root)
    return stats

def _require_dump_package(package_root: Path, name: str) -> None:
    """检查转储包是否包含构建差异所需的目录和文件。"""
    if not package_root.is_dir():
        raise FileNotFoundError(f"{name} 转储目录不存在：{package_root}")
    if not (package_root / DATABASE_DIR).is_dir():
        raise FileNotFoundError(f"{name} 数据库目录不存在：{package_root / DATABASE_DIR}")
    if not (package_root / DLL_STRINGS_FILE).is_file():
        raise FileNotFoundError(f"{name} DLL 字符串文件不存在：{package_root / DLL_STRINGS_FILE}")


def _reset_build_dir(build_root: Path) -> None:
    """每次构建前重建整个 build 目录，避免旧产物残留。"""
    if build_root.exists():
        paths.ensure_inside(build_root, paths.root)
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True, exist_ok=True)


def _prepare_output_dir(target: Path, output_root: Path) -> None:
    """准备输出目录；清理旧目录前做双重路径保护。"""
    if target.exists():
        paths.ensure_inside(target, output_root)
        paths.ensure_inside(target, paths.root)
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def _copy_database_tree(source_root: Path, output_root: Path, *, show_progress: bool) -> tuple[int, int]:
    """完整复制 MainGame 数据库树，并返回文件/词条数量。"""
    files = _json_files(source_root)
    entry_count = 0
    with ProgressBar(total=len(files), enabled=show_progress, desc="复制 MainGame 数据库", unit="文件") as progress:
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
) -> tuple[int, int]:
    """写出 DLC 数据库差异文件。

    每个 DLC 数据库文件只保留 MainGame 同路径文件中不存在的完整词条身份；
    同一份差异会同时写入 DLCGame 输出和独立 diff 输出。
    没有差异时跳过输出，避免产生空文件。
    """

    dlc_files = _json_files(dlc_database_root)
    read_entries = 0
    with ProgressBar(total=len(dlc_files), enabled=show_progress, desc="对比 DLCGame 数据库", unit="文件") as progress:
        for dlc_file in dlc_files:
            relative = dlc_file.relative_to(dlc_database_root)
            dlc_entries = read_paratranz_file(dlc_file)
            read_entries += len(dlc_entries)
            main_file = main_database_root / relative
            diff_entries = _diff_entries(read_paratranz_file(main_file) if main_file.exists() else [], dlc_entries)
            if diff_entries:
                _write_paratranz_file(output_root / relative, diff_entries)
                if _write_readable_json_diff(main_file, dlc_file, _diff_file_path(diff_output_root, relative)):
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
        diff_files_written = int(_write_readable_json_diff(main_file, dlc_file, diff_output_file))
    return len(dlc_entries), len(diff_entries), diff_files_written


def _diff_file_path(root: Path, relative: Path) -> Path:
    """把原始 JSON 相对路径映射为 diff 输出路径，例如 db.json -> db.json.diff。"""
    return root / relative.with_name(f"{relative.name}.diff")


def _write_readable_json_diff(main_file: Path, dlc_file: Path, target_file: Path) -> bool:
    """使用 diff-match-patch 写出可直接阅读的规范化 JSON 行级差异。"""
    main_text = _normalized_paratranz_json_text(read_paratranz_file(main_file) if main_file.exists() else [])
    dlc_text = _normalized_paratranz_json_text(read_paratranz_file(dlc_file))
    diff_text = _format_readable_json_diff(main_text, dlc_text, main_file.as_posix(), dlc_file.as_posix())
    if not diff_text:
        return False
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(diff_text, encoding="utf-8", newline="\n")
    return True


def _format_readable_json_diff(main_text: str, dlc_text: str, from_label: str, to_label: str) -> str:
    """把 diff-match-patch 的结果格式化为保留中文原文的行级 diff。"""
    if main_text == dlc_text:
        return ""
    main_chars, dlc_chars, line_array = _DIFF_MATCH_PATCH.diff_linesToChars(main_text, dlc_text)
    diffs = _DIFF_MATCH_PATCH.diff_main(main_chars, dlc_chars, False)
    _DIFF_MATCH_PATCH.diff_charsToLines(diffs, line_array)

    lines = [f"--- {from_label}", f"+++ {to_label}"]
    for operation, text in diffs:
        prefix = _diff_line_prefix(operation)
        lines.extend(f"{prefix}{line}" for line in text.splitlines())
    return "\n".join(lines) + "\n"


def _diff_line_prefix(operation: int) -> str:
    """把 diff-match-patch 操作码映射成常见 diff 前缀。"""
    if operation == DMP_DELETE:
        return "-"
    if operation == DMP_INSERT:
        return "+"
    return " "


def _normalized_paratranz_json_text(entries: list[ParatranzData]) -> str:
    """把 ParaTranz 词条重新序列化为稳定 JSON 文本，减少格式差异噪声。"""
    payload = [entry.model_dump(mode="json") for entry in entries]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _normalized_entry_json_text(
    entry: ParatranzData,
    *,
    key_normalizer: Callable[[str], str] | None = None,
) -> str:
    """把单条词条序列化为稳定文本，供 diff-match-patch 判断内容是否变化。"""
    payload = entry.model_dump(mode="json")
    if key_normalizer is not None:
        payload["key"] = key_normalizer(entry.key)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _diff_entries(main_entries: list[ParatranzData], dlc_entries: list[ParatranzData]) -> list[ParatranzData]:
    """计算普通数据库词条差异。"""
    return _diff_entries_by_patch(
        main_entries,
        dlc_entries,
        match_key=lambda entry: (entry.key, entry.original),
    )


def _diff_dll_entries(main_entries: list[ParatranzData], dlc_entries: list[ParatranzData]) -> list[ParatranzData]:
    """计算 DLL 字符串差异。"""
    return _diff_entries_by_patch(
        main_entries,
        dlc_entries,
        match_key=lambda entry: (entry.key, entry.original),
    )


def _diff_entries_by_patch(
    main_entries: list[ParatranzData],
    dlc_entries: list[ParatranzData],
    *,
    match_key: Callable[[ParatranzData], tuple[str, str]],
    key_normalizer: Callable[[str], str] | None = None,
) -> list[ParatranzData]:
    """用 diff-match-patch 逐词条判断 DLC 是否相对 MainGame 新增或变化。"""
    main_index: dict[tuple[str, str], list[ParatranzData]] = {}
    for entry in main_entries:
        main_index.setdefault(match_key(entry), []).append(entry)

    changed_entries: list[ParatranzData] = []
    for dlc_entry in dlc_entries:
        candidates = main_index.get(match_key(dlc_entry), [])
        if not candidates or all(_entries_differ_by_patch(candidate, dlc_entry, key_normalizer) for candidate in candidates):
            changed_entries.append(dlc_entry)
    return changed_entries


def _entries_differ_by_patch(
    main_entry: ParatranzData,
    dlc_entry: ParatranzData,
    key_normalizer: Callable[[str], str] | None,
) -> bool:
    """如果单条词条的 DMP diff 含有非相等片段，就认为内容变化。"""
    main_text = _normalized_entry_json_text(main_entry, key_normalizer=key_normalizer)
    dlc_text = _normalized_entry_json_text(dlc_entry, key_normalizer=key_normalizer)
    return any(operation != DMP_EQUAL for operation, _text in _DIFF_MATCH_PATCH.diff_main(main_text, dlc_text))


def _json_files(root: Path) -> list[Path]:
    """稳定列出目录内所有 JSON 文件。"""
    if not root.exists():
        return []
    return sorted(root.rglob("*.json"), key=lambda item: item.relative_to(root).as_posix().casefold())


def _write_paratranz_file(target: Path, entries: list[ParatranzData]) -> None:
    """以 ParaTranz 兼容格式写出 JSON。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [entry.model_dump(mode="json") for entry in entries]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


__all__ = ["DumpBuildStats", "build_dump_diff"]
