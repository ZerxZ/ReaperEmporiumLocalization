from __future__ import annotations

from pathlib import Path

import click

from reaper_tools.cli.common import HELP_OPTION_NAMES, LocalizedCommand, get_command_app_context, with_aliases
from reaper_tools.cli.registry import BUILD_DUMP_COMMAND, MIGRATE_TRANSLATIONS_COMMAND, PACKAGE_FINAL_COMMAND
from reaper_tools.localization.dump_builder import build_dump_diff
from reaper_tools.localization.installer import package_final_localization
from reaper_tools.localization.paratranz import Paratranz


@with_aliases(*BUILD_DUMP_COMMAND.aliases)
@click.command(
    BUILD_DUMP_COMMAND.name,
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help=BUILD_DUMP_COMMAND.help,
    short_help=BUILD_DUMP_COMMAND.short_help,
)
@click.option("--progress", is_flag=True, help="显示构建进度条。")
def build_dump_command(progress: bool) -> int:
    """从游戏转储数据构建可上传到 ParaTranz 的 MainGame/DLCGame 输出。"""
    context = get_command_app_context()
    stats = build_dump_diff(show_progress=progress, context=context)
    context.logger.success(
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


@with_aliases(*MIGRATE_TRANSLATIONS_COMMAND.aliases)
@click.command(
    MIGRATE_TRANSLATIONS_COMMAND.name,
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help=MIGRATE_TRANSLATIONS_COMMAND.help,
    short_help=MIGRATE_TRANSLATIONS_COMMAND.short_help,
)
@click.option("--source-root", type=click.Path(path_type=Path), help="旧 ParaTranz 本地导出目录；未传时默认使用 data/paratranz。")
@click.option("--dump-root", type=click.Path(path_type=Path), help="新提取的 build/dump 目录；未传时默认使用 build/dump。")
@click.option("--output-root", type=click.Path(path_type=Path), help="迁移结果输出目录；未传时默认使用 build/migrated。")
@click.option("--source-project-id", type=int, help="旧 ParaTranz 项目 ID；只读文件和译文，不会写入远端。")
@click.option("--dry-run", is_flag=True, help="只生成迁移统计，不写入 build/migrated。")
@click.option("--progress", is_flag=True, help="显示迁移进度条。")
def migrate_translations_command(
    source_root: Path | None,
    dump_root: Path | None,
    output_root: Path | None,
    source_project_id: int | None,
    dry_run: bool,
    progress: bool,
) -> int:
    """把旧 ParaTranz 译文迁移到当前 build/dump 新结构。"""
    context = get_command_app_context()
    result = Paratranz(context=context).migrate_legacy_translations_to_dump(
        source_root=source_root,
        dump_root=dump_root,
        output_root=output_root,
        source_project_id=source_project_id,
        dry_run=dry_run,
        show_progress=progress,
    )
    report = getattr(result, "report", {})
    context.logger.success(
        "{}旧译文迁移：{} 个文件，迁移 {} 条译文，未匹配 {} 条，重复逻辑文件 {} 组，冲突 {} 处。结果目录：{}",
        "[dry-run] " if dry_run else "",
        result.planned,
        result.migrated_entries,
        result.skipped,
        len(report.get("duplicate_files", [])),
        len(report.get("conflicts", [])),
        report.get("output_root", output_root or "build/migrated"),
    )
    if not dry_run:
        context.logger.info("迁移命令只生成本地文件，不会自动上传；请检查 build/migrated 后再决定是否上传到 ParaTranz。")
    return 0


@with_aliases(*PACKAGE_FINAL_COMMAND.aliases)
@click.command(
    PACKAGE_FINAL_COMMAND.name,
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help=PACKAGE_FINAL_COMMAND.help,
    short_help=PACKAGE_FINAL_COMMAND.short_help,
)
@click.option("--source-root", type=click.Path(path_type=Path), help="包含 MainGame/DLCGame 的目录；未传时默认使用 build/migrated。")
@click.option("--output-root", type=click.Path(path_type=Path), help="输出 localization 目录；未传时默认使用 build/package/localization。")
@click.option(
    "--zip-path",
    type=click.Path(path_type=Path),
    help="输出 zip 路径；未传时默认使用 build/package/ReaperEmporiumLocalization-localization.zip。",
)
@click.option("--no-zip", is_flag=True, help="只生成 localization 目录，不生成 zip。")
@click.option("--progress", is_flag=True, help="显示打包进度条。")
def package_final_command(
    source_root: Path | None,
    output_root: Path | None,
    zip_path: Path | None,
    no_zip: bool,
    progress: bool,
) -> int:
    """把 MainGame/DLCGame 合并为游戏运行时 localization 包。"""
    context = get_command_app_context()
    stats = package_final_localization(
        source_root=source_root,
        output_root=output_root,
        zip_path=zip_path,
        create_zip=not no_zip,
        show_progress=progress,
        context=context,
    )
    context.logger.success(
        "已生成最终本地化包：{} 个数据库文件，{} 条数据库词条，{} 条 DLL 词条，{} 个输出 JSON{}",
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
        stats.written_files,
        f"，zip：{stats.zip_path}" if stats.zip_path else "",
    )
    return 0


