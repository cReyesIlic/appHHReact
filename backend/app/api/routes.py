from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.agents.orchestrator import AgentOrchestrator
from app.schemas import ChatMessage, ChatRequest, ChatResponse, ChatSessionCreateRequest, ChatSessionRenameRequest, ExportRequest, IngestBatchRequest, MasterSearchRequest, MemoryRequest, ProposalSupportRequest, WikiAutoCreateRequest, WikiBuildRequest, WikiEntryRequest, WikiSearchRequest, WikiValidateRequest
from app.services.chat_sessions import ChatSessionService
from app.services.search_filters import SearchFilters, valid_categorias, valid_estados, valid_tipos_servicio
from app.services.exports import ExportService
from app.services.master_repository import MasterRepository
from app.services.master_stats_analyst import MasterStatsAnalyst
from app.core.config import settings
from app.services.sharepoint_client import SharePointClient
from app.services.proposal_index import ProposalIndexService
from app.services.structured_wiki import StructuredWikiService
from app.services.wiki_auto_compiler import WikiAutoCompiler
from app.services.proposal_ingestion import ProposalIngestionService
from app.services.proposal_sync_service import ProposalSyncService
from app.rag.parent_child import ParentChildIndexer
from app.rag.hybrid_store import HybridRagStore
from app.services.deliverables_economics import DeliverablesEconomicsAnalyst
from app.services.entity_index import EntityIndex
from app.services.hh_excel_extractor import HHExcelExtractor
from app.services.ops_dashboard import OpsDashboardService
from app.services.credits import CreditService
from app.services.personal_memory import PersonalMemoryService
from app.services.proposal_support_advisor import ProposalSupportAdvisor
from app.services.user_context import current_user_var, user_from_request

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    user = user_from_request(http_request)
    token = current_user_var.set(user)
    orchestrator = AgentOrchestrator()
    sessions = ChatSessionService()
    try:
        CreditService().ensure_user(user)
        # Resolver sesión: si no viene session_id pero `create_session_if_missing`, crear nueva
        session_id = request.session_id
        if not session_id and request.create_session_if_missing:
            session = sessions.create_session(user.id, title="Nueva conversación")
            session_id = session["id"]
        elif session_id:
            try:
                # Si vino session_id, cargar history persistido si el cliente no lo trae
                stored = sessions.get_session(user.id, session_id)
                if not request.history:
                    msgs = sessions.list_messages(user.id, session_id, limit=20)
                    request.history = [
                        ChatMessage(role=m["role"], content=m["content"]) for m in msgs[-12:]
                    ]
                if not request.working_context:
                    request.working_context = stored.get("working_context") or {}
            except KeyError:
                # session_id inválido — crear nueva
                session = sessions.create_session(user.id, title="Nueva conversación")
                session_id = session["id"]

        # Persistir mensaje del usuario antes de invocar al agente
        if session_id:
            sessions.append_message(user.id, session_id, role="user", content=request.message)

        response = await orchestrator.run(request)
        response.session_id = session_id

        # Persistir respuesta y working_context actualizado
        if session_id:
            sessions.append_message(
                user.id,
                session_id,
                role="assistant",
                content=response.answer,
                trace=[t.model_dump() for t in response.trace],
                sources=[s.model_dump() for s in response.sources],
                tables=response.tables,
            )
            sessions.update_working_context(user.id, session_id, response.working_context or {})
        return response
    finally:
        current_user_var.reset(token)


# ---- Chat sessions CRUD ----

@router.get("/sessions")
def sessions_list(http_request: Request, limit: int = 50) -> dict:
    user = user_from_request(http_request)
    sessions = ChatSessionService().list_sessions(user.id, limit=limit)
    return {"sessions": sessions, "count": len(sessions)}


@router.post("/sessions")
def sessions_create(request: ChatSessionCreateRequest, http_request: Request) -> dict:
    user = user_from_request(http_request)
    return ChatSessionService().create_session(user.id, title=request.title)


