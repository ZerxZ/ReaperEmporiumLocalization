"""CLI command exports and registration specs."""

from reaper_tools.cli.commands.dump_workflow import (
    build_dump_command,
    compare_paratranz_command,
    migrate_translations_command,
    package_final_command,
)
from reaper_tools.cli.commands.local_packages import download_command, install_command, pull_command, stats_command
from reaper_tools.cli.commands.paratranz_remote import (
    delete_filtered_files_command,
    migrate_terms_command,
    upload_compare_changes_command,
    upload_translations_command,
)
from reaper_tools.cli.common import RegisteredCommand
from reaper_tools.cli.registry import (
    BUILD_DUMP_COMMAND,
    COMPARE_PARATRANZ_COMMAND,
    DELETE_FILTERED_FILES_COMMAND,
    DOWNLOAD_COMMAND,
    INSTALL_COMMAND,
    MIGRATE_TERMS_COMMAND,
    MIGRATE_TRANSLATIONS_COMMAND,
    PACKAGE_FINAL_COMMAND,
    PULL_COMMAND,
    STATS_COMMAND,
    UPLOAD_COMPARE_CHANGES_COMMAND,
    UPLOAD_TRANSLATIONS_COMMAND,
)

ALL_COMMANDS = [
    RegisteredCommand(DOWNLOAD_COMMAND, download_command),
    RegisteredCommand(INSTALL_COMMAND, install_command),
    RegisteredCommand(PULL_COMMAND, pull_command),
    RegisteredCommand(STATS_COMMAND, stats_command),
    RegisteredCommand(BUILD_DUMP_COMMAND, build_dump_command),
    RegisteredCommand(COMPARE_PARATRANZ_COMMAND, compare_paratranz_command),
    RegisteredCommand(UPLOAD_COMPARE_CHANGES_COMMAND, upload_compare_changes_command),
    RegisteredCommand(DELETE_FILTERED_FILES_COMMAND, delete_filtered_files_command),
    RegisteredCommand(MIGRATE_TRANSLATIONS_COMMAND, migrate_translations_command),
    RegisteredCommand(MIGRATE_TERMS_COMMAND, migrate_terms_command),
    RegisteredCommand(UPLOAD_TRANSLATIONS_COMMAND, upload_translations_command),
    RegisteredCommand(PACKAGE_FINAL_COMMAND, package_final_command),
]

__all__ = ["ALL_COMMANDS"]
