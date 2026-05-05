from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel, Field, TypeAdapter, field_validator


class StageEnum(IntEnum):
    """ParaTranz 词条阶段枚举。

    数值必须和 ParaTranz 保持一致，因此成员名和数值都不做中文化。
    """

    hidden = -1
    untranslated = 0
    translated = 1
    questionable = 2
    checked = 3
    reviewed = 5
    locked = 9


class ParatranzData(BaseModel):
    """本地翻译 JSON 中使用的基础词条结构。"""

    key: str = Field(default="")
    original: str = Field(default="")
    translation: str = Field(default="")
    stage: StageEnum = Field(default=StageEnum.untranslated)
    context: str = Field(default="")

    @field_validator("stage", mode="before")
    @classmethod
    def normalize_stage(cls, value):
        """把空阶段归一为未翻译，兼容旧导出或手工整理的数据。"""
        if value in ("", None):
            return StageEnum.untranslated
        return value

    @property
    def runtime_original(self) -> str:
        """转成游戏运行时使用的原文，恢复换行并移除回车。"""
        return self.original.replace("\\n", "\n").replace("\r", "")

    @property
    def runtime_translation(self) -> str:
        """转成游戏运行时使用的译文，恢复换行并移除回车。"""
        return self.translation.replace("\\n", "\n").replace("\r", "")

    @property
    def is_runtime_usable(self) -> bool:
        """判断词条是否足够完整，可以写入游戏运行时。"""
        return int(self.stage) >= int(StageEnum.translated) and bool(
            self.runtime_original.strip() and self.runtime_translation.strip()
        )

    def quality_rank(self) -> tuple[int, int, int]:
        """给重复词条排序，优先选择可用、阶段更高且有译文的版本。"""
        return (
            1 if self.is_runtime_usable else 0,
            int(self.stage),
            1 if self.translation.strip() else 0,
        )


paratranz_data_list_adapter = TypeAdapter(list[ParatranzData])


__all__ = ["ParatranzData", "StageEnum", "paratranz_data_list_adapter"]
