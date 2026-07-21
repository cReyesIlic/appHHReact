import csv
import importlib.util
import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from openpyxl import Workbook

from app.core.config import settings
from app.rag.parent_child import ParentChildIndexer
from app.services.master_repository import MasterRepository
from app.services.proposal_sync_service import ProposalSyncService


class SettingsPathsMixin:
    def patch_settings(self, temp_dir: str):
        base = Path(temp_dir)
        return patch.multiple(
            settings,
            database_dir=str(base / "master.sqlite"),
            master_path=str(base / "master.xlsx"),
            master_path_blob="Master/master.xlsx",
        )


class ParentChildReliabilityTests(SettingsPathsMixin, unittest.TestCase):
    def test_colliding_parent_ids_are_disambiguated_and_old_embeddings_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.patch_settings(temp_dir):
            indexer = ParentChildIndexer()
            with closing(sqlite3.connect(settings.sqlite_path)) as conn:
                conn.execute(
                    """
                    create table rag_child_embeddings (
                        child_id text primary key, parent_id text, codigo text,
                        embedding blob, dim integer, model text, content_hash text
                    )
                    """
                )
                conn.execute(
                    "insert into rag_child_embeddings values (?, ?, ?, ?, ?, ?, ?)",
                    ("old-child", "old-parent", "O-9999", b"old", 1, "model", "hash"),
                )
                conn.commit()

            shared_prefix = "contenido repetido " * 12
            markdown = (
                f"## Fuente\n{shared_prefix}primera variante\n"
                f"## Fuente\n{shared_prefix}segunda variante\n"
            )
            result = indexer.index_parse_result("O-9999", {"text": markdown, "pages": []}, {})

            self.assertEqual(result["parents"], 2)
            with closing(sqlite3.connect(settings.sqlite_path)) as conn:
                parent_ids = [row[0] for row in conn.execute(
                    "select parent_id from rag_parent_sections where codigo = ?", ("O-9999",)
                )]
                old_embeddings = conn.execute(
                    "select count(*) from rag_child_embeddings where codigo = ?", ("O-9999",)
                ).fetchone()[0]
            self.assertEqual(len(parent_ids), len(set(parent_ids)))
            self.assertEqual(old_embeddings, 0)


class QueueReliabilityTests(unittest.TestCase):
    def test_pending_queue_rotates_by_last_attempt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "sync_manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=["codigo", "updated_at", "status"])
                writer.writeheader()
                writer.writerow({"codigo": "O-0001", "updated_at": "2026-07-21T12:00:00", "status": "no_files"})
                writer.writerow({"codigo": "O-0003", "updated_at": "2026-07-20T12:00:00", "status": "error"})

            service = object.__new__(ProposalSyncService)
            pending = [{"codigo": "O-0001"}, {"codigo": "O-0002"}, {"codigo": "O-0003"}]
            with patch("app.services.proposal_sync_service.MANIFEST_PATH", str(manifest)):
                ordered = service._order_pending_by_last_attempt(pending)

            self.assertEqual([row["codigo"] for row in ordered], ["O-0002", "O-0003", "O-0001"])


class MasterRefreshTests(SettingsPathsMixin, unittest.IsolatedAsyncioTestCase):
    def workbook_bytes(self) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Ofertas"
        for _ in range(21):
            sheet.append([None])
        sheet.append(["Codigo", "Cliente Directo", "Titulo", "Estado"])
        sheet.append(["O-9999", "Cliente prueba", "Oferta prueba", "PG"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    async def test_refresh_uses_sharepoint_validates_and_updates_blob_backup(self):
        content = self.workbook_bytes()
        with tempfile.TemporaryDirectory() as temp_dir, self.patch_settings(temp_dir):
            repository = MasterRepository()
            repository.blob = Mock()
            repository.blob.upload_bytes.return_value = True

            metadata = {
                "name": "master.xlsx",
                "last_modified": "2026-07-20T22:21:29Z",
                "size": len(content),
            }
            with patch(
                "app.services.sharepoint_client.SharePointClient.download_named_file",
                new=AsyncMock(return_value=(content, metadata)),
            ):
                result = await repository.refresh_from_source()

            self.assertEqual(result["source"], "sharepoint")
            self.assertEqual(result["rows_loaded"], 1)
            self.assertTrue(result["blob_updated"])
            self.assertTrue(Path(settings.master_path).exists())
            repository.blob.upload_bytes.assert_called_once()
            with closing(sqlite3.connect(settings.sqlite_path)) as conn:
                row = conn.execute("select codigo, estado from oferta").fetchone()
            self.assertEqual(row, ("O-9999", "PG"))


class SchedulerReliabilityTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(importlib.util.find_spec("apscheduler"), "APScheduler no instalado en el Python local")
    async def test_scheduler_is_daily_and_uses_chile_timezone(self):
        from app.services import scheduler

        scheduler.shutdown_scheduler()
        with patch.dict(
            os.environ,
            {
                "SYNC_SCHEDULE_ENABLED": "true",
                "SYNC_SCHEDULE_EVERY_DAYS": "1",
                "SYNC_SCHEDULE_TZ": "America/Santiago",
                "SYNC_SCHEDULE_HOUR": "2",
                "SYNC_SCHEDULE_MINUTE": "15",
            },
            clear=False,
        ):
            info = scheduler.start_scheduler()
            status = scheduler.scheduler_status()
            scheduler.shutdown_scheduler()

        self.assertEqual(info["every_days"], 1)
        self.assertEqual(status["timezone"], "America/Santiago")
        self.assertEqual(
            {job["id"] for job in status["jobs"]},
            {"sync_ganadas_periodic", "storage_monitor_daily"},
        )
        self.assertTrue(all(job["timezone"] == "America/Santiago" for job in status["jobs"]))


if __name__ == "__main__":
    unittest.main()
