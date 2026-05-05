from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from click.testing import CliRunner

import main as root_main
from reaper_tools.cli.commands import ALL_COMMANDS
from reaper_tools.cli.main import cli, main as cli_main
from reaper_tools.cli.registry import COMMAND_METADATA, DOWNLOAD_COMMAND


class CliRegressionTests(unittest.TestCase):
    def test_command_registry_matches_metadata_order_and_aliases(self) -> None:
        self.assertEqual(len(ALL_COMMANDS), len(COMMAND_METADATA))
        self.assertEqual([spec.metadata for spec in ALL_COMMANDS], list(COMMAND_METADATA))
        self.assertEqual([spec.command.name for spec in ALL_COMMANDS], [item.name for item in COMMAND_METADATA])
        self.assertEqual(
            [tuple(getattr(spec.command, "aliases", ())) for spec in ALL_COMMANDS],
            [item.aliases for item in COMMAND_METADATA],
        )

    def test_cli_main_and_root_main_forward_help(self) -> None:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli_main(["--help"]), 0)
            self.assertEqual(root_main.main(["--help"]), 0)

    def test_group_resolves_canonical_name_and_english_alias(self) -> None:
        runner = CliRunner()

        canonical = runner.invoke(cli, [DOWNLOAD_COMMAND.name, "--help"])
        alias = runner.invoke(cli, [DOWNLOAD_COMMAND.aliases[0], "--help"])

        self.assertEqual(canonical.exit_code, 0, canonical.output)
        self.assertEqual(alias.exit_code, 0, alias.output)


if __name__ == "__main__":
    unittest.main()
