from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PromptSpec:
    """Prompt metadata for interactive command entry."""

    kwarg: str
    kind: str
    message: str


@dataclass(frozen=True, slots=True)
class CommandMetadata:
    """Single source of truth for a CLI command's user-facing metadata."""

    key: str
    name: str
    aliases: tuple[str, ...]
    help: str
    short_help: str
    show_in_menu: bool = True
    prompts: tuple[PromptSpec, ...] = field(default_factory=tuple)


DOWNLOAD_COMMAND = CommandMetadata(
    key="download",
    name="下载包",
    aliases=("download",),
    help="下载并解压最新 ParaTranz 导出包。",
    short_help="下载并解压最新 ParaTranz 导出包。",
)

INSTALL_COMMAND = CommandMetadata(
    key="install",
    name="安装包",
    aliases=("install",),
    help="将本地翻译 JSON 包安装到游戏目录。",
    short_help="将本地翻译 JSON 包安装到游戏目录。",
)

PULL_COMMAND = CommandMetadata(
    key="pull",
    name="拉取安装",
    aliases=("pull",),
    help="下载 ParaTranz 导出包，并安装到游戏目录。",
    short_help="下载 ParaTranz 导出包，并安装到游戏目录。",
)

STATS_COMMAND = CommandMetadata(
    key="stats",
    name="查看统计",
    aliases=("stats",),
    help="统计本地翻译包中的 JSON 词条数量。",
    short_help="统计本地翻译包中的 JSON 词条数量。",
)

BUILD_DUMP_COMMAND = CommandMetadata(
    key="build_dump",
    name="构建差异",
    aliases=("build-dump",),
    help="构建 MainGame/DLCGame 转储输出，并把 DLCGame 缩减为相对 MainGame 的差异词条。",
    short_help="构建 MainGame/DLCGame 差异转储。",
)

COMPARE_PARATRANZ_COMMAND = CommandMetadata(
    key="compare_paratranz",
    name="下载对比",
    aliases=("compare-paratranz",),
    help="下载最新 ParaTranz 导出包，并与本地 MainGame 或 DLCGame 标准包结构做双向对比。",
    short_help="下载 ParaTranz 并对比本体或 DLC。",
)

UPLOAD_COMPARE_CHANGES_COMMAND = CommandMetadata(
    key="upload_compare_changes",
    name="上传对比变化",
    aliases=("upload-compare-changes",),
    help="把 compare-paratranz 产出的 source_changed / entry_changed 词条逐条上传到 ParaTranz；默认只预览。",
    short_help="上传对比中的原文类变化。",
)

MIGRATE_TRANSLATIONS_COMMAND = CommandMetadata(
    key="migrate_translations",
    name="迁移翻译",
    aliases=("migrate-translations",),
    help="把旧 ParaTranz 译文迁移到当前 build/dump 新结构，只生成本地 build/migrated。",
    short_help="迁移旧 ParaTranz 译文到 build/migrated。",
)

MIGRATE_TERMS_COMMAND = CommandMetadata(
    key="migrate_terms",
    name="迁移术语",
    aliases=("migrate-terms",),
    help="把旧 ParaTranz 项目的术语迁移到新 ParaTranz 项目，默认只预览，不直接写入。",
    short_help="迁移旧 ParaTranz 项目术语。",
    prompts=(PromptSpec(kwarg="source_project_id", kind="int", message="请输入旧 ParaTranz 项目 ID："),),
)

UPLOAD_TRANSLATIONS_COMMAND = CommandMetadata(
    key="upload_translations",
    name="上传翻译",
    aliases=("upload-translations",),
    help="把 build/migrated 上传到目标 ParaTranz 项目，并把冲突候选逐次写入文件修订历史后再恢复最终译文。",
    short_help="上传 build/migrated 到目标 ParaTranz 项目。",
)

PACKAGE_FINAL_COMMAND = CommandMetadata(
    key="package_final",
    name="最终打包",
    aliases=("package-final",),
    help="把 MainGame/DLCGame 合并为运行时 localization 目录，并生成发布 zip。",
    short_help="合并 MainGame/DLCGame 并生成最终包。",
)


COMMAND_METADATA = (
    DOWNLOAD_COMMAND,
    INSTALL_COMMAND,
    PULL_COMMAND,
    STATS_COMMAND,
    BUILD_DUMP_COMMAND,
    COMPARE_PARATRANZ_COMMAND,
    UPLOAD_COMPARE_CHANGES_COMMAND,
    MIGRATE_TRANSLATIONS_COMMAND,
    MIGRATE_TERMS_COMMAND,
    UPLOAD_TRANSLATIONS_COMMAND,
    PACKAGE_FINAL_COMMAND,
)

COMMAND_METADATA_BY_NAME = {item.name: item for item in COMMAND_METADATA}
COMMAND_METADATA_BY_KEY = {item.key: item for item in COMMAND_METADATA}
MENU_COMMAND_NAMES = [item.name for item in COMMAND_METADATA if item.show_in_menu]


__all__ = [
    "BUILD_DUMP_COMMAND",
    "COMMAND_METADATA",
    "COMMAND_METADATA_BY_KEY",
    "COMMAND_METADATA_BY_NAME",
    "COMPARE_PARATRANZ_COMMAND",
    "CommandMetadata",
    "DOWNLOAD_COMMAND",
    "INSTALL_COMMAND",
    "MENU_COMMAND_NAMES",
    "MIGRATE_TERMS_COMMAND",
    "MIGRATE_TRANSLATIONS_COMMAND",
    "PACKAGE_FINAL_COMMAND",
    "PULL_COMMAND",
    "PromptSpec",
    "STATS_COMMAND",
    "UPLOAD_TRANSLATIONS_COMMAND",
    "UPLOAD_COMPARE_CHANGES_COMMAND",
]
