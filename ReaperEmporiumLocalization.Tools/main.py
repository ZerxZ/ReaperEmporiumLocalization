from __future__ import annotations

import argparse
from pathlib import Path

from src.config import logger, paths
from src.localization.dump_builder import build_dump_diff
from src.localization.installer import install_translation_packages, package_final_localization, summarize_translation_packages
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


def cmd_migrate_translations(args: argparse.Namespace) -> int:
    """把旧 ParaTranz 译文迁移到当前 build/dump 新结构。"""
    result = Paratranz().migrate_legacy_translations_to_dump(
        source_root=Path(args.source_root) if args.source_root else None,
        dump_root=Path(args.dump_root) if args.dump_root else None,
        output_root=Path(args.output_root) if args.output_root else None,
        source_project_id=args.source_project_id,
        dry_run=args.dry_run,
        show_progress=args.progress,
    )
    report = getattr(result, "report", {})
    logger.success(
        "{}旧译文迁移：{} 个文件，迁移 {} 条译文，未匹配 {} 条，重复逻辑文件 {} 组，冲突 {} 处。结果目录：{}",
        "[dry-run] " if args.dry_run else "",
        result.planned,
        result.migrated_entries,
        result.skipped,
        len(report.get("duplicate_files", [])),
        len(report.get("conflicts", [])),
        report.get("output_root", args.output_root or "build/migrated"),
    )
    if not args.dry_run:
        logger.info("迁移命令只生成本地文件，不会自动上传；请检查 build/migrated 后手动上传到 ParaTranz。")
    return 0


def cmd_migrate_terms(args: argparse.Namespace) -> int:
    """把旧 ParaTranz 项目的术语迁移到新项目。"""
    api = Paratranz()
    result = api.migrate_terms_to_project(
        source_project_id=args.source_project_id,
        target_project_id=args.target_project_id,
        dry_run=not args.execute,
        show_progress=args.progress,
    )
    target_project_id = args.target_project_id or api.project_id
    logger.success(
        "{}项目术语迁移：源项目 {} -> 目标项目 {}，共 {} 页，{} 条术语{}",
        "[dry-run] " if not args.execute else "",
        args.source_project_id,
        target_project_id,
        result.planned,
        sum(len(action.metadata.get("terms", [])) for action in result.actions),
        f"，成功迁移 {result.migrated_entries} 条" if args.execute else "",
    )
    if result.errors:
        logger.warning("术语迁移过程中有 {} 个失败页：{}", len(result.errors), " | ".join(result.errors))
    if not args.execute:
        logger.info("默认只预览计划；确认无误后加 --execute 才会写入目标 ParaTranz 项目。")
    return 0


def cmd_package_final(args: argparse.Namespace) -> int:
    """把 MainGame/DLCGame 合并为游戏运行时 localization 包。"""
    stats = package_final_localization(
        source_root=Path(args.source_root) if args.source_root else None,
        output_root=Path(args.output_root) if args.output_root else None,
        zip_path=Path(args.zip_path) if args.zip_path else None,
        create_zip=not args.no_zip,
        show_progress=args.progress,
    )
    logger.success(
        "已生成最终本地化包：{} 个数据库文件，{} 条数据库词条，{} 条 DLL 词条，{} 个输出 JSON{}",
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
        stats.written_files,
        f"，zip：{stats.zip_path}" if stats.zip_path else "",
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

    migrate = _with_chinese_help(
        subparsers.add_parser(
            "迁移翻译",
            aliases=["migrate-translations"],
            help="把旧 ParaTranz 译文迁移到当前 build/dump 新结构，只生成本地 build/migrated。",
            add_help=False,
        )
    )
    migrate.add_argument("--source-root", help="旧 ParaTranz 本地导出目录；未传时默认使用 data/paratranz。")
    migrate.add_argument("--dump-root", help="新提取的 build/dump 目录；未传时默认使用 build/dump。")
    migrate.add_argument("--output-root", help="迁移结果输出目录；未传时默认使用 build/migrated。")
    migrate.add_argument("--source-project-id", type=int, help="旧 ParaTranz 项目 ID；只读文件和译文，不会写入远端。")
    migrate.add_argument("--dry-run", action="store_true", help="只生成迁移统计，不写入 build/migrated。")
    migrate.add_argument("--progress", action="store_true", help="显示迁移进度条。")
    migrate.set_defaults(func=cmd_migrate_translations)

    migrate_terms = _with_chinese_help(
        subparsers.add_parser(
            "迁移术语",
            aliases=["migrate-terms"],
            help="把旧 ParaTranz 项目的术语迁移到新 ParaTranz 项目；默认只预览，不直接写入。",
            add_help=False,
        )
    )
    migrate_terms.add_argument("--source-project-id", type=int, required=True, help="旧 ParaTranz 项目 ID。")
    migrate_terms.add_argument("--target-project-id", type=int, help="新 ParaTranz 项目 ID；未传时默认使用 .env 里的 PARATRANZ_PROJECT_ID。")
    migrate_terms.add_argument("--execute", action="store_true", help="真正执行术语导入；未传时仅预览迁移计划。")
    migrate_terms.add_argument("--progress", action="store_true", help="显示术语读取和导入进度。")
    migrate_terms.set_defaults(func=cmd_migrate_terms)

    package_final = _with_chinese_help(
        subparsers.add_parser(
            "最终打包",
            aliases=["package-final"],
            help="把 MainGame/DLCGame 合并为运行时 localization 目录，并生成发布 zip。",
            add_help=False,
        )
    )
    package_final.add_argument("--source-root", help="包含 MainGame/DLCGame 的目录；未传时默认使用 build/migrated。")
    package_final.add_argument("--output-root", help="输出 localization 目录；未传时默认使用 build/package/localization。")
    package_final.add_argument("--zip-path", help="输出 zip 路径；未传时默认使用 build/package/ReaperEmporiumLocalization-localization.zip。")
    package_final.add_argument("--no-zip", action="store_true", help="只生成 localization 目录，不生成 zip。")
    package_final.add_argument("--progress", action="store_true", help="显示打包进度条。")
    package_final.set_defaults(func=cmd_package_final)

    return parser


def main() -> int:
    """程序入口：解析命令行并分发到对应处理函数。"""
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
