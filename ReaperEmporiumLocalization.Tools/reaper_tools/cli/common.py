from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass

import click

from reaper_tools.app_context import AppContext, get_app_context

HELP_OPTION_NAMES = ["-h", "--help"]


@dataclass(frozen=True, slots=True)
class RegisteredCommand:
    """Command object paired with its user-facing metadata."""

    metadata: object
    command: click.Command


def is_interactive_tty() -> bool:
    """Return whether the current session should show interactive prompts."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _localize_help_text(text: str) -> str:
    """Translate Click's stock headings into Chinese."""
    return (
        text.replace("Usage:", "用法:")
        .replace("Options:", "选项:")
        .replace("Commands:", "命令:")
        .replace("Show this message and exit.", "显示帮助信息并退出。")
    )


class LocalizedCommand(click.Command):
    """Click command with Chinese help text."""

    def get_help(self, ctx: click.Context) -> str:
        return _localize_help_text(super().get_help(ctx))

    def get_help_option(self, ctx: click.Context) -> click.Option | None:
        option = super().get_help_option(ctx)
        if option is not None:
            option.help = "显示帮助信息并退出。"
        return option

    def format_options(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        records = [record for param in self.get_params(ctx) if (record := param.get_help_record(ctx)) is not None]
        if records:
            with formatter.section("选项"):
                formatter.write_dl(records)


class AliasedLocalizedGroup(click.Group, LocalizedCommand):
    """Chinese Click group that also resolves English aliases."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._aliases: dict[str, str] = {}

    def add_command(self, cmd: click.Command, name: str | None = None, aliases: Iterable[str] | None = None) -> None:
        super().add_command(cmd, name=name)
        canonical_name = name or cmd.name
        for alias in aliases or ():
            self._aliases[alias] = canonical_name

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        return super().get_command(ctx, self._aliases.get(cmd_name, cmd_name))

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        rows: list[tuple[str, str]] = []
        for name in self.list_commands(ctx):
            command = super().get_command(ctx, name)
            if command is None or command.hidden:
                continue
            aliases = getattr(command, "aliases", ())
            label = f"{name} ({', '.join(aliases)})" if aliases else name
            rows.append((label, command.get_short_help_str()))
        if rows:
            with formatter.section("命令"):
                formatter.write_dl(rows)


def with_aliases(*aliases: str):
    """Attach alias metadata to a Click command."""

    def decorator(command: click.Command) -> click.Command:
        command.aliases = tuple(aliases)
        return command

    return decorator


def register_commands(group: AliasedLocalizedGroup, commands: Iterable[RegisteredCommand]) -> None:
    """Register command specs on the root group."""
    for spec in commands:
        group.add_command(spec.command, aliases=getattr(spec.metadata, "aliases", ()))


def get_command_app_context() -> AppContext:
    """Return the AppContext prepared by the CLI root group."""
    ctx = click.get_current_context()
    root = ctx.find_root()
    obj = root.ensure_object(dict)
    return obj.setdefault("app_context", get_app_context())
