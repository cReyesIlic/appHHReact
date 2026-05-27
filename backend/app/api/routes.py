import re as _re

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

_CODIGO_RE = _re.compile(r"^[OS]H?-?\d{2,6}$")


def _validate_codigo(codigo: str, *, prefix: str | None = None) -> str:
    """Normaliza y valida que el código tenga formato O-XXXX o SH-XXXX.

    Bloquea path traversal, inyecciones SQL/shell con nulos, y formatos arbitrarios.
    """
    if codigo is None:
        raise HTTPException(status_code=400, detail="codigo requerido")
    norm = codigo.strip().upper().replace(" ", "")
    if not norm or "/" in norm or "\\" in norm or ".." in norm or "\x00" in norm:
        raise HTTPException(status_code=400, detail=f"codigo invalido: {codigo!r}")
    if not _CODIGO_RE.match(norm):
        raise HTTPException(status_code=400, detail=f"codigo debe ser O-XXXX o SH-XXXX: {codigo!r}")
    if prefix and not norm.startswith(prefix.upper()):
        raise HTTPException(status_code=400, detail=f"codigo debe empezar con {prefix}: {codigo!r}")
    return norm

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
from app.services.proposal_drafts import ProposalDraftService
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
    payload: dict = {"rows_loaded": count}
    # Reporte por email — best effort
    try:
        from app.services.email_client import EmailClient
        from app.services.ingestion_reporter import master_refresh_report
        email = EmailClient()
        if email.configured:
            subject, text, html = master_refresh_report(count)
            payload["email"] = email.send(subject, text, html)
    except Exception as exc:  # noqa: BLE001
        payload["email"] = {"sent": False, "reason": f"{type(exc).__name__}: {exc}"}
    return payload


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


@router.get("/sync/ganadas-pendientes")
def sync_ganadas_pendientes() -> dict:
    """Lista propuestas ganadas (PG) en master que aún NO están indexadas en RAG/Wiki.
    Es el listado que alimenta el botón 'Sincronizar ganadas nuevas'."""
    return ProposalSyncService().discover_ganadas_pendientes()


@router.post("/sync/ganadas")
async def sync_ganadas(limit: int = 10) -> dict:
    """Para cada propuesta ganada (PG) sin RAG, descarga PDFs/Excel de SharePoint
    y la alimenta al sistema (RAG + Wiki). Bajo demanda, no automático."""
    return await ProposalSyncService().sync_ganadas(limit=limit)


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
    codigo = _validate_codigo(codigo, prefix="O-")
    svc = ProposalSyncService()
    try:
        result = await svc.sync_code(codigo, force_wiki=force_wiki)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SharePoint/indexer: {exc}") from exc
    # Si el sync devolvió error interno (no_files, indexing, etc) lo dejamos como 200 con status,
    # para que el frontend muestre el detalle estructurado. Solo errores 5xx van como HTTP error.
    return result


# ---- Ingesta puntual + email admin ----


@router.post("/ingest/upload")
async def ingest_upload(
    file: UploadFile = File(...),
    kind: str = "pdf",
    target: str = "rag",
) -> dict:
    """Sube un archivo individual (PDF/DOCX/XLSX) y reporta por email.

    `target` puede ser 'rag' (indexa al store), 'master' (recarga master Excel) o 'inspect' (solo extrae texto).
    """
    from app.services.email_client import EmailClient
    from app.services.ingestion_reporter import upload_report
    from app.services.master_repository import MasterRepository

    raw = await file.read()
    filename = file.filename or "archivo.bin"
    kind = (kind or filename.rsplit(".", 1)[-1] if "." in filename else kind).lower()

    chars = 0
    rows_loaded = None
    try:
        svc = ProposalSyncService()
        text = svc._extract_text_any(raw, kind, filename)
        chars = len(text or "")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"No se pudo extraer texto: {exc}")

    if target == "master" and kind in {"xlsx", "xls"}:
        master_path = settings.resolve_path(settings.master_path or "storage/master.xlsx")
        master_path.parent.mkdir(parents=True, exist_ok=True)
        master_path.write_bytes(raw)
        rows_loaded = MasterRepository().refresh_from_excel()

    response = {
        "filename": filename,
        "kind": kind,
        "chars_extracted": chars,
        "target": target,
    }
    if rows_loaded is not None:
        response["rows_loaded"] = rows_loaded
    try:
        email = EmailClient()
        if email.configured:
            subject, text_body, html = upload_report(filename, kind, chars, target)
            response["email"] = email.send(subject, text_body, html)
    except Exception as exc:  # noqa: BLE001
        response["email"] = {"sent": False, "reason": f"{type(exc).__name__}: {exc}"}
    return response


