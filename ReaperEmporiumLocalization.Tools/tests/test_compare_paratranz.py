from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from reaper_tools.app_context import build_app_context
from reaper_tools.localization.compare_paratranz import compare_downloaded_paratranz_scope, download_and_compare_paratranz


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
                    self._entry("104", "Hero entered the shop.", "译文", 1),
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
            db_delta_entries = json.loads((output_root / "MainGame" / "delta" / "database" / "db_Test.json").read_text(encoding="utf-8"))
            dll_delta_entries = json.loads((output_root / "MainGame" / "delta" / "dll_strings.json").read_text(encoding="utf-8"))

        self.assertEqual(result.scope_dir, "MainGame")
        self.assertEqual(report_payload["local_mode"], "translation_package")
        self.assertEqual(report_payload["summary"]["scanned_files"], 4)
        self.assertEqual(report_payload["summary"]["remote_only_files"], 1)
        self.assertEqual(report_payload["summary"]["local_only_files"], 1)
        self.assertEqual(report_payload["summary"]["remote_only_entries"], 2)
        self.assertEqual(report_payload["summary"]["local_only_entries"], 2)
        self.assertEqual(report_payload["summary"]["source_changed_entries"], 2)
        self.assertEqual(report_payload["summary"]["translation_changed_entries"], 2)
        self.assertEqual(report_payload["summary"]["entry_changed_entries"], 3)

        self.assertEqual(file_reports["database/db_Test.json"]["remote_only"], 0)
        self.assertEqual(file_reports["database/db_Test.json"]["local_only"], 0)
        self.assertEqual(file_reports["database/db_Test.json"]["source_changed"], 1)
        self.assertEqual(file_reports["database/db_Test.json"]["translation_changed"], 1)
        self.assertEqual(file_reports["database/db_Test.json"]["entry_changed"], 2)
        self.assertEqual([entry["key"] for entry in db_delta_entries], ["1", "2", "3", "4"])
        self.assertEqual(file_reports["database/remote_only_file.json"]["only_in"], "remote")
        self.assertEqual(file_reports["database/local_only_file.json"]["only_in"], "local")
        self.assertEqual(file_reports["dll_strings.json"]["remote_only"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["local_only"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["source_changed"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["translation_changed"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["entry_changed"], 1)
        self.assertEqual([entry["key"] for entry in dll_delta_entries], ["Game.Type.Talk_0", "Game.Type.Source_0", "Game.Type.Entry_0", "Game.Type.LocalOnly_0"])
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
            db_delta_entries = json.loads(
                (output_root / "DLCGame" / "delta" / "database" / "asset_00_text" / "db_Test.json").read_text(encoding="utf-8")
            )
            dll_delta_entries = json.loads((output_root / "DLCGame" / "delta" / "dll_strings.json").read_text(encoding="utf-8"))

        self.assertEqual(report_payload["summary"]["remote_only_entries"], 0)
        self.assertEqual(report_payload["summary"]["local_only_entries"], 0)
        self.assertEqual(report_payload["local_mode"], "translation_package")
        self.assertEqual(report_payload["summary"]["translation_changed_entries"], 2)
        self.assertEqual(file_reports["database/asset_00_text/db_Test.json"]["translation_changed"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["translation_changed"], 1)
        self.assertIsNone(file_reports["database/asset_00_text/db_Test.json"]["diff_path"])
        self.assertIsNone(file_reports["dll_strings.json"]["diff_path"])
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
                    self._entry("1", "Old source", "保留", 1),
                ],
            )
            self._write_entries(
                local_root / "DLCGame" / "database" / "db_Test.json",
                [
                    self._entry("100", "Same", "", 0),
                    self._entry("101", "Old source changed", "", 0),
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
            db_delta_entries = json.loads((output_root / "DLCGame" / "delta" / "database" / "db_Test.json").read_text(encoding="utf-8"))

        self.assertEqual(result.local_mode, "source_text")
        self.assertEqual(report_payload["local_mode"], "source_text")
        self.assertEqual(report_payload["summary"]["translation_changed_entries"], 0)
        self.assertEqual(report_payload["summary"]["source_changed_entries"], 1)
        self.assertEqual(report_payload["summary"]["entry_changed_entries"], 0)
        self.assertEqual(file_reports["database/db_Test.json"]["translation_changed"], 0)
        self.assertEqual(file_reports["database/db_Test.json"]["source_changed"], 1)
        self.assertEqual(file_reports["dll_strings.json"]["translation_changed"], 0)
        self.assertEqual([entry["key"] for entry in db_delta_entries], ["1"])

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
