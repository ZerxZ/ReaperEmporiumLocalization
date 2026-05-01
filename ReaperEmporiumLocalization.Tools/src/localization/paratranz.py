from __future__ import annotations

import shutil
import time
from pathlib import Path
from zipfile import ZipFile

import httpx

from src.config.configuration import settings
from src.config.exceptions import ConfigurationError
from src.config.logging import logger
from src.config.paths import paths, safe_extract_zip
from src.config.progress import ProgressBar, extract_zip_with_progress


class Paratranz:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=60)
        self._base_url = "https://paratranz.cn/api"
        self._project_id = settings.paratranz.project_id

    def get_files(self) -> list:
        self._ensure_configured()
        response = self.client.get(f"{self.base_url}/projects/{self.project_id}/files", headers=self.headers)
        response.raise_for_status()
        return response.json()

    def download(self, *, force: bool = False, show_progress: bool = False) -> Path:
        self._ensure_configured()
        paths.ensure_base_dirs()

        if force or not paths.artifact_zip.exists():
            self._request_export()
            self._download_artifact(show_progress=show_progress)
        else:
            logger.info("Using cached ParaTranz artifact: {}", paths.artifact_zip)

        return self.extract_cached_artifact(show_progress=show_progress)

    def extract_cached_artifact(self, *, show_progress: bool = False) -> Path:
        if not paths.artifact_zip.exists():
            raise FileNotFoundError(f"ParaTranz artifact not found: {paths.artifact_zip}")

        shutil.rmtree(paths.paratranz, ignore_errors=True)
        paths.paratranz.mkdir(parents=True, exist_ok=True)

        with ZipFile(paths.artifact_zip) as archive:
            if show_progress:
                extract_zip_with_progress(archive, paths.paratranz, enabled=True, desc="Extract ParaTranz")
            else:
                safe_extract_zip(archive, paths.paratranz)

        utf8_root = paths.paratranz / "utf8"
        return utf8_root if utf8_root.exists() else paths.paratranz

    def _request_export(self) -> None:
        logger.info("Requesting ParaTranz export...")
        response = self.client.post(f"{self.base_url}/projects/{self.project_id}/artifacts", headers=self.headers)
        if response.status_code not in (200, 201, 202, 204, 409):
            response.raise_for_status()
        time.sleep(2)

    def _download_artifact(self, *, show_progress: bool = False) -> None:
        logger.info("Downloading ParaTranz artifact...")
        paths.cache.mkdir(parents=True, exist_ok=True)
        url = f"{self.base_url}/projects/{self.project_id}/artifacts/download"
        with self.client.stream("GET", url, headers=self.headers, follow_redirects=True) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", "0") or 0)
            with paths.artifact_zip.open("wb") as output:
                with ProgressBar(
                    total=total or None,
                    enabled=show_progress,
                    desc="Download ParaTranz",
                    unit="B",
                    unit_scale=True,
                ) as progress:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
                        progress.update(len(chunk))

    def _ensure_configured(self) -> None:
        if not self.project_id or not settings.paratranz.token:
            raise ConfigurationError("Set PARATRANZ_PROJECT_ID and PARATRANZ_TOKEN in .env first.")

    @property
    def client(self) -> httpx.Client:
        return self._client

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": settings.paratranz.token}

    @property
    def project_id(self) -> int:
        return self._project_id


__all__ = ["Paratranz"]
