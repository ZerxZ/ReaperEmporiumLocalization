from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import httpx
from pydantic import TypeAdapter

from src.config.configuration import settings
from src.config.exceptions import ConfigurationError
from src.config.logging import logger
from src.config.paths import paths, safe_extract_zip
from src.config.progress import ProgressBar, extract_zip_with_progress
from src.models import (
    BatchOperationResponse,
    BatchResult,
    BatchStringOperationRequest,
    FileMetadataRequest,
    FileUploadResult,
    MigrationResult,
    Page,
    ParatranzArtifact,
    ParatranzData,
    ParatranzFile,
    ParatranzJob,
    ParatranzRevision,
    ParatranzString,
    ParatranzTerm,
    ParatranzTermHistory,
    RateLimitSettings,
    StageEnum,
    StringWriteRequest,
    SyncAction,
    SyncPlan,
    TermImportResult,
    TermWriteRequest,
    paratranz_data_list_adapter,
)

MAIN_GAME_DIR = "MainGame"
DLC_GAME_DIR = "DLCGame"
DLL_STRINGS_FILE = "dll_strings.json"
DATABASE_DIR = "database"
DEFAULT_BASE_URL = "https://paratranz.cn/api"
MIGRATION_REPORT_FILE = "migration_report.json"
_CAB_SUFFIX_PATTERN = re.compile(r"-CAB-.*$")
_NUMBER_SUFFIX_PATTERN = re.compile(r"_\d+$")
_ASSET_TEXT_DIR_PATTERN = re.compile(r"^asset_\d+_text(?:_DLC)?$", re.IGNORECASE)


@dataclass(slots=True)
class _LegacyEntryCandidate:
    """旧 ParaTranz 词条候选，保留来源用于择优和报告冲突。"""

    entry: ParatranzData
    source_path: str
    source_priority: int
    order: int


@dataclass(slots=True)
class _LegacyTranslationIndex:
    """旧译文索引，按目标文件优先，同时保留全局兜底池。"""

    database_by_file: dict[str, dict[str, list[_LegacyEntryCandidate]]]
    database_global: dict[str, list[_LegacyEntryCandidate]]
    dll_by_file: dict[str, dict[tuple[str, str, str], list[_LegacyEntryCandidate]]]
    dll_global: dict[tuple[str, str, str], list[_LegacyEntryCandidate]]
    dll_original_by_file: dict[str, dict[str, list[_LegacyEntryCandidate]]]
    dll_original_global: dict[str, list[_LegacyEntryCandidate]]
    file_mappings: list[dict[str, Any]]
    duplicate_files: dict[str, list[str]]
    source_files: int = 0
    source_entries: int = 0


