from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from zipfile import ZIP_DEFLATED, ZipFile

from reaper_tools.app_context import AppContext, build_app_context, get_app_context
from reaper_tools.models import ParatranzData, paratranz_data_list_adapter


_CAB_SUFFIX_PATTERN = re.compile(r"-CAB-.*$")
_NUMBER_SUFFIX_PATTERN = re.compile(r"_\d+$")


@dataclass(slots=True)
class InstallStats:
    """安装/统计流程的汇总结果。"""

    packages: int = 0
    database_files: int = 0
    database_entries: int = 0
    dll_entries: int = 0
    written_files: int = 0

    def add(self, other: "InstallStats") -> None:
        """把另一个统计结果合并进当前对象。"""
        self.packages += other.packages
        self.database_files += other.database_files
        self.database_entries += other.database_entries
        self.dll_entries += other.dll_entries
        self.written_files += other.written_files


@dataclass(slots=True)
class PackageStats:
    """最终打包流程的输出统计。"""

    database_files: int = 0
    database_entries: int = 0
    dll_entries: int = 0
    written_files: int = 0
    zip_path: Path | None = None


def summarize_translation_packages(input_roots: Iterable[Path | str]) -> InstallStats:
    """扫描本地翻译包，只统计文件和词条数量，不写入游戏目录。"""
    package_roots = discover_translation_packages(input_roots)
    stats = InstallStats(packages=len(package_roots))
    for package_root in package_roots:
        for file_path in _database_files(package_root):
            stats.database_files += 1
            stats.database_entries += len(read_paratranz_file(file_path))
        dll_file = _dll_file(package_root)
        if dll_file.exists():
            stats.dll_entries += len(read_paratranz_file(dll_file))
    return stats


def install_translation_packages(
    input_roots: Iterable[Path | str],
    *,
    game_root: Path | str | None = None,
    clear: bool = True,
    show_progress: bool = False,
    context: AppContext | None = None,
) -> InstallStats:
    """把本地翻译包合并并安装到游戏目录。

    翻译包可能来自 ParaTranz 导出、手工整理目录或 build-dump 输出。安装时会先
    发现合法包目录，再按数据库类别和 DLL 原文分别合并，最后写成游戏插件读取
    的运行时目录结构。
    """

    package_roots = discover_translation_packages(input_roots)
    if not package_roots:
        raise FileNotFoundError("未找到可安装的翻译包。")

    ctx = context or build_app_context(project_paths=paths, app_logger=logger)
    target_game_root = ctx.paths.require_game_root(game_root)
    localization_root = target_game_root / "localization"
    database_root = localization_root / "database"
    dll_root = localization_root / "dll_strings"

    if clear:
        _clear_target(database_root, localization_root, context=ctx)
        _clear_target(dll_root, localization_root, context=ctx)

    database_by_category: dict[str, dict[str, ParatranzData]] = {}
    dll_by_original: dict[str, ParatranzData] = {}
    stats = InstallStats(packages=len(package_roots))

    with ctx.progress(total=len(package_roots), enabled=show_progress, desc="读取翻译包", unit="包") as progress:
        for package_root in package_roots:
            _merge_package(package_root, database_by_category, dll_by_original, stats)
            progress.set_postfix_str(package_root.name)
            progress.update()

    database_root.mkdir(parents=True, exist_ok=True)
    dll_root.mkdir(parents=True, exist_ok=True)

    categories = sorted(database_by_category)
    with ctx.progress(total=len(categories), enabled=show_progress, desc="写入数据库", unit="文件") as progress:
        for category in categories:
            entries = sorted(database_by_category[category].values(), key=lambda item: item.key or item.original)
            _write_paratranz_file(database_root / f"{category}.json", entries)
            stats.written_files += 1
            progress.set_postfix_str(category)
            progress.update()

    if dll_by_original:
        entries = sorted(dll_by_original.values(), key=lambda item: item.key or item.original)
        _write_paratranz_file(dll_root / "dll_strings.json", entries)
        stats.written_files += 1

    ctx.logger.info("已将翻译安装到 {}", localization_root)
    return stats


