from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from reaper_tools.models import MigrationResult, ParatranzData, SyncAction, UploadResult
from reaper_tools.services.base import (
    DATABASE_DIR,
    DLL_STRINGS_FILE,
    DLC_GAME_DIR,
    MAIN_GAME_DIR,
    MIGRATION_REPORT_FILE,
    ParatranzServiceBase,
    _ASSET_TEXT_DIR_PATTERN,
    _CAB_SUFFIX_PATTERN,
    _LegacyEntryCandidate,
    _LegacyTranslationIndex,
    _NUMBER_SUFFIX_PATTERN,
)
from reaper_tools.services.sync import SyncService


class MigrationService(ParatranzServiceBase):
    """Project migration, local migration, and upload orchestration workflows."""

    def __init__(self, api, *, context=None, sync_service: SyncService | None = None) -> None:
        super().__init__(api, context=context)
        self.sync_service = sync_service or SyncService(api, context=self.context)

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
            except Exception as exc:  # noqa: BLE001
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
        resolved_target_project_id = self._resolve_project_id(target_project_id)
        if source_project_id == resolved_target_project_id:
            raise ValueError("源项目和目标项目不能相同。")

        actions: list[SyncAction] = []
        page_number = 1

        with self.progress(total=None, enabled=show_progress, desc="读取旧项目术语", unit="页") as progress:
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

        result = MigrationResult(planned=len(actions), dry_run=dry_run, actions=actions)
        if dry_run:
            return result

        with self.progress(total=len(actions), enabled=show_progress, desc="迁移项目术语", unit="页") as progress:
            for action in actions:
                try:
                    with self._temporary_json_file(action.metadata["terms"], filename=f"terms-page-{action.metadata['page']}.json") as temp_file:
                        self.import_terms(temp_file, project_id=resolved_target_project_id)
                    result.succeeded += 1
                    result.migrated_entries += len(action.metadata["terms"])
                except Exception as exc:  # noqa: BLE001
                    result.failed += 1
                    result.errors.append(f"第 {action.metadata['page']} 页术语: {exc}")
                progress.set_postfix_str(f"第 {action.metadata['page']} 页")
                progress.update()

        return result

    def upload_migrated_translations(
        self,
        source_root: str | Path | None = None,
        *,
        report_path: str | Path | None = None,
        project_id: int | None = None,
        dry_run: bool = True,
        show_progress: bool = False,
    ) -> UploadResult:
        source_root_path = Path(source_root) if source_root is not None else self.paths.root / "build" / "migrated"
        report_file_path = Path(report_path) if report_path is not None else source_root_path / MIGRATION_REPORT_FILE
        resolved_project_id = self._resolve_project_id(project_id)

        if not source_root_path.is_dir():
            raise FileNotFoundError(f"未找到可上传的迁移目录：{source_root_path}")
        if not self._json_files(source_root_path):
            raise FileNotFoundError(f"迁移结果目录中没有可上传的 JSON 文件：{source_root_path}")

        initial_result = self.sync_service.sync_files_from_local(
            source_root_path,
            project_id=resolved_project_id,
            update_mode="translation",
            create_missing=True,
            update_existing=True,
            force_translation=True,
            dry_run=dry_run,
            show_progress=show_progress,
            progress_desc="上传迁移译文",
        )
        result = UploadResult(
            dry_run=dry_run,
            file_planned=initial_result.planned,
            file_succeeded=initial_result.succeeded,
            file_failed=initial_result.failed,
            file_skipped=initial_result.skipped,
            actions=list(initial_result.actions),
            errors=list(initial_result.errors),
        )

        conflicts = self._load_migration_conflicts(report_file_path)
        conflict_actions = self._build_conflict_record_actions(source_root_path, conflicts, project_id=resolved_project_id)
        result.conflict_planned = sum(1 for action in conflict_actions if action.will_write)
        result.conflict_skipped = sum(1 for action in conflict_actions if not action.will_write)
        result.actions.extend(conflict_actions)

        finalize_actions = self._build_finalize_actions(source_root_path, resolved_project_id) if result.conflict_planned else []
        result.finalize_planned = len(finalize_actions)
        result.actions.extend(finalize_actions)

        if dry_run:
            return result

        remote_files = {
            self._normalize_remote_name(item.name): item
            for item in self.get_files(project_id=resolved_project_id)
            if item.name
        }

        with self.progress(total=result.conflict_planned, enabled=show_progress, desc="记录冲突译文", unit="次") as progress:
            for action in conflict_actions:
                if not action.will_write:
                    continue
                remote_name = self._normalize_remote_name(action.remote_name or "")
                try:
                    remote_file = remote_files.get(remote_name)
                    if remote_file is None or remote_file.id is None:
                        result.conflict_skipped += 1
                        result.errors.append(f"{remote_name}: 远端文件不存在，无法记录冲突译文")
                        progress.set_postfix_str(remote_name)
                        progress.update()
                        continue
                    entries = self._build_conflict_record_entries(
                        source_root_path / remote_name,
                        action.metadata.get("identity"),
                        str(action.metadata.get("translation", "")),
                    )
                    if entries is None:
                        result.conflict_skipped += 1
                        result.errors.append(f"{remote_name}: 未找到对应的冲突词条，已跳过")
                        progress.set_postfix_str(remote_name)
                        progress.update()
                        continue
                    with self._temporary_paratranz_file(entries, filename=Path(remote_name).name) as temp_file:
                        self.update_file_translation(remote_file.id, temp_file, force=True, project_id=resolved_project_id)
                    result.conflict_recorded += 1
                except Exception as exc:  # noqa: BLE001
                    result.conflict_failed += 1
                    result.errors.append(f"{remote_name}: {exc}")
                progress.set_postfix_str(remote_name)
                progress.update()

        if finalize_actions:
            finalize_result = self.sync_service.sync_files_from_local(
                source_root_path,
                project_id=resolved_project_id,
                update_mode="translation",
                create_missing=True,
                update_existing=True,
                force_translation=True,
                dry_run=False,
                show_progress=show_progress,
                progress_desc="回写最终译文",
            )
            result.finalize_succeeded = finalize_result.succeeded
            result.finalize_failed = finalize_result.failed
            result.errors.extend(finalize_result.errors)

        return result

    def migrate_local_translations(
        self,
        old_root: str | Path,
        new_root: str | Path,
        output_root: str | Path,
        *,
        dry_run: bool = True,
    ) -> MigrationResult:
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
        source_root_path = Path(source_root) if source_root is not None else self.paths.paratranz
        dump_root_path = Path(dump_root) if dump_root is not None else self.paths.root / "build" / "dump"
        output_root_path = Path(output_root) if output_root is not None else self.paths.root / "build" / "migrated"

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

        with self.progress(total=len(target_files), enabled=show_progress, desc="迁移旧译文", unit="文件") as progress:
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

    def _load_migration_conflicts(self, report_path: Path) -> list[dict[str, Any]]:
        if not report_path.is_file():
            self.logger.warning("未找到迁移报告：{}，本次只上传迁移后的最终译文。", report_path)
            return []
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning("读取迁移报告失败：{}，本次跳过冲突历史记录。", exc)
            return []
        conflicts = payload.get("conflicts", [])
        if not isinstance(conflicts, list):
            self.logger.warning("迁移报告中的 conflicts 字段不是数组，本次跳过冲突历史记录。")
            return []
        return [item for item in conflicts if isinstance(item, dict)]

    def _build_conflict_record_actions(
        self,
        source_root: Path,
        conflicts: list[dict[str, Any]],
        *,
        project_id: int,
    ) -> list[SyncAction]:
        actions: list[SyncAction] = []
        entries_cache: dict[str, list[ParatranzData]] = {}

        for conflict_index, conflict in enumerate(conflicts, start=1):
            target_file = self._normalize_remote_name(str(conflict.get("target_file") or ""))
            if not target_file:
                actions.append(
                    SyncAction(
                        action="skip_conflict_record",
                        project_id=project_id,
                        will_write=False,
                        reason="冲突记录缺少 target_file。",
                        metadata={"conflict_index": conflict_index},
                    )
                )
                continue

            local_file = source_root / target_file
            if not local_file.is_file():
                actions.append(
                    SyncAction(
                        action="skip_conflict_record",
                        local_path=local_file,
                        remote_name=target_file,
                        project_id=project_id,
                        will_write=False,
                        reason="迁移结果中不存在对应文件。",
                        metadata={"conflict_index": conflict_index},
                    )
                )
                continue

            entries = entries_cache.setdefault(target_file, self._read_paratranz_file(local_file))
            local_entry = self._find_conflict_local_entry(Path(target_file), entries, conflict.get("identity"))
            if local_entry is None:
                actions.append(
                    SyncAction(
                        action="skip_conflict_record",
                        local_path=local_file,
                        remote_name=target_file,
                        project_id=project_id,
                        will_write=False,
                        reason="迁移结果中未找到对应冲突词条。",
                        metadata={"conflict_index": conflict_index, "identity": conflict.get("identity")},
                    )
                )
                continue

            translations = self._conflict_record_translations(conflict.get("translations"), local_entry.translation)
            if not translations:
                actions.append(
                    SyncAction(
                        action="skip_conflict_record",
                        local_path=local_file,
                        remote_name=target_file,
                        project_id=project_id,
                        will_write=False,
                        reason="冲突候选与最终迁移译文相同，无需额外记录。",
                        metadata={"conflict_index": conflict_index, "identity": conflict.get("identity")},
                    )
                )
                continue

            for translation in translations:
                actions.append(
                    SyncAction(
                        action="record_conflict_translation",
                        local_path=local_file,
                        remote_name=target_file,
                        project_id=project_id,
                        method="POST",
                        endpoint=f"/projects/{project_id}/files/{{fileId}}/translation",
                        metadata={
                            "conflict_index": conflict_index,
                            "identity": conflict.get("identity"),
                            "translation": translation,
                            "final_translation": local_entry.translation,
                            "phase": "conflict_record",
                        },
                    )
                )
        return actions

    def _build_finalize_actions(self, source_root: Path, project_id: int) -> list[SyncAction]:
        return [
            SyncAction(
                action="finalize_file_translation",
                local_path=file_path,
                remote_name=self._remote_name(source_root, file_path, ""),
                project_id=project_id,
                method="POST",
                endpoint=f"/projects/{project_id}/files/{{fileId}}/translation",
                metadata={"phase": "finalize"},
            )
            for file_path in self._json_files(source_root)
        ]

    def _conflict_record_translations(self, value: Any, final_translation: str) -> list[str]:
        if not isinstance(value, list):
            return []
        seen: set[str] = set()
        translations: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            if not item.strip() or item == final_translation or item in seen:
                continue
            seen.add(item)
            translations.append(item)
        return translations

    def _build_conflict_record_entries(
        self,
        local_file: Path,
        identity: Any,
        translation: str,
    ) -> list[ParatranzData] | None:
        relative = Path(local_file.name)
        entries = self._read_paratranz_file(local_file)
        updated = False
        cloned = [entry.model_copy(deep=True) for entry in entries]
        for entry in cloned:
            if not self._entry_matches_conflict_identity(relative, entry, identity):
                continue
            entry.translation = translation
            updated = True
            break
        if not updated:
            return None
        return cloned

    def _find_conflict_local_entry(
        self,
        relative: Path,
        entries: list[ParatranzData],
        identity: Any,
    ) -> ParatranzData | None:
        for entry in entries:
            if self._entry_matches_conflict_identity(relative, entry, identity):
                return entry
        return None

    def _entry_matches_conflict_identity(self, relative: Path, entry: ParatranzData, identity: Any) -> bool:
        if relative.name == DLL_STRINGS_FILE:
            if isinstance(identity, (list, tuple)) and len(identity) >= 3:
                return entry.key == str(identity[0]) and entry.original == str(identity[1]) and entry.context == str(identity[2])
            if isinstance(identity, str):
                return entry.runtime_original == identity
            return False
        return isinstance(identity, str) and entry.runtime_original == identity

    def _merge_local_translations(
        self,
        relative: Path,
        old_entries: list[ParatranzData],
        new_entries: list[ParatranzData],
    ) -> int:
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
        index = _LegacyTranslationIndex({}, {}, {}, {}, {}, {}, [], {})
        order = 0

        if source_root is not None:
            local_files = self._legacy_local_json_files(source_root)
            with self.progress(total=len(local_files), enabled=show_progress, desc="读取本地旧译文", unit="文件") as progress:
                for file_path in local_files:
                    relative_name = file_path.relative_to(source_root).as_posix()
                    entries = self._read_paratranz_file(file_path)
                    order = self._add_legacy_file_to_index(index, relative_name, entries, source_priority=0, order=order)
                    progress.set_postfix_str(relative_name)
                    progress.update()

        if source_project_id is not None:
            remote_files = self.get_files(project_id=source_project_id)
            with self.progress(total=len(remote_files), enabled=show_progress, desc="读取远程旧项目", unit="文件") as progress:
                for remote_file in remote_files:
                    if remote_file.id is None or not remote_file.name:
                        progress.update()
                        continue
                    entries = self.get_file_translation(remote_file.id, project_id=source_project_id)
                    order = self._add_legacy_file_to_index(index, remote_file.name, entries, source_priority=1, order=order)
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
        parts = [part.casefold() for part in Path(self._normalize_remote_name(source_name)).parts]
        return Path(source_name).name == DLL_STRINGS_FILE or "dll" in parts or "dll_strings" in parts

    def _merge_legacy_dump_entries(
        self,
        relative: Path,
        entries: list[ParatranzData],
        index: _LegacyTranslationIndex,
        conflicts: list[dict[str, Any]],
    ) -> tuple[int, int]:
        relative_key = relative.as_posix()
        migrated = 0
        unmatched = 0
        is_dll = relative.name == DLL_STRINGS_FILE

        for entry in entries:
            if is_dll:
                identity = (entry.key, entry.original, entry.context)
                file_candidates = index.dll_by_file.get(relative_key, {}).get(identity, [])
                candidates = file_candidates or index.dll_global.get(identity, [])
                chosen = self._choose_legacy_candidate(candidates, target_file=relative_key, identity=identity, conflicts=conflicts)
                if chosen is None:
                    original_identity = entry.runtime_original
                    file_candidates = index.dll_original_by_file.get(relative_key, {}).get(original_identity, [])
                    candidates = file_candidates or index.dll_original_global.get(original_identity, [])
                    chosen = self._choose_legacy_candidate(candidates, target_file=relative_key, identity=original_identity, conflicts=conflicts)
            else:
                identity = entry.runtime_original
                file_candidates = index.database_by_file.get(relative_key, {}).get(identity, [])
                candidates = file_candidates or index.database_global.get(identity, [])
                chosen = self._choose_legacy_candidate(candidates, target_file=relative_key, identity=identity, conflicts=conflicts)
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
        lowered = [part.casefold() for part in parts]
        filename = Path(parts[-1]).stem.casefold() if parts else ""
        if any(part in {DLC_GAME_DIR.casefold(), "dlc"} or part.endswith("_dlc") for part in lowered) or "dlc" in filename:
            return Path(DLC_GAME_DIR) / DLL_STRINGS_FILE
        return Path(MAIN_GAME_DIR) / DLL_STRINGS_FILE

    def _legacy_existing_dump_path(self, parts: list[str]) -> Path | None:
        game_dir = parts[0]
        if len(parts) >= 2 and parts[1] == DLL_STRINGS_FILE:
            return Path(game_dir) / DLL_STRINGS_FILE
        if len(parts) >= 3 and parts[1] == DATABASE_DIR:
            clean_parts = [*parts[2:-1], self._clean_legacy_json_file_name(parts[-1])]
            return Path(game_dir) / DATABASE_DIR / Path(*clean_parts)
        return None

    def _legacy_database_path_from_parts(self, parts: list[str]) -> Path | None:
        if len(parts) < 2 or not _ASSET_TEXT_DIR_PATTERN.match(parts[0]):
            return None
        asset_dir = parts[0]
        game_dir = DLC_GAME_DIR if asset_dir.casefold().endswith("_dlc") else MAIN_GAME_DIR
        target_asset_dir = asset_dir[:-4] if game_dir == DLC_GAME_DIR and asset_dir.casefold().endswith("_dlc") else asset_dir
        clean_parts = [target_asset_dir, *parts[1:-1], self._clean_legacy_json_file_name(parts[-1])]
        return Path(game_dir) / DATABASE_DIR / Path(*clean_parts)

    def _clean_legacy_json_file_name(self, file_name: str) -> str:
        path = Path(file_name)
        stem = _CAB_SUFFIX_PATTERN.sub("", path.stem)
        stem = _NUMBER_SUFFIX_PATTERN.sub("", stem)
        return f"{stem}.json"

    def _migration_target_files(self, dump_root: Path) -> list[Path]:
        files: list[Path] = []
        for game_dir in (MAIN_GAME_DIR, DLC_GAME_DIR):
            game_root = dump_root / game_dir
            files.extend(self._json_files(game_root))
        return sorted(files, key=lambda item: item.relative_to(dump_root).as_posix().casefold())

    def _reset_migration_output(self, output_root: Path, dump_root: Path) -> None:
        resolved_output = output_root.resolve()
        if resolved_output == dump_root.resolve():
            raise ValueError("迁移输出目录不能和 build/dump 相同。")
        if output_root.exists():
            if len(resolved_output.parts) <= 2:
                raise ValueError(f"拒绝清理过高层级目录：{output_root}")
            shutil.rmtree(output_root)
        output_root.mkdir(parents=True, exist_ok=True)

    def _write_migration_report(self, target: Path, report: dict[str, Any]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


__all__ = ["MigrationService"]
