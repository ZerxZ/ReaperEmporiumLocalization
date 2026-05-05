from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from reaper_tools.app_context import AppContext, build_app_context, get_app_context
from reaper_tools.models import ParatranzData

from .diff_helpers import (
    DATABASE_DIR,
    DLL_STRINGS_FILE,
    DLC_GAME_DIR,
    MAIN_GAME_DIR,
    DatabaseMatchPair,
    build_database_match_pairs,
    json_files,
    write_readable_json_diff,
)
from .installer import read_paratranz_file
from .paratranz import Paratranz

DIFF_DIR = "diff"
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
    diff_path: str | None = None

    @property
    def has_diff(self) -> bool:
        return any(
            (
                self.only_in is not None,
                self.remote_only,
                self.local_only,
                self.source_changed,
                self.translation_changed,
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
    summary: CompareParatranzSummary = field(default_factory=CompareParatranzSummary)
    files: list[CompareParatranzFileReport] = field(default_factory=list)

    def to_report_payload(self) -> dict:
        return {
            "scope": self.scope,
            "remote_root": self.remote_root.as_posix(),
            "local_root": self.local_root.as_posix(),
            "output_root": self.output_root.as_posix(),
            "summary": asdict(self.summary),
            "files": [asdict(item) for item in self.files],
        }


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
    remote_scope_root = remote_base / scope_dir
    local_scope_root = local_base / scope_dir
    scope_output_root = output_base / scope_dir

    _require_scope_package(remote_scope_root, f"ParaTranz {scope_dir}")
    _require_scope_package(local_scope_root, f"本地 {scope_dir}")
    _reset_scope_output(scope_output_root, output_base, context=ctx)

    result = CompareParatranzResult(
        scope=scope,
        scope_dir=scope_dir,
        remote_root=remote_scope_root,
        local_root=local_scope_root,
        output_root=scope_output_root,
        report_path=scope_output_root / "report.json",
    )

    remote_database_root = remote_scope_root / DATABASE_DIR
    local_database_root = local_scope_root / DATABASE_DIR
    remote_database_files = {file.relative_to(remote_database_root) for file in json_files(remote_database_root)}
    local_database_files = {file.relative_to(local_database_root) for file in json_files(local_database_root)}

    all_database_relatives = sorted(remote_database_files | local_database_files, key=lambda item: item.as_posix().casefold())
    with ctx.progress(total=len(all_database_relatives) + 1, enabled=show_progress, desc="对比 ParaTranz", unit="文件") as progress:
        for relative in all_database_relatives:
            report = _compare_database_file(
                remote_database_root / relative if relative in remote_database_files else None,
                local_database_root / relative if relative in local_database_files else None,
                relative=Path(DATABASE_DIR) / relative,
                scope_dir=scope_dir,
                diff_root=scope_output_root / DIFF_DIR,
            )
            _record_file_report(result, report)
            progress.update()

        dll_report = _compare_dll_file(
            remote_scope_root / DLL_STRINGS_FILE,
            local_scope_root / DLL_STRINGS_FILE,
            relative=Path(DLL_STRINGS_FILE),
            scope_dir=scope_dir,
            diff_root=scope_output_root / DIFF_DIR,
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
    remote_file: Path | None,
    local_file: Path | None,
    *,
    relative: Path,
    scope_dir: str,
    diff_root: Path,
) -> CompareParatranzFileReport:
    remote_entries = read_paratranz_file(remote_file) if remote_file is not None else []
    local_entries = read_paratranz_file(local_file) if local_file is not None else []
    report = CompareParatranzFileReport(
        relative_path=relative.as_posix(),
        file_type="database",
        only_in=_only_in_label(remote_file, local_file),
        remote_entries=len(remote_entries),
        local_entries=len(local_entries),
    )

    if remote_file is None or local_file is None:
        report.remote_only = len(remote_entries)
        report.local_only = len(local_entries)
        report.diff_path = _write_diff_file(
            remote_entries,
            local_entries,
            diff_root / relative.with_name(f"{relative.name}.diff"),
            from_label=f"ParaTranz/{scope_dir}/{relative.as_posix()}",
            to_label=f"Local/{scope_dir}/{relative.as_posix()}",
        )
        return report

    pairs, unmatched_remote_entries = build_database_match_pairs(remote_entries, local_entries)
    changed_remote_ids: set[int] = {id(entry) for entry in unmatched_remote_entries}
    changed_local_ids: set[int] = set()
    for pair in pairs:
        if pair.base_entry is None:
            report.local_only += 1
            changed_local_ids.add(id(pair.compare_entry))
            continue
        classification = _classify_entry_change(pair.base_entry, pair.compare_entry)
        if classification == "source_changed":
            report.source_changed += 1
        elif classification == "translation_changed":
            report.translation_changed += 1
        elif classification == "entry_changed":
            report.entry_changed += 1
        else:
            continue
        changed_remote_ids.add(id(pair.base_entry))
        changed_local_ids.add(id(pair.compare_entry))
    report.remote_only = len(unmatched_remote_entries)

    if report.has_diff:
        remote_diff_entries = [entry for entry in remote_entries if id(entry) in changed_remote_ids]
        local_diff_entries = [entry for entry in local_entries if id(entry) in changed_local_ids]
        report.diff_path = _write_diff_file(
            remote_diff_entries,
            local_diff_entries,
            diff_root / relative.with_name(f"{relative.name}.diff"),
            from_label=f"ParaTranz/{scope_dir}/{relative.as_posix()}",
            to_label=f"Local/{scope_dir}/{relative.as_posix()}",
        )
    return report


def _compare_dll_file(
    remote_file: Path,
    local_file: Path,
    *,
    relative: Path,
    scope_dir: str,
    diff_root: Path,
) -> CompareParatranzFileReport:
    remote_entries = read_paratranz_file(remote_file)
    local_entries = read_paratranz_file(local_file)
    report = CompareParatranzFileReport(
        relative_path=relative.as_posix(),
        file_type="dll",
        remote_entries=len(remote_entries),
        local_entries=len(local_entries),
    )

    remote_exact: dict[tuple[str, str], list[ParatranzData]] = {}
    remote_by_key: dict[str, list[ParatranzData]] = {}
    used_remote_ids: set[int] = set()
    changed_remote_ids: set[int] = set()
    changed_local_ids: set[int] = set()
    for entry in remote_entries:
        remote_exact.setdefault((entry.key, entry.original), []).append(entry)
        remote_by_key.setdefault(entry.key, []).append(entry)

    for local_entry in local_entries:
        exact_candidate = _take_first_unused(remote_exact.get((local_entry.key, local_entry.original), []), used_remote_ids)
        if exact_candidate is not None:
            classification = _classify_translation_side_change(exact_candidate, local_entry)
            if classification == "translation_changed":
                report.translation_changed += 1
                changed_remote_ids.add(id(exact_candidate))
                changed_local_ids.add(id(local_entry))
            continue

        key_candidate = _take_first_unused(remote_by_key.get(local_entry.key, []), used_remote_ids)
        if key_candidate is not None:
            classification = _classify_entry_change(key_candidate, local_entry)
            if classification == "entry_changed":
                report.entry_changed += 1
            else:
                report.source_changed += 1
            changed_remote_ids.add(id(key_candidate))
            changed_local_ids.add(id(local_entry))
            continue

        report.local_only += 1
        changed_local_ids.add(id(local_entry))

    unmatched_remote_entries = [entry for entry in remote_entries if id(entry) not in used_remote_ids]
    report.remote_only = len(unmatched_remote_entries)
    changed_remote_ids.update(id(entry) for entry in unmatched_remote_entries)

    if report.has_diff:
        remote_diff_entries = [entry for entry in remote_entries if id(entry) in changed_remote_ids]
        local_diff_entries = [entry for entry in local_entries if id(entry) in changed_local_ids]
        report.diff_path = _write_diff_file(
            remote_diff_entries,
            local_diff_entries,
            diff_root / relative.with_name(f"{relative.name}.diff"),
            from_label=f"ParaTranz/{scope_dir}/{relative.as_posix()}",
            to_label=f"Local/{scope_dir}/{relative.as_posix()}",
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


def _classify_entry_change(remote_entry: ParatranzData, local_entry: ParatranzData) -> str | None:
    source_changed = _source_signature(remote_entry) != _source_signature(local_entry)
    translation_changed = _translation_signature(remote_entry) != _translation_signature(local_entry)
    if source_changed and translation_changed:
        return "entry_changed"
    if source_changed:
        return "source_changed"
    if translation_changed:
        return "translation_changed"
    return None


def _classify_translation_side_change(remote_entry: ParatranzData, local_entry: ParatranzData) -> str | None:
    return "translation_changed" if _translation_signature(remote_entry) != _translation_signature(local_entry) else None


def _source_signature(entry: ParatranzData) -> tuple[str, str]:
    return entry.original, entry.context


def _translation_signature(entry: ParatranzData) -> tuple[str, int]:
    return entry.translation, int(entry.stage)


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


def _resolve_scope_dir(scope: str) -> str:
    try:
        return _SCOPE_DIRECTORY_BY_KEY[scope.casefold()]
    except KeyError as exc:
        raise ValueError(f"不支持的 scope：{scope}") from exc


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


def _only_in_label(remote_file: Path | None, local_file: Path | None) -> str | None:
    if remote_file is not None and local_file is None:
        return "remote"
    if remote_file is None and local_file is not None:
        return "local"
    return None


__all__ = [
    "CompareParatranzFileReport",
    "CompareParatranzResult",
    "CompareParatranzSummary",
    "compare_downloaded_paratranz_scope",
    "download_and_compare_paratranz",
]