def package_final_localization(
    source_root: Path | str | None = None,
    *,
    output_root: Path | str | None = None,
    zip_path: Path | str | None = None,
    create_zip: bool = True,
    show_progress: bool = False,
    context: AppContext | None = None,
) -> PackageStats:
    """把 MainGame/DLCGame 翻译包合并成游戏运行时 localization 目录。

    默认输入为 build/migrated；如果不需要旧译文迁移，也可以把 source_root 指向
    build/dump。输出目录本身就是 localization 目录，zip 内部固定使用
    localization/ 前缀，方便直接解压到游戏根目录。
    """

    ctx = context or build_app_context(project_paths=paths, app_logger=logger)
    source = Path(source_root) if source_root is not None else ctx.paths.root / "build" / "migrated"
    output = Path(output_root) if output_root is not None else ctx.paths.root / "build" / "package" / "localization"
    archive = (
        Path(zip_path)
        if zip_path is not None
        else ctx.paths.root / "build" / "package" / "ReaperEmporiumLocalization-localization.zip"
    )

    main_root = source / "MainGame"
    dlc_root = source / "DLCGame"
    if not main_root.is_dir():
        raise FileNotFoundError(f"MainGame 目录不存在：{main_root}")
    if not dlc_root.is_dir():
        raise FileNotFoundError(f"DLCGame 目录不存在：{dlc_root}")
    if output.resolve() == source.resolve():
        raise ValueError("最终打包输出目录不能和输入目录相同。")

    _reset_output_dir(output, context=ctx)
    stats = PackageStats()
    stats.database_files, stats.database_entries = _package_database_tree(
        main_root / "database",
        dlc_root / "database",
        output / "database",
        show_progress=show_progress,
        context=ctx,
    )
    stats.written_files += stats.database_files
    stats.dll_entries = _package_dll_strings(
        main_root / "dll_strings.json",
        dlc_root / "dll_strings.json",
        output / "dll_strings" / "dll_strings.json",
    )
    if stats.dll_entries:
        stats.written_files += 1

    if create_zip:
        _write_localization_zip(output, archive)
        stats.zip_path = archive

    ctx.logger.info("已生成最终本地化包：{}", output)
    return stats


def discover_translation_packages(input_roots: Iterable[Path | str]) -> list[Path]:
    """从输入目录中发现翻译包根目录。

    合法翻译包可以是本身包含 database/dll_strings 的目录，也可以是 ParaTranz
    导出包里常见的 utf8 子目录。
    """

    packages: list[Path] = []
    seen: set[Path] = set()
    for root_value in input_roots:
        root = Path(root_value).resolve()
        for package in _candidate_packages(root):
            resolved = package.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            packages.append(resolved)
    return sorted(packages, key=lambda item: item.as_posix().casefold())


def read_paratranz_file(file_path: Path) -> list[ParatranzData]:
    """读取 ParaTranz JSON 文件，并校验为统一的 ParatranzData 列表。"""
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"无效的 JSON 文件：{file_path}") from exc
    return paratranz_data_list_adapter.validate_python(payload)


def clean_category_name(file_path: Path) -> str:
    """清理数据库文件名中的 CAB 后缀和数字后缀，得到稳定类别名。"""
    name = _CAB_SUFFIX_PATTERN.sub("", file_path.stem)
    name = _NUMBER_SUFFIX_PATTERN.sub("", name)
    return name


def _database_category_name(file_path: Path, database_root: Path) -> str:
    """保留 database 下的相对目录，只清理 JSON 文件名本身。"""
    relative = file_path.relative_to(database_root)
    clean_name = clean_category_name(relative)
    if relative.parent == Path("."):
        return clean_name
    return (relative.parent / clean_name).as_posix()


def _candidate_packages(root: Path) -> list[Path]:
    """列出某个输入路径下可能的翻译包目录。"""
    if root.is_file():
        return []

    if _is_package_root(root):
        return [root]

    utf8_root = root / "utf8"
    if _is_package_root(utf8_root):
        return [utf8_root]

    if not root.exists():
        return []

    packages = [child for child in root.iterdir() if child.is_dir() and _is_package_root(child)]
    return packages


def _is_package_root(root: Path) -> bool:
    """判断目录是否拥有翻译包的关键结构。"""
    return root.exists() and ((root / "database").is_dir() or _dll_file(root).is_file())


def _database_files(package_root: Path) -> list[Path]:
    """列出翻译包内所有数据库 JSON 文件。"""
    database_root = package_root / "database"
    if database_root.is_dir():
        return sorted(database_root.rglob("*.json"), key=lambda item: item.as_posix().casefold())
    return []


def _merge_package(
    package_root: Path,
    database_by_category: dict[str, dict[str, ParatranzData]],
    dll_by_original: dict[str, ParatranzData],
    stats: InstallStats,
) -> None:
    """把单个翻译包合并进内存索引。

    数据库词条按清理后的类别名归组；DLL 字符串没有类别目录，因此按运行时原文
    归并。重复词条交给 _put_best 选择质量更高的一条。
    """

    database_root = package_root / "database"
    for file_path in _database_files(package_root):
        category = _database_category_name(file_path, database_root)
        category_entries = database_by_category.setdefault(category, {})
        entries = read_paratranz_file(file_path)
        stats.database_files += 1
        stats.database_entries += len(entries)
        for entry in entries:
            _put_best(category_entries, entry)

    dll_file = _dll_file(package_root)
    if dll_file.exists():
        entries = read_paratranz_file(dll_file)
        stats.dll_entries += len(entries)
        for entry in entries:
            _put_best(dll_by_original, entry)


