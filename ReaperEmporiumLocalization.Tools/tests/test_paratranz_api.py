from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from src.localization.paratranz import Paratranz
from src.models import Page, ParatranzString, RateLimitSettings, StageEnum


class ParatranzApiTests(unittest.TestCase):
    def test_get_strings_parses_page_and_uses_alias_query_params(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "page": 1,
                    "pageSize": 20,
                    "rowCount": 1,
                    "pageCount": 1,
                    "results": [
                        {
                            "id": 10,
                            "key": "hello",
                            "original": "Hello",
                            "translation": "你好",
                            "fileId": 3,
                            "stage": 1,
                        }
                    ],
                },
            )

        api = Paratranz(
            httpx.Client(transport=httpx.MockTransport(handler)),
            project_id=123,
            token="secret",
            rate_limit=RateLimitSettings(requests_per_second=1000),
        )

        result = api.get_strings(file=3, stage=StageEnum.translated, detailed=True, page=1, page_size=20)

        self.assertIsInstance(result, Page)
        self.assertIsInstance(result.results[0], ParatranzString)
        self.assertEqual(result.page_size, 20)
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.results[0].file_id, 3)
        self.assertEqual(requests[0].headers["authorization"], "Bearer secret")
        self.assertEqual(requests[0].url.path, "/api/projects/123/strings")
        self.assertEqual(requests[0].url.params["pageSize"], "20")
        self.assertEqual(requests[0].url.params["detailed"], "1")

    def test_existing_bearer_token_is_not_prefixed_twice(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json=[])

        api = Paratranz(
            httpx.Client(transport=httpx.MockTransport(handler)),
            project_id=123,
            token="Bearer secret",
            rate_limit=RateLimitSettings(requests_per_second=1000),
        )

        api.get_files()

        self.assertEqual(requests[0].headers["authorization"], "Bearer secret")

    def test_core_file_term_and_artifact_endpoints_are_typed(self) -> None:
        requests: list[httpx.Request] = []
        responses = [
            httpx.Response(200, json=[{"id": 7, "name": "database/db_Test.json", "updatedAt": "2026-05-01"}]),
            httpx.Response(200, json={"id": 8, "term": "apple", "translation": "苹果", "caseSensitive": True}),
            httpx.Response(200, json={"id": 2, "total": 10, "translated": 5}),
            httpx.Response(200, json={"id": 5, "status": 1, "type": "artifact"}),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return responses.pop(0)

        api = Paratranz(
            httpx.Client(transport=httpx.MockTransport(handler)),
            project_id=123,
            token="secret",
            rate_limit=RateLimitSettings(requests_per_second=1000),
        )

        files = api.get_files()
        term = api.create_term({"term": "apple", "translation": "苹果", "caseSensitive": True})
        artifact = api.get_artifact()
        job = api.generate_artifact()

        self.assertEqual(files[0].updated_at, "2026-05-01")
        self.assertEqual(term.case_sensitive, True)
        self.assertEqual(artifact.translated, 5)
        self.assertEqual(job.type_, "artifact")
        self.assertEqual([request.method for request in requests], ["GET", "POST", "GET", "POST"])
        self.assertEqual(requests[1].url.path, "/api/projects/123/terms")

    def test_429_retries_with_retry_after(self) -> None:
        sleeps: list[float] = []
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(429, headers={"Retry-After": "0.5"}, json={"message": "slow down"})
            return httpx.Response(200, json=[])

        api = Paratranz(
            httpx.Client(transport=httpx.MockTransport(handler)),
            project_id=123,
            token="secret",
            rate_limit=RateLimitSettings(requests_per_second=1000000, max_retries=2),
            sleeper=sleeps.append,
        )

        api.get_files()

        self.assertEqual(len(requests), 2)
        self.assertIn(0.5, sleeps)
        self.assertEqual(api.retry_count, 1)

    def test_sync_files_dry_run_does_not_send_write_requests(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            self.assertEqual(request.method, "GET")
            return httpx.Response(200, json=[])

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source"
            source.mkdir()
            (source / "db_Test.json").write_text("[]", encoding="utf-8")

            api = Paratranz(
                httpx.Client(transport=httpx.MockTransport(handler)),
                project_id=123,
                token="secret",
                rate_limit=RateLimitSettings(requests_per_second=1000),
            )
            result = api.sync_files_from_local(source, dry_run=True)

        self.assertEqual(len(requests), 1)
        self.assertEqual(result.planned, 1)
        self.assertEqual(result.actions[0].action, "create_file")

    def test_batch_update_strings_chunks_dry_run(self) -> None:
        api = Paratranz(project_id=123, token="secret", rate_limit=RateLimitSettings(requests_per_second=1000))

        result = api.batch_update_strings([1, 2, 3, 4, 5], stage=StageEnum.reviewed, chunk_size=2, dry_run=True)

        self.assertEqual(result.planned, 3)
        self.assertEqual([action.metadata["ids"] for action in result.actions], [[1, 2], [3, 4], [5]])
        self.assertEqual(result.actions[0].metadata["stage"], int(StageEnum.reviewed))

    def test_migrate_local_translations_moves_database_and_dll_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_root = root / "old"
            new_root = root / "new"
            output_root = root / "out"
            (old_root / "database").mkdir(parents=True)
            (new_root / "database").mkdir(parents=True)

            self._write_entries(
                old_root / "database" / "db_Test.json",
                [{"key": "k1", "original": "Hello", "translation": "你好", "stage": 1, "context": ""}],
            )
            self._write_entries(
                new_root / "database" / "db_Test.json",
                [{"key": "k1", "original": "Hello", "translation": "", "stage": 0, "context": ""}],
            )
            self._write_entries(
                old_root / "dll_strings.json",
                [
                    {
                        "key": "Game.Type.Run_0",
                        "original": "Run",
                        "translation": "运行",
                        "stage": 1,
                        "context": "ctx",
                    }
                ],
            )
            self._write_entries(
                new_root / "dll_strings.json",
                [
                    {
                        "key": "Game.Type.Run_0",
                        "original": "Run",
                        "translation": "",
                        "stage": 0,
                        "context": "ctx",
                    }
                ],
            )

            api = Paratranz(project_id=123, token="secret", rate_limit=RateLimitSettings(requests_per_second=1000))
            result = api.migrate_local_translations(old_root, new_root, output_root, dry_run=False)

            database = json.loads((output_root / "database" / "db_Test.json").read_text(encoding="utf-8"))
            dll = json.loads((output_root / "dll_strings.json").read_text(encoding="utf-8"))

        self.assertEqual(result.migrated_entries, 2)
        self.assertEqual(database[0]["translation"], "你好")
        self.assertEqual(database[0]["stage"], 1)
        self.assertEqual(dll[0]["translation"], "运行")
        self.assertEqual(dll[0]["stage"], 1)

    def test_migrate_local_translations_preserves_nested_database_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_root = root / "old"
            new_root = root / "new"
            output_root = root / "out"
            self._write_entries(
                old_root / "database" / "bundle_a" / "db_Test.json",
                [{"key": "0", "original": "Hello", "translation": "Ni hao", "stage": 1, "context": ""}],
            )
            self._write_entries(
                new_root / "database" / "bundle_a" / "db_Test.json",
                [{"key": "0", "original": "Hello", "translation": "", "stage": 0, "context": ""}],
            )

            api = Paratranz(project_id=123, token="secret", rate_limit=RateLimitSettings(requests_per_second=1000))
            result = api.migrate_local_translations(old_root, new_root, output_root, dry_run=False)
            output_file = output_root / "database" / "bundle_a" / "db_Test.json"
            flat_file = output_root / "database" / "db_Test.json"
            database = json.loads(output_file.read_text(encoding="utf-8"))
            output_exists = output_file.is_file()
            flat_exists = flat_file.exists()

        self.assertEqual(result.migrated_entries, 1)
        self.assertTrue(output_exists)
        self.assertFalse(flat_exists)
        self.assertEqual(database[0]["translation"], "Ni hao")

    def test_migrate_local_translations_does_not_compat_old_il_dll_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_root = root / "old"
            new_root = root / "new"
            output_root = root / "out"
            self._write_entries(
                old_root / "dll_strings.json",
                [{"key": "Game.Type.Method_IL_0001", "original": "Talk", "translation": "旧译文", "stage": 1, "context": "ctx"}],
            )
            self._write_entries(
                new_root / "dll_strings.json",
                [{"key": "Game.Type.Method_0", "original": "Talk", "translation": "", "stage": 0, "context": "ctx"}],
            )

            api = Paratranz(project_id=123, token="secret", rate_limit=RateLimitSettings(requests_per_second=1000))
            result = api.migrate_local_translations(old_root, new_root, output_root, dry_run=False)
            dll = json.loads((output_root / "dll_strings.json").read_text(encoding="utf-8"))

        self.assertEqual(result.migrated_entries, 0)
        self.assertEqual(dll[0]["translation"], "")
        self.assertEqual(dll[0]["stage"], 0)

    def test_migrate_legacy_translations_maps_asset_text_to_build_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "source"
            dump_root = root / "build" / "dump"
            output_root = root / "build" / "migrated"
            (output_root / "stale.txt").parent.mkdir(parents=True)
            (output_root / "stale.txt").write_text("old", encoding="utf-8")
            self._write_entries(
                source_root / "utf8" / "asset_00_text" / "db_Test-CAB-abc.json",
                [{"key": "old-key", "original": "Hello", "translation": "Ni hao", "stage": 1, "context": ""}],
            )
            self._write_entries(
                dump_root / "MainGame" / "database" / "asset_00_text" / "db_Test.json",
                [{"key": "0", "original": "Hello", "translation": "", "stage": 0, "context": ""}],
            )

            api = Paratranz(project_id=123, token="secret", rate_limit=RateLimitSettings(requests_per_second=1000))
            result = api.migrate_legacy_translations_to_dump(source_root, dump_root, output_root, dry_run=False)
            migrated = json.loads(
                (output_root / "MainGame" / "database" / "asset_00_text" / "db_Test.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result.migrated_entries, 1)
        self.assertFalse((output_root / "stale.txt").exists())
        self.assertEqual(migrated[0]["key"], "0")
        self.assertEqual(migrated[0]["translation"], "Ni hao")
        self.assertEqual(migrated[0]["stage"], 1)

    def test_migrate_legacy_translations_merges_duplicate_dlc_files_and_reports_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "source"
            dump_root = root / "build" / "dump"
            output_root = root / "build" / "migrated"
            self._write_entries(
                source_root / "utf8" / "asset_00_text_DLC" / "db_Dlc-CAB-a.json",
                [{"key": "0", "original": "Shared", "translation": "A", "stage": 1, "context": ""}],
            )
            self._write_entries(
                source_root / "utf8" / "asset_00_text_DLC" / "db_Dlc-CAB-b.json",
                [{"key": "1", "original": "Shared", "translation": "B", "stage": 1, "context": ""}],
            )
            self._write_entries(
                dump_root / "DLCGame" / "database" / "asset_00_text" / "db_Dlc.json",
                [{"key": "0", "original": "Shared", "translation": "", "stage": 0, "context": ""}],
            )

            api = Paratranz(project_id=123, token="secret", rate_limit=RateLimitSettings(requests_per_second=1000))
            result = api.migrate_legacy_translations_to_dump(source_root, dump_root, output_root, dry_run=False)
            report = json.loads((output_root / "migration_report.json").read_text(encoding="utf-8"))
            migrated = json.loads(
                (output_root / "DLCGame" / "database" / "asset_00_text" / "db_Dlc.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result.migrated_entries, 1)
        self.assertEqual(migrated[0]["translation"], "A")
        self.assertEqual(len(report["duplicate_files"]), 1)
        self.assertEqual(len(report["conflicts"]), 1)

    def test_migrate_legacy_translations_does_not_fuzzy_match_database_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "source"
            dump_root = root / "build" / "dump"
            output_root = root / "build" / "migrated"
            self._write_entries(
                source_root / "utf8" / "asset_00_text" / "db_Test.json",
                [{"key": "0", "original": "ならずもの", "translation": "旧译文", "stage": 1, "context": ""}],
            )
            self._write_entries(
                dump_root / "MainGame" / "database" / "asset_00_text" / "db_Test.json",
                [{"key": "0", "original": "ならずものA", "translation": "", "stage": 0, "context": ""}],
            )

            api = Paratranz(project_id=123, token="secret", rate_limit=RateLimitSettings(requests_per_second=1000))
            result = api.migrate_legacy_translations_to_dump(source_root, dump_root, output_root, dry_run=False)
            migrated = json.loads(
                (output_root / "MainGame" / "database" / "asset_00_text" / "db_Test.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result.migrated_entries, 0)
        self.assertEqual(migrated[0]["translation"], "")
        self.assertEqual(migrated[0]["stage"], 0)

    def test_migrate_legacy_translations_reads_remote_source_with_get_only(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/api/projects/999/files":
                return httpx.Response(200, json=[{"id": 7, "name": "asset_00_text/db_Remote.json"}])
            if request.url.path == "/api/projects/999/files/7/translation":
                return httpx.Response(
                    200,
                    json=[{"key": "old", "original": "Remote", "translation": "远程译文", "stage": 1, "context": ""}],
                )
            return httpx.Response(404, json={"message": "not found"})

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dump_root = root / "build" / "dump"
            output_root = root / "build" / "migrated"
            self._write_entries(
                dump_root / "MainGame" / "database" / "asset_00_text" / "db_Remote.json",
                [{"key": "0", "original": "Remote", "translation": "", "stage": 0, "context": ""}],
            )

            api = Paratranz(
                httpx.Client(transport=httpx.MockTransport(handler)),
                project_id=123,
                token="secret",
                rate_limit=RateLimitSettings(requests_per_second=1000),
            )
            result = api.migrate_legacy_translations_to_dump(
                root / "missing",
                dump_root,
                output_root,
                source_project_id=999,
                dry_run=False,
            )
            migrated = json.loads(
                (output_root / "MainGame" / "database" / "asset_00_text" / "db_Remote.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result.migrated_entries, 1)
        self.assertEqual(migrated[0]["translation"], "远程译文")
        self.assertEqual({request.method for request in requests}, {"GET"})

    def test_migrate_legacy_translations_dll_requires_new_exact_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "source"
            dump_root = root / "build" / "dump"
            output_root = root / "build" / "migrated"
            self._write_entries(
                source_root / "utf8" / "dll" / "strings.json",
                [
                    {"key": "Game.Type.Run_0", "original": "Run", "translation": "运行", "stage": 1, "context": "ctx"},
                    {"key": "12345", "original": "Numeric", "translation": "数字旧键", "stage": 1, "context": ""},
                    {"key": "Game.Type.Talk_IL_0001", "original": "Talk", "translation": "说话", "stage": 1, "context": "ctx"},
                ],
            )
            self._write_entries(
                dump_root / "MainGame" / "dll_strings.json",
                [
                    {"key": "Game.Type.Run_0", "original": "Run", "translation": "", "stage": 0, "context": "ctx"},
                    {"key": "Game.Type.Numeric_0", "original": "Numeric", "translation": "", "stage": 0, "context": ""},
                    {"key": "Game.Type.Talk_0", "original": "Talk", "translation": "", "stage": 0, "context": "ctx"},
                ],
            )

            api = Paratranz(project_id=123, token="secret", rate_limit=RateLimitSettings(requests_per_second=1000))
            result = api.migrate_legacy_translations_to_dump(source_root, dump_root, output_root, dry_run=False)
            dll = json.loads((output_root / "MainGame" / "dll_strings.json").read_text(encoding="utf-8"))

        self.assertEqual(result.migrated_entries, 2)
        self.assertEqual(dll[0]["translation"], "运行")
        self.assertEqual(dll[1]["translation"], "数字旧键")
        self.assertEqual(dll[2]["translation"], "")

    def _write_entries(self, path: Path, entries: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
