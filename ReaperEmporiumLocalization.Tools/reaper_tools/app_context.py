from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
from zipfile import ZipFile

from reaper_tools.config import ProgressBar, ProjectPaths, Settings, logger, paths, safe_extract_zip, settings
from reaper_tools.config.progress import copy_tree_with_progress, extract_zip_with_progress


@dataclass(frozen=True, slots=True)
class AppContext:
    """Tool runtime dependencies gathered in one place.

    Business modules receive an explicit context instead of importing process-wide
    singletons directly, which makes testing and future extension simpler.
    """

    settings: Settings
    paths: ProjectPaths
    logger: Any
    progress_factory: type[ProgressBar] = ProgressBar
    copy_tree_with_progress: Callable[[Path, Path], int] = copy_tree_with_progress
    extract_zip_with_progress: Callable[[ZipFile, Path], None] = extract_zip_with_progress
    safe_extract_zip: Callable[[ZipFile, Path], None] = safe_extract_zip

    def progress(
        self,
        *,
        total: int | None = None,
        enabled: bool = False,
        desc: str = "",
        unit: str = "it",
        unit_scale: bool = False,
    ) -> ProgressBar:
        """Create a progress bar using the configured progress factory."""
        return self.progress_factory(
            total=total,
            enabled=enabled,
            desc=desc,
            unit=unit,
            unit_scale=unit_scale,
        )


def build_app_context(
    *,
    app_settings: Settings | None = None,
    project_paths: ProjectPaths | None = None,
    app_logger: Any | None = None,
) -> AppContext:
    """Build a context from explicit overrides or the default project singletons."""
    return AppContext(
        settings=app_settings or settings,
        paths=project_paths or paths,
        logger=app_logger or logger,
    )


@lru_cache(maxsize=1)
def get_app_context() -> AppContext:
    """Return the process default application context."""
    return build_app_context()


__all__ = ["AppContext", "build_app_context", "get_app_context"]
