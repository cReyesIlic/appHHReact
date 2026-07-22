import unittest

from app.services.ingestion_reporter import (
    email_test_report,
    ganadas_sync_report,
    master_refresh_report,
    storage_usage_report,
    upload_report,
)


class EmailReportTests(unittest.TestCase):
    def test_daily_sync_report_is_actionable_and_escapes_external_text(self):
        subject, plain, html = ganadas_sync_report(
            {
                "total_ganadas_master": 965,
                "objetivo_corrida": 2,
                "ingested": 1,
                "skipped": 0,
                "errors": 1,
                "partial": 1,
                "wiki_ok": 1,
                "wiki_error": 0,
                "queue_before": 964,
                "queue_remaining": 963,
                "pending_new_remaining": 349,
                "pending_reprocess_remaining": 614,
                "details": [
                    {
                        "codigo": "O-0001",
                        "status": "ok",
                        "sync_reason": "new_rag",
                        "files_processed": 4,
                        "chunks_child": 18,
                        "wiki_status": "ok",
                        "quality": {"wiki_score": 91},
                    },
                    {
                        "codigo": "O-0003",
                        "status": "ok",
                        "sync_reason": "pipeline_stale",
                        "wiki_status": "error",
                        "wiki_error": "timeout Wiki",
                    },
                    {
                        "codigo": "O-0002",
                        "status": "error",
                        "sync_reason": "pipeline_stale",
                        "error": "<script>alert('x')</script>",
                    },
                ],
            }
        )

        self.assertIn("ATENCIÓN", subject)
        self.assertIn("2 alertas", subject)
        self.assertIn("Pendientes al terminar: 963", plain)
        self.assertIn("Incompletas para reintento: 1", plain)
        self.assertIn("Incompleta", html)
        self.assertIn("Acción requerida", plain)
        self.assertIn("Resultado por propuesta", html)
        self.assertIn("O-0001", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("sync ganadas", subject.lower())

    def test_master_report_explains_source_backup_and_warnings(self):
        subject, plain, html = master_refresh_report(
            2931,
            metadata={
                "source": "sharepoint",
                "file_name": "Planilla Master.xlsx",
                "source_last_modified": "2026-07-20T22:21:29Z",
                "blob_updated": True,
                "warnings": ["Advertencia de ejemplo"],
            },
        )

        self.assertIn("SharePoint", subject)
        self.assertIn("ATENCIÓN", subject)
        self.assertIn("Respaldo Blob actualizado: Sí", plain)
        self.assertIn("Advertencia de ejemplo", html)

    def test_upload_and_test_reports_explain_the_outcome(self):
        upload_subject, upload_plain, upload_html = upload_report("plano<script>.pdf", "pdf", 0, "rag")
        test_subject, test_plain, test_html = email_test_report("Canal de prueba")

        self.assertIn("ATENCIÓN", upload_subject)
        self.assertIn("Acción requerida", upload_plain)
        self.assertIn("plano&lt;script&gt;.pdf", upload_html)
        self.assertIn("configuradas correctamente", test_subject)
        self.assertIn("Azure Communication Services", test_plain)
        self.assertIn("Canal operativo disponible", test_html)

    def test_storage_report_has_visual_status_instead_of_preformatted_dump(self):
        subject, plain, html = storage_usage_report(
            {
                "account": "apphhdrive",
                "share": "shimin-data",
                "used_bytes": 80 * 1024**3,
                "quota_gb": 100,
                "utilization": 0.8,
            },
            [{"name": "database", "bytes": 30 * 1024**3}],
            0.7,
        )

        self.assertIn("ALERTA", subject)
        self.assertIn("Acción recomendada", plain)
        self.assertIn("80.0% utilizado", html)
        self.assertIn("database", html)
        self.assertNotIn("<pre", html)


if __name__ == "__main__":
    unittest.main()
