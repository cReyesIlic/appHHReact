import csv
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.hh_excel_extractor import HHExcelExtractor
from app.services.master_repository import MasterRepository
from app.rag.hybrid_store import HybridRagStore
from app.rag.parent_child import ParentChildIndexer


class OpsDashboardService:
    def __init__(self) -> None:
        self.root = settings.project_root
        self.manifest_path = self.root / "storage" / "emitted_offer_assets" / "manifest.csv"

    def build(self, limit: int = 80) -> dict[str, Any]:
        master_rows = MasterRepository().all_offers()
        manifest_rows = self._read_manifest()
        manifest_by_code = {self._code(row.get("codigo")): row for row in manifest_rows if self._code(row.get("codigo"))}

        won_rows = [row for row in master_rows if str(row.get("estado", "")).strip().upper() == "PG"]
        won_rows = sorted(won_rows, key=lambda row: self._date_key(row.get("fecha_recep")), reverse=True)
        recent_cutoff = datetime.now() - timedelta(days=180)
        new_won = [row for row in won_rows if self._date_key(row.get("fecha_recep")) >= recent_cutoff]

        gaps = []
        for row in master_rows:
            code = self._code(row.get("codigo"))
            if not code:
                continue
            manifest = manifest_by_code.get(code, {})
            gap = self._asset_gap(manifest)
            if gap:
                gaps.append(
                    {
                        "codigo": code,
                        "titulo": row.get("titulo", ""),
                        "cliente_final": row.get("cliente_final", ""),
                        "estado": row.get("estado", ""),
                        "fecha_recep": row.get("fecha_recep", ""),
                        "gap": gap,
                        "asset_status": manifest.get("status", "sin_manifest"),
                        "pdf_count": self._int(manifest.get("pdf_count")),
                        "excel_count": self._int(manifest.get("excel_count")),
                        "zip_count": self._int(manifest.get("zip_count")),
                        "selected_pdf": manifest.get("selected_pdf", ""),
                        "selected_excel": manifest.get("selected_excel", ""),
                    }
                )

        return {
            "summary": {
                "master_rows": len(master_rows),
                "manifest_rows": len(manifest_rows),
                "won_total": len(won_rows),
                "won_last_180_days": len(new_won),
                "missing_pdf": sum(1 for row in gaps if row["gap"] in {"sin_pdf", "sin_pdf_y_excel"}),
                "missing_excel": sum(1 for row in gaps if row["gap"] in {"sin_excel", "sin_pdf_y_excel"}),
                "no_assets": sum(1 for row in manifest_rows if row.get("status") == "no_assets"),
                "asset_errors": sum(1 for row in manifest_rows if row.get("status") == "error"),
            },
            "master": {
                "sqlite_path": str(settings.sqlite_path),
                "master_path": settings.master_path,
                "master_blob": settings.master_path_blob,
            },
            "sqlite": self._sqlite_counts(),
            "rag": {
                "parent_child": ParentChildIndexer().status(),
                "hybrid": HybridRagStore().status(),
            },
            "hh_excel": HHExcelExtractor().summary(),
            "asset_status": dict(Counter(row.get("status", "unknown") for row in manifest_rows)),
            "won_recent": [self._project_master_row(row) for row in won_rows[:limit]],
            "won_new": [self._project_master_row(row) for row in new_won[:limit]],
            "asset_gaps": gaps[:limit],
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def build_coverage(self, estado: str | None = "PG", limit: int = 5000) -> dict[str, Any]:
        master_rows = MasterRepository().all_offers()
        manifest_rows = self._read_manifest()
        manifest_by_code = {self._code(row.get("codigo")): row for row in manifest_rows if self._code(row.get("codigo"))}

        codes_in_rag: set[str] = set()
        codes_with_hh: set[str] = set()
        if settings.sqlite_path.exists():
            with sqlite3.connect(settings.sqlite_path) as conn:
                available = {
                    row[0]
                    for row in conn.execute("select name from sqlite_master where type='table'").fetchall()
                }
                if "rag_child_chunks" in available:
                    codes_in_rag = {
                        self._code(row[0])
                        for row in conn.execute("select distinct codigo from rag_child_chunks where codigo is not null").fetchall()
                    }
                if "hh_estimate_rows" in available:
                    codes_with_hh = {
                        self._code(row[0])
                        for row in conn.execute("select distinct codigo from hh_estimate_rows where codigo is not null").fetchall()
                    }
                if "proyectos_extracted" in available:
                    codes_with_hh |= {
                        self._code(row[0])
                        for row in conn.execute("select distinct codigo from proyectos_extracted where codigo is not null").fetchall()
                    }

        recent_cutoff = datetime.now() - timedelta(days=60)
        estado_norm = (estado or "").strip().upper()
        rows: list[dict[str, Any]] = []
        for row in master_rows:
            code = self._code(row.get("codigo"))
            if not code:
                continue
            row_estado = str(row.get("estado", "")).strip().upper()
            if estado_norm and row_estado != estado_norm:
                continue
            manifest = manifest_by_code.get(code, {})
            has_pdf = self._int(manifest.get("pdf_count")) > 0 or bool(manifest.get("selected_pdf_local"))
            has_excel = self._int(manifest.get("excel_count")) > 0 or bool(manifest.get("selected_excel_local"))
            for item in self._zip_assets(manifest.get("zip_assets")):
                lower = str(item).lower()
                has_pdf = has_pdf or lower.endswith(".pdf")
                has_excel = has_excel or lower.endswith((".xlsx", ".xls", ".xlsm"))
            manifest_updated = str(manifest.get("updated_at", "") or "")
            is_recent = False
            try:
                if manifest_updated:
                    ts = datetime.fromisoformat(manifest_updated[:19])
                    is_recent = ts >= recent_cutoff
            except ValueError:
                is_recent = False
            rows.append(
                {
                    "codigo": code,
                    "cod_proy": str(row.get("cod_proy", "") or "").strip(),
                    "titulo": row.get("titulo", ""),
                    "cliente_final": row.get("cliente_final", ""),
                    "estado": row_estado,
                    "fecha_recep": row.get("fecha_recep", ""),
                    "pdf": has_pdf,
                    "excel": has_excel,
                    "excel_parsed": code in codes_with_hh,
                    "in_db": code in codes_in_rag,
                    "updated_at": manifest_updated,
                    "is_recent": is_recent,
                }
            )

        rows.sort(key=lambda r: (r.get("updated_at") or "", self._date_key(r.get("fecha_recep")).isoformat()), reverse=True)
        totals = {
            "total": len(rows),
            "with_pdf": sum(1 for r in rows if r["pdf"]),
            "with_excel": sum(1 for r in rows if r["excel"]),
            "excel_parsed": sum(1 for r in rows if r["excel_parsed"]),
            "in_db": sum(1 for r in rows if r["in_db"]),
            "incomplete": sum(1 for r in rows if not (r["pdf"] and r["excel"] and r["in_db"])),
            "recent": sum(1 for r in rows if r["is_recent"]),
        }
        return {
            "estado_filter": estado_norm or None,
            "totals": totals,
            "rows": rows[:limit],
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _read_manifest(self) -> list[dict[str, str]]:
        if not self.manifest_path.exists():
            return []
        with self.manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def _sqlite_counts(self) -> list[dict[str, Any]]:
        if not settings.sqlite_path.exists():
            return []
        tables = [
            "oferta",
            "rag_parent_sections",
            "rag_child_chunks",
            "rag_child_embeddings",
            "proposal_entities",
            "hh_estimate_rows",
        ]
        rows = []
        with sqlite3.connect(settings.sqlite_path) as conn:
            available = {
                row[0]
                for row in conn.execute("select name from sqlite_master where type='table'").fetchall()
            }
            for table in tables:
                if table not in available:
                    rows.append({"table": table, "rows": 0, "exists": False})
                    continue
                count = conn.execute(f'select count(*) from "{table}"').fetchone()[0]
                rows.append({"table": table, "rows": count, "exists": True})
        return rows

    def _asset_gap(self, manifest: dict[str, Any]) -> str | None:
        has_pdf = self._int(manifest.get("pdf_count")) > 0 or bool(manifest.get("selected_pdf_local"))
        has_excel = self._int(manifest.get("excel_count")) > 0 or bool(manifest.get("selected_excel_local"))
        for item in self._zip_assets(manifest.get("zip_assets")):
            lower = str(item).lower()
            has_pdf = has_pdf or lower.endswith(".pdf")
            has_excel = has_excel or lower.endswith((".xlsx", ".xls", ".xlsm"))
        if has_pdf and has_excel:
            return None
        if not has_pdf and not has_excel:
            return "sin_pdf_y_excel"
        if not has_pdf:
            return "sin_pdf"
        return "sin_excel"

    def _zip_assets(self, value: object) -> list[str]:
        if not value:
            return []
        try:
            parsed = json.loads(str(value))
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            return []
        return []

    def _project_master_row(self, row: dict[str, Any]) -> dict[str, Any]:
        keys = ["codigo", "fecha_recep", "cliente_directo", "cliente_final", "titulo", "estado", "tipo_servicio", "cod_proy", "monto", "horas_lic", "tarifa_prom"]
        return {key: row.get(key, "") for key in keys}

    def _date_key(self, value: object) -> datetime:
        text = str(value or "").strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(text[:10], fmt)
            except ValueError:
                continue
        return datetime.min

    def _code(self, value: object) -> str:
        return str(value or "").strip().upper()

    def _int(self, value: object) -> int:
        try:
            return int(float(str(value or "0").replace(",", ".")))
        except ValueError:
            return 0