# ---- Entregables (HH licitadas local + reales staffing) ----


@router.get("/entregables/stats")
def entregables_stats() -> dict:
    from app.services.entregables_repository import EntregablesRepository
    return EntregablesRepository().stats()


@router.get("/entregables/disciplinas")
def entregables_disciplinas(limit: int = 50) -> dict:
    from app.services.entregables_repository import EntregablesRepository
    return {"disciplinas": EntregablesRepository().list_disciplines(limit=limit)}


@router.get("/entregables/aggregate")
async def entregables_aggregate(
    fuente: str = "licitadas",
    view: str = "proyecto",
    codigo: str | None = None,
    cliente: str | None = None,
    tipo_servicio: str | None = None,
    disciplina: str | None = None,
    text: str | None = None,
    min_hours: float = 0.0,
    ano: int | None = None,
    limit: int = 100,
) -> dict:
    """Pivot de entregables. fuente=licitadas|reales · view=proyecto|disciplina|role|entregable|persona."""
    from app.services.entregables_repository import EntregablesRepository
    repo = EntregablesRepository()
    if fuente == "reales":
        return await repo.aggregate_reales(view=view, codigo=codigo, disciplina=disciplina, text=text, ano=ano, top=limit)
    return repo.aggregate_licitadas(
        view=view, codigo=codigo, cliente=cliente, tipo_servicio=tipo_servicio,
        disciplina=disciplina, text=text, min_hours=min_hours, limit=limit,
    )


@router.post("/entregables/extract-budget/{codigo}")
async def entregables_extract_budget(codigo: str) -> dict:
    """Dispara la Azure Function de extracción de presupuesto para un O-XXXX.
    Baja Excels desde SharePoint, los manda al microservicio, y persiste en SQLite."""
    from app.services.budget_extractor_client import BudgetExtractorClient
    codigo = _validate_codigo(codigo, prefix="O-")
    client = BudgetExtractorClient()
    if not client.available:
        raise HTTPException(status_code=503, detail="BUDGET_EXTRACTOR_URL no configurada en App Settings")
    return await client.extract_from_sharepoint(codigo)


@router.get("/entregables/extracted/{codigo}")
def entregables_extracted(codigo: str) -> dict:
    """Devuelve lo extraído por la Function para un código (filas, tarifas, gastos, audit)."""
    from app.services.budget_extractor_client import BudgetExtractorClient
    codigo = _validate_codigo(codigo)
    return BudgetExtractorClient().get_for_codigo(codigo)


@router.get("/entregables/tipos-servicio")
def entregables_tipos_servicio() -> dict:
    """Lista los tipos de servicio del master (catálogo + presentes en oferta)."""
    import sqlite3
    with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
        try:
            cat = [r[0] for r in conn.execute("select tipo_servicio from servicio order by tipo_servicio").fetchall() if r[0]]
        except sqlite3.OperationalError:
            cat = []
        try:
            usados = [r[0] for r in conn.execute("select distinct tipo_servicio from oferta where tipo_servicio not in ('','No data') and tipo_servicio is not null").fetchall()]
        except sqlite3.OperationalError:
            usados = []
    return {"catalogo": cat, "presentes_en_oferta": sorted(set(usados))}


@router.post("/entregables/ask")
async def entregables_ask(payload: dict) -> dict:
    """Sub-agente conversacional de entregables. Body: {question, codigo?, tipo_servicio?}."""
    from app.services.entregables_agent import EntregablesAgent
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Falta 'question'")
    return await EntregablesAgent().ask(
        question=question,
        codigo=payload.get("codigo"),
        tipo_servicio=payload.get("tipo_servicio"),
    )


@router.get("/admin/scheduler/status")
def admin_scheduler_status() -> dict:
    """Estado del scheduler embebido (próxima corrida, última ejecución)."""
    from app.services.scheduler import scheduler_status
    return scheduler_status()


@router.post("/admin/scheduler/trigger")
async def admin_scheduler_trigger(payload: dict | None = None) -> dict:
    """Dispara un job ahora (no espera al cron). Body: {job: 'sync_ganadas'|'master_refresh'}."""
    from app.services.scheduler import trigger_now
    payload = payload or {}
    return await trigger_now(payload.get("job", "sync_ganadas"))


