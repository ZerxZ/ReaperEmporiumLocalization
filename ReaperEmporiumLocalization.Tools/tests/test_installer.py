from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.localization.installer import install_translation_packages


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

    def _write_entries(self, path: Path, entries: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
