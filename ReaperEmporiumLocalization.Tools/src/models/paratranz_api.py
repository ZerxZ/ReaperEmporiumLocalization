from __future__ import annotations

from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .paratranz import StageEnum


T = TypeVar("T")


class ApiModel(BaseModel):
    """ParaTranz API 模型基类。

    ParaTranz 返回值偶尔会比文档多字段，所以 extra 使用 allow；写回接口时则
    通过 to_api_payload 统一使用 alias，并过滤 None。
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def to_api_payload(self) -> dict[str, Any]:
        """生成适合直接传给 ParaTranz API 的 JSON payload。"""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class Page(ApiModel, Generic[T]):
    """ParaTranz 常见分页响应结构。"""

    page: int | None = None
    page_size: int | None = Field(default=None, alias="pageSize")
    row_count: int | None = Field(default=None, alias="rowCount")
    page_count: int | None = Field(default=None, alias="pageCount")
    results: list[T] = Field(default_factory=list)


class ParatranzTinyFile(ApiModel):
    """词条响应中嵌套的简化文件信息。"""

    id: int | None = None
    name: str | None = None


class ParatranzFile(ApiModel):
    """ParaTranz 文件信息。"""

    id: int | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    modified_at: str | None = Field(default=None, alias="modifiedAt")
    name: str = ""
    project: int | None = None
    format: str | None = None
    total: int | None = None
    translated: int | None = None
    disputed: int | None = None
    checked: int | None = None
    reviewed: int | None = None
    hidden: int | None = None
    locked: int | None = None
    words: int | None = None
    hash: str | None = None


class ParatranzString(ApiModel):
    """ParaTranz 词条信息。"""

    id: int | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    key: str = ""
    original: str = ""
    translation: str = ""
    file: ParatranzTinyFile | int | None = None
    file_id: int | None = Field(default=None, alias="fileId")
    stage: StageEnum | int | None = None
    project: int | None = None
    uid: int | None = None
    context: str = ""


class ParatranzTerm(ApiModel):
    """ParaTranz 术语信息。"""

    id: int | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    updated_by: int | None = Field(default=None, alias="updatedBy")
    pos: str | None = None
    uid: int | None = None
    term: str = ""
    translation: str = ""
    note: str | None = None
    project: int | None = None
    variants: list[str] = Field(default_factory=list)
    case_sensitive: bool | None = Field(default=None, alias="caseSensitive")


class ParatranzTermHistory(ApiModel):
    """ParaTranz 术语修改历史。"""

    id: int | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    field: str | None = None
    uid: int | None = None
    tid: int | None = None
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    target: dict[str, Any] | None = None
    operation: str | None = None


class ParatranzRevision(ApiModel):
    """ParaTranz 文件上传/导入历史。"""

    id: int | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    name: str | None = None
    filename: str | None = None
    type_: str | None = Field(default=None, alias="type")
    file: int | None = None
    uid: int | None = None
    project: int | None = None
    insert: int | None = None
    update: int | None = None
    remove: int | None = None
    hash: str | None = None
    force: bool | None = None
    incremental: bool | None = None


class ParatranzArtifact(ApiModel):
    """ParaTranz 最近一次导出结果。"""

    id: int | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    project: int | None = None
    total: int | None = None
    translated: int | None = None
    disputed: int | None = None
    reviewed: int | None = None
    hidden: int | None = None
    duration: int | None = None


class ParatranzJob(ApiModel):
    """ParaTranz 异步任务信息，例如触发导出后的任务。"""

    id: int | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    started_at: str | None = Field(default=None, alias="startedAt")
    finished_at: str | None = Field(default=None, alias="finishedAt")
    scheduled_at: str | None = Field(default=None, alias="scheduledAt")
    params: dict[str, Any] | None = None
    project: int | None = None
    uid: int | None = None
    type_: str | None = Field(default=None, alias="type")
    status: int | None = None
    result: dict[str, Any] | None = None


class FileUploadResult(ApiModel):
    """创建文件接口返回的文件和修订信息。"""

    file: ParatranzFile | None = None
    revision: ParatranzRevision | None = None


class TermImportResult(ApiModel):
    """批量导入术语接口的统计结果。"""

    inserted: int | None = None
    updated: int | None = None
    deleted: int | None = None


class BatchOperationResponse(ApiModel):
    """批量词条操作返回值。

    文档没有给出稳定结构，所以保留常见字段，并允许额外字段进入模型。
    """

    message: str | None = None
    code: int | None = None
    updated: int | None = None
    deleted: int | None = None


class StringWriteRequest(ApiModel):
    """创建或更新词条时使用的请求体。"""

    key: str | None = None
    original: str | None = None
    translation: str | None = None
    file: int | None = None
    stage: StageEnum | int | None = None
    context: str | None = None


class BatchStringOperationRequest(ApiModel):
    """ParaTranz 原生批量词条修改/删除请求。"""

    op: Literal["update", "delete"]
    ids: list[int] = Field(alias="id")
    stage: StageEnum | int | None = None
    translation: str | None = None

    @field_validator("ids")
    @classmethod
    def require_ids(cls, value: list[int]) -> list[int]:
        """批量操作必须至少包含一个词条 ID。"""
        if not value:
            raise ValueError("至少需要提供一个词条 ID。")
        return value


class TermWriteRequest(ApiModel):
    """创建或更新术语时使用的请求体。"""

    pos: str | None = None
    term: str | None = None
    translation: str | None = None
    note: str | None = None
    variants: list[str] | None = None
    case_sensitive: bool | None = Field(default=None, alias="caseSensitive")


class FileMetadataRequest(ApiModel):
    """修改 ParaTranz 文件元信息时使用的请求体。"""

    name: str | None = None
    extra: dict[str, Any] | None = None


class RateLimitSettings(ApiModel):
    """访问 ParaTranz 时使用的保守限速和重试设置。"""

    requests_per_second: float = Field(default=1.0, gt=0)
    max_retries: int = Field(default=5, ge=0)
    initial_retry_delay: float = Field(default=5.0, ge=0)
    max_retry_delay: float = Field(default=60.0, ge=0)
    retry_statuses: set[int] = Field(default_factory=lambda: {429, 500, 502, 503, 504})


class SyncAction(ApiModel):
    """批量同步/迁移计划中的单个动作。"""

    action: str
    local_path: Path | None = None
    remote_name: str | None = None
    file_id: int | None = None
    project_id: int | None = None
    target_project_id: int | None = None
    method: str | None = None
    endpoint: str | None = None
    reason: str | None = None
    will_write: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class SyncPlan(ApiModel):
    """批量同步计划。

    dry_run 模式会只返回计划，不对 ParaTranz 发起写入请求。
    """

    actions: list[SyncAction] = Field(default_factory=list)
    dry_run: bool = True
    source_root: Path | None = None

    @property
    def write_count(self) -> int:
        """计划中真正会写入远端或文件系统的动作数量。"""
        return sum(1 for action in self.actions if action.will_write)


class BatchResult(ApiModel):
    """批量同步或批量修改的执行结果。"""

    planned: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    retried: int = 0
    dry_run: bool = True
    errors: list[str] = Field(default_factory=list)
    actions: list[SyncAction] = Field(default_factory=list)


class MigrationResult(ApiModel):
    """项目间迁移或本地版本迁移的执行结果。"""

    planned: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    migrated_entries: int = 0
    dry_run: bool = True
    errors: list[str] = Field(default_factory=list)
    actions: list[SyncAction] = Field(default_factory=list)


__all__ = [
    "ApiModel",
    "BatchOperationResponse",
    "BatchResult",
    "BatchStringOperationRequest",
    "FileMetadataRequest",
    "FileUploadResult",
    "MigrationResult",
    "Page",
    "ParatranzArtifact",
    "ParatranzFile",
    "ParatranzJob",
    "ParatranzRevision",
    "ParatranzString",
    "ParatranzTerm",
    "ParatranzTermHistory",
    "ParatranzTinyFile",
    "RateLimitSettings",
    "StringWriteRequest",
    "SyncAction",
    "SyncPlan",
    "TermImportResult",
    "TermWriteRequest",
]
