from __future__ import annotations

import shutil
from pathlib import Path
from zipfile import ZipFile

from tqdm.auto import tqdm


class ProgressBar:
    """tqdm 的轻量包装。

    命令默认不显示进度条；只有用户传入 --progress 时才启用，避免普通日志被刷屏。
    """

    def __init__(
        self,
        *,
        total: int | None = None,
        enabled: bool = False,
        desc: str = "",
        unit: str = "it",
        unit_scale: bool = False,
    ):
        self._bar = tqdm(
            total=total,
            desc=desc,
            unit=unit,
            unit_scale=unit_scale,
            dynamic_ncols=True,
            mininterval=0.1,
            smoothing=0.1,
            disable=not enabled,
        )

    def update(self, step: int = 1) -> None:
        """推进进度条。"""
        self._bar.update(step)

    def set_postfix_str(self, text: str) -> None:
        """在进度条尾部显示当前处理对象。"""
        if text:
            self._bar.set_postfix_str(text, refresh=False)

    def close(self) -> None:
        self._bar.close()

    def __enter__(self) -> "ProgressBar":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def copy_tree_with_progress(source: Path, destination: Path, *, enabled: bool, desc: str) -> int:
    """复制目录树，并在需要时显示文件级进度。"""
    files = [path for path in source.rglob("*") if path.is_file()]
    destination.mkdir(parents=True, exist_ok=True)
    with ProgressBar(total=len(files), enabled=enabled, desc=desc, unit="文件") as progress:
        for file_path in files:
            relative = file_path.relative_to(source)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, target)
            progress.set_postfix_str(relative.as_posix())
            progress.update()
    return len(files)


def extract_zip_with_progress(archive: ZipFile, destination: Path, *, enabled: bool, desc: str) -> None:
    """安全解压 zip，并在需要时显示成员级进度。"""
    members = archive.infolist()
    destination = destination.resolve()
    for member in members:
        target = (destination / member.filename).resolve()
        if target != destination and destination not in target.parents:
            raise RuntimeError(f"压缩包成员会逃出解压目录：{member.filename}")
    with ProgressBar(total=len(members), enabled=enabled, desc=desc, unit="文件") as progress:
        for member in members:
            archive.extract(member, destination)
            progress.set_postfix_str(member.filename)
            progress.update()


__all__ = ["ProgressBar", "copy_tree_with_progress", "extract_zip_with_progress"]
