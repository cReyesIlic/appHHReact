import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from docx import Document

from app.core.config import settings
from app.services.proposal_drafts import ProposalDraftService
from app.services.structured_wiki import StructuredWikiService


class WikiPaginationTests(unittest.TestCase):
    def test_summaries_are_paginated_and_exclude_markdown(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            settings, "database_dir", str(Path(temp_dir) / "wiki.sqlite")
        ), patch.object(StructuredWikiService, "_sync_done", True):
            service = StructuredWikiService()
            with closing(sqlite3.connect(settings.sqlite_path)) as conn, conn:
                for index in range(120):
                    code = f"O-{index:04d}"
                    conn.execute(
                        """
                        insert into wiki_entries
                        (id, title, category, tags, content, source, pinned, created_at, updated_at,
                         propuestas_referenciadas, filtros_aplicables, times_used, validation_status)
                        values (?, ?, 'propuesta', ?, ?, 'pipeline', 0, '2026-01-01', ?, ?, '{}', 0, 'ok')
                        """,
                        (
                            code,
                            f"Wiki {code}",
                            json.dumps(["ingenieria"]),
                            "# Contenido\n" + ("detalle " * 1000),
                            f"2026-01-{(index % 28) + 1:02d}",
                            json.dumps([code]),
                        ),
                    )

            first = service.list_entry_summaries(limit=50)
            second = service.list_entry_summaries(limit=50, offset=50)
            searched = service.list_entry_summaries(query="O-0110")

            self.assertEqual(first["total"], 120)
            self.assertEqual(len(first["entries"]), 50)
            self.assertTrue(first["has_more"])
            self.assertEqual(len(second["entries"]), 50)
            self.assertNotIn("content", first["entries"][0])
            self.assertGreater(first["entries"][0]["content_chars"], 1000)
            self.assertEqual(searched["total"], 1)
            self.assertEqual(searched["entries"][0]["id"], "O-0110")


class ProposalFileRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database_patch = patch.object(
            settings, "database_dir", str(self.root / "drafts.sqlite")
        )
        self.storage_patch = patch.object(
            ProposalDraftService,
            "_owner_root",
            lambda _service, owner_id: self.root / "proposal_drafts" / str(owner_id),
        )
        self.database_patch.start()
        self.storage_patch.start()

    def tearDown(self):
        self.storage_patch.stop()
        self.database_patch.stop()
        self.temp.cleanup()

    def _docx(self) -> bytes:
        document = Document()
        document.add_paragraph("Alcance recuperado con horas y entregables del proyecto.")
        buffer = BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    def test_corrupt_all_zero_pdf_is_rejected_before_storage(self):
        service = ProposalDraftService()
        draft = service.create_draft("owner@shimin.cl", "Oferta")
        with self.assertRaisesRegex(ValueError, "bytes nulos"):
            service.add_file("owner@shimin.cl", draft["slug"], "Aclaracion.pdf", b"\x00" * 500)
        self.assertFalse(service.file_path("owner@shimin.cl", draft["slug"], "Aclaracion.pdf").exists())

    def test_alias_adoption_moves_draft_files_and_preserves_search(self):
        service = ProposalDraftService()
        draft = service.create_draft("entra-guid", "Oferta anterior")
        service.add_file("entra-guid", draft["slug"], "Bases.docx", self._docx())

        result = service.adopt_aliases("owner@shimin.cl", ("entra-guid",))

        self.assertEqual(result["drafts"], 1)
        self.assertFalse(service._draft_dir("entra-guid", draft["slug"]).exists())
        self.assertTrue(service._draft_dir("owner@shimin.cl", draft["slug"]).exists())
        self.assertEqual(service.get_draft("owner@shimin.cl", draft["slug"])["slug"], draft["slug"])
        self.assertTrue(service.search_chunks(draft["slug"], "horas entregables"))

    def test_reprocess_pending_rebuilds_text_and_chunks(self):
        service = ProposalDraftService()
        draft = service.create_draft("owner@shimin.cl", "Oferta reparable")
        uploaded = service.add_file("owner@shimin.cl", draft["slug"], "Bases.docx", self._docx())
        self.assertGreater(uploaded["chars_extracted"], 0)
        with closing(sqlite3.connect(settings.sqlite_path)) as conn, conn:
            conn.execute(
                "update proposal_draft_files set chars_extracted = 0 where slug = ?",
                (draft["slug"],),
            )
            conn.execute("delete from proposal_draft_chunks where slug = ?", (draft["slug"],))

        result = service.reprocess_pending("owner@shimin.cl")

        self.assertEqual(result["checked"], 1)
        self.assertGreater(result["repaired"][0]["chars_extracted"], 0)
        self.assertTrue(service.search_chunks(draft["slug"], "alcance recuperado"))

    def test_pdf_parser_failure_still_falls_back_to_document_intelligence(self):
        service = ProposalDraftService()
        with patch("PyPDF2.PdfReader", side_effect=RuntimeError("parser")), patch.object(
            service,
            "_extract_pdf_with_document_intelligence",
            return_value="[pagina 1]\nTexto OCR recuperado",
        ) as ocr:
            text = service._extract_text(b"%PDF-1.7\ncontenido", "pdf", "scan.pdf")
        self.assertIn("Texto OCR recuperado", text)
        self.assertEqual(service._last_extraction_method, "document_intelligence")
        ocr.assert_called_once()


if __name__ == "__main__":
    unittest.main()
