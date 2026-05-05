from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from reaper_tools.app_context import AppContext, get_app_context
from reaper_tools.models import RateLimitSettings
from reaper_tools.services import ArtifactService, DEFAULT_BASE_URL, MigrationService, ParatranzApiClient, SyncService


class Paratranz:
    """Compatibility facade over the split ParaTranz services."""

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
        self.api = ParatranzApiClient(
            client,
            context=self.context,
            project_id=project_id,
            token=token,
            base_url=base_url,
            rate_limit=rate_limit,
            sleeper=sleeper,
        )
        self.artifacts = ArtifactService(self.api, context=self.context)
        self.sync = SyncService(self.api, context=self.context)
        self.migration = MigrationService(self.api, context=self.context, sync_service=self.sync)

    def __getattr__(self, name: str) -> Any:
        for component in (self.artifacts, self.sync, self.migration, self.api):
            if hasattr(component, name):
                return getattr(component, name)
        raise AttributeError(f"{type(self).__name__!s} object has no attribute {name!r}")

    @property
    def client(self) -> httpx.Client:
        return self.api.client

    @property
    def base_url(self) -> str:
        return self.api.base_url

    @property
    def auth_token(self) -> str:
        return self.api.auth_token

    @property
    def headers(self) -> dict[str, str]:
        return self.api.headers

    @property
    def project_id(self) -> int:
        return self.api.project_id

    @property
    def retry_count(self) -> int:
        return self.api.retry_count


__all__ = ["DEFAULT_BASE_URL", "Paratranz"]
