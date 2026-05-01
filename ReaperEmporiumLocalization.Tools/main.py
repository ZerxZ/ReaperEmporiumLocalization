from __future__ import annotations

import argparse
from pathlib import Path

from src.config import logger, paths
from src.localization.dump_builder import build_dump_diff
from src.localization.installer import install_translation_packages, summarize_translation_packages
from src.localization.paratranz import Paratranz


def _path_args(values: list[str] | None) -> list[Path]:
    if not values:
        return [paths.paratranz]
    return [Path(value) for value in values]


def cmd_download(args: argparse.Namespace) -> int:
    extracted_root = Paratranz().download(force=args.force, show_progress=args.progress)
    logger.success("ParaTranz export ready: {}", extracted_root)
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    stats = install_translation_packages(
        _path_args(args.inputs),
        game_root=Path(args.game_root) if args.game_root else None,
        clear=not args.no_clear,
        show_progress=args.progress,
    )
    logger.success(
        "Installed {} package(s): {} database file(s), {} database entries, {} dll entries",
        stats.packages,
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
    )
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    extracted_root = Paratranz().download(force=args.force, show_progress=args.progress)
    stats = install_translation_packages(
        [extracted_root],
        game_root=Path(args.game_root) if args.game_root else None,
        clear=not args.no_clear,
        show_progress=args.progress,
    )
    logger.success(
        "Pulled and installed {} package(s): {} database file(s), {} database entries, {} dll entries",
        stats.packages,
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
    )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    stats = summarize_translation_packages(_path_args(args.inputs))
    logger.info(
        "Found {} package(s): {} database file(s), {} database entries, {} dll entries",
        stats.packages,
        stats.database_files,
        stats.database_entries,
        stats.dll_entries,
    )
    return 0


def cmd_build_dump(args: argparse.Namespace) -> int:
    stats = build_dump_diff(show_progress=args.progress)
    logger.success(
        "Built dump diff: MainGame {} database file(s), {} database entries, {} dll entries; "
        "DLCGame {} / {} database file(s), {} / {} database entries, {} / {} dll entries",
        stats.main_database_files,
        stats.main_database_entries,
        stats.main_dll_entries,
        stats.dlc_database_files_written,
        stats.dlc_database_files_read,
        stats.dlc_database_entries_written,
        stats.dlc_database_entries_read,
        stats.dlc_dll_entries_written,
        stats.dlc_dll_entries_read,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reaper Emporium localization helper tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download", help="Download and extract the latest ParaTranz artifact.")
    download.add_argument("--force", action="store_true", help="Ignore cached artifact files.")
    download.add_argument("--progress", action="store_true", help="Show download/extract progress bars.")
    download.set_defaults(func=cmd_download)

    install = subparsers.add_parser("install", help="Install local translation JSON packages into the game folder.")
    install.add_argument("inputs", nargs="*", help="Package directories. Defaults to PATH_PARATRANZ.")
    install.add_argument("--game-root", help="Game root folder. Defaults to PATH_GAME_ROOT or the dev-layout guess.")
    install.add_argument("--no-clear", action="store_true", help="Keep existing installed JSON files.")
    install.add_argument("--progress", action="store_true", help="Show copy/merge progress bars.")
    install.set_defaults(func=cmd_install)

    pull = subparsers.add_parser("pull", help="Download ParaTranz export, then install it into the game folder.")
    pull.add_argument("--force", action="store_true", help="Ignore cached artifact files.")
    pull.add_argument("--game-root", help="Game root folder. Defaults to PATH_GAME_ROOT or the dev-layout guess.")
    pull.add_argument("--no-clear", action="store_true", help="Keep existing installed JSON files.")
    pull.add_argument("--progress", action="store_true", help="Show progress bars.")
    pull.set_defaults(func=cmd_pull)

    stats = subparsers.add_parser("stats", help="Count translation JSON entries in local package directories.")
    stats.add_argument("inputs", nargs="*", help="Package directories. Defaults to PATH_PARATRANZ.")
    stats.set_defaults(func=cmd_stats)

    build_dump = subparsers.add_parser(
        "build-dump",
        help="Build MainGame/DLCGame dump output, with DLCGame reduced to entries absent from MainGame.",
    )
    build_dump.add_argument("--progress", action="store_true", help="Show build progress bars.")
    build_dump.set_defaults(func=cmd_build_dump)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
