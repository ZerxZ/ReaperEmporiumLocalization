from __future__ import annotations

import shutil
from pathlib import Path
from zipfile import ZipFile

from reaper_tools.services.base import ParatranzServiceBase


class ArtifactService(ParatranzServiceBase):
    """Artifact download, caching, and extraction workflows."""

    def download(self, *, force: bool = False, show_progress: bool = False) -> Path:
        self._ensure_configured()
        self.paths.ensure_base_dirs()

        if force or not self.paths.artifact_zip.exists():
            self.logger.info("正在请求 ParaTranz 导出...")
            self.generate_artifact()
            self.api._sleeper(2)
            self.logger.info("正在下载 ParaTranz 导出包...")
            self.download_artifact(self.paths.artifact_zip, show_progress=show_progress)
        else:
            self.logger.info("使用本地缓存的 ParaTranz 导出包：{}", self.paths.artifact_zip)

        return self.extract_cached_artifact(show_progress=show_progress)

    def extract_cached_artifact(self, *, show_progress: bool = False) -> Path:
        if not self.paths.artifact_zip.exists():
            raise FileNotFoundError(f"未找到 ParaTranz 导出包：{self.paths.artifact_zip}")

        shutil.rmtree(self.paths.paratranz, ignore_errors=True)
        self.paths.paratranz.mkdir(parents=True, exist_ok=True)

        with ZipFile(self.paths.artifact_zip) as archive:
            if show_progress:
                self.context.extract_zip_with_progress(archive, self.paths.paratranz, enabled=True, desc="解压 ParaTranz")
            else:
                self.context.safe_extract_zip(archive, self.paths.paratranz)

        utf8_root = self.paths.paratranz / "utf8"
        return utf8_root if utf8_root.exists() else self.paths.paratranz


__all__ = ["ArtifactService"]