@router.post("/admin/email-test")
def admin_email_test(payload: dict | None = None) -> dict:
    """Envía un email de prueba para verificar ACS. Body opcional: {to: [...], subject: '...', body: '...'}."""
    from app.services.email_client import EmailClient
    payload = payload or {}
    email = EmailClient()
    if not email.configured:
        return {
            "configured": False,
            "reason": "Define ACS_CONNECTION_STRING y ACS_SENDER_ADDRESS en variables de entorno",
        }
    subject = payload.get("subject") or "SHIMIN · Test de Azure Communication Services"
    body = payload.get("body") or "Este es un email de prueba enviado desde la app SHIMIN (Proposal Intelligence)."
    html = f"<p>{body}</p><p style='color:#5f747d;font-size:12px;'>Si recibiste este correo, ACS está bien configurado.</p>"
    result = email.send(subject, body, html, to=payload.get("to"))
    return {"configured": True, **result}


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


@router.get("/ops/coverage")
def ops_coverage(estado: str | None = "PG", limit: int = 5000) -> dict:
    estado_filter = None if estado in (None, "", "ALL", "*") else estado
    return OpsDashboardService().build_coverage(estado=estado_filter, limit=limit)


@router.get("/ops/coverage/{codigo}/wiki")
def ops_coverage_wiki(codigo: str) -> dict:
    """Devuelve el markdown de la página Wiki auto-compilada para una propuesta."""
    codigo = _validate_codigo(codigo)
    path = settings.resolve_path(f"storage/llm_wiki/proposals/{codigo}.md")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No hay página Wiki para {codigo}")
    return {
        "codigo": codigo,
        "path": str(path),
        "markdown": path.read_text(encoding="utf-8"),
        "size_bytes": path.stat().st_size,
    }


UPLOAD_MAX_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("/ops/coverage/{codigo}/upload")
async def ops_coverage_upload(codigo: str, file: UploadFile = File(...)) -> dict:
    """Subir manualmente un PDF/Excel para una propuesta, indexarlo a RAG (y HH si es Excel)."""
    codigo = _validate_codigo(codigo)
    raw = await file.read()
    if len(raw) > UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo demasiado grande ({len(raw) // 1024 // 1024} MB). Maximo: 50 MB.",
        )
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="Archivo vacio")
    filename = file.filename or "archivo.bin"
    return await ProposalSyncService().ingest_local_file(codigo, raw, filename)


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


# ---- Proposal drafts: cargar antecedentes + guía LLM ----

@router.get("/drafts")
def drafts_list(http_request: Request, limit: int = 50) -> dict:
    user = user_from_request(http_request)
    rows = ProposalDraftService().list_drafts(user.id, limit=limit)
    return {"drafts": rows, "count": len(rows)}


@router.post("/drafts")
def drafts_create(payload: dict, http_request: Request) -> dict:
    user = user_from_request(http_request)
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title requerido")
    cliente = (payload.get("cliente") or "").strip() or None
    return ProposalDraftService().create_draft(user.id, title, cliente)


