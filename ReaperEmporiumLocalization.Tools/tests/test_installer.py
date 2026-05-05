from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from reaper_tools.localization.installer import install_translation_packages, package_final_localization


class InstallerPathTests(unittest.TestCase):
    def test_install_preserves_nested_database_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "package"
            game_root = root / "game"
            self._write_entries(
                package / "database" / "bundle_a" / "db_Test.json",
                [{"key": "0", "original": "Hello", "translation": "Ni hao", "stage": 1, "context": ""}],
            )

            stats = install_translation_packages([package], game_root=game_root, clear=True)

            output_file = game_root / "localization" / "database" / "bundle_a" / "db_Test.json"
            flat_file = game_root / "localization" / "database" / "db_Test.json"
            output = json.loads(output_file.read_text(encoding="utf-8"))
            output_exists = output_file.is_file()
            flat_exists = flat_file.exists()

        self.assertTrue(output_exists)
        self.assertFalse(flat_exists)
        self.assertEqual(stats.database_files, 1)
        self.assertEqual(stats.written_files, 1)
        self.assertEqual(output[0]["translation"], "Ni hao")

    def test_install_keeps_same_database_name_in_different_bundles_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "package"
            game_root = root / "game"
            self._write_entries(
                package / "database" / "bundle_a" / "db_Test.json",
                [{"key": "0", "original": "A", "translation": "AA", "stage": 1, "context": ""}],
            )
            self._write_entries(
                package / "database" / "bundle_b" / "db_Test.json",
                [{"key": "0", "original": "B", "translation": "BB", "stage": 1, "context": ""}],
            )

            stats = install_translation_packages([package], game_root=game_root, clear=True)

            output_a = json.loads(
                (game_root / "localization" / "database" / "bundle_a" / "db_Test.json").read_text(encoding="utf-8")
            )
            output_b = json.loads(
                (game_root / "localization" / "database" / "bundle_b" / "db_Test.json").read_text(encoding="utf-8")
            )

        self.assertEqual(stats.database_files, 2)
        self.assertEqual(stats.written_files, 2)
        self.assertEqual(output_a[0]["original"], "A")
        self.assertEqual(output_b[0]["original"], "B")

    def test_package_final_merges_runtime_localization_and_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "migrated"
            output = root / "package" / "localization"
            zip_path = root / "package" / "release.zip"
            stale_file = output / "old.json"
            stale_file.parent.mkdir(parents=True)
            stale_file.write_text("old", encoding="utf-8")

            self._write_entries(
                source / "MainGame" / "database" / "asset_00_text" / "db_Test.json",
                [
                    {"key": "0", "original": "Shared", "translation": "Main", "stage": 1, "context": ""},
                    {"key": "1", "original": "Only Main", "translation": "Main only", "stage": 1, "context": ""},
                ],
            )
            self._write_entries(
                source / "DLCGame" / "database" / "asset_00_text" / "db_Test.json",
                [
                    {"key": "0", "original": "Shared", "translation": "DLC", "stage": 1, "context": ""},
                    {"key": "2", "original": "Only DLC", "translation": "DLC only", "stage": 1, "context": ""},
                ],
            )
            self._write_entries(
                source / "MainGame" / "database" / "asset_01_text" / "db_Test.json",
                [{"key": "0", "original": "Bundle A", "translation": "A", "stage": 1, "context": ""}],
            )
            self._write_entries(
                source / "MainGame" / "database" / "asset_02_text" / "db_Test.json",
                [{"key": "0", "original": "Bundle B", "translation": "B", "stage": 1, "context": ""}],
            )
            self._write_entries(
                source / "MainGame" / "dll_strings.json",
                [
                    {
                        "key": "Game.Main_0",
                        "original": "DLL Shared",
                        "translation": "Main DLL",
                        "stage": 1,
                        "context": "",
                    },
                    {
                        "key": "Game.Main_1",
                        "original": "DLL Main",
                        "translation": "Only Main DLL",
                        "stage": 1,
                        "context": "",
                    },
                ],
            )
            self._write_entries(
                source / "DLCGame" / "dll_strings.json",
                [
                    {
                        "key": "Game.Dlc_0",
                        "original": "DLL Shared",
                        "translation": "DLC DLL",
                        "stage": 1,
                        "context": "",
                    },
                    {
                        "key": "Game.Dlc_1",
                        "original": "DLL DLC",
                        "translation": "Only DLC DLL",
                        "stage": 1,
                        "context": "",
                    },
                ],
            )

            stats = package_final_localization(source, output_root=output, zip_path=zip_path)

            merged_database = json.loads(
                (output / "database" / "asset_00_text" / "db_Test.json").read_text(encoding="utf-8")
            )
            bundle_a = json.loads(
                (output / "database" / "asset_01_text" / "db_Test.json").read_text(encoding="utf-8")
            )
            bundle_b = json.loads(
                (output / "database" / "asset_02_text" / "db_Test.json").read_text(encoding="utf-8")
            )
            dll_entries = json.loads((output / "dll_strings" / "dll_strings.json").read_text(encoding="utf-8"))
            with ZipFile(zip_path) as archive:
                zip_names = sorted(archive.namelist())
            stale_exists = stale_file.exists()
            zip_exists = zip_path.is_file()

        self.assertFalse(stale_exists)
        self.assertEqual(stats.database_files, 3)
        self.assertEqual(stats.database_entries, 5)
        self.assertEqual(stats.dll_entries, 3)
        self.assertEqual(stats.written_files, 4)
        self.assertEqual([entry["translation"] for entry in merged_database], ["DLC", "Main only", "DLC only"])
        self.assertEqual(bundle_a[0]["original"], "Bundle A")
        self.assertEqual(bundle_b[0]["original"], "Bundle B")
        self.assertEqual(
            [entry["translation"] for entry in dll_entries],
            ["DLC DLL", "Only Main DLL", "Only DLC DLL"],
        )
        self.assertTrue(zip_exists)
        self.assertTrue(all(name.startswith("localization/") for name in zip_names))
        self.assertIn("localization/database/asset_00_text/db_Test.json", zip_names)
        self.assertIn("localization/dll_strings/dll_strings.json", zip_names)

    def _write_entries(self, path: Path, entries: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

