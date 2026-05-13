"""Sincronización end-to-end SharePoint → Master/RAG/Wiki.

Flujo por código:
  1. Lista PDFs en SharePoint (último válido)
  2. Descarga PDF localmente (cache)
  3. Parsea texto completo + páginas
  4. Indexa en `rag_parent_sections + rag_child_chunks` (tabla agente híbrido)
  5. Genera embeddings (`HybridRagStore.build()` con `--force=False` solo indexa pendientes)
  6. Compila página Wiki vía `WikiAutoCompiler.compile_for_proposal()`
  7. Actualiza manifest CSV

Idempotente:
  - Si el código ya tiene parent_sections, replace_chunks lo reemplaza.
  - Si la página Wiki ya existe y `force_wiki=False`, skip.
  - Si los embeddings ya existen para el child_id+model, skip (LEFT JOIN filter).

Modo dry-run:
  - `discover_new()` lista códigos en SharePoint que NO están aún en master/RAG/wiki.
  - No descarga, no llama LLM, no indexa.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.rag.hybrid_store import HybridRagStore
from app.rag.parent_child import ParentChildIndexer
from app.services.knowledge_extractor import KnowledgeExtractor
from app.services.knowledge_models import ProposalMetadata
from app.services.master_repository import MasterRepository
from app.services.proposal_taxonomy import enrich_metadata
from app.services.rag_store import RagStore
from app.services.sharepoint_client import SharePointClient
from app.services.structured_wiki import StructuredWikiService
from app.services.wiki_auto_compiler import WikiAutoCompiler


MANIFEST_PATH = "storage/sync_manifest.csv"
MANIFEST_COLUMNS = [
    "codigo",
    "status",
    "pdf_name",
    "chunks_parent",
    "chunks_child",
    "wiki_status",
    "wiki_path",
    "error",
    "updated_at",
]


@dataclass
class SyncCounters:
    discovered: int = 0
    ingested: int = 0
    skipped: int = 0
    errors: int = 0
    wiki_ok: int = 0
    wiki_skipped: int = 0
    wiki_no_rag: int = 0
    wiki_error: int = 0
    by_code: list[dict] = field(default_factory=list)


class ProposalSyncService:
    def __init__(self) -> None:
        self.sharepoint = SharePointClient()
        self.master = MasterRepository()
        self.extractor = KnowledgeExtractor()
        self.rag_store = RagStore()
        self.parent_child = ParentChildIndexer()
        self.hybrid = HybridRagStore()
        self.wiki = StructuredWikiService()
        self.wiki_compiler = WikiAutoCompiler()

    # ---- discovery ----

    async def discover_new(self, limit: int = 200) -> dict:
        """Lista códigos en SharePoint que aún NO están indexados en RAG parent_child."""
        folders = await self.sharepoint.list_offer_folders(limit=limit)
        already = self._codigos_with_rag()
        new = [f for f in folders if f.get("codigo", "").upper() not in already]
        return {
            "sharepoint_total": len(folders),
            "already_indexed": len(folders) - len(new),
            "new_count": len(new),
            "new": new[:limit],
        }

    def discover_wiki_gaps(self, only_with_rag: bool = True) -> dict:
        """Devuelve códigos con RAG indexado pero SIN página Wiki en disco."""
        rag_codes = self._codigos_with_rag()
        proposals_dir = settings.resolve_path("storage/llm_wiki/proposals")
        existing = {p.stem.upper() for p in proposals_dir.glob("O-*.md")} if proposals_dir.exists() else set()
        missing = sorted(rag_codes - existing)
        return {
            "rag_count": len(rag_codes),
            "wiki_pages": len(existing),
            "missing_wiki": len(missing),
            "missing_codes": missing,
        }

    # ---- sync per code ----

    async def sync_code(self, codigo: str, *, force_wiki: bool = False, build_embeddings: bool = True) -> dict:
        codigo = codigo.upper().strip()
        result = {
            "codigo": codigo,
            "status": "pending",
            "chunks_parent": 0,
            "chunks_child": 0,
            "wiki_status": "skipped",
        }

        # 1-3. Descargar y parsear
        try:
            pdfs = await self.sharepoint.list_pdfs(codigo)
            latest = self.sharepoint.select_latest_pdf(pdfs)
            if not latest:
                result.update({"status": "no_pdf"})
                self._record_manifest(result)
                return result
            content = await self.sharepoint.download_pdf(latest)
            local_path = self.sharepoint.save_pdf_locally(codigo, latest.get("name", "proposal.pdf"), content)
            first_pages = self.sharepoint.extract_first_pages_text(content, pages=5)
            full_text = self.sharepoint.extract_full_text(content)
            result["pdf_name"] = latest.get("name")
        except Exception as exc:  # noqa: BLE001
            result.update({"status": "error", "error": f"sharepoint: {exc}"})
            self._record_manifest(result)
            return result

        # 4. Indexar en parent_child (tabla híbrida)
        metadata = self._metadata(codigo, latest, str(local_path))
        try:
            knowledge = await self.extractor.extract(metadata, first_pages, full_text)
            raw_metadata = {**metadata.model_dump(), **knowledge.model_dump()}
            enriched = enrich_metadata(raw_metadata)
            parse_result = {"text": full_text, "pages": []}
            pc_result = self.parent_child.index_parse_result(codigo, parse_result, enriched)
            result["chunks_parent"] = pc_result.get("parents", 0)
            result["chunks_child"] = pc_result.get("children", 0)
            # Legacy chunks (rag_chunks) — opcional, mantiene compat
            chunks = self.rag_store.make_chunks(
                codigo=codigo,
                text=full_text,
                source=latest.get("webUrl") or str(local_path),
                metadata=raw_metadata,
            )
            self.rag_store.upsert_proposal(metadata, knowledge)
            self.rag_store.replace_chunks(codigo, chunks)
        except Exception as exc:  # noqa: BLE001
            result.update({"status": "error", "error": f"indexing: {exc}"})
            self._record_manifest(result)
            return result

        # 5. Embeddings (solo pendientes — idempotente)
        if build_embeddings:
            try:
                # Solo procesa chunks de este codigo si están sin embedding
                await self._build_embeddings_for_code(codigo)
            except Exception as exc:  # noqa: BLE001
                result["embedding_error"] = str(exc)

        # 6. Wiki autocompile
        try:
            wiki_res = await self.wiki_compiler.compile_for_proposal(codigo, force=force_wiki)
            result["wiki_status"] = wiki_res.get("status")
            result["wiki_path"] = wiki_res.get("path")
        except Exception as exc:  # noqa: BLE001
            result["wiki_status"] = "error"
            result["wiki_error"] = str(exc)

        result["status"] = "ok"
        self._record_manifest(result)
        return result

    async def sync_new(self, limit: int = 50, force_wiki: bool = False) -> dict:
        discovery = await self.discover_new(limit=limit)
        counters = SyncCounters(discovered=discovery["new_count"])
        for folder in discovery["new"]:
            codigo = folder.get("codigo")
            if not codigo:
                continue
            outcome = await self.sync_code(codigo, force_wiki=force_wiki)
            counters.by_code.append(outcome)
            if outcome["status"] == "ok":
                counters.ingested += 1
            elif outcome["status"] in {"skipped", "no_pdf"}:
                counters.skipped += 1
            else:
                counters.errors += 1
            wiki_st = outcome.get("wiki_status")
            if wiki_st == "ok":
                counters.wiki_ok += 1
            elif wiki_st == "skipped":
                counters.wiki_skipped += 1
            elif wiki_st == "no_rag":
                counters.wiki_no_rag += 1
            elif wiki_st in {"error"}:
                counters.wiki_error += 1
        return {
            "discovered": counters.discovered,
            "ingested": counters.ingested,
            "skipped": counters.skipped,
            "errors": counters.errors,
            "wiki_ok": counters.wiki_ok,
            "wiki_skipped": counters.wiki_skipped,
            "wiki_no_rag": counters.wiki_no_rag,
            "wiki_error": counters.wiki_error,
            "details": counters.by_code,
        }

    # ---- backfill wiki for already-RAG'd proposals ----

    async def backfill_wiki(
        self,
        codigos: list[str] | None = None,
        *,
        force: bool = False,
        limit: int | None = None,
        concurrency: int = 8,
    ) -> dict:
        """Compila páginas Wiki para códigos que ya tienen RAG indexado, en paralelo.

        Si `codigos` es None, usa `discover_wiki_gaps`. Útil para 1500+ propuestas existentes.
        Concurrencia por defecto = 8 (ajustable; Azure tiene rate limits — bajar si fallan llamadas).
        """
        import asyncio

        if codigos:
            target = [c.upper() for c in codigos]
        else:
            gap = self.discover_wiki_gaps()
            target = gap["missing_codes"]
        if limit:
            target = target[:limit]

        counters = SyncCounters(discovered=len(target))
        sem = asyncio.Semaphore(max(1, concurrency))
        progress = {"done": 0}
        total = len(target)
        progress_lock = asyncio.Lock()

        async def worker(codigo: str) -> dict:
            async with sem:
                try:
                    outcome = await self.wiki_compiler.compile_for_proposal(codigo, force=force)
                except Exception as exc:  # noqa: BLE001
                    outcome = {"codigo": codigo, "status": "error", "error": str(exc)}
                async with progress_lock:
                    progress["done"] += 1
                    if progress["done"] % 25 == 0 or progress["done"] == total:
                        print(
                            f"  · backfill: {progress['done']}/{total} ok={counters.wiki_ok} err={counters.wiki_error}",
                            flush=True,
                        )
                if outcome.get("status") == "ok":
                    counters.wiki_ok += 1
                elif outcome.get("status") == "skipped":
                    counters.wiki_skipped += 1
                elif outcome.get("status") == "no_rag":
                    counters.wiki_no_rag += 1
                else:
                    counters.wiki_error += 1
                counters.by_code.append(outcome)
                return outcome

        await asyncio.gather(*(worker(c) for c in target))
        return {
            "target_count": total,
            "wiki_ok": counters.wiki_ok,
            "wiki_skipped": counters.wiki_skipped,
            "wiki_no_rag": counters.wiki_no_rag,
            "wiki_error": counters.wiki_error,
            "details": counters.by_code,
        }

    # ---- internal helpers ----

    def _codigos_with_rag(self) -> set[str]:
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            rows = conn.execute("select distinct codigo from rag_parent_sections").fetchall()
        return {str(r[0]).upper() for r in rows if r[0]}

    async def _build_embeddings_for_code(self, codigo: str) -> dict:
        """Genera embeddings solo para los chunks del código sin embedding (del modelo activo)."""
        # HybridRagStore.build() ya filtra por LEFT JOIN sobre embeddings del modelo activo,
        # pero no por codigo. Hacemos una corrida limitada apuntada con un fetch directo.
        model = self.hybrid.embeddings.deployment
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            rows = [
                dict(r)
                for r in conn.execute(
                    """
                    select c.child_id, c.parent_id, c.codigo, c.text, c.page_start, c.page_end, c.metadata,
                           p.title, p.text as parent_text, p.metadata as parent_metadata
                    from rag_child_chunks c
                    join rag_parent_sections p on p.parent_id = c.parent_id
                    left join rag_child_embeddings e on e.child_id = c.child_id and e.model = ?
                    where c.codigo = ? and e.child_id is null
                    order by c.parent_id, c.child_id
                    """,
                    (model, codigo.upper()),
                ).fetchall()
            ]
        if not rows:
            return {"selected": 0, "processed": 0}
        for row in rows:
            metadata = json.loads(row.get("metadata") or "{}")
            parent_metadata = json.loads(row.get("parent_metadata") or "{}")
            row["metadata_dict"] = metadata
            row["parent_metadata_dict"] = parent_metadata
            row["embedding_text"] = self.hybrid._embedding_text(row, metadata, parent_metadata)
            row["content_hash"] = self.hybrid.embeddings.content_hash(row["embedding_text"])
        vectors = await self.hybrid.embeddings.embed_texts([r["embedding_text"] for r in rows])
        self.hybrid._save_batch(rows, vectors)
        return {"selected": len(rows), "processed": len(rows)}

    def _metadata(self, codigo: str, pdf: dict, local_path: str) -> ProposalMetadata:
        master = self.master.search(codigo=codigo, limit=1)
        row = master[0] if master else {}
        return ProposalMetadata(
            codigo=codigo,
            pdf_name=pdf.get("name", ""),
            url=pdf.get("webUrl"),
            local_path=local_path,
            cliente=row.get("cliente_directo"),
            cliente_final=row.get("cliente_final"),
            titulo=row.get("titulo"),
            estado=row.get("estado"),
            tipo_servicio=row.get("tipo_servicio"),
            fecha_recepcion=row.get("fecha_recep") or row.get("fecha_recepcion"),
        )

    def _record_manifest(self, result: dict) -> None:
        path = settings.resolve_path(MANIFEST_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
            if is_new:
                writer.writeheader()
            writer.writerow(
                {
                    "codigo": result.get("codigo", ""),
                    "status": result.get("status", ""),
                    "pdf_name": result.get("pdf_name", ""),
                    "chunks_parent": result.get("chunks_parent", 0),
                    "chunks_child": result.get("chunks_child", 0),
                    "wiki_status": result.get("wiki_status", ""),
                    "wiki_path": result.get("wiki_path", ""),
                    "error": result.get("error", ""),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
