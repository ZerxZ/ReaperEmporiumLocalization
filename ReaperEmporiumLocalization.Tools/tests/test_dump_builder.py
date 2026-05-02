from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.localization import dump_builder
from src.localization.dump_builder import (
    DumpBuildStats,
    build_dump_diff,
    _DatabaseEntryMatcher,
    _diff_entries,
    _write_dlc_database_diff,
    _write_dlc_dll_diff,
)
from src.models import ParatranzData


class DumpBuilderDiffTests(unittest.TestCase):
    def test_build_dump_diff_recreates_entire_build_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_entries(root / "data" / "0-DumpData" / "MainGame" / "database" / "db_Test.json", [])
            self._write_entries(root / "data" / "0-DumpData" / "MainGame" / "dll_strings.json", [])
            self._write_entries(
                root / "data" / "0-DumpData" / "DLCGame" / "database" / "db_Test.json",
                [self._entry("new", "New", "added", 1)],
            )
            self._write_entries(root / "data" / "0-DumpData" / "DLCGame" / "dll_strings.json", [])
            stale_file = root / "build" / "stale.txt"
            stale_file.parent.mkdir(parents=True)
            stale_file.write_text("old build artifact", encoding="utf-8")

            with patch.object(dump_builder, "paths", _FakePaths(root)):
                stats = build_dump_diff(show_progress=False)

            output_file = root / "build" / "dump" / "DLCGame" / "database" / "db_Test.json"

            self.assertFalse(stale_file.exists())
            self.assertTrue(output_file.is_file())
            self.assertEqual(stats.dlc_database_files_written, 1)

    def test_database_diff_is_written_to_dlc_json_and_readable_dmp_diff_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            main_db = root / "main" / "database"
            dlc_db = root / "dlc" / "database"
            dlc_out = root / "out" / "DLCGame" / "database"
            diff_out = root / "out" / "diff" / "database"
            main_db.mkdir(parents=True)
            dlc_db.mkdir(parents=True)

            main_file = main_db / "db_Test.json"
            dlc_file = dlc_db / "db_Test.json"
            self._write_entries(
                main_file,
                [
                    self._entry("same", "Same", "same-translation", 1),
                    self._entry("changed", "Changed", "旧译文", 1),
                    self._entry("2", "Key Drift", "drift-translation", 1),
                    self._entry("9", "Hero entered shop.", "", 0),
                ],
            )
            self._write_entries(
                dlc_file,
                [
                    self._entry("100", "Same", "same-translation", 1),
                    self._entry("101", "Changed", "新译文", 1),
                    self._entry("102", "Key Drift", "drift-translation", 1),
                    self._entry("103", "Hero entered the shop.", "", 0),
                    self._entry("104", "Brand New", "新增译文", 1),
                ],
            )

            stats = DumpBuildStats()
            read_files, read_entries = _write_dlc_database_diff(
                main_db,
                dlc_db,
                dlc_out,
                diff_out,
                stats=stats,
                show_progress=False,
            )

            dlc_entries = json.loads((dlc_out / "db_Test.json").read_text(encoding="utf-8"))
            diff_file = diff_out / "db_Test.json.diff"
            diff_text = diff_file.read_text(encoding="utf-8")
            diff_file_exists = diff_file.is_file()
            legacy_diff_exists = (diff_out / "db_Test.json").exists()

        self.assertEqual((read_files, read_entries), (1, 5))
        self.assertEqual([entry["key"] for entry in dlc_entries], ["changed", "9", "10"])
        self.assertTrue(diff_file_exists)
        self.assertFalse(legacy_diff_exists)
        self.assertIn("--- ", diff_text)
        self.assertIn("+++ ", diff_text)
        self.assertIn('-    "translation": "旧译文"', diff_text)
        self.assertIn('+    "translation": "新译文"', diff_text)
        self.assertIn('+    "translation": "新增译文"', diff_text)
        self.assertNotIn('"key": "100"', diff_text)
        self.assertNotIn('"key": "102"', diff_text)
        self.assertNotIn("%E6", diff_text)
        self.assertEqual(stats.diff_database_files_written, 1)

    def test_database_diff_uses_array_count_before_index_matching(self) -> None:
        main_entries = self._models(
            [
                self._entry("0", "Same", "same-translation", 1),
                self._entry("1", "Changed original", "", 0),
            ]
        )
        dlc_entries = self._models(
            [
                self._entry("100", "Same", "same-translation", 1),
                self._entry("101", "Changed originals", "", 0),
            ]
        )

        changed = _diff_entries(main_entries, dlc_entries)

        self.assertEqual([entry.key for entry in changed], ["1"])

    def test_database_matcher_uses_key_after_fuzzy_original(self) -> None:
        main_entries = self._models(
            [
                self._entry("0", "Completely different text.", "", 0),
                self._entry("9", "Hero entered shop.", "", 0),
            ]
        )
        dlc_entry = ParatranzData.model_validate(self._entry("0", "Hero entered the shop.", "", 0))

        candidate = _DatabaseEntryMatcher(main_entries).find(dlc_entry, index=None, use_index=False)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.key, "9")

    def test_database_matcher_uses_context_before_key_for_duplicate_original(self) -> None:
        main_entries = self._models(
            [
                self._entry("0", "Same original", "", 0, "wrong context"),
                self._entry("9", "Same original", "", 0, "right context"),
            ]
        )
        dlc_entry = ParatranzData.model_validate(self._entry("0", "Same original", "", 0, "right context"))

        candidate = _DatabaseEntryMatcher(main_entries).find(dlc_entry, index=None, use_index=False)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.key, "9")

    def test_database_fuzzy_does_not_reuse_already_matched_original(self) -> None:
        main_entries = self._models(
            [
                self._entry("0", "ならずものＡ", "", 0),
            ]
        )
        dlc_entries = self._models(
            [
                self._entry("96", "ならずものＡ", "", 0),
                self._entry("228", "ならずものA", "", 0),
            ]
        )

        changed = _diff_entries(main_entries, dlc_entries)

        self.assertEqual([(entry.key, entry.original) for entry in changed], [("1", "ならずものA")])

    def test_database_new_key_counter_follows_maingame_file_order(self) -> None:
        main_entries = self._models(
            [
                self._entry("0", "First", "", 0),
                self._entry("10", "Historical high key", "", 0),
                self._entry("2", "Current tail", "", 0),
            ]
        )
        dlc_entries = self._models(
            [
                self._entry("100", "Brand New", "", 0),
                self._entry("101", "Another New", "", 0),
            ]
        )

        changed = _diff_entries(main_entries, dlc_entries)

        self.assertEqual([entry.key for entry in changed], ["3", "4"])

    def test_dll_diff_uses_dmp_filtering_and_writes_readable_dmp_diff_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            main_file = root / "main" / "dll_strings.json"
            dlc_file = root / "dlc" / "dll_strings.json"
            dlc_out = root / "out" / "DLCGame" / "dll_strings.json"
            diff_out = root / "out" / "diff" / "dll_strings.json.diff"

            self._write_entries(
                main_file,
                [
                    self._entry("Game.Type.Run_0", "Run", "运行", 1, "ctx"),
                    self._entry("Game.Type.Method_0", "Talk", "旧对话", 1, "ctx"),
                ],
            )
            self._write_entries(
                dlc_file,
                [
                    self._entry("Game.Type.Run_0", "Run", "运行", 1, "ctx"),
                    self._entry("Game.Type.Method_0", "Talk", "新对话", 1, "ctx"),
                ],
            )

            read_entries, written_entries, diff_files = _write_dlc_dll_diff(main_file, dlc_file, dlc_out, diff_out)
            dlc_entries = json.loads(dlc_out.read_text(encoding="utf-8"))
            diff_text = diff_out.read_text(encoding="utf-8")
            diff_file_exists = diff_out.is_file()

        self.assertEqual((read_entries, written_entries, diff_files), (2, 1, 1))
        self.assertEqual([entry["key"] for entry in dlc_entries], ["Game.Type.Method_0"])
        self.assertEqual(dlc_entries[0]["translation"], "新对话")
        self.assertTrue(diff_file_exists)
        self.assertIn("--- ", diff_text)
        self.assertIn("+++ ", diff_text)
        self.assertIn('-    "translation": "旧对话"', diff_text)
        self.assertIn('+    "translation": "新对话"', diff_text)
        self.assertNotIn("%E6", diff_text)

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

    def _models(self, entries: list[dict]) -> list[ParatranzData]:
        return [ParatranzData.model_validate(entry) for entry in entries]


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
