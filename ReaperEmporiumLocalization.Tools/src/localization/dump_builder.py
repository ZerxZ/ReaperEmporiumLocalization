from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from src.config.logging import logger
from src.config.paths import paths
from src.config.progress import ProgressBar
from src.models import ParatranzData

from .installer import read_paratranz_file


MAIN_GAME_DIR = "MainGame"
DLC_GAME_DIR = "DLCGame"
DATABASE_DIR = "database"
DLL_STRINGS_FILE = "dll_strings.json"
STATE_MACHINE_METHOD_PATTERN = re.compile(r"^(?P<owner>.+)/<(?P<method>[^>]+)>d__\d+\.MoveNext$")


@dataclass(slots=True)
class DumpBuildStats:
    main_database_files: int = 0
    main_database_entries: int = 0
    main_dll_entries: int = 0
    dlc_database_files_read: int = 0
    dlc_database_files_written: int = 0
    dlc_database_entries_read: int = 0
    dlc_database_entries_written: int = 0
    dlc_dll_entries_read: int = 0
    dlc_dll_entries_written: int = 0


def build_dump_diff(*, show_progress: bool = False) -> DumpBuildStats:
    input_root = paths.root / "data" / "0-DumpData"
    output_root = paths.root / "build" / "dump"
    main_source = input_root / MAIN_GAME_DIR
    dlc_source = input_root / DLC_GAME_DIR
    main_output = output_root / MAIN_GAME_DIR
    dlc_output = output_root / DLC_GAME_DIR

    _require_dump_package(main_source, MAIN_GAME_DIR)
    _require_dump_package(dlc_source, DLC_GAME_DIR)
    _prepare_output_dir(main_output, output_root)
    _prepare_output_dir(dlc_output, output_root)

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
        stats=stats,
        show_progress=show_progress,
    )
    stats.dlc_dll_entries_read, stats.dlc_dll_entries_written = _write_dlc_dll_diff(
        main_source / DLL_STRINGS_FILE,
        dlc_source / DLL_STRINGS_FILE,
        dlc_output / DLL_STRINGS_FILE,
    )

    logger.info("Built dump diff into {}", output_root)
    return stats


def _entry_identity(entry: ParatranzData) -> tuple[str, str, str, int, str]:
    return (
        entry.key,
        entry.original,
        entry.translation,
        int(entry.stage),
        entry.context,
    )


def _dll_entry_identity(entry: ParatranzData) -> tuple[str, str, str, int, str]:
    return (
        _key_method_identity(entry.key),
        entry.original,
        entry.translation,
        int(entry.stage),
        entry.context,
    )


def _key_method_identity(key: str) -> str:
    method = key.rsplit("_IL_", 1)[0] if "_IL_" in key else key
    state_machine_match = STATE_MACHINE_METHOD_PATTERN.match(method)
    if state_machine_match:
        return f"{state_machine_match.group('owner')}.{state_machine_match.group('method')}"
    return method


def _require_dump_package(package_root: Path, name: str) -> None:
    if not package_root.is_dir():
        raise FileNotFoundError(f"{name} dump folder is missing: {package_root}")
    if not (package_root / DATABASE_DIR).is_dir():
        raise FileNotFoundError(f"{name} database folder is missing: {package_root / DATABASE_DIR}")
    if not (package_root / DLL_STRINGS_FILE).is_file():
        raise FileNotFoundError(f"{name} dll_strings file is missing: {package_root / DLL_STRINGS_FILE}")


def _prepare_output_dir(target: Path, output_root: Path) -> None:
    if target.exists():
        paths.ensure_inside(target, output_root)
        paths.ensure_inside(target, paths.root)
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def _copy_database_tree(source_root: Path, output_root: Path, *, show_progress: bool) -> tuple[int, int]:
    files = _json_files(source_root)
    entry_count = 0
    with ProgressBar(total=len(files), enabled=show_progress, desc="Copy MainGame database", unit="file") as progress:
        for source_file in files:
            relative = source_file.relative_to(source_root)
            entries = read_paratranz_file(source_file)
            entry_count += len(entries)
            _write_paratranz_file(output_root / relative, entries)
            progress.set_postfix_str(relative.as_posix())
            progress.update()
    return len(files), entry_count


def _copy_dll_strings(source_root: Path, output_root: Path) -> int:
    entries = read_paratranz_file(source_root / DLL_STRINGS_FILE)
    _write_paratranz_file(output_root / DLL_STRINGS_FILE, entries)
    return len(entries)


def _write_dlc_database_diff(
    main_database_root: Path,
    dlc_database_root: Path,
    output_root: Path,
    *,
    stats: DumpBuildStats,
    show_progress: bool,
) -> tuple[int, int]:
    dlc_files = _json_files(dlc_database_root)
    read_entries = 0
    with ProgressBar(total=len(dlc_files), enabled=show_progress, desc="Diff DLCGame database", unit="file") as progress:
        for dlc_file in dlc_files:
            relative = dlc_file.relative_to(dlc_database_root)
            dlc_entries = read_paratranz_file(dlc_file)
            read_entries += len(dlc_entries)
            main_file = main_database_root / relative
            diff_entries = _diff_entries(read_paratranz_file(main_file) if main_file.exists() else [], dlc_entries)
            if diff_entries:
                _write_paratranz_file(output_root / relative, diff_entries)
                stats.dlc_database_files_written += 1
                stats.dlc_database_entries_written += len(diff_entries)
            progress.set_postfix_str(relative.as_posix())
            progress.update()
    return len(dlc_files), read_entries


def _write_dlc_dll_diff(main_file: Path, dlc_file: Path, output_file: Path) -> tuple[int, int]:
    main_entries = read_paratranz_file(main_file) if main_file.exists() else []
    dlc_entries = read_paratranz_file(dlc_file)
    diff_entries = _diff_dll_entries(main_entries, dlc_entries)
    if diff_entries:
        _write_paratranz_file(output_file, diff_entries)
    return len(dlc_entries), len(diff_entries)


def _diff_entries(main_entries: list[ParatranzData], dlc_entries: list[ParatranzData]) -> list[ParatranzData]:
    main_identities = {_entry_identity(entry) for entry in main_entries}
    return [entry for entry in dlc_entries if _entry_identity(entry) not in main_identities]


def _diff_dll_entries(main_entries: list[ParatranzData], dlc_entries: list[ParatranzData]) -> list[ParatranzData]:
    main_identities = {_dll_entry_identity(entry) for entry in main_entries}
    return [entry for entry in dlc_entries if _dll_entry_identity(entry) not in main_identities]


def _json_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.json"), key=lambda item: item.relative_to(root).as_posix().casefold())


def _write_paratranz_file(target: Path, entries: list[ParatranzData]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [entry.model_dump(mode="json") for entry in entries]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


__all__ = ["DumpBuildStats", "build_dump_diff"]
