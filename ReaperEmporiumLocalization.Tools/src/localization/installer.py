from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.config.logging import logger
from src.config.paths import paths
from src.config.progress import ProgressBar
from src.models import ParatranzData, paratranz_data_list_adapter


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
) -> InstallStats:
    """把本地翻译包合并并安装到游戏目录。

    翻译包可能来自 ParaTranz 导出、手工整理目录或 build-dump 输出。安装时会先
    发现合法包目录，再按数据库类别和 DLL 原文分别合并，最后写成游戏插件读取
    的运行时目录结构。
    """

    package_roots = discover_translation_packages(input_roots)
    if not package_roots:
        raise FileNotFoundError("未找到可安装的翻译包。")

    target_game_root = paths.require_game_root(game_root)
    localization_root = target_game_root / "localization"
    database_root = localization_root / "database"
    dll_root = localization_root / "dll_strings"

    if clear:
        _clear_target(database_root, localization_root)
        _clear_target(dll_root, localization_root)

    database_by_category: dict[str, dict[str, ParatranzData]] = {}
    dll_by_original: dict[str, ParatranzData] = {}
    stats = InstallStats(packages=len(package_roots))

    with ProgressBar(total=len(package_roots), enabled=show_progress, desc="读取翻译包", unit="包") as progress:
        for package_root in package_roots:
            _merge_package(package_root, database_by_category, dll_by_original, stats)
            progress.set_postfix_str(package_root.name)
            progress.update()

    database_root.mkdir(parents=True, exist_ok=True)
    dll_root.mkdir(parents=True, exist_ok=True)

    categories = sorted(database_by_category)
    with ProgressBar(total=len(categories), enabled=show_progress, desc="写入数据库", unit="文件") as progress:
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

    logger.info("已将翻译安装到 {}", localization_root)
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


def _write_paratranz_file(target: Path, entries: list[ParatranzData]) -> None:
    """以稳定 UTF-8/缩进格式写出 ParaTranz JSON。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [entry.model_dump(mode="json") for entry in entries]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def _clear_target(target: Path, localization_root: Path) -> None:
    """清理旧安装结果；删除前先确认目标仍在 localization 目录内部。"""
    if not target.exists():
        return
    paths.ensure_inside(target, localization_root)
    shutil.rmtree(target)


__all__ = [
    "InstallStats",
    "clean_category_name",
    "discover_translation_packages",
    "install_translation_packages",
    "read_paratranz_file",
    "summarize_translation_packages",
]
