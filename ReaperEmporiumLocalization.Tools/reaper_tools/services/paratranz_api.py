from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import TypeAdapter

from reaper_tools.app_context import AppContext, get_app_context
from reaper_tools.config.exceptions import ConfigurationError
from reaper_tools.models import (
    BatchOperationResponse,
    BatchStringOperationRequest,
    FileMetadataRequest,
    FileUploadResult,
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
    TermImportResult,
    TermWriteRequest,
    paratranz_data_list_adapter,
)


DEFAULT_BASE_URL = "https://paratranz.cn/api"


class _RateLimiter:
    """Simple serial rate limiter shared by the API client."""

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
        interval = 1 / self.settings.requests_per_second
        now = self._monotonic()
        if self._last_request_at is not None:
            wait_for = self._last_request_at + interval - now
            if wait_for > 0:
                self._sleeper(wait_for)
                now = self._monotonic()
        self._last_request_at = now


class _UploadContext:
    """Multipart upload context that always closes its file handle."""

    def __init__(self, handle, files):
        self._handle = handle
        self._files = files

    def __enter__(self):
        return self._files

    def __exit__(self, exc_type, exc, traceback):
        self._handle.close()
        return False


class ParatranzApiClient:
    """Low-level typed ParaTranz API client."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        context: AppContext | None = None,
        project_id: int | None = None,
        token: str | None = None,
        base_url: str | None = None,
        rate_limit: RateLimitSettings | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.context = context or get_app_context()
        self._client = client
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._project_id = project_id if project_id is not None else self.context.settings.paratranz.project_id
        self._token = token if token is not None else self.context.settings.paratranz.token
        self._rate_limit = rate_limit or RateLimitSettings()
        self._limiter = _RateLimiter(self._rate_limit, sleeper=sleeper)
        self._sleeper = sleeper
        self._retry_count = 0

    def get_files(self, *, project_id: int | None = None) -> list[ParatranzFile]:
        response = self._request("GET", f"/projects/{self._resolve_project_id(project_id)}/files")
        return TypeAdapter(list[ParatranzFile]).validate_python(response.json())

    def get_file(self, file_id: int, *, project_id: int | None = None) -> ParatranzFile:
        response = self._request("GET", f"/projects/{self._resolve_project_id(project_id)}/files/{file_id}")
        return ParatranzFile.model_validate(response.json())

    def create_file(
        self,
        file_path: str | Path,
        *,
        path: str = "",
        project_id: int | None = None,
    ) -> FileUploadResult:
        with self._open_upload(file_path) as files:
            response = self._request(
                "POST",
                f"/projects/{self._resolve_project_id(project_id)}/files",
                files=files,
                data={"path": path} if path else None,
            )
        return FileUploadResult.model_validate(response.json())

    def update_file(self, file_id: int, file_path: str | Path, *, project_id: int | None = None) -> ParatranzFile:
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
        payload = self._payload(metadata or FileMetadataRequest(name=name, extra=extra))
        response = self._request("PUT", f"/projects/{self._resolve_project_id(project_id)}/files/{file_id}", json=payload)
        return ParatranzFile.model_validate(response.json())

    def delete_file(self, file_id: int, *, project_id: int | None = None) -> None:
        response = self._request("DELETE", f"/projects/{self._resolve_project_id(project_id)}/files/{file_id}")
        response.raise_for_status()

    def get_file_translation(self, file_id: int, *, project_id: int | None = None) -> list[ParatranzData]:
        response = self._request("GET", f"/projects/{self._resolve_project_id(project_id)}/files/{file_id}/translation")
        return paratranz_data_list_adapter.validate_python(response.json())

    def update_file_translation(
        self,
        file_id: int,
        file_path: str | Path,
        *,
        force: bool = False,
        project_id: int | None = None,
    ) -> ParatranzFile:
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
        response = self._request("GET", f"/projects/{self._resolve_project_id(project_id)}/strings/{string_id}")
        return ParatranzString.model_validate(response.json())

    def create_string(
        self,
        request: StringWriteRequest | dict[str, Any],
        *,
        project_id: int | None = None,
    ) -> ParatranzString:
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
        response = self._request(
            "PUT",
            f"/projects/{self._resolve_project_id(project_id)}/strings/{string_id}",
            json=self._payload(request),
        )
        return ParatranzString.model_validate(response.json())

    def delete_string(self, string_id: int, *, project_id: int | None = None) -> None:
        response = self._request("DELETE", f"/projects/{self._resolve_project_id(project_id)}/strings/{string_id}")
        response.raise_for_status()

    def batch_operate_strings(
        self,
        request: BatchStringOperationRequest | dict[str, Any],
        *,
        project_id: int | None = None,
    ) -> BatchOperationResponse:
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
        response = self._request(
            "GET",
            f"/projects/{self._resolve_project_id(project_id)}/terms",
            params=self._params(page=page, pageSize=page_size),
        )
        return TypeAdapter(Page[ParatranzTerm]).validate_python(response.json())

    def get_term(self, term_id: int, *, project_id: int | None = None) -> ParatranzTerm:
        response = self._request("GET", f"/projects/{self._resolve_project_id(project_id)}/terms/{term_id}")
        return ParatranzTerm.model_validate(response.json())

    def create_term(
        self,
        request: TermWriteRequest | dict[str, Any],
        *,
        project_id: int | None = None,
    ) -> ParatranzTerm:
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
        response = self._request(
            "PUT",
            f"/projects/{self._resolve_project_id(project_id)}/terms/{term_id}",
            json=self._payload(request),
        )
        return ParatranzTerm.model_validate(response.json())

    def delete_term(self, term_id: int, *, project_id: int | None = None) -> None:
        response = self._request("DELETE", f"/projects/{self._resolve_project_id(project_id)}/terms/{term_id}")
        response.raise_for_status()

    def import_terms(self, file_path: str | Path, *, project_id: int | None = None) -> TermImportResult:
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
        response = self._request(
            "GET",
            f"/projects/{self._resolve_project_id(project_id)}/terms/{term_id}/history",
            params=self._params(page=page, pageSize=page_size),
        )
        return TypeAdapter(Page[ParatranzTermHistory]).validate_python(response.json())

    def get_artifact(self, *, project_id: int | None = None) -> ParatranzArtifact:
        response = self._request("GET", f"/projects/{self._resolve_project_id(project_id)}/artifacts")
        return ParatranzArtifact.model_validate(response.json())

    def generate_artifact(self, *, project_id: int | None = None) -> ParatranzJob:
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
        self._ensure_configured(project_id=project_id)
        target = Path(target_path) if target_path else self.context.paths.artifact_zip
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
                    with self.context.progress(
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

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
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
        return response.status_code in self._rate_limit.retry_statuses and attempt < self._rate_limit.max_retries

    def _sleep_before_retry(self, response: httpx.Response, attempt: int) -> None:
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
        resolved = project_id if project_id is not None else self.project_id
        if not resolved:
            raise ConfigurationError("请先在 .env 中设置 PARATRANZ_PROJECT_ID。")
        return resolved

    def _ensure_configured(self, *, project_id: int | None = None) -> None:
        self._resolve_project_id(project_id)
        if not self._token:
            raise ConfigurationError("请先在 .env 中设置 PARATRANZ_TOKEN。")

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _payload(self, value: Any) -> dict[str, Any]:
        if hasattr(value, "to_api_payload"):
            return value.to_api_payload()
        return {key: item for key, item in dict(value).items() if item is not None}

    def _params(self, **values: Any) -> dict[str, Any]:
        return {key: value for key, value in values.items() if value is not None}

    def _json_or_empty(self, response: httpx.Response) -> dict[str, Any]:
        if not response.content:
            return {}
        return response.json()

    def _open_upload(self, file_path: str | Path):
        path = Path(file_path)
        handle = path.open("rb")
        return _UploadContext(handle, {"file": (path.name, handle, "application/json")})

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=60)
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


__all__ = ["ParatranzApiClient"]
