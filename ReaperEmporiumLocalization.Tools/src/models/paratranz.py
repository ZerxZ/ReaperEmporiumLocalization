from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel, Field, TypeAdapter, field_validator


class StageEnum(IntEnum):
    hidden = -1
    untranslated = 0
    translated = 1
    questionable = 2
    checked = 3
    reviewed = 5
    locked = 9


class ParatranzData(BaseModel):
    key: str = Field(default="")
    original: str = Field(default="")
    translation: str = Field(default="")
    stage: StageEnum = Field(default=StageEnum.untranslated)
    context: str = Field(default="")

    @field_validator("stage", mode="before")
    @classmethod
    def normalize_stage(cls, value):
        if value in ("", None):
            return StageEnum.untranslated
        return value

    @property
    def runtime_original(self) -> str:
        return self.original.replace("\\n", "\n").replace("\r", "")

    @property
    def runtime_translation(self) -> str:
        return self.translation.replace("\\n", "\n").replace("\r", "")

    @property
    def is_runtime_usable(self) -> bool:
        return int(self.stage) >= int(StageEnum.translated) and bool(
            self.runtime_original.strip() and self.runtime_translation.strip()
        )

    def quality_rank(self) -> tuple[int, int, int]:
        return (
            1 if self.is_runtime_usable else 0,
            int(self.stage),
            1 if self.translation.strip() else 0,
        )


paratranz_data_list_adapter = TypeAdapter(list[ParatranzData])


__all__ = ["ParatranzData", "StageEnum", "paratranz_data_list_adapter"]
