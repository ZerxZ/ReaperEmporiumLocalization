"""CLI 命令集合。"""

from src.apps.cli.commands.dump_workflow import build_dump_command, migrate_translations_command, package_final_command
from src.apps.cli.commands.local_packages import download_command, install_command, pull_command, stats_command
from src.apps.cli.commands.paratranz_remote import migrate_terms_command, upload_translations_command

ALL_COMMANDS = [
    download_command,
    install_command,
    pull_command,
    stats_command,
    build_dump_command,
    migrate_translations_command,
    migrate_terms_command,
    upload_translations_command,
    package_final_command,
]

__all__ = ["ALL_COMMANDS"]
