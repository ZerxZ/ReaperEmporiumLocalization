from __future__ import annotations

from pathlib import Path

import click

from reaper_tools.cli.common import HELP_OPTION_NAMES, LocalizedCommand, get_command_app_context, with_aliases
from reaper_tools.cli.registry import DOWNLOAD_COMMAND, INSTALL_COMMAND, PULL_COMMAND, STATS_COMMAND
from reaper_tools.localization.installer import install_translation_packages, summarize_translation_packages
from reaper_tools.localization.paratranz import Paratranz


def _package_inputs(values: tuple[Path, ...]) -> list[Path]:
    """把 Click 参数转换成业务层期望的路径列表。"""
    context = get_command_app_context()
    return list(values) if values else [context.paths.paratranz]


@with_aliases(*DOWNLOAD_COMMAND.aliases)
@click.command(
    DOWNLOAD_COMMAND.name,
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help=DOWNLOAD_COMMAND.help,
    short_help=DOWNLOAD_COMMAND.short_help,
)
@click.option("--force", is_flag=True, help="忽略本地缓存，强制重新下载导出包。")
@click.option("--progress", is_flag=True, help="显示下载和解压进度条。")
def download_command(force: bool, progress: bool) -> int:
    """下载并解压最新 ParaTranz 导出包。"""
    context = get_command_app_context()
    extracted_root = Paratranz(context=context).download(force=force, show_progress=progress)
    context.logger.success("ParaTranz 导出包已准备好：{}", extracted_root)
    return 0


@with_aliases(*INSTALL_COMMAND.aliases)
@click.command(
    INSTALL_COMMAND.name,
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help=INSTALL_COMMAND.help,
    short_help=INSTALL_COMMAND.short_help,
)
@click.argument("inputs", nargs=-1, type=click.Path(path_type=Path))
@click.option("--game-root", type=click.Path(path_type=Path), help="游戏根目录；未传时使用 PATH_GAME_ROOT 或开发目录推断值。")
@click.option("--no-clear", is_flag=True, help="保留已安装的旧 JSON 文件，不在安装前清空。")
@click.option("--progress", is_flag=True, help="显示复制和合并进度条。")
def install_command(inputs: tuple[Path, ...], game_root: Path | None, no_clear: bool, progress: bool) -> int:
    """把一个或多个本地翻译包安装到游戏目录。"""
    context = get_command_app_context()
    stats = install_translation_packages(
        _package_inputs(inputs),
        game_root=game_root,
        clear=not no_clear,
        show_progress=progress,
        context=context,
    )
    context.logger.success(
        "已安装 {} 个翻译包，{} 个数据库文件，{} 条数据库词条，{} 条 DLL 词条",
        stats.packages,
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
    )
    return 0


@with_aliases(*PULL_COMMAND.aliases)
@click.command(
    PULL_COMMAND.name,
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help=PULL_COMMAND.help,
    short_help=PULL_COMMAND.short_help,
)
@click.option("--force", is_flag=True, help="忽略本地缓存，强制重新下载导出包。")
@click.option("--game-root", type=click.Path(path_type=Path), help="游戏根目录；未传时使用 PATH_GAME_ROOT 或开发目录推断值。")
@click.option("--no-clear", is_flag=True, help="保留已安装的旧 JSON 文件，不在安装前清空。")
@click.option("--progress", is_flag=True, help="显示处理进度条。")
def pull_command(force: bool, game_root: Path | None, no_clear: bool, progress: bool) -> int:
    """下载 ParaTranz 导出包，并立即安装到游戏目录。"""
    context = get_command_app_context()
    extracted_root = Paratranz(context=context).download(force=force, show_progress=progress)
    stats = install_translation_packages(
        [extracted_root],
        game_root=game_root,
        clear=not no_clear,
        show_progress=progress,
        context=context,
    )
    context.logger.success(
        "已拉取并安装 {} 个翻译包，{} 个数据库文件，{} 条数据库词条，{} 条 DLL 词条",
        stats.packages,
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
    )
    return 0


@with_aliases(*STATS_COMMAND.aliases)
@click.command(
    STATS_COMMAND.name,
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help=STATS_COMMAND.help,
    short_help=STATS_COMMAND.short_help,
)
@click.argument("inputs", nargs=-1, type=click.Path(path_type=Path))
def stats_command(inputs: tuple[Path, ...]) -> int:
    """统计本地翻译包中的词条数量。"""
    context = get_command_app_context()
    stats = summarize_translation_packages(_package_inputs(inputs))
    context.logger.info(
        "发现 {} 个翻译包，{} 个数据库文件，{} 条数据库词条，{} 条 DLL 词条",
        stats.packages,
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
    )
    return 0


