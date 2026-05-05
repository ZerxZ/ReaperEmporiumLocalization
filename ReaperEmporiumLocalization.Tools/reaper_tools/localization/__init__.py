"""Localization workflows and ParaTranz compatibility facade."""

from .compare_paratranz import (
    CompareParatranzFileReport,
    CompareParatranzResult,
    CompareParatranzSummary,
    compare_downloaded_paratranz_scope,
    download_and_compare_paratranz,
)
from .dump_builder import DumpBuildStats, build_dump_diff
from .installer import (
    InstallStats,
    PackageStats,
    install_translation_packages,
    package_final_localization,
    summarize_translation_packages,
)
from .paratranz import Paratranz

__all__ = [
    "CompareParatranzFileReport",
    "CompareParatranzResult",
    "CompareParatranzSummary",
    "DumpBuildStats",
    "InstallStats",
    "PackageStats",
    "Paratranz",
    "build_dump_diff",
    "compare_downloaded_paratranz_scope",
    "download_and_compare_paratranz",
    "install_translation_packages",
    "package_final_localization",
    "summarize_translation_packages",
]
