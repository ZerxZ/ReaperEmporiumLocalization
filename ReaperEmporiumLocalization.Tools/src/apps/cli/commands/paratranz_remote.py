from __future__ import annotations

from pathlib import Path

import click

from src.apps.cli.common import HELP_OPTION_NAMES, LocalizedCommand, is_interactive_tty, with_aliases
from src.apps.cli.prompts import confirm_remote_write
from src.config import logger
from src.localization.paratranz import Paratranz


def _confirm_execute_if_needed(action_name: str, detail: str, execute: bool) -> None:
    """对关键远端写入操作做交互确认。"""
    if not execute or not is_interactive_tty():
        return
    if not confirm_remote_write(action_name, detail):
        raise click.Abort()


@with_aliases("migrate-terms")
@click.command(
    "迁移术语",
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help="把旧 ParaTranz 项目的术语迁移到新 ParaTranz 项目；默认只预览，不直接写入。",
    short_help="迁移旧 ParaTranz 项目术语。",
)
@click.option("--source-project-id", type=int, required=True, help="旧 ParaTranz 项目 ID。")
@click.option("--target-project-id", type=int, help="新 ParaTranz 项目 ID；未传时默认使用 .env 里的 PARATRANZ_PROJECT_ID。")
@click.option("--execute", is_flag=True, help="真正执行术语导入；未传时仅预览迁移计划。")
@click.option("--progress", is_flag=True, help="显示术语读取和导入进度。")
def migrate_terms_command(
    source_project_id: int,
    target_project_id: int | None,
    execute: bool,
    progress: bool,
) -> int:
    """把旧 ParaTranz 项目的术语迁移到新项目。"""
    api = Paratranz()
    resolved_target_project_id = target_project_id or api.project_id
    _confirm_execute_if_needed(
        "迁移术语",
        f"源项目 {source_project_id} -> 目标项目 {resolved_target_project_id}",
        execute,
    )
    result = api.migrate_terms_to_project(
        source_project_id=source_project_id,
        target_project_id=target_project_id,
        dry_run=not execute,
        show_progress=progress,
    )
    logger.success(
        "{}项目术语迁移：源项目 {} -> 目标项目 {}，共 {} 页，{} 条术语{}",
        "[dry-run] " if not execute else "",
        source_project_id,
        resolved_target_project_id,
        result.planned,
        sum(len(action.metadata.get("terms", [])) for action in result.actions),
        f"，成功迁移 {result.migrated_entries} 条" if execute else "",
    )
    if result.errors:
        logger.warning("术语迁移过程中有 {} 个失败页：{}", len(result.errors), " | ".join(result.errors))
    if not execute:
        logger.info("默认只预览计划；确认无误后加 --execute 才会写入目标 ParaTranz 项目。")
    return 0


@with_aliases("upload-translations")
@click.command(
    "上传翻译",
    cls=LocalizedCommand,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help="把 build/migrated 上传到目标 ParaTranz 项目，并把冲突候选逐次写入文件修订历史后再恢复最终译文。",
    short_help="上传 build/migrated 到目标 ParaTranz 项目。",
)
@click.option("--source-root", type=click.Path(path_type=Path), help="待上传的迁移结果目录；未传时默认使用 build/migrated。")
@click.option("--report-path", type=click.Path(path_type=Path), help="迁移报告路径；未传时默认使用 build/migrated/migration_report.json。")
@click.option("--project-id", type=int, help="目标 ParaTranz 项目 ID；未传时默认使用 .env 里的 PARATRANZ_PROJECT_ID。")
@click.option("--execute", is_flag=True, help="真正执行上传；未传时仅预览上传计划。")
@click.option("--progress", is_flag=True, help="显示文件上传、冲突记录和最终回写进度。")
def upload_translations_command(
    source_root: Path | None,
    report_path: Path | None,
    project_id: int | None,
    execute: bool,
    progress: bool,
) -> int:
    """把人工检查后的迁移结果上传到新 ParaTranz 项目。"""
    api = Paratranz()
    resolved_project_id = project_id or api.project_id
    _confirm_execute_if_needed(
        "上传翻译",
        f"目标项目 {resolved_project_id}",
        execute,
    )
    result = api.upload_migrated_translations(
        source_root=source_root,
        report_path=report_path,
        project_id=project_id,
        dry_run=not execute,
        show_progress=progress,
    )
    logger.success(
        "{}上传翻译：目标项目 {}，首轮文件 {} / {} / {} / {}（计划 / 成功 / 失败 / 跳过），"
        "冲突记录 {} / {} / {} / {}（计划 / 成功 / 失败 / 跳过），"
        "最终回写 {} / {} / {}（计划 / 成功 / 失败）。",
        "[dry-run] " if not execute else "",
        resolved_project_id,
        result.file_planned,
        result.file_succeeded,
        result.file_failed,
        result.file_skipped,
        result.conflict_planned,
        result.conflict_recorded,
        result.conflict_failed,
        result.conflict_skipped,
        result.finalize_planned,
        result.finalize_succeeded,
        result.finalize_failed,
    )
    if result.errors:
        logger.warning("上传过程中有 {} 条提示或失败记录：{}", len(result.errors), " | ".join(result.errors))
    if not execute:
        logger.info("默认只预览计划；确认无误后加 --execute 才会真正写入目标 ParaTranz 项目。")
    return 0