@router.get("/sessions/{session_id}")
def sessions_get(session_id: str, http_request: Request) -> dict:
    user = user_from_request(http_request)
    svc = ChatSessionService()
    try:
        session = svc.get_session(user.id, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Sesión no encontrada") from exc
    session["messages"] = svc.list_messages(user.id, session_id, limit=500)
    return session


@router.patch("/sessions/{session_id}")
def sessions_rename(session_id: str, request: ChatSessionRenameRequest, http_request: Request) -> dict:
    user = user_from_request(http_request)
    try:
        return ChatSessionService().rename_session(user.id, session_id, request.title)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Sesión no encontrada") from exc


@router.delete("/sessions/{session_id}")
def sessions_delete(session_id: str, http_request: Request) -> dict:
    user = user_from_request(http_request)
    return ChatSessionService().delete_session(user.id, session_id)


@router.get("/me")
def me(http_request: Request) -> dict:
    user = user_from_request(http_request)
    CreditService().ensure_user(user)
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}


@router.get("/credits/status")
def credits_status(http_request: Request) -> dict:
    user = user_from_request(http_request)
    return CreditService().status(user)


@router.get("/credits/ledger")
def credits_ledger(http_request: Request, limit: int = 100) -> dict:
    user = user_from_request(http_request)
    rows = CreditService().ledger(user, limit=limit)
    return {"rows": rows, "count": len(rows)}


@router.get("/memory")
def memory_list(http_request: Request, limit: int = 50) -> dict:
    user = user_from_request(http_request)
    rows = PersonalMemoryService().list(user, limit=limit)
    return {"rows": rows, "count": len(rows)}


@router.post("/memory")
def memory_save(request: MemoryRequest, http_request: Request) -> dict:
    user = user_from_request(http_request)
    return PersonalMemoryService().upsert(request.key, request.value, request.scope, request.tags, user)


@router.delete("/memory/{entry_id}")
def memory_delete(entry_id: str, http_request: Request) -> dict:
    user = user_from_request(http_request)
    return PersonalMemoryService().delete(entry_id, user)


@router.post("/master/search")
def master_search(request: MasterSearchRequest) -> dict:
    import re as _re
    repo = MasterRepository()
    query = request.query
    promoted_codigo = request.codigo
    rows: list[dict] = []

    # 1. Si el query parece un código, intentar primero por codigo/cod_proy con variantes
    if query and not promoted_codigo:
        q_clean = query.strip().upper()
        if _re.match(r"^[A-Z]{1,4}-?\d{1,5}$", q_clean) or _re.match(r"^\d{2,5}$", q_clean):
            rows = repo.search(
                query=None,
                codigo=q_clean,
                cliente=request.cliente,
                limit=request.limit,
                filters=request.filters,
            )

    # 2. Si no hubo match por código (o el query no parecía código), búsqueda normal con texto libre
    if not rows:
        rows = repo.search(
            query=query,
            codigo=promoted_codigo,
            cliente=request.cliente,
            limit=request.limit,
            filters=request.filters,
        )
    return {"rows": rows, "count": len(rows)}


@router.post("/analysis/deliverables-economics")
async def deliverables_economics(request: MasterSearchRequest) -> dict:
    repo = MasterRepository()
    rows = repo.search(query=request.query, codigo=request.codigo, cliente=request.cliente, limit=request.limit)
    rows = AgentOrchestrator()._enrich_rows(rows)
    return await DeliverablesEconomicsAnalyst().analyze(rows, limit=request.limit)


@router.post("/analysis/master-stats")
def master_stats(request: MasterSearchRequest) -> dict:
    return MasterStatsAnalyst().analyze(query=request.query, limit=request.limit)


@router.post("/proposal-support/advice")
def proposal_support_advice(request: ProposalSupportRequest) -> dict:
    return ProposalSupportAdvisor().advise(
        query=request.query,
        selected_codes=request.selected_codes,
        limit=request.limit,
    )


@router.post("/master/refresh")
def master_refresh() -> dict:
    repo = MasterRepository()
    count = repo.refresh_from_excel()
    return {"rows_loaded": count}


@router.get("/sharepoint/pdfs/{code}")
async def sharepoint_pdfs(code: str) -> dict:
    client = SharePointClient()
    try:
        pdfs = await client.list_pdfs(code)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "code": code,
        "count": len(pdfs),
        "pdfs": [{"name": pdf.get("name"), "webUrl": pdf.get("webUrl")} for pdf in pdfs],
    }


