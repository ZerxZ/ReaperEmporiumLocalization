from __future__ import annotations

import json
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable
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
DLL_STRINGS_FILE = "dll_strings.json"
DATABASE_DIR = "database"
DEFAULT_BASE_URL = "https://paratranz.cn/api"


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
                            metadata={"terms": [term.to_api_payload() for term in term_page.results]},
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
