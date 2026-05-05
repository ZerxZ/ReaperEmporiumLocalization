from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from reaper_tools.localization.database_filter import load_database_dump_filter
from reaper_tools.localization.paratranz_cleanup import delete_filtered_database_files
from reaper_tools.models import ParatranzFile


class _Progress:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def set_postfix_str(self, _value: str) -> None:
        return None

    def update(self, _amount: int = 1) -> None:
        return None


class _Context:
    def __init__(self, root: Path) -> None:
        self.paths = SimpleNamespace(root=root, game_root=None)

    def progress(self, **_kwargs):
        return _Progress()


class _FakeParatranz:
    project_id = 123

    def __init__(self, files: list[ParatranzFile]) -> None:
        self.files = files
        self.deleted: list[tuple[int, int | None]] = []

    def get_files(self, *, project_id: int | None = None) -> list[ParatranzFile]:
        return self.files

    def delete_file(self, file_id: int, *, project_id: int | None = None) -> None:
        self.deleted.append((file_id, project_id))


class ParatranzCleanupTests(unittest.TestCase):
    def test_default_filter_matches_image_voice_and_sound_tables(self) -> None:
        dump_filter = load_database_dump_filter()

        self.assertTrue(dump_filter.matches("db_ImageCutin"))
        self.assertTrue(dump_filter.matches("db_ImageDotQuarterCharaWalkOneBody"))
        self.assertTrue(dump_filter.matches("db_VoiceChara"))
        self.assertTrue(dump_filter.matches("db_ResourceSoundBgmUse"))
        self.assertTrue(dump_filter.matches("db_ResourceSoundSeUse"))
        self.assertTrue(dump_filter.matches("db_Direct"))
        self.assertFalse(dump_filter.matches("db_EventInfo"))

    def test_delete_filtered_database_files_dry_run_only_plans_database_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            files = [
                ParatranzFile(id=1, name="MainGame/database/asset_00_text/db_ImageCutin.json"),
                ParatranzFile(id=2, name="DLCGame/database/asset_01_text/db_ResourceSoundSeUse.json"),
                ParatranzFile(id=3, name="MainGame/database/asset_00_text/db_EventInfo.json"),
                ParatranzFile(id=4, name="MainGame/scene/SceneTitle.json"),
                ParatranzFile(id=5, name="MainGame/dll_strings.json"),
            ]
            api = _FakeParatranz(files)

            result = delete_filtered_database_files(api=api, context=_Context(Path(temp_dir)), dry_run=True)

        self.assertEqual(result.summary.scanned_files, 5)
        self.assertEqual(result.summary.matched_files, 2)
        self.assertEqual(result.summary.planned_files, 2)
        self.assertEqual([action.remote_name for action in result.actions], [files[0].name, files[1].name])
        self.assertEqual(api.deleted, [])

    def test_delete_filtered_database_files_execute_deletes_matching_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            files = [
                ParatranzFile(id=1, name="MainGame/database/asset_00_text/db_ImageCutin.json"),
                ParatranzFile(id=2, name="DLCGame/database/asset_01_text/db_EventInfo.json"),
            ]
            api = _FakeParatranz(files)

            result = delete_filtered_database_files(
                api=api,
                context=_Context(Path(temp_dir)),
                project_id=456,
                dry_run=False,
            )

        self.assertEqual(result.summary.deleted_files, 1)
        self.assertEqual(api.deleted, [(1, 456)])

    def test_custom_filter_ignores_invalid_regex_and_uses_valid_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "database_dump_filter.json"
            config_path.write_text(
                json.dumps(
                    {
                        "excluded_asset_names": ["db_CustomExact"],
                        "excluded_asset_name_regex": ["^db_Custom", "["],
                    }
                ),
                encoding="utf-8",
            )

            dump_filter = load_database_dump_filter(config_path)

        self.assertTrue(dump_filter.matches("db_CustomExact"))
        self.assertTrue(dump_filter.matches("db_CustomRegex"))
        self.assertEqual(dump_filter.invalid_regex, ("[",))


if __name__ == "__main__":
    unittest.main()
