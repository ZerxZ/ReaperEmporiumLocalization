from __future__ import annotations

import argparse
from pathlib import Path

from src.config import logger, paths
from src.localization.dump_builder import build_dump_diff
from src.localization.installer import install_translation_packages, summarize_translation_packages
from src.localization.paratranz import Paratranz


class ChineseArgumentParser(argparse.ArgumentParser):
    """把 argparse 默认帮助中的固定英文前缀替换为中文。"""

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法:", 1)

    def format_help(self) -> str:
        return super().format_help().replace("usage:", "用法:", 1)


def _with_chinese_help(parser: ChineseArgumentParser) -> ChineseArgumentParser:
    """统一本地化 argparse 的帮助选项和分组标题。"""
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出。")
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    return parser


def _path_args(values: list[str] | None) -> list[Path]:
    """把命令行传入的目录参数转成 Path；未传时默认使用 ParaTranz 解包目录。"""
    if not values:
        return [paths.paratranz]
    return [Path(value) for value in values]


def cmd_download(args: argparse.Namespace) -> int:
    """下载并解压 ParaTranz 导出包。"""
    extracted_root = Paratranz().download(force=args.force, show_progress=args.progress)
    logger.success("ParaTranz 导出包已准备好：{}", extracted_root)
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    """把一个或多个本地翻译包安装到游戏目录。"""
    stats = install_translation_packages(
        _path_args(args.inputs),
        game_root=Path(args.game_root) if args.game_root else None,
        clear=not args.no_clear,
        show_progress=args.progress,
    )
    logger.success(
        "已安装 {} 个翻译包：{} 个数据库文件，{} 条数据库词条，{} 条 DLL 词条",
        stats.packages,
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
    )
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    """下载 ParaTranz 导出包，并立即安装到游戏目录。"""
    extracted_root = Paratranz().download(force=args.force, show_progress=args.progress)
    stats = install_translation_packages(
        [extracted_root],
        game_root=Path(args.game_root) if args.game_root else None,
        clear=not args.no_clear,
        show_progress=args.progress,
    )
    logger.success(
        "已拉取并安装 {} 个翻译包：{} 个数据库文件，{} 条数据库词条，{} 条 DLL 词条",
        stats.packages,
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
    )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """统计本地翻译包中的词条数量。"""
    stats = summarize_translation_packages(_path_args(args.inputs))
    logger.info(
        "发现 {} 个翻译包：{} 个数据库文件，{} 条数据库词条，{} 条 DLL 词条",
        stats.packages,
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
    )
    return 0


def cmd_build_dump(args: argparse.Namespace) -> int:
    """从游戏转储数据构建可上传到 ParaTranz 的 MainGame/DLCGame 输出。"""
    stats = build_dump_diff(show_progress=args.progress)
    logger.success(
        "已构建转储差异：MainGame {} 个数据库文件，{} 条数据库词条，{} 条 DLL 词条；"
        "DLCGame 写入/读取 {} / {} 个数据库文件，{} / {} 条数据库词条，{} / {} 条 DLL 词条；"
        "diff 输出 {} 个数据库 diff 文件，{} 个 DLL diff 文件",
        stats.main_database_files,
        stats.main_database_entries,
        stats.main_dll_entries,
        stats.dlc_database_files_written,
        stats.dlc_database_files_read,
        stats.dlc_database_entries_written,
        stats.dlc_database_entries_read,
        stats.dlc_dll_entries_written,
        stats.dlc_dll_entries_read,
        stats.diff_database_files_written,
        stats.diff_dll_files_written,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。

    中文命令是主入口；英文命令通过 aliases 保留，确保旧脚本不需要立刻迁移。
    选项名仍使用英文，是为了兼容 argparse、README 示例和已有自动化调用。
    """
    parser = _with_chinese_help(ChineseArgumentParser(description="死神商馆汉化辅助工具。", add_help=False))
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=ChineseArgumentParser)
    subparsers.title = "命令"

    download = _with_chinese_help(
        subparsers.add_parser("下载包", aliases=["download"], help="下载并解压最新 ParaTranz 导出包。", add_help=False)
    )
    download.add_argument("--force", action="store_true", help="忽略本地缓存，强制重新下载导出包。")
    download.add_argument("--progress", action="store_true", help="显示下载和解压进度条。")
    download.set_defaults(func=cmd_download)

    install = _with_chinese_help(
        subparsers.add_parser("安装包", aliases=["install"], help="将本地翻译 JSON 包安装到游戏目录。", add_help=False)
    )
    install.add_argument("inputs", nargs="*", help="翻译包目录；未传时默认使用 PATH_PARATRANZ。")
    install.add_argument("--game-root", help="游戏根目录；未传时使用 PATH_GAME_ROOT 或开发目录推断值。")
    install.add_argument("--no-clear", action="store_true", help="保留已安装的旧 JSON 文件，不在安装前清空。")
    install.add_argument("--progress", action="store_true", help="显示复制和合并进度条。")
    install.set_defaults(func=cmd_install)

    pull = _with_chinese_help(
        subparsers.add_parser("拉取安装", aliases=["pull"], help="下载 ParaTranz 导出包，并安装到游戏目录。", add_help=False)
    )
    pull.add_argument("--force", action="store_true", help="忽略本地缓存，强制重新下载导出包。")
    pull.add_argument("--game-root", help="游戏根目录；未传时使用 PATH_GAME_ROOT 或开发目录推断值。")
    pull.add_argument("--no-clear", action="store_true", help="保留已安装的旧 JSON 文件，不在安装前清空。")
    pull.add_argument("--progress", action="store_true", help="显示处理进度条。")
    pull.set_defaults(func=cmd_pull)

    stats = _with_chinese_help(
        subparsers.add_parser("查看统计", aliases=["stats"], help="统计本地翻译包中的 JSON 词条数量。", add_help=False)
    )
    stats.add_argument("inputs", nargs="*", help="翻译包目录；未传时默认使用 PATH_PARATRANZ。")
    stats.set_defaults(func=cmd_stats)

    build_dump = _with_chinese_help(
        subparsers.add_parser(
            "构建差异",
            aliases=["build-dump"],
            help="构建 MainGame/DLCGame 转储输出，并把 DLCGame 缩减为相对 MainGame 的差异词条。",
            add_help=False,
        )
    )
    build_dump.add_argument("--progress", action="store_true", help="显示构建进度条。")
    build_dump.set_defaults(func=cmd_build_dump)

    return parser


def main() -> int:
    """程序入口：解析命令行并分发到对应处理函数。"""
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
