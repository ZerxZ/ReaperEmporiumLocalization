from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from reaper_tools.config.configuration import FilepathSettings, ParatranzSettings
from reaper_tools.config.exceptions import SafePathError
from reaper_tools.config.paths import ProjectPaths, safe_extract_zip


class ConfigAndPathTests(unittest.TestCase):
    def test_blank_env_values_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text("PATH_GAME_ROOT=\nPARATRANZ_PROJECT_ID=\n", encoding="utf-8")

            with patch.dict("os.environ", {}, clear=True):
                filepath = FilepathSettings(_env_file=env_file)
                paratranz = ParatranzSettings(_env_file=env_file)

        self.assertIsNone(filepath.game_root)
        self.assertEqual(paratranz.project_id, 0)

    def test_require_game_root_prefers_override_then_configured_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            configured_game_root = root / "configured-game"
            override_game_root = root / "override-game"
            project_paths = ProjectPaths(
                root=root,
                data=root / "data",
                cache=root / "cache",
                paratranz=root / "paratranz",
                logs=root / "logs",
                game_root=configured_game_root,
            )

            self.assertEqual(project_paths.require_game_root(), configured_game_root.resolve())
            self.assertEqual(project_paths.require_game_root(override_game_root), override_game_root.resolve())

            without_game_root = ProjectPaths(
                root=root,
                data=root / "data",
                cache=root / "cache",
                paratranz=root / "paratranz",
                logs=root / "logs",
                game_root=None,
            )
            self.assertEqual(without_game_root.require_game_root(), root.parents[2].resolve())

    def test_ensure_inside_accepts_child_and_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_paths = ProjectPaths(
                root=root,
                data=root / "data",
                cache=root / "cache",
                paratranz=root / "paratranz",
                logs=root / "logs",
                game_root=None,
            )
            child = root / "data" / "child"
            sibling = root.parent / "elsewhere"

            self.assertEqual(project_paths.ensure_inside(child, root), child.resolve())
            with self.assertRaises(SafePathError):
                project_paths.ensure_inside(root, root)
            with self.assertRaises(SafePathError):
                project_paths.ensure_inside(sibling, root)

    def test_safe_extract_zip_blocks_zip_slip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "bad.zip"
            destination = root / "extract"
            destination.mkdir()

            with ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", "bad")

            with ZipFile(archive_path) as archive:
                with self.assertRaises(RuntimeError):
                    safe_extract_zip(archive, destination)


if __name__ == "__main__":
    unittest.main()