@router.post("/proposal-index/{code}")
async def build_proposal_index(code: str) -> dict:
    service = ProposalIndexService()
    try:
        return await service.build_for_code(code)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/ingestion/offers")
async def ingestion_offers(limit: int = 50) -> dict:
    try:
        return await ProposalIngestionService().discover_offers(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/ingestion/offers/{code}")
async def ingestion_offer(code: str) -> dict:
    try:
        return await ProposalIngestionService().ingest_code(code)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/ingestion/batch")
async def ingestion_batch(request: IngestBatchRequest) -> dict:
    try:
        return await ProposalIngestionService().ingest_batch(limit=request.limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---- Sync end-to-end SharePoint ↔ RAG ↔ Wiki ----


@router.get("/sync/status")
def sync_status() -> dict:
    svc = ProposalSyncService()
    gap = svc.discover_wiki_gaps()
    return {
        "wiki_pages_existing": gap["wiki_pages"],
        "rag_proposals": gap["rag_count"],
        "wiki_missing": gap["missing_wiki"],
        "missing_codes_preview": gap["missing_codes"][:20],
    }


@router.get("/sync/discover-new")
async def sync_discover_new(limit: int = 200) -> dict:
    svc = ProposalSyncService()
    try:
        return await svc.discover_new(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sync/new")
async def sync_new(limit: int = 20, force_wiki: bool = False) -> dict:
    svc = ProposalSyncService()
    try:
        return await svc.sync_new(limit=limit, force_wiki=force_wiki)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sync/code/{codigo}")
async def sync_code(codigo: str, force_wiki: bool = False) -> dict:
    svc = ProposalSyncService()
    try:
        return await svc.sync_code(codigo, force_wiki=force_wiki)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sync/backfill-wiki")
async def sync_backfill_wiki(payload: dict | None = None) -> dict:
    payload = payload or {}
    svc = ProposalSyncService()
    try:
        return await svc.backfill_wiki(
            codigos=payload.get("codigos"),
            force=bool(payload.get("force", False)),
            limit=payload.get("limit"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/config/status")
def config_status() -> dict:
    status_errors = []

    def safe_status(label: str, factory, fallback: dict | None = None) -> dict:
        try:
            return factory()
        except Exception as exc:
            status_errors.append(f"{label}: {exc}")
            return {**(fallback or {}), "available": False, "error": str(exc)}

    wiki_status = safe_status("LLM Wiki", lambda: StructuredWikiService().status(), {"sections": 0, "entries": 0, "proposal_pages": 0})
    parent_rag_status = safe_status("RAG parent-child", lambda: ParentChildIndexer().status(), {"proposal_count": 0, "parent_sections": 0, "child_chunks": 0})
    hybrid_rag_status = safe_status("RAG hybrid", lambda: HybridRagStore().status(), {"chunks": 0})
    entity_status = safe_status("Entity index", lambda: EntityIndex().status(), {"entities": 0})
    hh_status = safe_status("HH Excel", lambda: HHExcelExtractor().summary(), {"files": 0})
    master_count_status = safe_status("Master", lambda: {"count": MasterRepository().count_offers()}, {"count": 0})
    master_count = master_count_status.get("count", 0)
    coverage_warnings = []
    coverage_warnings.extend(status_errors)
    if master_count:
        if parent_rag_status.get("proposal_count", 0) / master_count < 0.1:
            coverage_warnings.append(f"RAG parent-child bajo: {parent_rag_status.get('proposal_count', 0)}/{master_count} propuestas.")
        if wiki_status.get("proposal_pages", 0) / master_count < 0.1:
            coverage_warnings.append(f"LLM Wiki bajo: {wiki_status.get('proposal_pages', 0)}/{master_count} propuestas.")
    return {
        "master": {
            "sqlite_path": str(settings.sqlite_path),
            "has_master_path": bool(settings.master_path),
            "has_master_blob": bool(settings.master_path_blob),
            "blob_enabled": bool(settings.azure_connection_string and settings.container_name),
        },
        "azure_openai": {
            "has_key": bool(settings.openai_key),
            "has_endpoint": bool(settings.azure_openai_endpoint),
            "has_deployment": bool(settings.azure_openai_deployment or settings.azure_openai_answer_deployment),
            "planner_deployment": settings.planner_deployment,
            "index_deployment": settings.index_deployment,
            "answer_deployment": settings.answer_deployment,
            "api_version": settings.azure_openai_api_version,
            "mode": "azure" if settings.azure_openai_endpoint else "openai-compatible",
        },
        "sharepoint_graph": {
            "has_tenant_id": bool(settings.tenant_id),
            "has_client_id": bool(settings.client_id),
            "has_client_secret": bool(settings.client_secret),
            "has_sharepoint_site": bool(settings.sharepoint_site),
            "has_site_url_ofertas": bool(settings.site_url_ofertas),
            "has_site_url_proyectos": bool(settings.site_url_proyectos),
        },
        "rag": {
            "has_liteparse_url": bool(settings.liteparse_function_url),
            "has_rag_endpoint": bool(settings.rag_endpoint),
            "has_wiki_endpoint": bool(settings.wiki_endpoint),
        },
        "llm_wiki": wiki_status,
        "rag_parent_child": parent_rag_status,
        "rag_hybrid": hybrid_rag_status,
        "entity_index": entity_status,
        "hh_excel": hh_status,
        "coverage_warnings": coverage_warnings,
    }


@router.get("/ops/dashboard")
def ops_dashboard(limit: int = 80) -> dict:
    return OpsDashboardService().build(limit=limit)


@router.get("/entities/status")
def entities_status() -> dict:
    return EntityIndex().status()


@router.get("/rag/hybrid/status")
def rag_hybrid_status() -> dict:
    return HybridRagStore().status()


@router.get("/rag/hybrid/search")
async def rag_hybrid_search(q: str, codes: str = "", limit: int = 8) -> dict:
    selected_codes = [code.strip().upper() for code in codes.split(",") if code.strip()] or None
    hits = await HybridRagStore().search(q, codes=selected_codes, limit=limit)
    return {"hits": hits, "count": len(hits), "status": HybridRagStore().status()}


@router.get("/entities/search")
def entities_search(q: str, limit: int = 40) -> dict:
    hits = EntityIndex().search(q, limit=limit)
    return {"hits": hits, "count": len(hits), "expansions": EntityIndex().expand_query(q, limit=20)}


@router.get("/hh/status")
def hh_status() -> dict:
    return HHExcelExtractor().summary()


@router.get("/hh/{code}")
def hh_by_code(code: str, limit: int = 100) -> dict:
    extractor = HHExcelExtractor()
    rows = extractor.query(codigo=code.upper(), limit=limit)
    return {"summary": extractor.summary(code.upper()), "rows": rows, "count": len(rows)}


@router.get("/wiki/status")
def wiki_status() -> dict:
    return StructuredWikiService().status()


@router.get("/wiki/sections")
def wiki_sections() -> dict:
    rows = StructuredWikiService().list_sections()
    return {"sections": rows, "count": len(rows)}


@router.get("/wiki/markdown")
def wiki_markdown() -> dict:
    return StructuredWikiService().markdown()


@router.get("/wiki/quick-access")
def wiki_quick_access() -> dict:
    return StructuredWikiService().quick_access()


@router.get("/wiki/entries")
def wiki_entries() -> dict:
    rows = StructuredWikiService().list_entries()
    return {"entries": rows, "count": len(rows)}


@router.get("/wiki/entries/{entry_id}")
def wiki_entry(entry_id: str) -> dict:
    try:
        return StructuredWikiService().get_entry(entry_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Entrada Wiki no encontrada") from exc


@router.post("/wiki/entries")
def wiki_entry_create(request: WikiEntryRequest) -> dict:
    return StructuredWikiService().upsert_entry(
        title=request.title,
        content=request.content,
        category=request.category,
        tags=request.tags,
        pinned=request.pinned,
        source=request.source,
        propuestas_referenciadas=request.propuestas_referenciadas,
        filtros_aplicables=request.filtros_aplicables,
    )


@router.put("/wiki/entries/{entry_id}")
def wiki_entry_update(entry_id: str, request: WikiEntryRequest) -> dict:
    return StructuredWikiService().upsert_entry(
        entry_id=entry_id,
        title=request.title,
        content=request.content,
        category=request.category,
        tags=request.tags,
        pinned=request.pinned,
        source=request.source,
        propuestas_referenciadas=request.propuestas_referenciadas,
        filtros_aplicables=request.filtros_aplicables,
    )


@router.post("/wiki/entries/{entry_id}/validate")
def wiki_entry_validate(entry_id: str) -> dict:
    try:
        entry = StructuredWikiService().get_entry(entry_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Entrada Wiki no encontrada") from exc
    refs = entry.get("propuestas_referenciadas") or []
    repo = MasterRepository()
    valid: list[str] = []
    for code in refs:
        rows = repo.search(codigo=code, limit=1)
        if rows:
            valid.append(code)
    return StructuredWikiService().validate_proposals(entry_id, valid)


@router.post("/library/search")
def library_search(payload: dict) -> dict:
    wiki = StructuredWikiService()
    entries = wiki.search_entries(
        query=payload.get("query"),
        category=payload.get("category"),
        tags=payload.get("tags"),
        codigos=payload.get("codigos"),
        limit=int(payload.get("limit") or 20),
    )
    return {"entries": entries, "count": len(entries)}


@router.get("/search/filter-options")
def search_filter_options() -> dict:
    return {
        "estados": valid_estados(),
        "estado_categoria": valid_categorias(),
        "tipos_servicio": valid_tipos_servicio(),
    }


@router.delete("/wiki/entries/{entry_id}")
def wiki_entry_delete(entry_id: str) -> dict:
    try:
        return StructuredWikiService().delete_entry(entry_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Entrada Wiki no encontrada") from exc


@router.post("/wiki/reindex")
def wiki_reindex() -> dict:
    return StructuredWikiService().reindex_entries()


@router.post("/wiki/auto-create")
async def wiki_auto_create(request: WikiAutoCreateRequest) -> dict:
    compiler = WikiAutoCompiler()
    if request.approve:
        return await compiler.create_or_update(
            topic=request.topic,
            source_text=request.source_text,
            source_kind=request.source_kind,
            candidate_codes=request.candidate_codes,
            pin_if_operational=request.pin_if_operational,
            existing_entry_id=request.existing_entry_id,
        )
    return await compiler.propose(
        topic=request.topic,
        source_text=request.source_text,
        source_kind=request.source_kind,
        candidate_codes=request.candidate_codes,
        pin_if_operational=request.pin_if_operational,
        existing_entry_id=request.existing_entry_id,
    )


@router.post("/wiki/build")
def wiki_build(request: WikiBuildRequest) -> dict:
    return StructuredWikiService().build(request.markdown)


@router.post("/wiki/search")
def wiki_search(request: WikiSearchRequest) -> dict:
    hits = StructuredWikiService().search(request.query, mode=request.mode, limit=request.limit)
    return {"hits": hits, "count": len(hits)}


@router.post("/wiki/test")
def wiki_test(request: WikiSearchRequest) -> dict:
    return StructuredWikiService().answer(request.query)


@router.get("/exports/file/{filename}")
def export_file_download(filename: str) -> FileResponse:
    """Sirve un archivo previamente generado (por la tool generate_document del agente)."""
    import re as _re
    if not _re.match(r"^[A-Za-z0-9_.-]+$", filename):
        raise HTTPException(status_code=400, detail="filename inválido")
    path = settings.resolve_path(settings.export_dir) / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="archivo no encontrado o expirado")
    return FileResponse(path, filename=filename)


@router.get("/exports/{kind}")
def export_info(kind: str) -> dict:
    """Endpoint amigable si alguien abre la URL directamente en el browser."""
    return {
        "kind": kind,
        "method": "POST",
        "usage": (
            f"Este endpoint requiere POST con JSON. Desde la UI: usa los botones de descarga "
            f"bajo cada respuesta del agente. Desde código: POST /api/exports/{kind} con "
            "{title, answer, tables, sources, charts}."
        ),
        "supported_kinds": ["docx", "pdf", "xlsx", "typst-pdf", "report"],
    }


@router.post("/exports/{kind}")
def export(kind: str, request: ExportRequest) -> FileResponse:
    service = ExportService()
    try:
        path = service.create(kind, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name)
