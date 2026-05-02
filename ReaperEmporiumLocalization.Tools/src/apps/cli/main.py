from __future__ import annotations

from collections.abc import Sequence

import click

from src.apps.cli.commands import ALL_COMMANDS
from src.apps.cli.common import AliasedLocalizedGroup, HELP_OPTION_NAMES, is_interactive_tty, register_commands
from src.apps.cli.prompts import choose_main_command, prompt_required_command_kwargs

MENU_COMMANDS = [
    "下载包",
    "安装包",
    "拉取安装",
    "查看统计",
    "构建差异",
    "迁移翻译",
    "迁移术语",
    "上传翻译",
    "最终打包",
]


@click.group(
    cls=AliasedLocalizedGroup,
    invoke_without_command=True,
    context_settings={"help_option_names": HELP_OPTION_NAMES},
    help="死神商馆汉化辅助工具。",
)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """根命令组：无参数时进入交互菜单，否则按脚本模式执行。"""
    ctx.ensure_object(dict)
    ctx.obj["interactive"] = is_interactive_tty()

    if ctx.invoked_subcommand is not None:
        return
    if ctx.obj["interactive"]:
        _run_interactive_menu(ctx)
        return
    click.echo(ctx.get_help())


def _run_interactive_menu(ctx: click.Context) -> None:
    """在交互式终端里弹出中文主菜单。"""
    selected = choose_main_command(MENU_COMMANDS)
    if selected is None:
        click.echo("已取消。")
        return

    command = ctx.command.get_command(ctx, selected)
    if command is None:
        raise click.ClickException(f"未找到命令：{selected}")

    kwargs = prompt_required_command_kwargs(selected)
    ctx.invoke(command, **kwargs)


register_commands(cli, ALL_COMMANDS)


def main(argv: Sequence[str] | None = None) -> int:
    """供 `reaper-tools` 和根目录 `main.py` 共同复用的入口函数。"""
    try:
        cli.main(args=list(argv) if argv is not None else None, standalone_mode=False)
        return 0
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.Abort:
        click.echo("已取消。", err=True)
        return 1