def _dll_file(package_root: Path) -> Path:
    """兼容平铺和目录式两种 dll_strings.json 布局。"""
    flat_file = package_root / "dll_strings.json"
    if flat_file.exists():
        return flat_file
    return package_root / "dll_strings" / "dll_strings.json"


def _put_best(target: dict[str, ParatranzData], entry: ParatranzData) -> None:
    """按可用性和阶段选择最适合写入游戏运行时的翻译。"""
    original = entry.runtime_original
    if not original.strip():
        return
    current = target.get(original)
    if current is None or entry.quality_rank() > current.quality_rank():
        target[original] = entry


def _package_database_tree(
    main_database_root: Path,
    dlc_database_root: Path,
    output_root: Path,
    *,
    show_progress: bool,
    context: AppContext,
) -> tuple[int, int]:
    """按 database 相对路径合并 MainGame 完整包和 DLCGame 差异包。"""
    relative_files = sorted(
        {
            file_path.relative_to(root)
            for root in (main_database_root, dlc_database_root)
            if root.exists()
            for file_path in root.rglob("*.json")
        },
        key=lambda item: item.as_posix().casefold(),
    )
    entry_count = 0
    with context.progress(total=len(relative_files), enabled=show_progress, desc="合并数据库", unit="文件") as progress:
        for relative in relative_files:
            main_file = main_database_root / relative
            dlc_file = dlc_database_root / relative
            entries = _merge_database_entries(
                read_paratranz_file(main_file) if main_file.exists() else [],
                read_paratranz_file(dlc_file) if dlc_file.exists() else [],
            )
            entry_count += len(entries)
            _write_paratranz_file(output_root / relative, entries)
            progress.set_postfix_str(relative.as_posix())
            progress.update()
    return len(relative_files), entry_count


def _merge_database_entries(main_entries: list[ParatranzData], dlc_entries: list[ParatranzData]) -> list[ParatranzData]:
    """数据库以原文为身份，DLC 同原文覆盖 MainGame，新原文追加。"""
    merged: dict[str, ParatranzData] = {}
    for entry in main_entries:
        merged.setdefault(entry.runtime_original, entry)
    for entry in dlc_entries:
        merged[entry.runtime_original] = entry
    return list(merged.values())


def _package_dll_strings(main_file: Path, dlc_file: Path, output_file: Path) -> int:
    """把 MainGame/DLCGame DLL 字符串合并成运行时唯一 dll_strings.json。"""
    candidates: dict[str, ParatranzData] = {}
    source_priority: dict[str, int] = {}
    for priority, file_path in ((0, main_file), (1, dlc_file)):
        if not file_path.exists():
            continue
        for entry in read_paratranz_file(file_path):
            original = entry.runtime_original
            current = candidates.get(original)
            current_priority = source_priority.get(original, -1)
            if current is None or (priority, entry.quality_rank()) > (current_priority, current.quality_rank()):
                candidates[original] = entry
                source_priority[original] = priority
    entries = list(candidates.values())
    _write_paratranz_file(output_file, entries)
    return len(entries)


def _reset_output_dir(output: Path, *, context: AppContext) -> None:
    """重建最终打包输出目录，避免旧产物混入。"""
    if output.exists():
        if len(output.resolve().parts) <= 2:
            raise ValueError(f"拒绝清理过高层级目录：{output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)


def _write_localization_zip(localization_root: Path, zip_path: Path) -> None:
    """写出只包含 localization/ 前缀的 zip。"""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    files = sorted(localization_root.rglob("*"), key=lambda item: item.relative_to(localization_root).as_posix().casefold())
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in files:
            if file_path.is_file():
                archive_name = (Path("localization") / file_path.relative_to(localization_root)).as_posix()
                archive.write(file_path, archive_name)


def _write_paratranz_file(target: Path, entries: list[ParatranzData]) -> None:
    """以稳定 UTF-8/缩进格式写出 ParaTranz JSON。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [entry.model_dump(mode="json") for entry in entries]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def _clear_target(target: Path, localization_root: Path, *, context: AppContext) -> None:
    """清理旧安装结果；删除前先确认目标仍在 localization 目录内部。"""
    if not target.exists():
        return
    context.paths.ensure_inside(target, localization_root)
    shutil.rmtree(target)


__all__ = [
    "InstallStats",
    "PackageStats",
    "clean_category_name",
    "discover_translation_packages",
    "install_translation_packages",
    "package_final_localization",
    "read_paratranz_file",
    "summarize_translation_packages",
]

_DEFAULT_CONTEXT = get_app_context()
paths = _DEFAULT_CONTEXT.paths
logger = _DEFAULT_CONTEXT.logger

