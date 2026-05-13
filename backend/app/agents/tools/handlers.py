"""Handlers ejecutables para cada tool del agente.

Cada handler es una función `async def fn(ctx, **args) -> dict`. Recibe servicios
via `ToolContext` (creado una vez por request) y devuelve un dict serializable.

El dispatcher en `registry.py` se encarga de mapear nombres a funciones.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.rag.hybrid_store import HybridRagStore
from app.rag.parent_child import ParentChildIndexer
from app.services.deliverables_economics import DeliverablesEconomicsAnalyst
from app.services.entity_index import EntityIndex
from app.services.master_repository import MasterRepository
from app.services.master_stats_analyst import MasterStatsAnalyst
from app.services.proposal_index import ProposalIndexService
from app.services.proposal_support_advisor import ProposalSupportAdvisor
from app.services.search_filters import SearchFilters
from app.services.sharepoint_client import SharePointClient
from app.services.structured_wiki import StructuredWikiService


@dataclass
class ToolContext:
    master: MasterRepository
    hybrid_rag: HybridRagStore
    parent_child_rag: ParentChildIndexer
    proposal_index: ProposalIndexService
    entity_index: EntityIndex
    master_stats: MasterStatsAnalyst
    economics: DeliverablesEconomicsAnalyst
    proposal_support: ProposalSupportAdvisor
    wiki: StructuredWikiService
    sharepoint: SharePointClient

    @classmethod
    def build(cls) -> "ToolContext":
        return cls(
            master=MasterRepository(),
            hybrid_rag=HybridRagStore(),
            parent_child_rag=ParentChildIndexer(),
            proposal_index=ProposalIndexService(),
            entity_index=EntityIndex(),
            master_stats=MasterStatsAnalyst(),
            economics=DeliverablesEconomicsAnalyst(),
            proposal_support=ProposalSupportAdvisor(),
            wiki=StructuredWikiService(),
            sharepoint=SharePointClient(),
        )


def _filters(payload: dict | None, query: str | None = None, limit: int | None = None) -> SearchFilters:
    data = dict(payload or {})
    if query and not data.get("query"):
        data["query"] = query
    if limit and not data.get("limit"):
        data["limit"] = limit
    return SearchFilters(**data)


def _compact_master_row(row: dict) -> dict:
    keys = [
        "codigo",
        "titulo",
        "estado",
        "tipo_servicio",
        "cliente_directo",
        "cliente_final",
        "fecha_recep",
        "monto",
        "horas_lic",
        "tarifa_prom",
        "cod_proy",
    ]
    return {k: row.get(k) for k in keys if k in row}


def _compact_rag_hit(hit: dict) -> dict:
    meta = hit.get("metadata") or {}
    keep = ["estado", "estado_categoria", "cliente", "cliente_final", "tipo_servicio", "titulo", "section_title", "page_start", "page_end"]
    return {
        "codigo": hit.get("codigo"),
        "title": hit.get("title"),
        "url": hit.get("url"),
        "score": round(float(hit.get("score") or 0), 4),
        "vector_score": round(float(hit.get("vector_score") or 0), 4),
        "lexical_score": round(float(hit.get("lexical_score") or 0), 4),
        "summary": str(hit.get("summary") or "")[:700],
        "metadata": {k: meta.get(k) for k in keep if meta.get(k) is not None},
    }


def _compact_wiki_entry(entry: dict) -> dict:
    return {
        "id": entry.get("id"),
        "title": entry.get("title"),
        "category": entry.get("category"),
        "tags": entry.get("tags") or [],
        "propuestas_referenciadas": entry.get("propuestas_referenciadas") or [],
        "content": str(entry.get("content") or "")[:1200],
        "pinned": entry.get("pinned", False),
        "times_used": entry.get("times_used", 0),
        "validated_at": entry.get("validated_at"),
    }


# ---- handlers ----

async def search_master(
    ctx: ToolContext,
    query: str | None = None,
    queries: list[str] | None = None,
    filters: dict | None = None,
    limit: int = 12,
) -> dict:
    """Busca en master. `queries` permite sinónimos (OR semántico) — recomendado.

    Ej: queries=["depósito relaves", "tranque relaves", "relavera"]
    Si se da `queries`, se hace OR (search_many). Si no, búsqueda simple con `query`.
    """
    f = _filters(filters, query=query, limit=limit)
    rows: list[dict]
    if queries:
        all_rows = ctx.master.search_many([q for q in queries if q and q.strip()], limit=limit * 3)
        # Aplicar filtros estructurados post-hoc si vienen filtros
        if f.has_metadata_filters():
            seen = set()
            filtered: list[dict] = []
            for r in all_rows:
                codigo = str(r.get("codigo", "")).upper()
                if codigo in seen:
                    continue
                if f.matches_row_metadata(r, codigo):
                    filtered.append(r)
                    seen.add(codigo)
            rows = filtered[:limit]
        else:
            rows = all_rows[:limit]
    else:
        rows = ctx.master.search_filtered(f, limit=limit)
    return {
        "count": len(rows),
        "rows": [_compact_master_row(r) for r in rows[:limit]],
        "queries_used": queries or ([query] if query else []),
    }


async def search_rag(ctx: ToolContext, query: str | None = None, filters: dict | None = None, limit: int = 8) -> dict:
    f = _filters(filters, query=query, limit=limit)
    hits = await ctx.hybrid_rag.search(f.query or "", filters=f, limit=limit)
    return {
        "count": len(hits),
        "hits": [_compact_rag_hit(h) for h in hits[:limit]],
    }


async def search_proposal_index(ctx: ToolContext, query: str, codigos: list[str] | None = None, limit: int = 8) -> dict:
    codes = [c.upper() for c in codigos or []] or None
    hits = ctx.proposal_index.search(query, codes=codes, limit=limit)
    return {
        "count": len(hits),
        "hits": [
            {
                "codigo": h.get("codigo"),
                "title": h.get("title"),
                "url": h.get("url"),
                "summary": str(h.get("summary") or "")[:900],
                "score": float(h.get("score") or 0),
            }
            for h in hits[:limit]
        ],
    }


async def search_wiki_entries(ctx: ToolContext, query: str, category: str | None = None, tags: list[str] | None = None, limit: int = 6) -> dict:
    entries = ctx.wiki.search_entries(query=query, category=category, tags=tags, limit=limit)
    for entry in entries:
        if entry.get("id"):
            try:
                ctx.wiki.bump_usage(entry["id"])
            except Exception:
                pass
    return {
        "count": len(entries),
        "entries": [_compact_wiki_entry(e) for e in entries[:limit]],
    }


async def search_entities(ctx: ToolContext, query: str, filters: dict | None = None, limit: int = 20) -> dict:
    f = _filters(filters, query=query, limit=limit) if filters else None
    hits = ctx.entity_index.search(query, limit=limit, filters=f)
    return {
        "count": len(hits),
        "hits": hits[:limit],
        "codigos_top": list(dict.fromkeys(h["codigo"] for h in hits))[:12],
    }


async def compute_master_stats(ctx: ToolContext, query: str | None = None, limit: int = 50) -> dict:
    result = await asyncio.to_thread(ctx.master_stats.analyze, query, limit)
    summary = result.get("summary", {})
    return {
        "summary": summary,
        "tables": result.get("tables", [])[:4],
        "charts": result.get("charts", [])[:6],
    }


async def compute_economics(ctx: ToolContext, codigos: list[str] | None = None, limit: int = 6) -> dict:
    if not codigos:
        return {"rows": [], "note": "Sin códigos: pasa al menos uno"}
    upper = [c.upper() for c in codigos]
    rows: list[dict] = []
    for code in upper[:limit]:
        master_rows = ctx.master.search(codigo=code, limit=1)
        rows.extend(master_rows)
    result = await ctx.economics.analyze(rows, limit=limit)
    return {
        "rows": result.get("rows", []),
        "summary": result.get("summary", {}),
    }


async def compute_proposal_support(ctx: ToolContext, query: str, codigos: list[str] | None = None, limit: int = 10) -> dict:
    result = await asyncio.to_thread(ctx.proposal_support.advise, query, codigos or [], limit)
    return {
        "referencias_directas": result.get("referencias_directas", [])[:5],
        "referencias_comparables": result.get("referencias_comparables", [])[:5],
        "referencias_metodologicas": result.get("referencias_metodologicas", [])[:5],
        "referencias_hh_entregables": result.get("referencias_hh_entregables", [])[:5],
        "texto_sugerido_pdf": result.get("texto_sugerido_pdf", [])[:3],
        "gaps_a_validar": result.get("gaps_a_validar", [])[:6],
    }


async def get_proposal_detail(ctx: ToolContext, codigo: str) -> dict:
    upper = codigo.strip().upper()
    master_rows = ctx.master.search(codigo=upper, limit=3)
    f = SearchFilters(codigos=[upper], limit=6)
    rag_hits = await ctx.hybrid_rag.search("", filters=f, limit=6)
    wiki_entries = ctx.wiki.search_entries(query=upper, limit=4)
    return {
        "codigo": upper,
        "master_rows": [_compact_master_row(r) for r in master_rows],
        "rag_hits": [_compact_rag_hit(h) for h in rag_hits],
        "wiki_entries": [_compact_wiki_entry(e) for e in wiki_entries],
    }


async def read_pdf_deep(ctx: ToolContext, codigo: str, focus: str | None = None) -> dict:
    try:
        contexts = await asyncio.wait_for(
            ctx.sharepoint.fetch_relevant_pdf_text([codigo.upper()], focus or codigo),
            timeout=25,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"no se pudo leer PDF de {codigo}: {exc}", "contexts": []}
    summary = [
        {
            "pdf_name": c.get("pdf_name") or c.get("name") or "",
            "url": c.get("url"),
            "text": (c.get("text") or "")[:6000],
        }
        for c in contexts[:2]
    ]
    return {"codigo": codigo.upper(), "contexts": summary}


async def generate_document(
    ctx: ToolContext,
    kind: str = "docx",
    title: str = "Respuesta SHIMIN",
    content: str = "",
    tables: list[dict] | None = None,
    sources: list[dict] | None = None,
) -> dict:
    """Genera un documento descargable (docx/pdf/xlsx/typst-pdf con header SHIMIN).

    Guarda el archivo con un nombre único y devuelve la URL GET para descargarlo.
    """
    import shutil
    import uuid
    from app.core.config import settings
    from app.schemas import ExportRequest, Source
    from app.services.exports import ExportService
    valid_kinds = {"docx", "pdf", "xlsx", "typst-pdf", "report"}
    if kind not in valid_kinds:
        return {"error": f"kind inválido: {kind}. Usa: {sorted(valid_kinds)}"}
    request = ExportRequest(
        title=title,
        answer=content,
        tables=tables or [],
        sources=[Source(**s) if isinstance(s, dict) else s for s in (sources or [])],
    )
    base_path = ExportService().create(kind, request)
    # Mover a un nombre único para que múltiples documentos coexistan y el link no se sobrescriba
    ext = base_path.suffix or "." + ("pdf" if kind in {"report", "typst-pdf"} else kind)
    unique_name = f"{kind}_{uuid.uuid4().hex[:10]}{ext}"
    final_path = settings.resolve_path(settings.export_dir) / unique_name
    final_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(base_path, final_path)
    download_url = f"/api/exports/file/{unique_name}"
    return {
        "kind": kind,
        "filename": unique_name,
        "download_url": download_url,
        "markdown_link": f"📥 [Descargar {kind}]({download_url})",
        "note": (
            f"Archivo {unique_name} listo. Incluye este link en tu respuesta para que el usuario "
            f"lo descargue con un click: {download_url}"
        ),
    }


async def save_library_entry(
    ctx: ToolContext,
    title: str,
    content: str,
    category: str = "general",
    tags: list[str] | None = None,
    propuestas_referenciadas: list[str] | None = None,
    pinned: bool = False,
) -> dict:
    entry = ctx.wiki.upsert_entry(
        title=title,
        content=content,
        category=category,
        tags=tags or [],
        pinned=pinned,
        source="agent",
        propuestas_referenciadas=propuestas_referenciadas or [],
    )
    return {"saved": True, "entry": _compact_wiki_entry(entry)}
