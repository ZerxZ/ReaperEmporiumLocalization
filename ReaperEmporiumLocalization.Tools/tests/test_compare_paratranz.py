from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from reaper_tools.app_context import build_app_context
from reaper_tools.localization.compare_paratranz import (
    compare_downloaded_paratranz_scope,
    download_and_compare_paratranz,
    upload_compare_source_changes,
)
from reaper_tools.models import Page, ParatranzFile, ParatranzString


class CompareParatranzTests(unittest.TestCase):
    def test_compare_downloaded_paratranz_scope_writes_report_and_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote_root = root / "remote"
            local_root = root / "local"
            output_root = root / "out"

            self._write_entries(
                remote_root / "MainGame" / "database" / "db_Test.json",
                [
                    self._entry("0", "Same", "same", 1),
                    self._entry("1", "Old source", "keep", 1),
                    self._entry("2", "Trans only", "old translation", 1),
                    self._entry("3", "Remote only", "", 0),
                    self._entry("4", "Hero entered shop.", "", 0),
                ],
            )
            self._write_entries(
                local_root / "MainGame" / "database" / "db_Test.json",
                [
                    self._entry("100", "Same", "same", 1),
                    self._entry("101", "Old sources", "keep", 1),
                    self._entry("102", "Trans only", "new translation", 1),
                    self._entry("103", "Brand New", "fresh", 1),
                    self._entry("104", "Hero entered shops.", "译文", 1),
                ],
            )
            self._write_entries(
                remote_root / "MainGame" / "database" / "remote_only_file.json",
                [self._entry("0", "Remote file entry", "", 0)],
            )
            self._write_entries(
                local_root / "MainGame" / "database" / "local_only_file.json",
                [self._entry("0", "Local file entry", "", 0)],
            )
            self._write_entries(
                remote_root / "MainGame" / "dll_strings.json",
                [
                    self._entry("Game.Type.Run_0", "Run", "运行", 1),
                    self._entry("Game.Type.Talk_0", "Talk", "旧对话", 1),
                    self._entry("Game.Type.Source_0", "Old source", "保持", 1),
                    self._entry("Game.Type.Entry_0", "Hero arrived", "旧译文", 1),
                    self._entry("Game.Type.RemoteOnly_0", "Missing", "", 0),
                ],
            )
            self._write_entries(
                local_root / "MainGame" / "dll_strings.json",
                [
                    self._entry("Game.Type.Run_0", "Run", "运行", 1),
                    self._entry("Game.Type.Talk_0", "Talk", "新对话", 1),
                    self._entry("Game.Type.Source_0", "Old sources", "保持", 1),
                    self._entry("Game.Type.Entry_0", "Hero arrives", "新译文", 1),
                    self._entry("Game.Type.LocalOnly_0", "Added", "", 0),
                ],
            )

            context = build_app_context(project_paths=_FakePaths(root), app_logger=Mock())
            result = compare_downloaded_paratranz_scope(
                remote_root=remote_root,
                scope="main",
                local_root=local_root,
                output_root=output_root,
                context=context,
            )
            report_payload = json.loads(result.report_path.read_text(encoding="utf-8"))
            file_reports = {item["relative_path"]: item for item in report_payload["files"]}
            db_diff_text = (output_root / "MainGame" / "diff" / "database" / "db_Test.json.diff").read_text(encoding="utf-8")
            db_source_entries = self._read_entries(output_root / "MainGame" / "delta" / "source_updates" / "database" / "db_Test.json")
            db_translation_entries = self._read_entries(output_root / "MainGame" / "delta" / "translation_updates" / "database" / "db_Test.json")
            db_entry_entries = self._read_entries(output_root / "MainGame" / "delta" / "entry_updates" / "database" / "db_Test.json")
            db_new_entries = self._read_entries(output_root / "MainGame" / "delta" / "new_entries" / "database" / "db_Test.json")
            db_remote_review_entries_for_changed_file = self._read_entries(output_root / "MainGame" / "review" / "remote_only" / "database" / "db_Test.json")
            db_new_file_entries = self._read_entries(output_root / "MainGame" / "delta" / "new_entries" / "database" / "local_only_file.json")
            db_remote_review_entries = self._read_entries(output_root / "MainGame" / "review" / "remote_only" / "database" / "remote_only_file.json")
            dll_source_entries = self._read_entries(output_root / "MainGame" / "delta" / "source_updates" / "dll_strings.json")
            dll_translation_entries = self._read_entries(output_root / "MainGame" / "delta" / "translation_updates" / "dll_strings.json")
            dll_entry_entries = self._read_entries(output_root / "MainGame" / "delta" / "entry_updates" / "dll_strings.json")
            dll_new_entries = self._read_entries(output_root / "MainGame" / "delta" / "new_entries" / "dll_strings.json")
            dll_remote_review_entries = self._read_entries(output_root / "MainGame" / "review" / "remote_only" / "dll_strings.json")

        self.assertEqual(result.scope_dir, "MainGame")
        self.assertEqual(report_payload["report_version"], 2)
        self.assertEqual(report_payload["local_mode"], "translation_package")
        self.assertEqual(report_payload["summary"]["scanned_files"], 4)
        self.assertEqual(report_payload["summary"]["remote_only_files"], 1)
        self.assertEqual(report_payload["summary"]["local_only_files"], 1)
        self.assertEqual(report_payload["summary"]["remote_only_entries"], 3)
        self.assertEqual(report_payload["summary"]["local_only_entries"], 3)
        self.assertEqual(report_payload["summary"]["source_changed_entries"], 2)
        self.assertEqual(report_payload["summary"]["translation_changed_entries"], 2)
        self.assertEqual(report_payload["summary"]["entry_changed_entries"], 2)

        self.assertEqual(file_reports["database/db_Test.json"]["remote_only"], 1)
        self.assertEqual(file_reports["database/db_Test.json"]["local_only"], 1)
        self.assertEqual(file_reports["database/db_Test.json"]["source_changed"], 1)
        self.assertEqual(file_reports["database/db_Test.json"]["translation_changed"], 1)
        self.assertEqual(file_reports["database/db_Test.json"]["entry_changed"], 1)
        self.assertEqual(set(file_reports["database/db_Test.json"]["delta_paths"]), {"source_updates", "translation_updates", "entry_updates", "new_entries"})
        self.assertEqual(set(file_reports["database/db_Test.json"]["review_paths"]), {"remote_only"})
        self.assertEqual([entry["key"] for entry in db_source_entries], ["1"])
        self.assertEqual([entry["key"] for entry in db_translation_entries], ["2"])
        self.assertEqual([entry["key"] for entry in db_entry_entries], ["4"])
        self.assertEqual(db_source_entries[0]["translation"], "keep")
        self.assertEqual(db_source_entries[0]["stage"], 0)
        self.assertEqual(db_entry_entries[0]["translation"], "")
        self.assertEqual(db_entry_entries[0]["stage"], 0)
        self.assertEqual([entry["key"] for entry in db_new_entries], ["5"])
        self.assertEqual([entry["key"] for entry in db_remote_review_entries_for_changed_file], ["3"])
        self.assertEqual(file_reports["database/remote_only_file.json"]["only_in"], "remote")
        self.assertEqual(set(file_reports["database/remote_only_file.json"]["review_paths"]), {"remote_only"})
        self.assertIsNone(file_reports["database/remote_only_file.json"]["diff_path"])
        self.assertEqual([entry["key"] for entry in db_remote_review_entries], ["0"])
        self.assertEqual(file_reports["database/local_only_file.json"]["only_in"], "local")
        self.assertEqual(set(file_reports["database/local_only_file.json"]["delta_paths"]), {"new_entries"})
        self.assertIsNone(file_reports["database/local_only_file.json"]["diff_path"])
        self.assertEqual([entry["key"] for entry in db_new_file_entries], ["0"])
        self.assertEqual(file_reports["dll_strings.json"]["remote_only"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["local_only"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["source_changed"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["translation_changed"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["entry_changed"], 1)
        self.assertEqual([entry["key"] for entry in dll_source_entries], ["Game.Type.Source_0"])
        self.assertEqual([entry["key"] for entry in dll_translation_entries], ["Game.Type.Talk_0"])
        self.assertEqual([entry["key"] for entry in dll_entry_entries], ["Game.Type.Entry_0"])
        self.assertEqual(dll_source_entries[0]["translation"], "保持")
        self.assertEqual(dll_source_entries[0]["stage"], 0)
        self.assertTrue(dll_entry_entries[0]["translation"])
        self.assertEqual(dll_entry_entries[0]["stage"], 0)
        self.assertEqual([entry["key"] for entry in dll_new_entries], ["Game.Type.LocalOnly_0"])
        self.assertEqual([entry["key"] for entry in dll_remote_review_entries], ["Game.Type.RemoteOnly_0"])
        self.assertIn("--- ParaTranz/MainGame/database/db_Test.json", db_diff_text)
        self.assertIn("+++ Local/MainGame/database/db_Test.json", db_diff_text)
        self.assertNotIn('-    "translation": "old translation"', db_diff_text)
        self.assertNotIn('+    "translation": "new translation"', db_diff_text)
        self.assertNotIn('"key": "100"', db_diff_text)

    def test_download_and_compare_paratranz_uses_downloaded_root_and_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_api = Mock()
            fake_api.download.return_value = root / "downloaded"
            context = build_app_context(project_paths=_FakePaths(root), app_logger=Mock())

            with patch("reaper_tools.localization.compare_paratranz.compare_downloaded_paratranz_scope", return_value="done") as mock_compare:
                result = download_and_compare_paratranz(
                    scope="dlc",
                    local_root=root / "local",
                    output_root=root / "out",
                    force=True,
                    show_progress=True,
                    context=context,
                    api=fake_api,
                )

        self.assertEqual(result, "done")
        fake_api.download.assert_called_once_with(force=True, show_progress=True)
        self.assertEqual(mock_compare.call_args.kwargs["remote_root"], root / "downloaded")
        self.assertTrue(mock_compare.call_args.kwargs["show_progress"])

    def test_compare_downloaded_paratranz_scope_requires_expected_scope_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote_root = root / "remote"
            local_root = root / "local"
            self._write_entries(remote_root / "MainGame" / "database" / "db_Test.json", [])
            self._write_entries(remote_root / "MainGame" / "dll_strings.json", [])
            context = build_app_context(project_paths=_FakePaths(root), app_logger=Mock())

            with self.assertRaises(FileNotFoundError):
                compare_downloaded_paratranz_scope(
                    remote_root=remote_root,
                    scope="main",
                    local_root=local_root,
                    output_root=root / "out",
                    context=context,
                )

    def test_compare_downloaded_paratranz_scope_supports_legacy_export_and_merged_remote_dlc_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote_root = root / "remote" / "utf8"
            local_root = root / "local"
            output_root = root / "out"

            self._write_entries(
                remote_root / "asset_00_text" / "db_Test-CAB-aaa-1.json",
                [self._entry("0", "Base", "本体译文", 1)],
            )
            self._write_entries(
                remote_root / "asset_00_text_DLC" / "db_Test-CAB-bbb-2.json",
                [self._entry("1", "Shared", "旧DLC译文", 1)],
            )
            self._write_entries(
                remote_root / "DLL" / "test.json",
                [self._entry("Game.Type.Base_0", "BaseDll", "本体DLL", 1)],
            )
            self._write_entries(
                remote_root / "DLL" / "DLC-2.0.05.json",
                [self._entry("Game.Type.Shared_0", "SharedDll", "旧DLC DLL", 1)],
            )
            self._write_entries(
                local_root / "DLCGame" / "database" / "asset_00_text" / "db_Test.json",
                [
                    self._entry("100", "Base", "本体译文", 1),
                    self._entry("101", "Shared", "新DLC译文", 1),
                ],
            )
            self._write_entries(
                local_root / "DLCGame" / "dll_strings.json",
                [
                    self._entry("Game.Type.Base_0", "BaseDll", "本体DLL", 1),
                    self._entry("Game.Type.Shared_0", "SharedDll", "新DLC DLL", 1),
                ],
            )
            context = build_app_context(project_paths=_FakePaths(root), app_logger=Mock())

            result = compare_downloaded_paratranz_scope(
                remote_root=remote_root,
                scope="dlc",
                local_root=local_root,
                output_root=output_root,
                context=context,
            )
            report_payload = json.loads(result.report_path.read_text(encoding="utf-8"))
            file_reports = {item["relative_path"]: item for item in report_payload["files"]}
            db_delta_entries = self._read_entries(
                output_root / "DLCGame" / "delta" / "translation_updates" / "database" / "asset_00_text" / "db_Test.json"
            )
            dll_delta_entries = self._read_entries(output_root / "DLCGame" / "delta" / "translation_updates" / "dll_strings.json")

        self.assertEqual(report_payload["summary"]["remote_only_entries"], 0)
        self.assertEqual(report_payload["summary"]["local_only_entries"], 0)
        self.assertEqual(report_payload["local_mode"], "translation_package")
        self.assertEqual(report_payload["summary"]["translation_changed_entries"], 2)
        self.assertEqual(file_reports["database/asset_00_text/db_Test.json"]["translation_changed"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["translation_changed"], 1)
        self.assertIsNone(file_reports["database/asset_00_text/db_Test.json"]["diff_path"])
        self.assertIsNone(file_reports["dll_strings.json"]["diff_path"])
        self.assertEqual(set(file_reports["database/asset_00_text/db_Test.json"]["delta_paths"]), {"translation_updates"})
        self.assertEqual(set(file_reports["dll_strings.json"]["delta_paths"]), {"translation_updates"})
        self.assertEqual([entry["key"] for entry in db_delta_entries], ["1"])
        self.assertEqual([entry["key"] for entry in dll_delta_entries], ["Game.Type.Shared_0"])

    def test_compare_downloaded_paratranz_scope_merges_local_main_and_dlc_for_complete_dlc_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote_root = root / "remote"
            local_root = root / "local"
            output_root = root / "out"

            self._write_entries(
                remote_root / "MainGame" / "database" / "db_Test.json",
                [self._entry("0", "Base", "base", 1)],
            )
            self._write_entries(
                remote_root / "DLCGame" / "database" / "db_Test.json",
                [self._entry("1", "Shared", "remote dlc", 1)],
            )
            self._write_entries(
                local_root / "MainGame" / "database" / "db_Test.json",
                [self._entry("0", "Base", "base", 1)],
            )
            self._write_entries(
                local_root / "DLCGame" / "database" / "db_Test.json",
                [self._entry("100", "Shared", "local dlc", 1)],
            )
            self._write_entries(
                remote_root / "MainGame" / "dll_strings.json",
                [self._entry("Game.Type.Base_0", "BaseDll", "base", 1)],
            )
            self._write_entries(
                remote_root / "DLCGame" / "dll_strings.json",
                [self._entry("Game.Type.Shared_0", "SharedDll", "remote", 1)],
            )
            self._write_entries(
                local_root / "MainGame" / "dll_strings.json",
                [self._entry("Game.Type.Base_0", "BaseDll", "base", 1)],
            )
            self._write_entries(
                local_root / "DLCGame" / "dll_strings.json",
                [self._entry("Game.Type.Shared_0", "SharedDll", "local", 1)],
            )

            context = build_app_context(project_paths=_FakePaths(root), app_logger=Mock())
            result = compare_downloaded_paratranz_scope(
                remote_root=remote_root,
                scope="dlc",
                local_root=local_root,
                output_root=output_root,
                context=context,
            )
            report_payload = json.loads(result.report_path.read_text(encoding="utf-8"))
            file_reports = {item["relative_path"]: item for item in report_payload["files"]}

        self.assertEqual(result.local_root, local_root)
        self.assertEqual(report_payload["summary"]["remote_only_entries"], 0)
        self.assertEqual(report_payload["summary"]["local_only_entries"], 0)
        self.assertEqual(report_payload["summary"]["translation_changed_entries"], 2)
        self.assertEqual(file_reports["database/db_Test.json"]["translation_changed"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["translation_changed"], 1)

    def test_compare_downloaded_paratranz_scope_dlc_new_keys_follow_remote_dlc_then_maingame(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote_root = root / "remote"
            local_root = root / "local"
            output_root = root / "out"

            self._write_entries(
                remote_root / "MainGame" / "database" / "db_Test.json",
                [
                    self._entry("0", "First", "", 0),
                    self._entry("10", "Historical high key", "", 0),
                    self._entry("2", "Current tail", "", 0),
                ],
            )
            self._write_entries(
                remote_root / "DLCGame" / "database" / "db_Test.json",
                [self._entry("50", "Remote DLC only", "old dlc", 1)],
            )
            self._write_entries(
                remote_root / "MainGame" / "database" / "db_MainOnly.json",
                [
                    self._entry("0", "Main first", "", 0),
                    self._entry("10", "Main historical high key", "", 0),
                    self._entry("2", "Main current tail", "", 0),
                ],
            )
            self._write_entries(
                local_root / "MainGame" / "database" / "db_Test.json",
                [
                    self._entry("0", "First", "", 0),
                    self._entry("10", "Historical high key", "", 0),
                    self._entry("2", "Current tail", "", 0),
                ],
            )
            self._write_entries(
                local_root / "DLCGame" / "database" / "db_Test.json",
                [
                    self._entry("100", "Remote DLC only", "old dlc", 1),
                    self._entry("101", "Brand New", "", 0),
                    self._entry("102", "Another New", "", 0),
                ],
            )
            self._write_entries(
                local_root / "MainGame" / "database" / "db_MainOnly.json",
                [
                    self._entry("0", "Main first", "", 0),
                    self._entry("10", "Main historical high key", "", 0),
                    self._entry("2", "Main current tail", "", 0),
                ],
            )
            self._write_entries(
                local_root / "DLCGame" / "database" / "db_MainOnly.json",
                [
                    self._entry("100", "Main current tail", "", 0),
                    self._entry("101", "Main fallback new", "", 0),
                ],
            )
            self._write_entries(
                local_root / "DLCGame" / "database" / "db_NoRemoteSeed.json",
                [self._entry("999", "No remote seed new", "", 0)],
            )
            self._write_entries(remote_root / "MainGame" / "dll_strings.json", [])
            self._write_entries(remote_root / "DLCGame" / "dll_strings.json", [])
            self._write_entries(local_root / "MainGame" / "dll_strings.json", [])
            self._write_entries(local_root / "DLCGame" / "dll_strings.json", [])

            context = build_app_context(project_paths=_FakePaths(root), app_logger=Mock())
            result = compare_downloaded_paratranz_scope(
                remote_root=remote_root,
                scope="dlc",
                local_root=local_root,
                output_root=output_root,
                context=context,
            )
            new_entries = self._read_entries(output_root / "DLCGame" / "delta" / "new_entries" / "database" / "db_Test.json")
            main_fallback_entries = self._read_entries(output_root / "DLCGame" / "delta" / "new_entries" / "database" / "db_MainOnly.json")
            zero_fallback_entries = self._read_entries(output_root / "DLCGame" / "delta" / "new_entries" / "database" / "db_NoRemoteSeed.json")

        self.assertEqual(result.summary.local_only_entries, 4)
        self.assertEqual([entry["key"] for entry in new_entries], ["51", "52"])
        self.assertEqual([entry["key"] for entry in main_fallback_entries], ["3"])
        self.assertEqual([entry["key"] for entry in zero_fallback_entries], ["0"])

    def test_compare_downloaded_paratranz_scope_ignores_translation_diffs_for_source_text_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote_root = root / "remote"
            local_root = root / "0-DumpData"
            output_root = root / "out"

            self._write_entries(
                remote_root / "DLCGame" / "database" / "db_Test.json",
                [
                    self._entry("0", "Same", "已翻译", 1),
                    self._entry("1", "Old source sentence.", "保留", 1),
                ],
            )
            self._write_entries(
                local_root / "DLCGame" / "database" / "db_Test.json",
                [
                    self._entry("100", "Same", "", 0),
                    self._entry("101", "Old source sentence!", "", 0),
                ],
            )
            self._write_entries(
                remote_root / "DLCGame" / "dll_strings.json",
                [self._entry("Game.Type.Run_0", "Run", "运行", 1)],
            )
            self._write_entries(
                local_root / "DLCGame" / "dll_strings.json",
                [self._entry("Game.Type.Run_0", "Run", "", 0)],
            )

            context = build_app_context(project_paths=_FakePaths(root), app_logger=Mock())
            result = compare_downloaded_paratranz_scope(
                remote_root=remote_root,
                scope="dlc",
                local_root=local_root,
                output_root=output_root,
                context=context,
            )
            report_payload = json.loads(result.report_path.read_text(encoding="utf-8"))
            file_reports = {item["relative_path"]: item for item in report_payload["files"]}
            db_delta_entries = self._read_entries(output_root / "DLCGame" / "delta" / "source_updates" / "database" / "db_Test.json")

        self.assertEqual(result.local_mode, "source_text")
        self.assertEqual(report_payload["local_mode"], "source_text")
        self.assertEqual(report_payload["summary"]["translation_changed_entries"], 0)
        self.assertEqual(report_payload["summary"]["source_changed_entries"], 1)
        self.assertEqual(report_payload["summary"]["entry_changed_entries"], 0)
        self.assertEqual(file_reports["database/db_Test.json"]["translation_changed"], 0)
        self.assertEqual(file_reports["database/db_Test.json"]["source_changed"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["translation_changed"], 0)
        self.assertEqual([entry["key"] for entry in db_delta_entries], ["1"])

    def test_compare_downloaded_paratranz_scope_splits_source_text_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote_root = root / "remote"
            local_root = root / "0-DumpData"
            output_root = root / "out"

            self._write_entries(
                remote_root / "DLCGame" / "database" / "db_Test.json",
                [
                    self._entry("0", "Same", "same translation", 1),
                    self._entry("1", "Old source sentence.", "remote keep", 1),
                ],
            )
            self._write_entries(
                local_root / "DLCGame" / "database" / "db_Test.json",
                [
                    self._entry("100", "Same", "", 0),
                    self._entry("101", "Old source sentence!", "", 0),
                ],
            )
            self._write_entries(
                remote_root / "DLCGame" / "database" / "remote_only_file.json",
                [self._entry("0", "Remote stale", "stale translation", 1)],
            )
            self._write_entries(
                local_root / "DLCGame" / "database" / "local_only_file.json",
                [self._entry("0", "Local new", "", 0)],
            )
            self._write_entries(
                remote_root / "DLCGame" / "dll_strings.json",
                [
                    self._entry("Game.Type.Run_0", "Run", "run translation", 1),
                    self._entry("Game.Type.Source_0", "Old dll source.", "dll keep", 1),
                    self._entry("Game.Type.RemoteOnly_0", "Remote dll stale", "dll stale", 1),
                ],
            )
            self._write_entries(
                local_root / "DLCGame" / "dll_strings.json",
                [
                    self._entry("Game.Type.Run_0", "Run", "", 0),
                    self._entry("Game.Type.Source_0", "Old dll source!", "", 0),
                    self._entry("Game.Type.LocalOnly_0", "Local dll new", "", 0),
                ],
            )

            context = build_app_context(project_paths=_FakePaths(root), app_logger=Mock())
            result = compare_downloaded_paratranz_scope(
                remote_root=remote_root,
                scope="dlc",
                local_root=local_root,
                output_root=output_root,
                context=context,
            )
            report_payload = json.loads(result.report_path.read_text(encoding="utf-8"))
            file_reports = {item["relative_path"]: item for item in report_payload["files"]}
            db_source_entries = self._read_entries(output_root / "DLCGame" / "delta" / "source_updates" / "database" / "db_Test.json")
            db_new_entries = self._read_entries(output_root / "DLCGame" / "delta" / "new_entries" / "database" / "local_only_file.json")
            db_review_entries = self._read_entries(output_root / "DLCGame" / "review" / "remote_only" / "database" / "remote_only_file.json")
            dll_source_entries = self._read_entries(output_root / "DLCGame" / "delta" / "source_updates" / "dll_strings.json")
            dll_new_entries = self._read_entries(output_root / "DLCGame" / "delta" / "new_entries" / "dll_strings.json")
            dll_review_entries = self._read_entries(output_root / "DLCGame" / "review" / "remote_only" / "dll_strings.json")

        self.assertEqual(result.local_mode, "source_text")
        self.assertEqual(report_payload["summary"]["translation_changed_entries"], 0)
        self.assertEqual(report_payload["summary"]["source_changed_entries"], 2)
        self.assertEqual(report_payload["summary"]["local_only_entries"], 2)
        self.assertEqual(report_payload["summary"]["remote_only_entries"], 2)
        self.assertEqual(set(file_reports["database/local_only_file.json"]["delta_paths"]), {"new_entries"})
        self.assertIsNone(file_reports["database/local_only_file.json"]["diff_path"])
        self.assertEqual(set(file_reports["database/remote_only_file.json"]["review_paths"]), {"remote_only"})
        self.assertEqual(file_reports["database/remote_only_file.json"]["delta_paths"], {})
        self.assertIsNone(file_reports["database/remote_only_file.json"]["diff_path"])
        self.assertEqual([entry["key"] for entry in db_source_entries], ["1"])
        self.assertEqual(db_source_entries[0]["original"], "Old source sentence!")
        self.assertEqual(db_source_entries[0]["translation"], "remote keep")
        self.assertEqual(db_source_entries[0]["stage"], 0)
        self.assertEqual([entry["key"] for entry in db_new_entries], ["0"])
        self.assertEqual([entry["key"] for entry in db_review_entries], ["0"])
        self.assertEqual([entry["key"] for entry in dll_source_entries], ["Game.Type.Source_0"])
        self.assertEqual(dll_source_entries[0]["original"], "Old dll source!")
        self.assertEqual(dll_source_entries[0]["translation"], "dll keep")
        self.assertEqual(dll_source_entries[0]["stage"], 0)
        self.assertEqual([entry["key"] for entry in dll_new_entries], ["Game.Type.LocalOnly_0"])
        self.assertEqual([entry["key"] for entry in dll_review_entries], ["Game.Type.RemoteOnly_0"])

    def test_compare_downloaded_paratranz_scope_rejects_unrelated_index_source_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote_root = root / "remote"
            local_root = root / "local"
            output_root = root / "out"

            self._write_entries(
                remote_root / "MainGame" / "database" / "db_Test.json",
                [self._entry("5", "んぅ、ああД　あ、暑いですねД　もうちょっと、脱ごうかなぁ？", "keep translation", 1)],
            )
            self._write_entries(
                local_root / "MainGame" / "database" / "db_Test.json",
                [self._entry("99", "【<pl>】さんになら、いっぱい身体を見られてもД　嬉しいだけですからД", "", 0)],
            )
            self._write_entries(remote_root / "MainGame" / "dll_strings.json", [])
            self._write_entries(local_root / "MainGame" / "dll_strings.json", [])

            context = build_app_context(project_paths=_FakePaths(root), app_logger=Mock())
            result = compare_downloaded_paratranz_scope(
                remote_root=remote_root,
                scope="main",
                local_root=local_root,
                output_root=output_root,
                context=context,
            )
            report_payload = json.loads(result.report_path.read_text(encoding="utf-8"))
            file_reports = {item["relative_path"]: item for item in report_payload["files"]}
            new_entries = self._read_entries(output_root / "MainGame" / "delta" / "new_entries" / "database" / "db_Test.json")
            review_entries = self._read_entries(output_root / "MainGame" / "review" / "remote_only" / "database" / "db_Test.json")

        self.assertEqual(result.summary.source_changed_entries, 0)
        self.assertEqual(result.summary.local_only_entries, 1)
        self.assertEqual(result.summary.remote_only_entries, 1)
        self.assertIsNone(file_reports["database/db_Test.json"]["diff_path"])
        self.assertEqual(set(file_reports["database/db_Test.json"]["delta_paths"]), {"new_entries"})
        self.assertEqual(set(file_reports["database/db_Test.json"]["review_paths"]), {"remote_only"})
        self.assertEqual([entry["key"] for entry in new_entries], ["6"])
        self.assertEqual([entry["key"] for entry in review_entries], ["5"])

    def test_upload_compare_source_changes_uploads_delta_files_with_update_and_create(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compare_root = root / "compare"
            scope_root = compare_root / "DLCGame"
            source_delta = scope_root / "delta" / "source_updates" / "database" / "db_Test.json"
            entry_delta = scope_root / "delta" / "entry_updates" / "database" / "db_Test.json"
            translation_delta = scope_root / "delta" / "translation_updates" / "database" / "db_Test.json"
            new_delta = scope_root / "delta" / "new_entries" / "database" / "db_Test.json"
            self._write_entries(
                source_delta,
                [self._entry("1", "Main source fixed.", "keep main translation", 1, "main ctx")],
            )
            self._write_entries(
                entry_delta,
                [self._entry("2", "DLC source fixed.", "new dlc translation", 1, "dlc ctx")],
            )
            self._write_entries(
                translation_delta,
                [self._entry("3", "DLC translation source.", "better dlc translation", 1, "translation ctx")],
            )
            self._write_entries(
                new_delta,
                [self._entry("99", "Brand new DLC source.", "", 0, "new ctx")],
            )
            api = _FakeCompareUploadApi()
            context = build_app_context(project_paths=_FakePaths(root), app_logger=Mock())

            result = upload_compare_source_changes(
                scope="dlc",
                compare_root=compare_root,
                project_id=77,
                dry_run=False,
                context=context,
                api=api,
            )

        self.assertEqual(result.summary.scanned_files, 4)
        self.assertEqual(result.summary.source_changed_entries, 1)
        self.assertEqual(result.summary.entry_changed_entries, 1)
        self.assertEqual(result.summary.translation_changed_entries, 1)
        self.assertEqual(result.summary.new_entries, 1)
        self.assertEqual(result.summary.planned_entries, 4)
        self.assertEqual(result.summary.succeeded_entries, 4)
        self.assertEqual(result.summary.skipped_entries, 0)
        saved_by_id = {item[0]: item for item in api.saved_strings}
        self.assertEqual(set(saved_by_id), {101, 202, 203})
        self.assertEqual([item[2] for item in api.saved_strings], [77, 77, 77])
        self.assertEqual(saved_by_id[101][1].original, "Main source fixed.")
        self.assertEqual(saved_by_id[101][1].translation, "keep main translation")
        self.assertEqual(saved_by_id[101][1].stage, 0)
        self.assertEqual(saved_by_id[101][1].context, "main ctx")
        self.assertEqual(saved_by_id[202][1].original, "DLC source fixed.")
        self.assertEqual(saved_by_id[202][1].translation, "new dlc translation")
        self.assertEqual(saved_by_id[202][1].stage, 0)
        self.assertEqual(saved_by_id[202][1].context, "dlc ctx")
        self.assertEqual(saved_by_id[203][1].original, "DLC translation source.")
        self.assertEqual(saved_by_id[203][1].translation, "better dlc translation")
        self.assertEqual(saved_by_id[203][1].stage, 1)
        self.assertEqual(api.created_strings[0][0].file, 10)
        self.assertEqual(api.created_strings[0][0].key, "99")
        self.assertEqual(api.created_strings[0][0].stage, 0)
        self.assertEqual(api.created_strings[0][1], 77)

    def test_upload_compare_source_changes_dry_run_does_not_write_remote(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compare_root = root / "compare"
            scope_root = compare_root / "MainGame"
            source_delta = scope_root / "delta" / "source_updates" / "dll_strings.json"
            self._write_entries(source_delta, [self._entry("Game.Type.Run_0", "Run fixed", "run", 1)])
            self._write_compare_report(
                scope_root / "report.json",
                [
                    {
                        "relative_path": "dll_strings.json",
                        "delta_paths": {
                            "source_updates": source_delta.as_posix(),
                        },
                    }
                ],
            )
            api = _FakeCompareUploadApi()
            context = build_app_context(project_paths=_FakePaths(root), app_logger=Mock())

            result = upload_compare_source_changes(
                scope="main",
                compare_root=compare_root,
                project_id=77,
                dry_run=True,
                context=context,
                api=api,
            )

        self.assertEqual(result.summary.planned_entries, 1)
        self.assertEqual(result.summary.succeeded_entries, 0)
        self.assertEqual(api.saved_strings, [])

    def _entry(self, key: str, original: str, translation: str, stage: int, context: str = "") -> dict:
        return {
            "key": key,
            "original": original,
            "translation": translation,
            "stage": stage,
            "context": context,
        }

    def _write_entries(self, path: Path, entries: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")

    def _write_compare_report(self, path: Path, files: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "report_version": 2,
                    "scope": "dlc",
                    "files": files,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _read_entries(self, path: Path) -> list[dict]:
        return json.loads(path.read_text(encoding="utf-8"))


class _FakeCompareUploadApi:
    project_id = 77

    def __init__(self) -> None:
        self.saved_strings = []
        self.created_strings = []
        self.files = [
            ParatranzFile(id=10, name="DLCGame/database/db_Test.json"),
            ParatranzFile(id=20, name="MainGame/database/db_Test.json"),
            ParatranzFile(id=30, name="MainGame/dll_strings.json"),
        ]
        self.strings = {
            10: [
                ParatranzString(id=202, key="2", original="DLC source old.", translation="old", stage=1),
                ParatranzString(id=203, key="3", original="DLC translation source.", translation="old translation", stage=1),
            ],
            20: [ParatranzString(id=101, key="1", original="Main source old.", translation="keep main translation", stage=1)],
            30: [ParatranzString(id=303, key="Game.Type.Run_0", original="Run old", translation="run", stage=1)],
        }

    def get_files(self, *, project_id: int | None = None):
        return self.files

    def get_strings(self, *, file: int, detailed: bool, page: int, page_size: int, project_id: int | None = None):
        return Page(page=page, page_count=1, results=self.strings.get(file, []))

    def save_string(self, string_id: int, request, *, project_id: int | None = None):
        self.saved_strings.append((string_id, request, project_id))
        return ParatranzString(id=string_id, key=request.key or "", original=request.original or "")

    def create_string(self, request, *, project_id: int | None = None):
        self.created_strings.append((request, project_id))
        return ParatranzString(id=900 + len(self.created_strings), key=request.key or "", original=request.original or "")


class _FakePaths:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def ensure_inside(self, path: Path, root: Path) -> Path:
        target = path.resolve()
        anchor = root.resolve()
        if target == anchor or anchor not in target.parents:
            raise AssertionError(f"unsafe path in test: {target}")
        return target


if __name__ == "__main__":
    unittest.main()
