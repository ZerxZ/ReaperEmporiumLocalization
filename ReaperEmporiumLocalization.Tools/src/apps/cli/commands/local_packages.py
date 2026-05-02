from __future__ import annotations

from pathlib import Path

import click

from src.apps.cli.common import HELP_OPTION_NAMES, LocalizedCommand, with_aliases
from src.config import logger, paths
from src.localization.installer import install_translation_packages, summarize_translation_packages
from src.localization.paratranz import Paratranz


def _package_inputs(values: tuple[Path, ...]) -> list[Path]:
    """把 Click 参数转换成业务层期望的路径列表。"""
    return list(values) if values else [paths.paratranz]


@with_aliases("download")
@click.command(
    "下载包",
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help="下载并解压最新 ParaTranz 导出包。",
    short_help="下载并解压最新 ParaTranz 导出包。",
)
@click.option("--force", is_flag=True, help="忽略本地缓存，强制重新下载导出包。")
@click.option("--progress", is_flag=True, help="显示下载和解压进度条。")
def download_command(force: bool, progress: bool) -> int:
    """下载并解压最新 ParaTranz 导出包。"""
    extracted_root = Paratranz().download(force=force, show_progress=progress)
    logger.success("ParaTranz 导出包已准备好：{}", extracted_root)
    return 0


@with_aliases("install")
@click.command(
    "安装包",
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help="将本地翻译 JSON 包安装到游戏目录。",
    short_help="将本地翻译 JSON 包安装到游戏目录。",
)
@click.argument("inputs", nargs=-1, type=click.Path(path_type=Path))
@click.option("--game-root", type=click.Path(path_type=Path), help="游戏根目录；未传时使用 PATH_GAME_ROOT 或开发目录推断值。")
@click.option("--no-clear", is_flag=True, help="保留已安装的旧 JSON 文件，不在安装前清空。")
@click.option("--progress", is_flag=True, help="显示复制和合并进度条。")
def install_command(inputs: tuple[Path, ...], game_root: Path | None, no_clear: bool, progress: bool) -> int:
    """把一个或多个本地翻译包安装到游戏目录。"""
    stats = install_translation_packages(
        _package_inputs(inputs),
        game_root=game_root,
        clear=not no_clear,
        show_progress=progress,
    )
    logger.success(
        "已安装 {} 个翻译包，{} 个数据库文件，{} 条数据库词条，{} 条 DLL 词条",
        stats.packages,
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
    )
    return 0


@with_aliases("pull")
@click.command(
    "拉取安装",
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help="下载 ParaTranz 导出包，并安装到游戏目录。",
    short_help="下载 ParaTranz 导出包，并安装到游戏目录。",
)
@click.option("--force", is_flag=True, help="忽略本地缓存，强制重新下载导出包。")
@click.option("--game-root", type=click.Path(path_type=Path), help="游戏根目录；未传时使用 PATH_GAME_ROOT 或开发目录推断值。")
@click.option("--no-clear", is_flag=True, help="保留已安装的旧 JSON 文件，不在安装前清空。")
@click.option("--progress", is_flag=True, help="显示处理进度条。")
def pull_command(force: bool, game_root: Path | None, no_clear: bool, progress: bool) -> int:
    """下载 ParaTranz 导出包，并立即安装到游戏目录。"""
    extracted_root = Paratranz().download(force=force, show_progress=progress)
    stats = install_translation_packages(
        [extracted_root],
        game_root=game_root,
        clear=not no_clear,
        show_progress=progress,
    )
    logger.success(
        "已拉取并安装 {} 个翻译包，{} 个数据库文件，{} 条数据库词条，{} 条 DLL 词条",
        stats.packages,
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
    )
    return 0


@with_aliases("stats")
@click.command(
    "查看统计",
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help="统计本地翻译包中的 JSON 词条数量。",
    short_help="统计本地翻译包中的 JSON 词条数量。",
)
@click.argument("inputs", nargs=-1, type=click.Path(path_type=Path))
def stats_command(inputs: tuple[Path, ...]) -> int:
    """统计本地翻译包中的词条数量。"""
    stats = summarize_translation_packages(_package_inputs(inputs))
    logger.info(
        "发现 {} 个翻译包，{} 个数据库文件，{} 条数据库词条，{} 条 DLL 词条",
        stats.packages,
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
    )
    return 0
