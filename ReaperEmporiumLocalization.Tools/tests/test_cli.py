from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

import main as root_main
from reaper_tools.cli.commands import ALL_COMMANDS
from reaper_tools.cli.main import cli, main as cli_main
from reaper_tools.cli.registry import COMMAND_METADATA, COMPARE_PARATRANZ_COMMAND, DOWNLOAD_COMMAND, UPLOAD_COMPARE_CHANGES_COMMAND


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

    def test_compare_command_requires_scope(self) -> None:
        runner = CliRunner()

        result = runner.invoke(cli, [COMPARE_PARATRANZ_COMMAND.aliases[0]])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--scope", result.output)

    def test_compare_command_forwards_custom_paths(self) -> None:
        runner = CliRunner()
        fake_result = SimpleNamespace(
            scope_dir="MainGame",
            summary=SimpleNamespace(
                scanned_files=4,
                remote_only_files=1,
                remote_only_entries=3,
                local_only_files=1,
                local_only_entries=3,
                source_changed_entries=2,
                translation_changed_entries=2,
                entry_changed_entries=2,
            ),
            report_path=Path("build/compare_paratranz/MainGame/report.json"),
        )

        with patch("reaper_tools.cli.commands.dump_workflow.download_and_compare_paratranz", return_value=fake_result) as mock_compare:
            result = runner.invoke(
                cli,
                [COMPARE_PARATRANZ_COMMAND.aliases[0], "--scope", "main", "--local-root", "custom", "--output-root", "out"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        mock_compare.assert_called_once()
        self.assertEqual(mock_compare.call_args.kwargs["scope"], "main")
        self.assertEqual(mock_compare.call_args.kwargs["local_root"], Path("custom"))
        self.assertEqual(mock_compare.call_args.kwargs["output_root"], Path("out"))

    def test_upload_compare_changes_command_forwards_custom_paths(self) -> None:
        runner = CliRunner()
        fake_result = SimpleNamespace(
            scope_dir="DLCGame",
            compare_root=Path("build/compare_paratranz/DLCGame"),
            report_path=Path("build/compare_paratranz/DLCGame/report.json"),
            errors=[],
            summary=SimpleNamespace(
                scanned_files=2,
                source_changed_entries=1,
                entry_changed_entries=1,
                translation_changed_entries=0,
                new_entries=0,
                planned_entries=2,
                succeeded_entries=0,
                failed_entries=0,
                skipped_entries=0,
            ),
        )
        fake_api = SimpleNamespace(project_id=123)

        with (
            patch("reaper_tools.cli.commands.paratranz_remote.Paratranz", return_value=fake_api),
            patch("reaper_tools.cli.commands.paratranz_remote.upload_compare_source_changes", return_value=fake_result) as mock_upload,
        ):
            result = runner.invoke(
                cli,
                [UPLOAD_COMPARE_CHANGES_COMMAND.aliases[0], "--scope", "dlc", "--compare-root", "compare-out"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        mock_upload.assert_called_once()
        self.assertEqual(mock_upload.call_args.kwargs["scope"], "dlc")
        self.assertEqual(mock_upload.call_args.kwargs["compare_root"], Path("compare-out"))
        self.assertTrue(mock_upload.call_args.kwargs["dry_run"])


if __name__ == "__main__":
    unittest.main()
