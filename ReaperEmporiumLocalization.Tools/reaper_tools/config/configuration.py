from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = ".env"


class ProjectSettings(BaseSettings):
    """项目级配置。

    这些字段只影响工具自己的日志和显示，不参与游戏文件或 ParaTranz 协议。
    环境变量统一使用 PROJECT_ 前缀，便于和路径、ParaTranz 配置区分。
    """

    model_config = SettingsConfigDict(env_prefix="PROJECT_", env_file=ENV_FILE, extra="ignore")

    name: str = Field(default="ReaperEmporium-Paratranz")
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}")


class FilepathSettings(BaseSettings):
    """路径配置。

    相对路径都以工具项目根目录为基准解析。这样无论从哪个工作目录运行命令，
    输出目录、缓存目录和 ParaTranz 解包目录都能稳定落在工具项目内。
    """

    model_config = SettingsConfigDict(env_prefix="PATH_", env_file=ENV_FILE, extra="ignore")

    root: Path = Field(default=Path(__file__).resolve().parents[2])
    data: Path = Field(default=Path("data"))
    cache: Path = Field(default=Path("data/cache"))
    paratranz: Path = Field(default=Path("data/paratranz"))
    game_root: Path | None = Field(default=None)

    @field_validator("game_root", mode="before")
    @classmethod
    def blank_game_root_to_none(cls, value):
        """允许 .env 中把 PATH_GAME_ROOT 留空；空值会被视为未配置。"""
        if value in ("", None):
            return None
        return value


class ParatranzSettings(BaseSettings):
    """ParaTranz 访问配置。

    project_id 和 token 只有在调用远端 API 时才是必需项；本地统计、安装、
    构建转储等离线命令可以不填写。
    """

    model_config = SettingsConfigDict(env_prefix="PARATRANZ_", env_file=ENV_FILE, extra="ignore")

    project_id: int = Field(default=0)
    token: str = Field(default="")

    @field_validator("project_id", mode="before")
    @classmethod
    def blank_project_id_to_zero(cls, value):
        """把空项目 ID 归一成 0，方便后续统一做“是否已配置”的判断。"""
        if value in ("", None):
            return 0
        return value


class Settings(BaseSettings):
    """工具的顶层配置对象，聚合各个配置分组。"""

    project: ProjectSettings = Field(default_factory=ProjectSettings)
    filepath: FilepathSettings = Field(default_factory=FilepathSettings)
    paratranz: ParatranzSettings = Field(default_factory=ParatranzSettings)


settings = Settings()


__all__ = ["Settings", "settings"]