@router.get("/drafts/{slug}")
def drafts_get(slug: str, http_request: Request) -> dict:
    user = user_from_request(http_request)
    try:
        draft = ProposalDraftService().get_draft(user.id, slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft no encontrado") from exc
    draft["guide_markdown"] = ProposalDraftService().get_guide(user.id, slug) if draft.get("guide_exists") else ""
    return draft


@router.delete("/drafts/{slug}")
def drafts_delete(slug: str, http_request: Request) -> dict:
    user = user_from_request(http_request)
    return ProposalDraftService().delete_draft(user.id, slug)


@router.post("/drafts/{slug}/upload")
async def drafts_upload(slug: str, http_request: Request, file: UploadFile = File(...)) -> dict:
    user = user_from_request(http_request)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="archivo vacío")
    if len(content) > 50 * 1024 * 1024:  # 50 MB max
        raise HTTPException(status_code=413, detail="archivo > 50 MB")
    try:
        return ProposalDraftService().add_file(user.id, slug, file.filename or "archivo", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft no encontrado") from exc


@router.get("/drafts/{slug}/files/{filename}")
def drafts_download_file(slug: str, filename: str, http_request: Request) -> FileResponse:
    user = user_from_request(http_request)
    # Verifica ownership
    try:
        ProposalDraftService().get_draft(user.id, slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft no encontrado") from exc
    path = ProposalDraftService().file_path(user.id, slug, filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="archivo no encontrado")
    return FileResponse(path, filename=path.name)


@router.get("/drafts/sharepoint-preview/{codigo}")
async def drafts_sharepoint_preview(codigo: str, http_request: Request) -> dict:
    """Lista (sin descargar) los archivos antecedentes en SharePoint de una oferta O-XXXX."""
    user_from_request(http_request)  # solo verifica auth
    try:
        return await ProposalDraftService().preview_sharepoint(codigo)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/drafts/{slug}/import-sharepoint")
async def drafts_import_sharepoint(slug: str, payload: dict, http_request: Request) -> dict:
    """Descarga los antecedentes desde la carpeta '01 Informacion Cliente' de SharePoint
    al draft. Body: {codigo: 'O-XXXX', filenames: [opcional]}."""
    user = user_from_request(http_request)
    codigo = (payload.get("codigo") or "").strip().upper()
    if not codigo:
        raise HTTPException(status_code=400, detail="codigo requerido (ej. O-1376)")
    filenames = payload.get("filenames") or None
    try:
        return await ProposalDraftService().import_from_sharepoint(user.id, slug, codigo, filenames)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft no encontrado") from exc


@router.post("/drafts/{slug}/build-guide")
async def drafts_build_guide(slug: str, http_request: Request) -> dict:
    """Genera la guía .md sintética con los puntos principales (LLM)."""
    user = user_from_request(http_request)
    service = ProposalDraftService()
    try:
        draft = service.get_draft(user.id, slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft no encontrado") from exc
    if not draft["files"]:
        raise HTTPException(status_code=400, detail="No hay archivos subidos. Sube PDF/DOCX antes.")

    from app.services.llm import LlmService
    import json as _json

    llm = LlmService()
    text = service.all_text(slug, max_chars=80000)
    if not text.strip():
        raise HTTPException(status_code=400, detail="No se extrajo texto de los archivos")

    system = (
        "Eres un analista senior de propuestas SHIMIN. El usuario te entrega los antecedentes "
        "técnicos (PDFs/DOCX del cliente) para preparar una propuesta nueva. Tu objetivo es "
        "generar una GUÍA en MARKDOWN con los puntos clave que el equipo SHIMIN debe considerar "
        "para responder esta licitación o propuesta.\n\n"
        "Estructura obligatoria de la guía:\n"
        "## 1. Identidad del trabajo\n"
        "Cliente, sitio, tipo de obra, etapa de ingeniería, plazo, monto referencial si aparece.\n"
        "## 2. Alcance solicitado por el cliente\n"
        "Lista en bullets de lo que SHIMIN debe entregar. Cita textual cuando sea posible.\n"
        "## 3. Disciplinas involucradas\n"
        "Hidráulica, mecánica, civil, geotecnia, instrumentación, etc.\n"
        "## 4. Entregables esperados\n"
        "Lista de entregables (MDC, planos, P&ID, informes, etc.) con la disciplina responsable.\n"
        "## 5. Criterios de evaluación / requisitos\n"
        "Si el cliente especifica criterios técnicos, comerciales, de plazo.\n"
        "## 6. Restricciones, supuestos, exclusiones\n"
        "Lo que el cliente no incluye o asume aparte.\n"
        "## 7. Riesgos detectados\n"
        "Lo que SHIMIN debe validar antes de cotizar (ambigüedades, gaps en la información).\n"
        "## 8. Propuestas SHIMIN históricas que pueden servir de base\n"
        "Si en los antecedentes aparecen códigos O-XXXX o nombres de proyectos similares, listarlos.\n"
        "## 9. Próximos pasos para armar la propuesta\n"
        "Acciones concretas: buscar referencias, validar HH típicas, definir equipo, etc.\n\n"
        "Reglas: cita textual cuando ayude; sé conciso; si algo no aparece en los antecedentes, "
        "márcalo como 'no especificado en antecedentes'. Markdown limpio con headings ## y bullets."
    )

    user_payload = (
        f"Trabajo: {draft['title']}\n"
        f"Cliente: {draft['cliente'] or 'no especificado'}\n\n"
        f"Antecedentes (texto extraído de {len(draft['files'])} archivos):\n\n{text}"
    )

    if not llm.client:
        guide = (
            f"# Guía generada (sin LLM disponible)\n\nTítulo: {draft['title']}\n\n"
            f"Antecedentes extraídos: {len(draft['files'])} archivos, {len(text)} caracteres.\n\n"
            f"(Configura Azure OpenAI para generar la guía completa.)"
        )
    else:
        try:
            deployment = settings.answer_deployment if llm.azure else "gpt-4o-mini"
            guide = await llm._chat(
                deployment=deployment,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_payload[:120000]},
                ],
                max_completion_tokens=4096,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"LLM falló: {exc}") from exc

    path = service.save_guide(user.id, slug, guide or "(sin contenido)")
    return {
        "slug": slug,
        "guide_path": str(path),
        "guide_chars": len(guide or ""),
        "files_used": len(draft["files"]),
    }
