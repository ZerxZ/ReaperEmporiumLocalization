from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from reaper_tools.models import BatchResult, BatchStringOperationRequest, StageEnum, SyncAction, SyncPlan
from reaper_tools.services.base import ParatranzServiceBase


class SyncService(ParatranzServiceBase):
    """Remote file sync and batch string workflows."""

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
        show_progress: bool = False,
        progress_desc: str = "同步 ParaTranz 文件",
    ) -> BatchResult:
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
        with self.progress(total=plan.write_count, enabled=show_progress, desc=progress_desc, unit="文件") as progress:
            for action in plan.actions:
                if not action.will_write:
                    continue
                remote_name = action.remote_name or (action.local_path.as_posix() if action.local_path else action.action)
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
                except Exception as exc:  # noqa: BLE001
                    result.failed += 1
                    result.errors.append(f"{action.remote_name}: {exc}")
                progress.set_postfix_str(self._normalize_remote_name(str(remote_name)))
                progress.update()
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

    def _execute_string_batches(
        self,
        actions: list[SyncAction],
        op: str,
        *,
        dry_run: bool,
        project_id: int | None,
    ) -> BatchResult:
        result = BatchResult(planned=len(actions), dry_run=dry_run, actions=actions)
        if dry_run:
            return result

        before_retries = self.retry_count
        for action in actions:
            try:
                self.batch_operate_strings(
                    BatchStringOperationRequest(
                        op=op,
                        id=action.metadata["ids"],
                        stage=action.metadata.get("stage"),
                        translation=action.metadata.get("translation"),
                    ),
                    project_id=project_id,
                )
                result.succeeded += 1
            except Exception as exc:  # noqa: BLE001
                result.failed += 1
                result.errors.append(f"{action.action}: {exc}")
        result.retried = self.retry_count - before_retries
        return result


__all__ = ["SyncService"]
