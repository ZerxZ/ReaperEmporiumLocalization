from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from .configuration import settings
from .exceptions import ConfigurationError, SafePathError


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """集中管理工具项目会使用到的路径。

    所有派生路径都从配置对象解析而来；删除、解压这类有风险的操作会先经过
    ensure_inside 校验，确保目标仍在预期目录内部。
    """

    root: Path
    data: Path
    cache: Path
    paratranz: Path
    logs: Path
    game_root: Path | None

    @classmethod
    def from_settings(cls) -> "ProjectPaths":
        """从 .env 和默认配置构建路径集合。"""
        root = settings.filepath.root.resolve()
        data = _resolve_under(root, settings.filepath.data)
        cache = _resolve_under(root, settings.filepath.cache)
        paratranz = _resolve_under(root, settings.filepath.paratranz)
        game_root = _resolve_game_root(root, settings.filepath.game_root)
        return cls(
            root=root,
            data=data,
            cache=cache,
            paratranz=paratranz,
            logs=data / "logs",
            game_root=game_root,
        )

    @property
    def artifact_zip(self) -> Path:
        """ParaTranz 导出包的本地缓存路径。"""
        return self.cache / "paratranz_export.zip"

    def ensure_base_dirs(self) -> None:
        """创建工具运行所需的基础目录。"""
        for path in (self.data, self.cache, self.paratranz, self.logs):
            path.mkdir(parents=True, exist_ok=True)

    def require_game_root(self, override: Path | str | None = None) -> Path:
        """获取游戏根目录；命令行参数优先，其次使用配置或开发目录推断值。"""
        candidate = _resolve_game_root(self.root, Path(override) if override else self.game_root)
        if candidate is None:
            raise ConfigurationError("未配置游戏根目录。请设置 PATH_GAME_ROOT，或传入 --game-root。")
        return candidate

    def ensure_inside(self, path: Path, root: Path) -> Path:
        """确认目标路径位于指定根目录内部，避免递归删除时越界。"""
        target = path.resolve()
        anchor = root.resolve()
        if target == anchor or anchor not in target.parents:
            raise SafePathError(f"拒绝修改 {anchor} 之外的路径：{target}")
        return target


def _resolve_under(root: Path, path: Path) -> Path:
    """把相对路径解析到工具根目录下；绝对路径保持自身含义。"""
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _resolve_game_root(tool_root: Path, value: Path | None) -> Path | None:
    """解析游戏根目录；没有显式配置时按当前仓库布局向上推断。"""
    if value is not None:
        return value.resolve() if value.is_absolute() else (tool_root / value).resolve()
    try:
        return tool_root.parents[2].resolve()
    except IndexError:
        return None


def safe_extract_zip(archive: ZipFile, destination: Path) -> None:
    """安全解压 zip，拒绝带有路径穿越的压缩包成员。"""
    destination = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != destination and destination not in target.parents:
            raise RuntimeError(f"压缩包成员会逃出解压目录：{member.filename}")
    archive.extractall(destination)


paths = ProjectPaths.from_settings()


__all__ = ["ProjectPaths", "paths", "safe_extract_zip"]
