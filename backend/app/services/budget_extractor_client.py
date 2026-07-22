"""Cliente del microservicio Azure Function `budget-extractor-function`.

Flujo:
  1. Baja el Excel emitido del proyecto desde SharePoint
  2. Lo envía a la Function `/api/extract-normalized?codigo=O-XXXX`
  3. Recibe JSON normalizado (proyecto_filas, tarifas_filas, gastos_filas)
  4. Inserta en tablas SQLite locales: `proyectos_extracted`, `proyecto_tarifas`,
     `proyecto_gastos_reembolsables`, `proyecto_extraction_audit`

Stateless: cada extracción reemplaza los datos previos del mismo `codigo + source_file`.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("shimin.budget_extractor")


class BudgetExtractorClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 540.0) -> None:
        self.base_url = (base_url or settings.budget_extractor_url or "").rstrip("/")
        self.api_key = api_key or settings.budget_extractor_api_key or ""
        self.timeout = timeout
        self._ensure_tables()

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    async def extract_normalized(self, codigo: str, file_bytes: bytes, filename: str) -> dict:
        """POST al microservicio. Devuelve el dict tal cual lo manda la Function."""
        if not self.available:
            return {"error": "BUDGET_EXTRACTOR_URL no configurada"}
        headers = {"x-codigo": codigo, "x-filename": filename}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/extract-normalized",
                    params={"codigo": codigo},
                    headers=headers,
                    files={"file": (filename, file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                )
                if resp.status_code == 401:
                    return {"error": "401: BUDGET_EXTRACTOR_API_KEY inválida"}
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("extract_normalized HTTP %s for %s: %s", exc.response.status_code, codigo, exc.response.text[:300])
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"}
        except httpx.RequestError as exc:
            logger.warning("extract_normalized request error for %s: %s", codigo, exc)
            return {"error": f"Conexión: {exc}"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("extract_normalized unexpected error for %s", codigo)
            return {"error": f"{type(exc).__name__}: {exc}"}

    async def extract_from_sharepoint(self, codigo: str) -> dict:
        """Baja Excels emitidos del SharePoint para el código y los procesa con la Function.

        Devuelve `{extracted: [...], persisted: {...}}` con la persistencia agregada por archivo.
        """
        from app.services.sharepoint_client import SharePointClient
        sp = SharePointClient()
        files = await sp.list_emitido_files(codigo, kinds=(".xlsx", ".xlsm", ".xls"))
        if not files:
            return {"codigo": codigo, "error": "Sin Excels en '03 Oferta/02 Emitido' en SharePoint"}

        results = []
        for f in files:
            try:
                content = await sp.download_file(f)
            except Exception as exc:  # noqa: BLE001
                results.append({"file": f.get("name"), "error": f"download: {exc}"})
                continue
            extracted = await self.extract_normalized(codigo, content, f.get("name", "x.xlsx"))
            if extracted.get("error"):
                results.append({"file": f.get("name"), "error": extracted["error"]})
                continue
            persisted = self.persist(codigo, f.get("name", ""), extracted)
            results.append({"file": f.get("name"), "persisted": persisted, "totals": extracted.get("totals")})
        return {"codigo": codigo, "results": results}

    # ---- Persistencia ----

    def persist(self, codigo: str, source_file: str, extracted: dict) -> dict:
        """Inserta proyecto_filas / tarifas_filas / gastos_filas. Idempotente por (codigo, source_file)."""
        now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        source_file = self._canonical_source_file(source_file)
        proyecto_filas = extracted.get("proyecto_filas") or []
        tarifas_filas = extracted.get("tarifas_filas") or []
        gastos_filas = extracted.get("gastos_filas") or []
        with closing(sqlite3.connect(settings.sqlite_path, timeout=10)) as conn, conn:
            # Reemplaza también aliases históricos creados por el sufijo técnico
            # del cache local (archivo__ITEMID.xlsx).
            existing_names = {
                str(row[0])
                for row in conn.execute(
                    """
                    select source_file from proyectos_extracted where codigo=?
                    union select source_file from proyecto_tarifas where codigo=?
                    union select source_file from proyecto_gastos_reembolsables where codigo=?
                    """,
                    (codigo, codigo, codigo),
                ).fetchall()
                if row[0]
            }
            aliases = {
                name for name in existing_names
                if self._canonical_source_file(name).casefold() == source_file.casefold()
            }
            aliases.add(source_file)
            placeholders = ",".join("?" for _ in aliases)
            params = (codigo, *sorted(aliases))
            conn.execute(f"delete from proyectos_extracted where codigo=? and source_file in ({placeholders})", params)
            conn.execute(f"delete from proyecto_tarifas where codigo=? and source_file in ({placeholders})", params)
            conn.execute(f"delete from proyecto_gastos_reembolsables where codigo=? and source_file in ({placeholders})", params)
            for r in proyecto_filas:
                conn.execute(
                    """insert into proyectos_extracted
                       (codigo, descripcion, clasificacion, cargo, cargo_raw, hh, item, source_file, source_sheet, confidence, extracted_at)
                       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (codigo, r.get("descripcion"), r.get("clasificacion"), r.get("cargo"), r.get("cargo_raw"),
                     r.get("hh"), r.get("item"), source_file, r.get("source_sheet"), r.get("confidence"), now),
                )
            for r in tarifas_filas:
                conn.execute(
                    """insert into proyecto_tarifas
                       (codigo, cargo, cargo_raw, nombre_profesional, tarifa, moneda, source_file, source_sheet, confidence, extracted_at)
                       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (codigo, r.get("cargo"), r.get("cargo_raw"), r.get("nombre_profesional"),
                     r.get("tarifa"), r.get("moneda"), source_file, r.get("source_sheet"), r.get("confidence"), now),
                )
            for r in gastos_filas:
                conn.execute(
                    """insert into proyecto_gastos_reembolsables
                       (codigo, concepto, cantidad, precio_unit, total, moneda, source_file, source_sheet, confidence, extracted_at)
                       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (codigo, r.get("concepto"), r.get("cantidad"), r.get("precio_unit"),
                     r.get("total"), r.get("moneda"), source_file, r.get("source_sheet"), r.get("confidence"), now),
                )
            conn.execute(
                """insert into proyecto_extraction_audit
                   (codigo, source_file, proyecto_filas, tarifas_filas, gastos_filas, processing_time, extracted_at)
                   values (?, ?, ?, ?, ?, ?, ?)""",
                (codigo, source_file, len(proyecto_filas), len(tarifas_filas), len(gastos_filas),
                 extracted.get("_processing_time"), now),
            )
        return {
            "proyecto_filas": len(proyecto_filas),
            "tarifas_filas": len(tarifas_filas),
            "gastos_filas": len(gastos_filas),
        }

    @staticmethod
    def _canonical_source_file(source_file: str) -> str:
        """Converge nombre SharePoint y nombre del cache sin confundir archivos distintos."""
        name = Path(str(source_file or "").replace("\\", "/")).name
        path = Path(name)
        stem = re.sub(r"__[A-Z0-9]{8,}$", "", path.stem, flags=re.IGNORECASE)
        return f"{stem}{path.suffix}"

    def _ensure_tables(self) -> None:
        # Azure Files monta este directorio en produccion. SQLite no crea por
        # si solo el directorio padre durante el primer request del contenedor.
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(settings.sqlite_path, timeout=10)) as conn, conn:
            conn.executescript("""
                create table if not exists proyectos_extracted (
                    id integer primary key autoincrement,
                    codigo text not null,
                    descripcion text,
                    clasificacion text,
                    cargo text,
                    cargo_raw text,
                    hh real,
                    item text,
                    source_file text,
                    source_sheet text,
                    confidence real,
                    extracted_at text
                );
                create index if not exists idx_proyectos_extracted_codigo on proyectos_extracted(codigo);
                create index if not exists idx_proyectos_extracted_file on proyectos_extracted(codigo, source_file);

                create table if not exists proyecto_tarifas (
                    id integer primary key autoincrement,
                    codigo text not null,
                    cargo text,
                    cargo_raw text,
                    nombre_profesional text,
                    tarifa real,
                    moneda text,
                    source_file text,
                    source_sheet text,
                    confidence real,
                    extracted_at text
                );
                create index if not exists idx_proyecto_tarifas_codigo on proyecto_tarifas(codigo);
                create index if not exists idx_proyecto_tarifas_cargo on proyecto_tarifas(codigo, cargo);

                create table if not exists proyecto_gastos_reembolsables (
                    id integer primary key autoincrement,
                    codigo text not null,
                    concepto text,
                    cantidad real,
                    precio_unit real,
                    total real,
                    moneda text,
                    source_file text,
                    source_sheet text,
                    confidence real,
                    extracted_at text
                );
                create index if not exists idx_proyecto_gastos_codigo on proyecto_gastos_reembolsables(codigo);

                create table if not exists proyecto_extraction_audit (
                    id integer primary key autoincrement,
                    codigo text not null,
                    source_file text,
                    proyecto_filas integer,
                    tarifas_filas integer,
                    gastos_filas integer,
                    processing_time real,
                    extracted_at text
                );
                create index if not exists idx_extraction_audit_codigo on proyecto_extraction_audit(codigo);
            """)

    # ---- Lectura ----

    def get_for_codigo(self, codigo: str) -> dict:
        """Devuelve todo lo extraído para un código: filas, tarifas y gastos."""
        codigo = codigo.strip().upper()
        with closing(sqlite3.connect(settings.sqlite_path, timeout=10)) as conn:
            conn.row_factory = sqlite3.Row
            filas = [dict(r) for r in conn.execute(
                "select * from proyectos_extracted where codigo=? order by source_file, item", (codigo,)
            ).fetchall()]
            tarifas = [dict(r) for r in conn.execute(
                "select * from proyecto_tarifas where codigo=? order by cargo", (codigo,)
            ).fetchall()]
            gastos = [dict(r) for r in conn.execute(
                "select * from proyecto_gastos_reembolsables where codigo=?", (codigo,)
            ).fetchall()]
            audit = [dict(r) for r in conn.execute(
                "select * from proyecto_extraction_audit where codigo=? order by extracted_at desc", (codigo,)
            ).fetchall()]
        return {"codigo": codigo, "filas": filas, "tarifas": tarifas, "gastos": gastos, "audit": audit}
