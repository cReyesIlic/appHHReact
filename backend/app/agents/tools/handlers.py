"""Handlers ejecutables para cada tool del agente.

Cada handler es una función `async def fn(ctx, **args) -> dict`. Recibe servicios
via `ToolContext` (creado una vez por request) y devuelve un dict serializable.

El dispatcher en `registry.py` se encarga de mapear nombres a funciones.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from app.rag.hybrid_store import HybridRagStore
from app.rag.parent_child import ParentChildIndexer
from app.services.budget_extractor_client import BudgetExtractorClient
from app.services.deliverables_economics import DeliverablesEconomicsAnalyst
from app.services.entity_index import EntityIndex
from app.services.entregables_repository import EntregablesRepository
from app.services.master_repository import MasterRepository
from app.services.master_stats_analyst import MasterStatsAnalyst
from app.services.proposal_index import ProposalIndexService
from app.services.proposal_support_advisor import ProposalSupportAdvisor
from app.services.proposal_drafts import ProposalDraftService
from app.services.search_filters import SearchFilters
from app.services.sharepoint_client import SharePointClient
from app.services.staffing_client import StaffingClient
from app.services.structured_wiki import StructuredWikiService
from app.services.user_context import get_current_user


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
    staffing: StaffingClient
    entregables: EntregablesRepository
    budget_extractor: BudgetExtractorClient
    drafts: ProposalDraftService

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
            staffing=StaffingClient(),
            entregables=EntregablesRepository(),
            budget_extractor=BudgetExtractorClient(),
            drafts=ProposalDraftService(),
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


async def search_rag(
    ctx: ToolContext,
    query: str | None = None,
    queries: list[str] | None = None,
    filters: dict | None = None,
    limit: int = 8,
) -> dict:
    """Busca varias formulaciones semánticas y fusiona los resultados."""
    variants: list[str] = []
    for value in [*(queries or []), query]:
        clean = str(value or "").strip()
        if clean and clean.casefold() not in {item.casefold() for item in variants}:
            variants.append(clean)
    variants = variants[:6] or [""]

    async def run_variant(value: str) -> tuple[str, list[dict]]:
        effective = _filters(filters, query=value, limit=limit)
        return value, await ctx.hybrid_rag.search(value, filters=effective, limit=limit)

    groups = await asyncio.gather(*(run_variant(value) for value in variants))
    merged: dict[tuple, dict] = {}
    coverage: list[dict] = []
    for variant, variant_hits in groups:
        coverage.append({"query": variant, "hits": len(variant_hits)})
        for hit in variant_hits:
            compact = _compact_rag_hit(hit)
            compact["matched_query"] = variant
            key = (compact.get("codigo"), compact.get("title"), compact.get("summary"))
            previous = merged.get(key)
            if previous is None or float(compact.get("score") or 0) > float(previous.get("score") or 0):
                merged[key] = compact
    hits = sorted(
        merged.values(),
        key=lambda item: float(item.get("score") or 0),
        reverse=True,
    )[:limit]
    return {
        "count": len(hits),
        "hits": hits,
        "queries_used": variants,
        "coverage": coverage,
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
    result_rows = result.get("rows", [])
    return {
        "rows": result_rows,
        "summary": result.get("summary", {}),
        "tables": [{"name": "Economía de referencias", "rows": result_rows}],
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
        "entity_expansions": result.get("entity_expansions", [])[:18],
        "deepening_plan": result.get("deepening_plan", [])[:8],
        "tables": result.get("tables", [])[:2],
    }


async def get_proposal_detail(ctx: ToolContext, codigo: str) -> dict:
    upper = codigo.strip().upper()
    master_rows = ctx.master.search(codigo=upper, limit=3)
    f = SearchFilters(codigos=[upper], limit=6)
    rag_hits = await ctx.hybrid_rag.search("", filters=f, limit=6)
    wiki_entries = ctx.wiki.search_entries(query=upper, limit=4)
    compact_master = [_compact_master_row(r) for r in master_rows]
    return {
        "codigo": upper,
        "master_rows": compact_master,
        "rag_hits": [_compact_rag_hit(h) for h in rag_hits],
        "wiki_entries": [_compact_wiki_entry(e) for e in wiki_entries],
        "tables": [{"name": f"Ficha comercial {upper}", "rows": compact_master}],
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


async def get_hh_licitadas(
    ctx: ToolContext,
    codigo: str,
    view: str = "entregable",
    text: str | None = None,
    limit: int = 200,
) -> dict:
    """Consulta HH estimadas/licitadas del Excel-Master y devuelve sus archivos fuente."""
    from app.services.sharepoint_client import normalize_offer_code

    normalized = normalize_offer_code(codigo)
    if not normalized:
        return {"error": f"Código de oferta inválido: {codigo}", "rows": []}
    if view not in {"proyecto", "disciplina", "role", "entregable"}:
        return {"error": f"Vista licitada desconocida: {view}", "rows": []}

    result = await asyncio.to_thread(
        ctx.entregables.aggregate_licitadas,
        view=view,
        codigo=normalized,
        text=text,
        limit=max(1, min(int(limit or 200), 500)),
    )
    result["codigo"] = normalized

    # Entrega enlaces reales a los PDF/Excel emitidos. Los datos tabulares siguen
    # siendo válidos aunque Graph no esté disponible temporalmente.
    assets: list[dict] = []
    files: list[dict] = []
    try:
        files = await ctx.sharepoint.list_emitido_files(
            normalized,
            kinds=(".pdf", ".docx", ".xlsx", ".xlsm", ".xls"),
        )
        assets = [
            {
                "codigo": normalized,
                "title": item.get("name") or normalized,
                "url": item.get("webUrl"),
                "kind": item.get("kind"),
                "last_modified": item.get("lastModifiedDateTime"),
            }
            for item in files[:12]
            if item.get("webUrl")
        ]
    except Exception as exc:  # noqa: BLE001
        result["source_assets_error"] = f"No se pudieron listar enlaces SharePoint: {exc}"
    result["source_assets"] = assets

    # Si el pipeline todavía no procesó este código, intenta el Excel emitido
    # inmediatamente. Así una pregunta no confunde "aún no ingerido" con
    # "el desglose no existe".
    if not result.get("rows"):
        excel_files = [
            item for item in files
            if str(item.get("kind") or "").casefold() in {"xlsx", "xlsm", "xls"}
        ]
        refresh_rows = []
        if excel_files and ctx.budget_extractor.available:
            selected = sorted(
                excel_files,
                key=lambda item: str(item.get("lastModifiedDateTime") or ""),
                reverse=True,
            )[:2]
            for item in selected:
                name = str(item.get("name") or f"{normalized}.xlsx")
                try:
                    content = await ctx.sharepoint.download_file(item)
                    extracted = await asyncio.wait_for(
                        ctx.budget_extractor.extract_normalized(normalized, content, name),
                        timeout=240,
                    )
                    if extracted.get("error"):
                        refresh_rows.append({"file": name, "error": extracted["error"]})
                        continue
                    persisted = ctx.budget_extractor.persist(normalized, name, extracted)
                    refresh_rows.append({"file": name, "persisted": persisted})
                except Exception as exc:  # noqa: BLE001
                    refresh_rows.append({"file": name, "error": str(exc)})
            refreshed = await asyncio.to_thread(
                ctx.entregables.aggregate_licitadas,
                view=view,
                codigo=normalized,
                text=text,
                limit=max(1, min(int(limit or 200), 500)),
            )
            if refreshed.get("rows"):
                result = refreshed
                result["codigo"] = normalized
                result["source_assets"] = assets
        result["excel_refresh"] = refresh_rows

    table_rows = []
    for row in result.get("rows") or []:
        compact = dict(row)
        roles = compact.get("roles")
        if isinstance(roles, dict):
            compact["roles"] = ", ".join(
                f"{role.upper()}: {hours:g}" for role, hours in roles.items()
            )
        table_rows.append(compact)
    result["tables"] = [{"name": f"HH licitadas {normalized} · {view}", "rows": table_rows}]
    return result


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


def _compact_entregable(row: dict) -> dict:
    """Compactar una fila de entregable de la API staffing para no inflar contexto."""
    return {
        "entregable_id": row.get("entregable_id"),
        "entregable_nombre": str(row.get("entregable_nombre") or "")[:160],
        "proyecto_codigo": row.get("proyecto_codigo"),
        "horas_totales": row.get("horas_totales") or row.get("hh_totales"),
        "personas_count": row.get("personas_count") or row.get("n_personas"),
        "disciplina": row.get("disciplina") or row.get("disciplina_nombre"),
        "cliente_resuelto": row.get("cliente_resuelto") or row.get("cliente"),
        "codigo_prop": row.get("codigo_prop"),
        "servicio": row.get("servicio") or row.get("tipo_servicio"),
        "personas_detalle": [
            {
                "usuario_id": p.get("usuario_id"),
                "nombre": p.get("nombre"),
                "horas": p.get("horas") or p.get("hh"),
            }
            for p in (row.get("personas_detalle") or [])[:6]
        ] if row.get("personas_detalle") else None,
    }


async def search_entregables_hh(
    ctx: ToolContext,
    q: str | None = None,
    disciplina: str | None = None,
    contexto: str | None = None,
    proyecto_codigo: str | None = None,
    ano: int | None = None,
    top: int = 30,
    incluir_personas: bool = True,
) -> dict:
    """Búsqueda de entregables con HH REALES cargadas (no estimadas).

    Llama al endpoint /external/entregables/analisis-hh del staffing app.
    Útil para responder preguntas tipo "memoria de cálculo hidráulica en Caserones",
    "planos de piping para Vale", "informes de hidráulica con Codelco".
    """
    if not ctx.staffing.available:
        return {"error": "STAFFING_API_KEY no configurada — agrégalo al .env / App Settings"}
    result = await ctx.staffing.analisis_hh(
        q=q, disciplina=disciplina, contexto=contexto,
        proyecto_codigo=proyecto_codigo, ano=ano,
        top=min(top, 200), incluir_personas=incluir_personas,
    )
    if "error" in result:
        return result
    detalle = result.get("detalle") or []
    compacted = [_compact_entregable(row) for row in detalle[:top]]
    table_rows = [
        {
            "proyecto": row.get("proyecto_codigo"),
            "oferta": row.get("codigo_prop"),
            "entregable": row.get("entregable_nombre"),
            "disciplina": row.get("disciplina"),
            "hh_reales": row.get("horas_totales"),
            "personas": row.get("personas_count"),
            "cliente": row.get("cliente_resuelto"),
        }
        for row in compacted
    ]
    return {
        "resumen": result.get("resumen") or {},
        "distribucion_disciplina": result.get("distribucion_disciplina") or {},
        "distribucion_cliente": result.get("distribucion_cliente") or {},
        "distribucion_servicio": result.get("distribucion_servicio") or {},
        "count": len(detalle),
        "entregables": compacted,
        "tables": [{"name": "HH reales de entregables comparables", "rows": table_rows}],
    }


async def get_horas_detalle(
    ctx: ToolContext,
    q: str | None = None,
    proyecto_codigo: str | None = None,
    entregable_id: str | None = None,
    persona_id: str | None = None,
    disciplina: str | None = None,
    contexto: str | None = None,
    ano: int | None = None,
    semana_desde: int | None = None,
    semana_hasta: int | None = None,
    limit: int = 300,
) -> dict:
    """Detalle auditable: quién cargó qué HH en qué semana en qué entregable.

    Llama /external/entregables/horas-detalle. Requiere al menos uno de:
    q, proyecto_codigo, entregable_id, persona_id, contexto.
    """
    if not ctx.staffing.available:
        return {"error": "STAFFING_API_KEY no configurada"}
    if not any([q, proyecto_codigo, entregable_id, persona_id, contexto]):
        return {"error": "Debes pasar al menos uno: q, proyecto_codigo, entregable_id, persona_id o contexto"}
    result = await ctx.staffing.horas_detalle(
        q=q, proyecto_codigo=proyecto_codigo, entregable_id=entregable_id,
        persona_id=persona_id, disciplina=disciplina, contexto=contexto, ano=ano,
        semana_desde=semana_desde, semana_hasta=semana_hasta, limit=min(limit, 1500),
    )
    if "error" in result:
        return result
    detalle = result.get("detalle") or []
    rows = [
        {
            "usuario_id": r.get("usuario_id"),
            "nombre": r.get("nombre"),
            "ano": r.get("ano"),
            "semana": r.get("semana"),
            "horas": r.get("horas"),
            "entregable_id": r.get("entregable_id"),
            "proyecto_codigo": r.get("proyecto_codigo"),
            "cliente_resuelto": r.get("cliente_resuelto"),
        }
        for r in detalle[:limit]
    ]
    return {
        "count": len(detalle),
        "filas": rows,
        "tables": [{"name": "Detalle auditable de HH", "rows": rows}],
    }


async def get_proyecto_staffing(ctx: ToolContext, codigo: str, ano: int | None = None) -> dict:
    """Devuelve proyecto + entregables + personas en un solo call.

    Llama /external/proyectos/{codigo}/completo.
    `codigo` es el código de proyecto staffing (ej. SH-0392).
    """
    if not ctx.staffing.available:
        return {"error": "STAFFING_API_KEY no configurada"}
    result = await ctx.staffing.proyecto_completo(codigo, ano=ano)
    if "error" in result:
        return result
    proyecto = result.get("proyecto") or {}
    entregables = result.get("entregables") or []
    personas = result.get("personas") or []
    compact_deliverables = [_compact_entregable(e) for e in entregables[:30]]
    compact_people = [
        {
            "usuario_id": p.get("usuario_id"),
            "nombre": p.get("nombre"),
            "disciplina": p.get("disciplina"),
            "cargo": p.get("cargo"),
            "horas_totales": p.get("horas_totales") or p.get("hh"),
        }
        for p in personas[:30]
    ]
    return {
        "proyecto": {
            "codigo": proyecto.get("codigo") or codigo,
            "nombre": proyecto.get("nombre"),
            "cliente": proyecto.get("cliente"),
            "jp": proyecto.get("jp_nombre") or proyecto.get("jp_id"),
            "horas_totales": proyecto.get("horas_totales"),
        },
        "entregables_count": len(entregables),
        "entregables": compact_deliverables,
        "personas_count": len(personas),
        "personas": compact_people,
        "tables": [
            {"name": f"Entregables reales {codigo.upper()}", "rows": compact_deliverables},
            {"name": f"Equipo real {codigo.upper()}", "rows": compact_people},
        ],
    }


async def get_persona_historial(ctx: ToolContext, usuario_id: str, ano: int | None = None) -> dict:
    """Historial de una persona: proyectos y entregables donde cargó HH.

    Llama /external/personas/{usuario_id}.
    """
    if not ctx.staffing.available:
        return {"error": "STAFFING_API_KEY no configurada"}
    return await ctx.staffing.historial_persona(usuario_id, ano=ano)


async def listar_proyectos_staffing(ctx: ToolContext, activo: bool = True, limit: int = 50) -> dict:
    """Lista proyectos del staffing app (SH-XXXX) con su jefe de proyecto y estado."""
    if not ctx.staffing.available:
        return {"error": "STAFFING_API_KEY no configurada"}
    result = await ctx.staffing.listar_proyectos(activo=activo, limit=min(limit, 500))
    if "error" in result:
        return result
    proyectos = result.get("proyectos") or result.get("data") or []
    return {
        "count": len(proyectos),
        "proyectos": [
            {
                "codigo": p.get("codigo"),
                "nombre": p.get("nombre"),
                "cliente": p.get("cliente"),
                "activo": p.get("activo"),
                "jp": p.get("jp_nombre") or p.get("jp_id"),
            }
            for p in proyectos[:limit]
        ],
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


async def list_my_drafts(ctx: ToolContext, limit: int = 20) -> dict:
    """Lista los drafts (propuestas en armado) del usuario actual.

    Cada draft tiene: slug, title, cliente, status, files_count, fechas.
    """
    user = get_current_user()
    rows = ctx.drafts.list_drafts(user.id, limit=limit)
    return {"count": len(rows), "drafts": rows}


async def get_draft_context(ctx: ToolContext, slug: str, include_guide: bool = True, include_chunks_preview: bool = False) -> dict:
    """Trae todo el contexto de un draft: metadata, archivos subidos y la GUÍA generada por LLM.

    Si `include_chunks_preview=True`, agrega un preview de los primeros chunks de los antecedentes.
    Útil cuando el usuario está chateando dentro del contexto de una propuesta y quieres traer
    su info para usarla en las respuestas.
    """
    user = get_current_user()
    try:
        draft = ctx.drafts.get_draft(user.id, slug)
    except KeyError:
        return {"error": f"draft '{slug}' no encontrado o no es tuyo"}
    out = {
        "slug": draft["slug"],
        "title": draft["title"],
        "cliente": draft["cliente"],
        "brief_text": draft.get("brief_text") or "",
        "status": draft["status"],
        "files_count": len(draft.get("files") or []),
        "files": [
            {"filename": f["filename"], "kind": f["kind"], "chars_extracted": f["chars_extracted"]}
            for f in draft.get("files") or []
        ],
        "source_assets": [
            {
                "title": f["filename"],
                "url": f"/api/drafts/{quote(slug, safe='')}/files/{quote(f['filename'], safe='')}",
                "kind": f["kind"],
            }
            for f in draft.get("files") or []
        ],
        "workspace_sections": [
            {
                "key": section.get("key"),
                "title": section.get("title"),
                "content": str(section.get("content") or "")[:10000],
                "tables": [
                    {
                        **table,
                        "rows": (table.get("rows") or [])[:20],
                        "rows_total": len(table.get("rows") or []),
                    }
                    for table in (section.get("tables") or [])[:4]
                    if isinstance(table, dict)
                ],
            }
            for section in draft.get("workspace_sections") or []
        ],
        "agent_checkpoint": draft.get("agent_checkpoint"),
    }
    if include_guide and draft.get("guide_exists"):
        out["guide"] = ctx.drafts.get_guide(user.id, slug)
    if include_chunks_preview:
        out["chunks_preview"] = ctx.drafts.all_text(slug, max_chars=12000)
    return out


async def search_draft_chunks(ctx: ToolContext, slug: str, query: str, limit: int = 6) -> dict:
    """Busca dentro de los antecedentes (PDFs/DOCX subidos) de un draft específico.

    Devuelve los chunks de texto más relevantes con la fuente (qué archivo) y un snippet.
    """
    user = get_current_user()
    try:
        ctx.drafts.get_draft(user.id, slug)
    except KeyError:
        return {"error": f"draft '{slug}' no encontrado"}
    hits = ctx.drafts.search_chunks(slug, query, limit=limit)
    for hit in hits:
        filename = str(hit.get("source_file") or "")
        hit["title"] = filename or f"Antecedente {slug}"
        hit["url"] = f"/api/drafts/{quote(slug, safe='')}/files/{quote(filename, safe='')}"
    return {"count": len(hits), "hits": hits}


async def analyze_draft_document_register(ctx: ToolContext, slug: str) -> dict:
    """Cuenta y clasifica los documentos que deberán revisarse en el draft."""
    user = get_current_user()
    try:
        result = ctx.drafts.analyze_document_register(user.id, slug)
    except KeyError:
        return {"error": f"draft '{slug}' no encontrado"}
    discipline_rows = [
        {"disciplina": key, "documentos": value}
        for key, value in sorted(result["by_discipline"].items())
    ]
    type_rows = [
        {"tipo_documento": key, "documentos": value}
        for key, value in sorted(result["by_type"].items())
    ]
    return {
        "total_documents": result["total_documents"],
        "by_discipline": result["by_discipline"],
        "by_type": result["by_type"],
        "by_area": result["by_area"],
        "sample_documents": result["documents"][:24],
        "tables": [
            {"name": "Documentos a revisar por disciplina", "rows": discipline_rows},
            {"name": "Documentos a revisar por tipo", "rows": type_rows},
        ],
    }


async def estimate_draft_review_hours(
    ctx: ToolContext,
    slug: str,
    default_hours: float = 5.0,
    hours_by_type: dict[str, float] | None = None,
    discipline_factors: dict[str, float] | None = None,
    general_activities: dict[str, float] | None = None,
    basis: str = "",
) -> dict:
    """Estima REVISIÓN documental con parámetros elegidos por el agente, no elaboración."""
    user = get_current_user()
    try:
        result = ctx.drafts.estimate_document_review_hours(
            user.id,
            slug,
            default_hours=default_hours,
            hours_by_type=hours_by_type,
            discipline_factors=discipline_factors,
            general_activities=general_activities,
            basis=basis,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": str(exc)}
    return {
        "basis": result["basis"],
        "total_documents": result["total_documents"],
        "review_hours": result["review_hours"],
        "general_hours": result["general_hours"],
        "total_hours": result["total_hours"],
        "discipline_totals": result["discipline_totals"],
        "general_rows": result["general_rows"],
        "tables": [
            {"name": "Estimación de revisión por disciplina", "rows": result["discipline_totals"]},
            {"name": "HH de actividades generales", "rows": result["general_rows"]},
            {"name": "Estimación por documento a revisar", "rows": result["document_rows"]},
        ],
    }


async def import_draft_from_sharepoint(ctx: ToolContext, slug: str, codigo: str) -> dict:
    """Importa antecedentes (PDF/DOCX) desde la carpeta '01 Informacion Cliente' de la oferta
    O-XXXX en SharePoint al draft del usuario. Úsala cuando el usuario diga 'trae los antecedentes
    de O-XXXX', 'descarga lo que el cliente subió a SharePoint', 'importa la información del
    cliente de la carpeta'.
    """
    user = get_current_user()
    try:
        return await ctx.drafts.import_from_sharepoint(user.id, slug, codigo)
    except KeyError:
        return {"error": f"draft '{slug}' no encontrado o no es tuyo"}
