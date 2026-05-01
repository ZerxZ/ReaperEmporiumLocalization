from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = ".env"


class ProjectSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROJECT_", env_file=ENV_FILE, extra="ignore")

    name: str = Field(default="ReaperEmporium-Paratranz")
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}")


class FilepathSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PATH_", env_file=ENV_FILE, extra="ignore")

    root: Path = Field(default=Path(__file__).resolve().parents[2])
    data: Path = Field(default=Path("data"))
    cache: Path = Field(default=Path("data/cache"))
    paratranz: Path = Field(default=Path("data/paratranz"))
    game_root: Path | None = Field(default=None)

    @field_validator("game_root", mode="before")
    @classmethod
    def blank_game_root_to_none(cls, value):
        if value in ("", None):
            return None
        return value


class ParatranzSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PARATRANZ_", env_file=ENV_FILE, extra="ignore")

    project_id: int = Field(default=0)
    token: str = Field(default="")

    @field_validator("project_id", mode="before")
    @classmethod
    def blank_project_id_to_zero(cls, value):
        if value in ("", None):
            return 0
        return value


class Settings(BaseSettings):
    project: ProjectSettings = Field(default_factory=ProjectSettings)
    filepath: FilepathSettings = Field(default_factory=FilepathSettings)
    paratranz: ParatranzSettings = Field(default_factory=ParatranzSettings)


settings = Settings()


__all__ = ["Settings", "settings"]
