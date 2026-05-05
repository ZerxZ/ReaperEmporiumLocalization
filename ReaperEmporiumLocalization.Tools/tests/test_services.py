from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from reaper_tools.app_context import build_app_context
from reaper_tools.config.paths import ProjectPaths
from reaper_tools.services.artifacts import ArtifactService


class _FakeArtifactApi:
    def __init__(self, context) -> None:
        self.context = context
        self.generated = 0
        self.downloaded = 0

    def _ensure_configured(self, *, project_id=None) -> None:
        return None

    def generate_artifact(self, *, project_id=None) -> None:
        self.generated += 1

    def download_artifact(self, target_path=None, *, show_progress=False, project_id=None) -> Path:
        self.downloaded += 1
        raise AssertionError("cached artifact flow should not re-download")


class ArtifactServiceTests(unittest.TestCase):
    def test_download_uses_cached_artifact_and_extracts_utf8_root(self) -> None:
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
            context = build_app_context(project_paths=project_paths)
            api = _FakeArtifactApi(context)
            service = ArtifactService(api, context=context)

            project_paths.cache.mkdir(parents=True, exist_ok=True)
            with ZipFile(project_paths.artifact_zip, "w") as archive:
                archive.writestr("utf8/database/db_Test.json", "[]")

            extracted_root = service.download(force=False, show_progress=False)

            self.assertEqual(api.generated, 0)
            self.assertEqual(api.downloaded, 0)
            self.assertEqual(extracted_root, project_paths.paratranz / "utf8")
            self.assertTrue((extracted_root / "database" / "db_Test.json").is_file())


if __name__ == "__main__":
    unittest.main()