class _RateLimiter:
    """简单串行限速器。

    ParaTranz 是公共服务，批量同步时不能把请求打得太密。这里用最朴素的
    “距离上次请求至少间隔 N 秒”策略，保证所有 API 调用按顺序慢慢发出。
    """

    def __init__(
        self,
        settings: RateLimitSettings,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    def wait(self) -> None:
        """在下一次请求前等待，确保不超过配置的每秒请求数。"""
        interval = 1 / self.settings.requests_per_second
        now = self._monotonic()
        if self._last_request_at is not None:
            wait_for = self._last_request_at + interval - now
            if wait_for > 0:
                self._sleeper(wait_for)
                now = self._monotonic()
        self._last_request_at = now


class Paratranz:
    """ParaTranz 核心 API 客户端。

    这个类同时承担三类工作：
    1. 低层 API 封装，返回 Pydantic 模型；
    2. 原有下载导出包流程，供 CLI 的 下载包/拉取安装 使用；
    3. 批量同步、批量修改和迁移计划，默认 dry-run，避免误写远端。
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        project_id: int | None = None,
        token: str | None = None,
        base_url: str | None = None,
        rate_limit: RateLimitSettings | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        """创建客户端。

        参数都允许外部注入，测试可以传 MockTransport，实际运行则默认读取 .env。
        sleeper 也可注入，方便测试限速和重试时不用真的等待。
        """
        self._client = client or httpx.Client(timeout=60)
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._project_id = project_id if project_id is not None else settings.paratranz.project_id
        self._token = token if token is not None else settings.paratranz.token
        self._rate_limit = rate_limit or RateLimitSettings()
        self._limiter = _RateLimiter(self._rate_limit, sleeper=sleeper)
        self._sleeper = sleeper
        self._retry_count = 0

    def get_files(self, *, project_id: int | None = None) -> list[ParatranzFile]:
        """获取项目文件列表。"""
        response = self._request("GET", f"/projects/{self._resolve_project_id(project_id)}/files")
        return TypeAdapter(list[ParatranzFile]).validate_python(response.json())

    def get_file(self, file_id: int, *, project_id: int | None = None) -> ParatranzFile:
        """获取单个文件信息。"""
        response = self._request("GET", f"/projects/{self._resolve_project_id(project_id)}/files/{file_id}")
        return ParatranzFile.model_validate(response.json())

    def create_file(
        self,
        file_path: str | Path,
        *,
        path: str = "",
        project_id: int | None = None,
    ) -> FileUploadResult:
        """上传并创建文件。

        path 是 ParaTranz 远端目录，文件名来自 file_path 自身。
        """
        with self._open_upload(file_path) as files:
            response = self._request(
                "POST",
                f"/projects/{self._resolve_project_id(project_id)}/files",
                files=files,
                data={"path": path} if path else None,
            )
        return FileUploadResult.model_validate(response.json())

    def update_file(self, file_id: int, file_path: str | Path, *, project_id: int | None = None) -> ParatranzFile:
        """更新文件原文内容，不改动已有译文。"""
        with self._open_upload(file_path) as files:
            response = self._request(
                "POST",
                f"/projects/{self._resolve_project_id(project_id)}/files/{file_id}",
                files=files,
            )
        return ParatranzFile.model_validate(response.json())

    def save_file(
        self,
        file_id: int,
        metadata: FileMetadataRequest | dict[str, Any] | None = None,
        *,
        name: str | None = None,
        extra: dict[str, Any] | None = None,
        project_id: int | None = None,
    ) -> ParatranzFile:
        """修改 ParaTranz 文件元信息，例如远端文件名或 extra。"""
        payload = self._payload(metadata or FileMetadataRequest(name=name, extra=extra))
        response = self._request("PUT", f"/projects/{self._resolve_project_id(project_id)}/files/{file_id}", json=payload)
        return ParatranzFile.model_validate(response.json())

    def delete_file(self, file_id: int, *, project_id: int | None = None) -> None:
        """删除远端文件。"""
        response = self._request("DELETE", f"/projects/{self._resolve_project_id(project_id)}/files/{file_id}")
        response.raise_for_status()

    def get_file_translation(self, file_id: int, *, project_id: int | None = None) -> list[ParatranzData]:
        """获取某个文件的翻译 JSON 数据。"""
        response = self._request(
            "GET",
            f"/projects/{self._resolve_project_id(project_id)}/files/{file_id}/translation",
        )
        return paratranz_data_list_adapter.validate_python(response.json())

    def update_file_translation(
        self,
        file_id: int,
        file_path: str | Path,
        *,
        force: bool = False,
        project_id: int | None = None,
    ) -> ParatranzFile:
        """上传并更新某个文件的译文。

        默认不强制覆盖人工编辑过的译文；需要强制覆盖时显式传入 force=True。
        """
        with self._open_upload(file_path) as files:
            response = self._request(
                "POST",
                f"/projects/{self._resolve_project_id(project_id)}/files/{file_id}/translation",
                files=files,
                data={"force": str(force).lower()},
            )
        return ParatranzFile.model_validate(response.json())

    def get_file_revisions(
        self,
        *,
        file: int | None = None,
        type: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        project_id: int | None = None,
    ) -> Page[ParatranzRevision]:
        """获取文件上传/导入历史。"""
        response = self._request(
            "GET",
            f"/projects/{self._resolve_project_id(project_id)}/files/revisions",
            params=self._params(file=file, type=type, page=page, pageSize=page_size),
        )
        return TypeAdapter(Page[ParatranzRevision]).validate_python(response.json())

    def get_strings(
        self,
        *,
        file: int | None = None,
        stage: StageEnum | int | None = None,
        detailed: bool | None = None,
        page: int | None = None,
        page_size: int | None = None,
        project_id: int | None = None,
    ) -> Page[ParatranzString]:
        """分页获取项目词条。"""
        response = self._request(
            "GET",
            f"/projects/{self._resolve_project_id(project_id)}/strings",
            params=self._params(
                file=file,
                stage=int(stage) if stage is not None else None,
                detailed=1 if detailed else ("" if detailed is False else None),
                page=page,
                pageSize=page_size,
            ),
        )
        return TypeAdapter(Page[ParatranzString]).validate_python(response.json())

    def get_string(self, string_id: int, *, project_id: int | None = None) -> ParatranzString:
        """获取单个词条。"""
        response = self._request("GET", f"/projects/{self._resolve_project_id(project_id)}/strings/{string_id}")
        return ParatranzString.model_validate(response.json())

    def create_string(
        self,
        request: StringWriteRequest | dict[str, Any],
        *,
        project_id: int | None = None,
    ) -> ParatranzString:
        """创建词条。"""
        response = self._request(
            "POST",
            f"/projects/{self._resolve_project_id(project_id)}/strings",
            json=self._payload(request),
        )
        return ParatranzString.model_validate(response.json())

    def save_string(
        self,
        string_id: int,
        request: StringWriteRequest | dict[str, Any],
        *,
        project_id: int | None = None,
    ) -> ParatranzString:
        """更新词条。"""
        response = self._request(
            "PUT",
            f"/projects/{self._resolve_project_id(project_id)}/strings/{string_id}",
            json=self._payload(request),
        )
        return ParatranzString.model_validate(response.json())

    def delete_string(self, string_id: int, *, project_id: int | None = None) -> None:
        """删除单个词条。"""
        response = self._request("DELETE", f"/projects/{self._resolve_project_id(project_id)}/strings/{string_id}")
        response.raise_for_status()

    def batch_operate_strings(
        self,
        request: BatchStringOperationRequest | dict[str, Any],
        *,
        project_id: int | None = None,
    ) -> BatchOperationResponse:
        """调用 ParaTranz 原生批量词条修改/删除接口。"""
        response = self._request(
            "PUT",
            f"/projects/{self._resolve_project_id(project_id)}/strings",
            json=self._payload(request),
        )
        return BatchOperationResponse.model_validate(self._json_or_empty(response))

    def get_terms(
        self,
        *,
        page: int | None = None,
        page_size: int | None = None,
        project_id: int | None = None,
    ) -> Page[ParatranzTerm]:
        """分页获取项目术语。"""
        response = self._request(
            "GET",
            f"/projects/{self._resolve_project_id(project_id)}/terms",
            params=self._params(page=page, pageSize=page_size),
        )
        return TypeAdapter(Page[ParatranzTerm]).validate_python(response.json())

    def get_term(self, term_id: int, *, project_id: int | None = None) -> ParatranzTerm:
        """获取单个术语。"""
        response = self._request("GET", f"/projects/{self._resolve_project_id(project_id)}/terms/{term_id}")
        return ParatranzTerm.model_validate(response.json())

    def create_term(
        self,
        request: TermWriteRequest | dict[str, Any],
        *,
        project_id: int | None = None,
    ) -> ParatranzTerm:
        """创建术语。"""
        response = self._request(
            "POST",
            f"/projects/{self._resolve_project_id(project_id)}/terms",
            json=self._payload(request),
        )
        return ParatranzTerm.model_validate(response.json())

    def save_term(
        self,
        term_id: int,
        request: TermWriteRequest | dict[str, Any],
        *,
        project_id: int | None = None,
    ) -> ParatranzTerm:
        """更新术语。"""
        response = self._request(
            "PUT",
            f"/projects/{self._resolve_project_id(project_id)}/terms/{term_id}",
            json=self._payload(request),
        )
        return ParatranzTerm.model_validate(response.json())

    def delete_term(self, term_id: int, *, project_id: int | None = None) -> None:
        """删除术语。"""
        response = self._request("DELETE", f"/projects/{self._resolve_project_id(project_id)}/terms/{term_id}")
        response.raise_for_status()

    def import_terms(self, file_path: str | Path, *, project_id: int | None = None) -> TermImportResult:
        """批量导入术语 JSON 文件。"""
        with self._open_upload(file_path) as files:
            response = self._request(
                "PUT",
                f"/projects/{self._resolve_project_id(project_id)}/terms",
                files=files,
            )
        return TermImportResult.model_validate(response.json())

    def get_term_history(
        self,
        term_id: int,
        *,
        page: int | None = None,
        page_size: int | None = None,
        project_id: int | None = None,
    ) -> Page[ParatranzTermHistory]:
        """获取某个术语的历史记录。"""
        response = self._request(
            "GET",
            f"/projects/{self._resolve_project_id(project_id)}/terms/{term_id}/history",
            params=self._params(page=page, pageSize=page_size),
        )
        return TypeAdapter(Page[ParatranzTermHistory]).validate_python(response.json())

    def get_artifact(self, *, project_id: int | None = None) -> ParatranzArtifact:
        """获取最近一次导出结果。"""
        response = self._request("GET", f"/projects/{self._resolve_project_id(project_id)}/artifacts")
        return ParatranzArtifact.model_validate(response.json())

    def generate_artifact(self, *, project_id: int | None = None) -> ParatranzJob:
        """触发 ParaTranz 生成导出包。

        409 通常表示已有导出任务或导出状态冲突；旧实现允许这个状态，这里继续兼容。
        """
        response = self._request(
            "POST",
            f"/projects/{self._resolve_project_id(project_id)}/artifacts",
            allowed_statuses={409},
        )
        return ParatranzJob.model_validate(self._json_or_empty(response))

    def download_artifact(
        self,
        target_path: str | Path | None = None,
        *,
        show_progress: bool = False,
        project_id: int | None = None,
    ) -> Path:
        """下载导出包到指定路径。"""
        self._ensure_configured(project_id=project_id)
        target = Path(target_path) if target_path else paths.artifact_zip
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"{self.base_url}/projects/{self._resolve_project_id(project_id)}/artifacts/download"

        for attempt in range(self._rate_limit.max_retries + 1):
            self._limiter.wait()
            with self.client.stream("GET", url, headers=self.headers, follow_redirects=True) as response:
                if self._should_retry(response, attempt):
                    self._sleep_before_retry(response, attempt)
                    continue
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", "0") or 0)
                with target.open("wb") as output:
                    with ProgressBar(
                        total=total or None,
                        enabled=show_progress,
                        desc="下载 ParaTranz",
                        unit="B",
                        unit_scale=True,
                    ) as progress:
                        for chunk in response.iter_bytes():
                            output.write(chunk)
                            progress.update(len(chunk))
                return target

        raise RuntimeError("下载 ParaTranz 导出包时进入了不可达的重试状态。")

    def download(self, *, force: bool = False, show_progress: bool = False) -> Path:
        """请求导出、下载缓存包并解压，保持旧 CLI 行为。"""
        self._ensure_configured()
        paths.ensure_base_dirs()

        if force or not paths.artifact_zip.exists():
            logger.info("正在请求 ParaTranz 导出...")
            self.generate_artifact()
            self._sleeper(2)
            logger.info("正在下载 ParaTranz 导出包...")
            self.download_artifact(paths.artifact_zip, show_progress=show_progress)
        else:
            logger.info("使用本地缓存的 ParaTranz 导出包：{}", paths.artifact_zip)

        return self.extract_cached_artifact(show_progress=show_progress)

    def extract_cached_artifact(self, *, show_progress: bool = False) -> Path:
        """解压本地缓存的 ParaTranz 导出包。"""
        if not paths.artifact_zip.exists():
            raise FileNotFoundError(f"未找到 ParaTranz 导出包：{paths.artifact_zip}")

        shutil.rmtree(paths.paratranz, ignore_errors=True)
        paths.paratranz.mkdir(parents=True, exist_ok=True)

        with ZipFile(paths.artifact_zip) as archive:
            if show_progress:
                extract_zip_with_progress(archive, paths.paratranz, enabled=True, desc="解压 ParaTranz")
            else:
                safe_extract_zip(archive, paths.paratranz)

        utf8_root = paths.paratranz / "utf8"
        return utf8_root if utf8_root.exists() else paths.paratranz

    def build_sync_plan(
        self,
        source_root: str | Path,
        *,
        project_id: int | None = None,
        remote_prefix: str = "",
        update_mode: str = "translation",
        create_missing: bool = True,
        update_existing: bool = True,
        dry_run: bool = True,
    ) -> SyncPlan:
        """生成本地文件到 ParaTranz 的同步计划。

        这里只读取远端文件列表并扫描本地 JSON，不进行写入。调用方可以先查看
        SyncPlan，再决定是否把 dry_run 关掉真正执行。
        """

        source = Path(source_root)
        remote_files = {self._normalize_remote_name(item.name): item for item in self.get_files(project_id=project_id)}
        actions: list[SyncAction] = []

        for file_path in self._json_files(source):
            remote_name = self._remote_name(source, file_path, remote_prefix)
            remote_file = remote_files.get(self._normalize_remote_name(remote_name))
            if remote_file and update_existing:
                action = "update_file_translation" if update_mode == "translation" else "update_file"
                actions.append(
                    SyncAction(
                        action=action,
                        local_path=file_path,
                        remote_name=remote_name,
                        file_id=remote_file.id,
                        project_id=self._resolve_project_id(project_id),
                        method="POST",
                        endpoint=f"/projects/{self._resolve_project_id(project_id)}/files/{remote_file.id}"
                        + ("/translation" if action == "update_file_translation" else ""),
                    )
                )
            elif remote_file:
                actions.append(
                    SyncAction(
                        action="skip",
                        local_path=file_path,
                        remote_name=remote_name,
                        file_id=remote_file.id,
                        project_id=self._resolve_project_id(project_id),
                        reason="远端文件已存在，且 update_existing 为 false。",
                        will_write=False,
                    )
                )
            elif create_missing:
                actions.append(
                    SyncAction(
                        action="create_file",
                        local_path=file_path,
                        remote_name=remote_name,
                        project_id=self._resolve_project_id(project_id),
                        method="POST",
                        endpoint=f"/projects/{self._resolve_project_id(project_id)}/files",
                    )
                )
            else:
                actions.append(
                    SyncAction(
                        action="skip",
                        local_path=file_path,
                        remote_name=remote_name,
                        project_id=self._resolve_project_id(project_id),
                        reason="远端文件不存在，且 create_missing 为 false。",
                        will_write=False,
                    )
                )

        return SyncPlan(actions=actions, dry_run=dry_run, source_root=source)

    def sync_files_from_local(
        self,
        source_root: str | Path,
        *,
        project_id: int | None = None,
        remote_prefix: str = "",
        update_mode: str = "translation",
        create_missing: bool = True,
        update_existing: bool = True,
        force_translation: bool = False,
        dry_run: bool = True,
    ) -> BatchResult:
        """把本地 JSON 批量同步到 ParaTranz。

        默认 dry_run=True，因此只返回计划结果；真正写入时仍会串行限速，并把单个
        文件失败记录到 BatchResult，继续处理后续动作。
        """

        if update_mode not in {"translation", "source"}:
            raise ValueError("update_mode 必须是 'translation' 或 'source'。")

        plan = self.build_sync_plan(
            source_root,
            project_id=project_id,
            remote_prefix=remote_prefix,
            update_mode=update_mode,
            create_missing=create_missing,
            update_existing=update_existing,
            dry_run=dry_run,
        )
        result = BatchResult(planned=plan.write_count, skipped=len(plan.actions) - plan.write_count, dry_run=dry_run)
        result.actions = plan.actions
        if dry_run:
            return result

        before_retries = self.retry_count
        for action in plan.actions:
            if not action.will_write:
                continue
            try:
                if action.action == "create_file":
                    path = self._remote_parent(action.remote_name or "")
                    self.create_file(action.local_path or "", path=path, project_id=project_id)
                elif action.action == "update_file_translation":
                    self.update_file_translation(
                        action.file_id or 0,
                        action.local_path or "",
                        force=force_translation,
                        project_id=project_id,
                    )
                elif action.action == "update_file":
                    self.update_file(action.file_id or 0, action.local_path or "", project_id=project_id)
                result.succeeded += 1
            except Exception as exc:  # noqa: BLE001 - 批量结果需要收集失败并继续处理后续动作。
                result.failed += 1
                result.errors.append(f"{action.remote_name}: {exc}")
        result.retried = self.retry_count - before_retries
        return result

    def batch_update_strings(
        self,
        ids: Iterable[int],
        *,
        stage: StageEnum | int | None = None,
        translation: str | None = None,
        chunk_size: int = 50,
        dry_run: bool = True,
        project_id: int | None = None,
    ) -> BatchResult:
        """批量更新词条阶段或译文，默认只生成 dry-run 计划。"""
        chunks = self._chunks(list(ids), chunk_size)
        actions = [
            SyncAction(
                action="batch_update_strings",
                project_id=self._resolve_project_id(project_id),
                method="PUT",
                endpoint=f"/projects/{self._resolve_project_id(project_id)}/strings",
                metadata={"ids": chunk, "stage": int(stage) if stage is not None else None, "translation": translation},
            )
            for chunk in chunks
        ]
        return self._execute_string_batches(actions, "update", dry_run=dry_run, project_id=project_id)

    def batch_delete_strings(
        self,
        ids: Iterable[int],
        *,
        chunk_size: int = 50,
        dry_run: bool = True,
        project_id: int | None = None,
    ) -> BatchResult:
        """批量删除词条，默认只生成 dry-run 计划。"""
        chunks = self._chunks(list(ids), chunk_size)
        actions = [
            SyncAction(
                action="batch_delete_strings",
                project_id=self._resolve_project_id(project_id),
                method="PUT",
                endpoint=f"/projects/{self._resolve_project_id(project_id)}/strings",
                metadata={"ids": chunk},
            )
            for chunk in chunks
        ]
        return self._execute_string_batches(actions, "delete", dry_run=dry_run, project_id=project_id)

    def migrate_project(
        self,
        source_project_id: int,
        target_project_id: int,
        *,
        include_files: bool = True,
        include_translations: bool = True,
        include_terms: bool = True,
        overwrite: bool = False,
        dry_run: bool = True,
    ) -> MigrationResult:
        """在两个 ParaTranz 项目之间迁移文件、译文和术语。

        迁移不会自动删除目标项目中的内容；目标已有文件时，只有 overwrite=True
        才会更新译文。
        """

        actions: list[SyncAction] = []
        if include_files or include_translations:
            source_files = self.get_files(project_id=source_project_id)
            target_files = {self._normalize_remote_name(item.name): item for item in self.get_files(project_id=target_project_id)}
            for source_file in source_files:
                target_file = target_files.get(self._normalize_remote_name(source_file.name))
                if target_file is None and include_files:
                    actions.append(
                        SyncAction(
                            action="migrate_create_file",
                            remote_name=source_file.name,
                            file_id=source_file.id,
                            project_id=source_project_id,
                            target_project_id=target_project_id,
                        )
                    )
                elif target_file and include_translations and overwrite:
                    actions.append(
                        SyncAction(
                            action="migrate_update_translation",
                            remote_name=source_file.name,
                            file_id=source_file.id,
                            project_id=source_project_id,
                            target_project_id=target_project_id,
                            metadata={"target_file_id": target_file.id},
                        )
                    )
                elif target_file:
                    actions.append(
                        SyncAction(
                            action="skip",
                            remote_name=source_file.name,
                            file_id=source_file.id,
                            project_id=source_project_id,
                            target_project_id=target_project_id,
                            reason="目标文件已存在，且 overwrite 为 false。",
                            will_write=False,
                        )
                    )

        if include_terms:
            for term_page in self._iter_term_pages(project_id=source_project_id):
                if term_page.results:
                    actions.append(
                        SyncAction(
                            action="migrate_import_terms",
                            project_id=source_project_id,
                            target_project_id=target_project_id,
                            metadata={"terms": [self._term_import_payload(term) for term in term_page.results]},
                        )
                    )

        result = MigrationResult(
            planned=sum(1 for action in actions if action.will_write),
            skipped=sum(1 for action in actions if not action.will_write),
            dry_run=dry_run,
            actions=actions,
        )
        if dry_run:
            return result

        for action in actions:
            if not action.will_write:
                continue
            try:
                if action.action in {"migrate_create_file", "migrate_update_translation"}:
                    entries = self.get_file_translation(action.file_id or 0, project_id=source_project_id)
                    with self._temporary_paratranz_file(entries, filename=Path(action.remote_name or "").name) as temp_file:
                        if action.action == "migrate_create_file":
                            self.create_file(temp_file, path=self._remote_parent(action.remote_name or ""), project_id=target_project_id)
                        else:
                            self.update_file_translation(
                                int(action.metadata["target_file_id"]),
                                temp_file,
                                force=overwrite,
                                project_id=target_project_id,
                            )
                    result.migrated_entries += len(entries)
                elif action.action == "migrate_import_terms":
                    with self._temporary_json_file(action.metadata["terms"]) as temp_file:
                        self.import_terms(temp_file, project_id=target_project_id)
                    result.migrated_entries += len(action.metadata["terms"])
                result.succeeded += 1
            except Exception as exc:  # noqa: BLE001 - 迁移流程需要报告所有失败项。
                result.failed += 1
                result.errors.append(f"{action.remote_name or action.action}: {exc}")
        return result

    def migrate_terms_to_project(
        self,
        source_project_id: int,
        target_project_id: int | None = None,
        *,
        dry_run: bool = True,
        show_progress: bool = False,
    ) -> MigrationResult:
        """把旧 ParaTranz 项目的术语迁移到目标项目。
        这个流程只处理术语，不碰文件和译文。默认 dry-run，只生成迁移计划；真正执行时会
        按页读取旧项目术语，再调用目标项目的术语导入接口。
        """

        resolved_target_project_id = self._resolve_project_id(target_project_id)
        if source_project_id == resolved_target_project_id:
            raise ValueError("源项目和目标项目不能相同。")

        actions: list[SyncAction] = []
        page_number = 1

        with ProgressBar(total=None, enabled=show_progress, desc="读取旧项目术语", unit="页") as progress:
            while True:
                page = self.get_terms(page=page_number, page_size=100, project_id=source_project_id)
                if page.results:
                    actions.append(
                        SyncAction(
                            action="migrate_terms",
                            project_id=source_project_id,
                            target_project_id=resolved_target_project_id,
                            will_write=True,
                            metadata={
                                "page": page_number,
                                "terms": [self._term_import_payload(term) for term in page.results],
                            },
                        )
                    )
                progress.set_postfix_str(f"第 {page_number} 页")
                progress.update()
                if not page.results or (page.page_count is not None and page_number >= page.page_count):
                    break
                page_number += 1

        result = MigrationResult(
            planned=len(actions),
            dry_run=dry_run,
            actions=actions,
        )
        if dry_run:
            return result

        with ProgressBar(total=len(actions), enabled=show_progress, desc="迁移项目术语", unit="页") as progress:
            for action in actions:
                try:
                    with self._temporary_json_file(action.metadata["terms"], filename=f"terms-page-{action.metadata['page']}.json") as temp_file:
                        self.import_terms(temp_file, project_id=resolved_target_project_id)
                    result.succeeded += 1
                    result.migrated_entries += len(action.metadata["terms"])
                except Exception as exc:  # noqa: BLE001 - 术语迁移需要继续处理后续页并报告失败
                    result.failed += 1
                    result.errors.append(f"第 {action.metadata['page']} 页术语: {exc}")
                progress.set_postfix_str(f"第 {action.metadata['page']} 页")
                progress.update()

        return result

    def migrate_local_translations(
        self,
        old_root: str | Path,
        new_root: str | Path,
        output_root: str | Path,
        *,
        dry_run: bool = True,
    ) -> MigrationResult:
        """把旧本地翻译迁移到新转储目录。

        普通数据库按 (key, original) 匹配；DLL 字符串按新导出的
        类名.方法名_索引 key、original 和 context 精确匹配。
        """

        old_root_path = Path(old_root)
        new_root_path = Path(new_root)
        output_root_path = Path(output_root)
        actions: list[SyncAction] = []
        migrated_entries = 0

        for new_file in self._json_files(new_root_path):
            relative = new_file.relative_to(new_root_path)
            old_file = old_root_path / relative
            output_file = output_root_path / relative
            new_entries = self._read_paratranz_file(new_file)
            old_entries = self._read_paratranz_file(old_file) if old_file.exists() else []
            migrated = self._merge_local_translations(relative, old_entries, new_entries)
            migrated_entries += migrated
            actions.append(
                SyncAction(
                    action="migrate_local_translations",
                    local_path=new_file,
                    remote_name=relative.as_posix(),
                    will_write=not dry_run,
                    metadata={"output": output_file.as_posix(), "migrated_entries": migrated},
                )
            )
            if not dry_run:
                self._write_paratranz_file(output_file, new_entries)

        return MigrationResult(
            planned=len(actions),
            succeeded=0 if dry_run else len(actions),
            migrated_entries=migrated_entries,
            dry_run=dry_run,
            actions=actions,
        )

    def migrate_legacy_translations_to_dump(
        self,
        source_root: str | Path | None = None,
        dump_root: str | Path | None = None,
        output_root: str | Path | None = None,
        *,
        source_project_id: int | None = None,
        dry_run: bool = False,
        show_progress: bool = False,
    ) -> MigrationResult:
        """把历史 ParaTranz 译文迁移到当前 build/dump 新结构。

        这个流程只读取旧本地导出或旧远程项目，并把结果写到本地 output_root；它不会调用
        ParaTranz 的任何写入接口。数据库按 original 精确迁移，DLL 按新 key、original、
        context 精确迁移，避免把历史结构里的相似词条误套到新提取文本上。
        """

        source_root_path = Path(source_root) if source_root is not None else paths.paratranz
        dump_root_path = Path(dump_root) if dump_root is not None else paths.root / "build" / "dump"
        output_root_path = Path(output_root) if output_root is not None else paths.root / "build" / "migrated"

        if not dump_root_path.is_dir():
            raise FileNotFoundError(f"新转储目录不存在：{dump_root_path}")
        if not source_root_path.exists() and source_project_id is None:
            raise FileNotFoundError(f"旧 ParaTranz 导出目录不存在：{source_root_path}")

        target_files = self._migration_target_files(dump_root_path)
        if not target_files:
            raise FileNotFoundError(f"未在新转储目录中找到可迁移的 JSON：{dump_root_path}")

        index = self._build_legacy_translation_index(
            source_root_path if source_root_path.exists() else None,
            source_project_id=source_project_id,
            show_progress=show_progress,
        )
        if not dry_run:
            self._reset_migration_output(output_root_path, dump_root_path)

        actions: list[SyncAction] = []
        migrated_entries = 0
        unmatched_entries = 0
        conflicts: list[dict[str, Any]] = []

        with ProgressBar(total=len(target_files), enabled=show_progress, desc="迁移旧译文", unit="文件") as progress:
            for target_file in target_files:
                relative = target_file.relative_to(dump_root_path)
                output_file = output_root_path / relative
                entries = self._read_paratranz_file(target_file)
                migrated, unmatched = self._merge_legacy_dump_entries(relative, entries, index, conflicts)
                migrated_entries += migrated
                unmatched_entries += unmatched
                actions.append(
                    SyncAction(
                        action="migrate_legacy_translations",
                        local_path=target_file,
                        remote_name=relative.as_posix(),
                        will_write=not dry_run,
                        metadata={
                            "output": output_file.as_posix(),
                            "migrated_entries": migrated,
                            "unmatched_entries": unmatched,
                        },
                    )
                )
                if not dry_run:
                    self._write_paratranz_file(output_file, entries)
                progress.set_postfix_str(relative.as_posix())
                progress.update()

        duplicate_files = [
            {"logical_path": logical_path, "sources": sources}
            for logical_path, sources in sorted(index.duplicate_files.items())
            if len(sources) > 1
        ]
        report = {
            "source_root": self._report_path(source_root_path),
            "source_project_id": source_project_id,
            "dump_root": self._report_path(dump_root_path),
            "output_root": self._report_path(output_root_path),
            "dry_run": dry_run,
            "source_files": index.source_files,
            "source_entries": index.source_entries,
            "target_files": len(target_files),
            "migrated_entries": migrated_entries,
            "unmatched_entries": unmatched_entries,
            "duplicate_files": duplicate_files,
            "conflicts": conflicts,
            "file_mappings": index.file_mappings,
        }
        if not dry_run:
            self._write_migration_report(output_root_path / MIGRATION_REPORT_FILE, report)

        return MigrationResult(
            planned=len(actions),
            succeeded=0 if dry_run else len(actions),
            skipped=unmatched_entries,
            migrated_entries=migrated_entries,
            dry_run=dry_run,
            actions=actions,
            report=report,
        )

    def _execute_string_batches(
        self,
        actions: list[SyncAction],
        op: str,
        *,
        dry_run: bool,
        project_id: int | None,
    ) -> BatchResult:
        """执行批量词条操作的公共分块逻辑。"""
        result = BatchResult(planned=len(actions), dry_run=dry_run, actions=actions)
        if dry_run:
            return result

        before_retries = self.retry_count
        for action in actions:
            try:
                self.batch_operate_strings(
                    BatchStringOperationRequest(
                        op=op, id=action.metadata["ids"], stage=action.metadata.get("stage"), translation=action.metadata.get("translation")
                    ),
                    project_id=project_id,
                )
                result.succeeded += 1
            except Exception as exc:  # noqa: BLE001 - 批量结果需要收集失败并继续处理后续动作。
                result.failed += 1
                result.errors.append(f"{action.action}: {exc}")
        result.retried = self.retry_count - before_retries
        return result

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """统一发送 HTTP 请求，并处理限速、授权头和可重试状态码。"""
        if not self._token:
            raise ConfigurationError("请先在 .env 中设置 PARATRANZ_TOKEN。")
        allowed_statuses = set(kwargs.pop("allowed_statuses", set()) or set())
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Authorization", self.auth_token)
        kwargs["headers"] = headers
        if "params" in kwargs:
            kwargs["params"] = self._params(**(kwargs["params"] or {}))

        for attempt in range(self._rate_limit.max_retries + 1):
            self._limiter.wait()
            response = self.client.request(method, self._url(path), **kwargs)
            if self._should_retry(response, attempt):
                self._sleep_before_retry(response, attempt)
                continue
            if response.status_code in allowed_statuses:
                return response
            response.raise_for_status()
            return response

        raise RuntimeError("请求 ParaTranz API 时进入了不可达的重试状态。")

    def _should_retry(self, response: httpx.Response, attempt: int) -> bool:
        """判断当前响应是否应该退避后重试。"""
        return response.status_code in self._rate_limit.retry_statuses and attempt < self._rate_limit.max_retries

    def _sleep_before_retry(self, response: httpx.Response, attempt: int) -> None:
        """根据 Retry-After 或指数退避策略等待下一次重试。"""
        self._retry_count += 1
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = self._rate_limit.initial_retry_delay
        else:
            delay = self._rate_limit.initial_retry_delay * (2**attempt)
        self._sleeper(min(delay, self._rate_limit.max_retry_delay))

    def _resolve_project_id(self, project_id: int | None = None) -> int:
        """解析项目 ID；显式参数优先，其次使用客户端默认值。"""
        resolved = project_id if project_id is not None else self.project_id
        if not resolved:
            raise ConfigurationError("请先在 .env 中设置 PARATRANZ_PROJECT_ID。")
        return resolved

    def _ensure_configured(self, *, project_id: int | None = None) -> None:
        """确认远端 API 所需配置齐全。"""
        self._resolve_project_id(project_id)
        if not self._token:
            raise ConfigurationError("请先在 .env 中设置 PARATRANZ_TOKEN。")

    def _url(self, path: str) -> str:
        """拼接完整 API URL。"""
        return f"{self.base_url}/{path.lstrip('/')}"

    def _payload(self, value: Any) -> dict[str, Any]:
        """把 Pydantic 模型或 dict 转成去掉 None 的 API payload。"""
        if hasattr(value, "to_api_payload"):
            return value.to_api_payload()
        return {key: item for key, item in dict(value).items() if item is not None}

    def _params(self, **values: Any) -> dict[str, Any]:
        """过滤掉值为 None 的 query 参数。"""
        return {key: value for key, value in values.items() if value is not None}

    def _json_or_empty(self, response: httpx.Response) -> dict[str, Any]:
        """兼容无响应体的成功请求。"""
        if not response.content:
            return {}
        return response.json()

    def _open_upload(self, file_path: str | Path):
        """打开上传文件，并组装 httpx multipart 所需结构。"""
        path = Path(file_path)
        handle = path.open("rb")
        return _UploadContext(handle, {"file": (path.name, handle, "application/json")})

    def _temporary_paratranz_file(self, entries: list[ParatranzData], *, filename: str | None = None):
        """把词条列表写成临时 JSON 文件，用于项目间迁移上传。"""
        payload = [entry.model_dump(mode="json") for entry in entries]
        return self._temporary_json_file(payload, filename=filename)

    def _temporary_json_file(self, payload: Any, *, filename: str | None = None):
        """创建临时 JSON 文件上下文。"""
        return _TemporaryJsonFile(payload, filename=filename)

    def _read_paratranz_file(self, file_path: Path) -> list[ParatranzData]:
        """读取本地 ParaTranz JSON 文件。"""
        payload = json.loads(file_path.read_text(encoding="utf-8-sig"))
        return paratranz_data_list_adapter.validate_python(payload)

    def _write_paratranz_file(self, target: Path, entries: list[ParatranzData]) -> None:
        """写出本地 ParaTranz JSON 文件。"""
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = [entry.model_dump(mode="json") for entry in entries]
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    def _merge_local_translations(
        self,
        relative: Path,
        old_entries: list[ParatranzData],
        new_entries: list[ParatranzData],
    ) -> int:
        """把旧翻译合并到新词条列表中，并返回成功迁移数量。"""
        if relative.name == DLL_STRINGS_FILE:
            old_by_identity = {(entry.key, entry.original, entry.context): entry for entry in old_entries}
            identity = lambda entry: (entry.key, entry.original, entry.context)
        else:
            old_by_identity = {(entry.key, entry.original): entry for entry in old_entries}
            identity = lambda entry: (entry.key, entry.original)

        migrated = 0
        for entry in new_entries:
            old_entry = old_by_identity.get(identity(entry))
            if old_entry is None:
                continue
            entry.translation = old_entry.translation
            entry.stage = old_entry.stage
            migrated += 1
        return migrated

    def _build_legacy_translation_index(
        self,
        source_root: Path | None,
        *,
        source_project_id: int | None,
        show_progress: bool,
    ) -> _LegacyTranslationIndex:
        """读取本地/远程旧译文，并建立按文件与全局兜底的迁移索引。"""
        index = _LegacyTranslationIndex({}, {}, {}, {}, {}, {}, [], {})
        order = 0

        if source_root is not None:
            local_files = self._legacy_local_json_files(source_root)
            with ProgressBar(total=len(local_files), enabled=show_progress, desc="读取本地旧译文", unit="文件") as progress:
                for file_path in local_files:
                    relative_name = file_path.relative_to(source_root).as_posix()
                    entries = self._read_paratranz_file(file_path)
                    order = self._add_legacy_file_to_index(
                        index,
                        relative_name,
                        entries,
                        source_priority=0,
                        order=order,
                    )
                    progress.set_postfix_str(relative_name)
                    progress.update()

        if source_project_id is not None:
            remote_files = self.get_files(project_id=source_project_id)
            with ProgressBar(total=len(remote_files), enabled=show_progress, desc="读取远程旧项目", unit="文件") as progress:
                for remote_file in remote_files:
                    if remote_file.id is None or not remote_file.name:
                        progress.update()
                        continue
                    entries = self.get_file_translation(remote_file.id, project_id=source_project_id)
                    order = self._add_legacy_file_to_index(
                        index,
                        remote_file.name,
                        entries,
                        source_priority=1,
                        order=order,
                    )
                    progress.set_postfix_str(remote_file.name)
                    progress.update()

        return index

    def _add_legacy_file_to_index(
        self,
        index: _LegacyTranslationIndex,
        source_name: str,
        entries: list[ParatranzData],
        *,
        source_priority: int,
        order: int,
    ) -> int:
        """把一个旧文件的词条加入迁移索引，重复逻辑文件只记录不覆盖。"""
        normalized_source = self._normalize_remote_name(source_name)
        logical_path = self._legacy_logical_dump_path(normalized_source)
        logical_key = logical_path.as_posix() if logical_path is not None else None
        is_dll = self._is_legacy_dll_source(normalized_source)

        index.source_files += 1
        index.source_entries += len(entries)
        index.file_mappings.append(
            {
                "source": normalized_source,
                "logical_path": logical_key,
                "entries": len(entries),
                "kind": "dll" if is_dll else "database",
            }
        )
        if logical_key is not None:
            index.duplicate_files.setdefault(logical_key, []).append(normalized_source)

        for entry in entries:
            candidate = _LegacyEntryCandidate(entry, normalized_source, source_priority, order)
            order += 1
            if is_dll:
                identity = (entry.key, entry.original, entry.context)
                original_identity = entry.runtime_original
                index.dll_global.setdefault(identity, []).append(candidate)
                if logical_key is not None:
                    index.dll_by_file.setdefault(logical_key, {}).setdefault(identity, []).append(candidate)
                if entry.key.isdecimal() and original_identity.strip():
                    index.dll_original_global.setdefault(original_identity, []).append(candidate)
                    if logical_key is not None:
                        index.dll_original_by_file.setdefault(logical_key, {}).setdefault(original_identity, []).append(candidate)
                continue

            identity = entry.runtime_original
            if not identity.strip():
                continue
            index.database_global.setdefault(identity, []).append(candidate)
            if logical_key is not None:
                index.database_by_file.setdefault(logical_key, {}).setdefault(identity, []).append(candidate)
        return order

    def _is_legacy_dll_source(self, source_name: str) -> bool:
        """旧项目里 dll 文件夹等价于当前统一的 dll_strings.json。"""
        parts = [part.casefold() for part in Path(self._normalize_remote_name(source_name)).parts]
        return Path(source_name).name == DLL_STRINGS_FILE or "dll" in parts or "dll_strings" in parts

    def _merge_legacy_dump_entries(
        self,
        relative: Path,
        entries: list[ParatranzData],
        index: _LegacyTranslationIndex,
        conflicts: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """把旧译文索引合并进一个新 dump 文件，返回迁移/未匹配词条数。"""
        relative_key = relative.as_posix()
        migrated = 0
        unmatched = 0
        is_dll = relative.name == DLL_STRINGS_FILE

        for entry in entries:
            if is_dll:
                identity = (entry.key, entry.original, entry.context)
                file_candidates = index.dll_by_file.get(relative_key, {}).get(identity, [])
                candidates = file_candidates or index.dll_global.get(identity, [])
                chosen = self._choose_legacy_candidate(
                    candidates,
                    target_file=relative_key,
                    identity=identity,
                    conflicts=conflicts,
                )
                if chosen is None:
                    original_identity = entry.runtime_original
                    file_candidates = index.dll_original_by_file.get(relative_key, {}).get(original_identity, [])
                    candidates = file_candidates or index.dll_original_global.get(original_identity, [])
                    chosen = self._choose_legacy_candidate(
                        candidates,
                        target_file=relative_key,
                        identity=original_identity,
                        conflicts=conflicts,
                    )
            else:
                identity = entry.runtime_original
                file_candidates = index.database_by_file.get(relative_key, {}).get(identity, [])
                candidates = file_candidates or index.database_global.get(identity, [])
                chosen = self._choose_legacy_candidate(
                    candidates,
                    target_file=relative_key,
                    identity=identity,
                    conflicts=conflicts,
                )
            if chosen is None:
                unmatched += 1
                continue
            entry.translation = chosen.entry.translation
            entry.stage = chosen.entry.stage
            migrated += 1
        return migrated, unmatched

    def _choose_legacy_candidate(
        self,
        candidates: list[_LegacyEntryCandidate],
        *,
        target_file: str,
        identity: str | tuple[str, str, str],
        conflicts: list[dict[str, Any]],
    ) -> _LegacyEntryCandidate | None:
        """按译文质量和来源优先级选择一个旧词条，质量相同冲突写入报告。"""
        usable = [candidate for candidate in candidates if candidate.entry.translation.strip()]
        if not usable:
            return None

        stable = sorted(usable, key=lambda candidate: (candidate.source_path.casefold(), candidate.order))
        best_quality = max(candidate.entry.quality_rank() for candidate in stable)
        top_quality = [candidate for candidate in stable if candidate.entry.quality_rank() == best_quality]
        translations = sorted({candidate.entry.translation for candidate in top_quality if candidate.entry.translation.strip()})
        if len(translations) > 1:
            conflicts.append(
                {
                    "target_file": target_file,
                    "identity": list(identity) if isinstance(identity, tuple) else identity,
                    "translations": translations,
                    "sources": [candidate.source_path for candidate in top_quality],
                }
            )

        best_source_priority = max(candidate.source_priority for candidate in top_quality)
        for candidate in top_quality:
            if candidate.source_priority == best_source_priority:
                return candidate
        return top_quality[0]

    def _legacy_local_json_files(self, source_root: Path) -> list[Path]:
        """列出旧本地导出中的 JSON，兼容 utf8、database 和历史平铺目录。"""
        roots: list[Path] = []
        utf8_root = source_root / "utf8"
        if utf8_root.is_dir():
            roots.append(utf8_root)
        roots.append(source_root)

        files: list[Path] = []
        seen: set[Path] = set()
        for root in roots:
            if not root.exists():
                continue
            for file_path in sorted(root.rglob("*.json"), key=lambda item: item.as_posix().casefold()):
                resolved = file_path.resolve()
                if resolved in seen or file_path.name == MIGRATION_REPORT_FILE:
                    continue
                seen.add(resolved)
                files.append(file_path)
        return files

    def _legacy_logical_dump_path(self, source_name: str) -> Path | None:
        """把旧 ParaTranz 文件名映射到 build/dump 下的新逻辑路径。"""
        parts = [part for part in Path(self._normalize_remote_name(source_name)).parts if part not in {"", "."}]
        if not parts:
            return None
        if parts[0].casefold() == "utf8":
            parts = parts[1:]
        if not parts:
            return None

        if self._is_legacy_dll_source(source_name):
            return self._legacy_dll_logical_path(parts)
        if parts[0] in {MAIN_GAME_DIR, DLC_GAME_DIR}:
            return self._legacy_existing_dump_path(parts)
        if parts[0] == DATABASE_DIR:
            return self._legacy_database_path_from_parts(parts[1:])

        asset_index = next((index for index, part in enumerate(parts) if _ASSET_TEXT_DIR_PATTERN.match(part)), None)
        if asset_index is not None:
            return self._legacy_database_path_from_parts(parts[asset_index:])
        if parts[-1] == DLL_STRINGS_FILE and parts[0] in {MAIN_GAME_DIR, DLC_GAME_DIR}:
            return Path(parts[0]) / DLL_STRINGS_FILE
        return None

    def _legacy_dll_logical_path(self, parts: list[str]) -> Path:
        """把旧 DLL 文件夹映射到当前 MainGame/DLCGame 的 dll_strings.json。"""
        lowered = [part.casefold() for part in parts]
        filename = Path(parts[-1]).stem.casefold() if parts else ""
        if any(part in {DLC_GAME_DIR.casefold(), "dlc"} or part.endswith("_dlc") for part in lowered) or "dlc" in filename:
            return Path(DLC_GAME_DIR) / DLL_STRINGS_FILE
        return Path(MAIN_GAME_DIR) / DLL_STRINGS_FILE

    def _legacy_existing_dump_path(self, parts: list[str]) -> Path | None:
        """兼容已经整理成 MainGame/DLCGame 的旧目录。"""
        game_dir = parts[0]
        if len(parts) >= 2 and parts[1] == DLL_STRINGS_FILE:
            return Path(game_dir) / DLL_STRINGS_FILE
        if len(parts) >= 3 and parts[1] == DATABASE_DIR:
            clean_parts = [*parts[2:-1], self._clean_legacy_json_file_name(parts[-1])]
            return Path(game_dir) / DATABASE_DIR / Path(*clean_parts)
        return None

    def _legacy_database_path_from_parts(self, parts: list[str]) -> Path | None:
        """把 asset_XX_text 目录映射到 MainGame/DLCGame database 目录。"""
        if len(parts) < 2 or not _ASSET_TEXT_DIR_PATTERN.match(parts[0]):
            return None
        asset_dir = parts[0]
        game_dir = DLC_GAME_DIR if asset_dir.casefold().endswith("_dlc") else MAIN_GAME_DIR
        target_asset_dir = asset_dir[:-4] if game_dir == DLC_GAME_DIR and asset_dir.casefold().endswith("_dlc") else asset_dir
        clean_parts = [target_asset_dir, *parts[1:-1], self._clean_legacy_json_file_name(parts[-1])]
        return Path(game_dir) / DATABASE_DIR / Path(*clean_parts)

    def _clean_legacy_json_file_name(self, file_name: str) -> str:
        """清理历史 CAB/hash 和数字后缀，只保留稳定 JSON 文件名。"""
        path = Path(file_name)
        stem = _CAB_SUFFIX_PATTERN.sub("", path.stem)
        stem = _NUMBER_SUFFIX_PATTERN.sub("", stem)
        return f"{stem}.json"

    def _migration_target_files(self, dump_root: Path) -> list[Path]:
        """只迁移 MainGame/DLCGame 里的 JSON，不处理 diff 目录。"""
        files: list[Path] = []
        for game_dir in (MAIN_GAME_DIR, DLC_GAME_DIR):
            game_root = dump_root / game_dir
            files.extend(self._json_files(game_root))
        return sorted(files, key=lambda item: item.relative_to(dump_root).as_posix().casefold())

    def _reset_migration_output(self, output_root: Path, dump_root: Path) -> None:
        """重建 build/migrated，避免旧迁移产物残留。"""
        resolved_output = output_root.resolve()
        if resolved_output == dump_root.resolve():
            raise ValueError("迁移输出目录不能和 build/dump 相同。")
        if output_root.exists():
            if len(resolved_output.parts) <= 2:
                raise ValueError(f"拒绝清理过高层级目录：{output_root}")
            shutil.rmtree(output_root)
        output_root.mkdir(parents=True, exist_ok=True)

    def _write_migration_report(self, target: Path, report: dict[str, Any]) -> None:
        """写出迁移报告，方便人工检查重复文件和冲突译文。"""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    def _report_path(self, path: Path) -> str:
        """迁移报告里使用相对路径，避免写入本机绝对盘符。"""
        resolved = path.resolve()
        for base in (paths.root, Path.cwd()):
            try:
                return Path(os.path.relpath(resolved, base.resolve())).as_posix()
            except (OSError, ValueError):
                continue
        return path.as_posix()

    def _term_import_payload(self, term: ParatranzTerm) -> dict[str, Any]:
        """把术语响应模型收敛成导入接口真正需要的字段。"""
        return TermWriteRequest(
            pos=term.pos,
            term=term.term,
            translation=term.translation,
            note=term.note,
            variants=term.variants,
            case_sensitive=term.case_sensitive,
        ).to_api_payload()

    def _iter_term_pages(self, *, project_id: int) -> Iterable[Page[ParatranzTerm]]:
        """按页迭代项目术语，供项目间迁移使用。"""
        page_number = 1
        while True:
            page = self.get_terms(page=page_number, page_size=100, project_id=project_id)
            yield page
            if not page.results or (page.page_count is not None and page_number >= page.page_count):
                break
            page_number += 1

    def _json_files(self, root: Path) -> list[Path]:
        """稳定列出目录内所有 JSON 文件。"""
        if not root.exists():
            return []
        return sorted(root.rglob("*.json"), key=lambda item: item.relative_to(root).as_posix().casefold())

    def _remote_name(self, source_root: Path, file_path: Path, remote_prefix: str) -> str:
        """根据本地相对路径生成 ParaTranz 远端文件名。"""
        relative = file_path.relative_to(source_root).as_posix()
        prefix = remote_prefix.strip("/")
        return f"{prefix}/{relative}" if prefix else relative

    def _remote_parent(self, remote_name: str) -> str:
        """从远端文件名中提取 ParaTranz 创建文件接口需要的目录。"""
        parent = Path(remote_name).parent.as_posix()
        if parent == ".":
            return ""
        return f"{parent}/"

    def _normalize_remote_name(self, name: str) -> str:
        """统一远端文件名分隔符，便于本地和远端匹配。"""
        return name.replace("\\", "/").strip("/")

    def _chunks(self, values: list[int], chunk_size: int) -> list[list[int]]:
        """把 ID 列表切成安全的小批次。"""
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0。")
        return [values[index : index + chunk_size] for index in range(0, len(values), chunk_size)]

    @property
    def client(self) -> httpx.Client:
        return self._client

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def auth_token(self) -> str:
        token = self._token.strip()
        if token.lower().startswith("bearer "):
            return token
        return f"Bearer {token}"

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": self.auth_token}

    @property
    def project_id(self) -> int:
        return self._project_id

    @property
    def retry_count(self) -> int:
        return self._retry_count


class _UploadContext:
    """上传文件上下文，确保 multipart 请求结束后关闭文件句柄。"""

    def __init__(self, handle, files):
        self._handle = handle
        self._files = files

    def __enter__(self):
        return self._files

    def __exit__(self, exc_type, exc, traceback):
        self._handle.close()
        return False


class _TemporaryJsonFile:
    """临时 JSON 文件上下文。

    如果指定 filename，会创建临时目录并保留该文件名，确保上传到 ParaTranz 时
    远端仍能拿到期望的文件名。
    """

    def __init__(self, payload: Any, *, filename: str | None = None):
        self._payload = payload
        self._filename = filename
        self._name: str | None = None
        self._directory: tempfile.TemporaryDirectory | None = None

    def __enter__(self) -> Path:
        if self._filename:
            self._directory = tempfile.TemporaryDirectory()
            target = Path(self._directory.name) / Path(self._filename).name
            self._name = str(target)
            target.write_text(json.dumps(self._payload, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
                self._name = handle.name
                json.dump(self._payload, handle, ensure_ascii=False, indent=2)
        return Path(self._name)

    def __exit__(self, exc_type, exc, traceback):
        if self._directory is not None:
            self._directory.cleanup()
        elif self._name:
            Path(self._name).unlink(missing_ok=True)
        return False


__all__ = ["Paratranz"]
