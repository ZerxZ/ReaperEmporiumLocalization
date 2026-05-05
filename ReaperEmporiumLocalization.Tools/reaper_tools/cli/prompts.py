from __future__ import annotations

import collections
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

import click

from reaper_tools.cli.registry import COMMAND_METADATA_BY_NAME


def _load_inquirer():
    """懒加载 python-inquirer，并补齐它在 Python 3.11 下缺失的旧 collections 名称。"""
    compatibility_exports = {
        "Mapping": Mapping,
        "MutableMapping": MutableMapping,
        "Sequence": Sequence,
    }
    for name, value in compatibility_exports.items():
        if not hasattr(collections, name):
            setattr(collections, name, value)

    import python_inquirer as inquirer

    return inquirer


def choose_main_command(command_names: list[str]) -> str | None:
    """在无参数交互模式下，让用户先选一个顶层命令。"""
    inquirer = _load_inquirer()
    answers = inquirer.prompt(
        [
            {
                "type": "list",
                "name": "command",
                "message": "请选择要执行的命令：",
                "choices": command_names,
            }
        ]
    )
    if not answers:
        return None
    selected = answers.get("command")
    return str(selected).strip() or None


def prompt_required_command_kwargs(command_name: str) -> dict[str, Any]:
    """只为带必填参数的命令补最少输入。"""
    metadata = COMMAND_METADATA_BY_NAME.get(command_name)
    if metadata is None:
        return {}

    kwargs: dict[str, Any] = {}
    for prompt in metadata.prompts:
        if prompt.kind == "int":
            kwargs[prompt.kwarg] = _prompt_int(prompt.message)
            continue
        raise click.ClickException(f"不支持的交互提示类型：{prompt.kind}")
    return kwargs


def confirm_remote_write(action_name: str, detail: str) -> bool:
    """在交互式终端里确认远端写入。"""
    inquirer = _load_inquirer()
    answers = inquirer.prompt(
        [
            {
                "type": "confirm",
                "name": "confirmed",
                "message": f"即将执行 {action_name}，{detail}。是否继续？",
                "default": False,
            }
        ]
    )
    if not answers:
        return False
    return bool(answers.get("confirmed"))


def _prompt_int(message: str) -> int:
    """循环读取整数输入，直到拿到合法值或用户取消。"""
    while True:
        inquirer = _load_inquirer()
        answers = inquirer.prompt(
            [
                {
                    "type": "input",
                    "name": "value",
                    "message": message,
                }
            ]
        )
        if not answers:
            raise click.Abort()
        raw = str(answers.get("value") or "").strip()
        if raw.isdecimal():
            return int(raw)
        click.echo("请输入有效的数字。")
