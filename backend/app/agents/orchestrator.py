import asyncio

from app.agents.agent_loop import AgentLoop
from app.schemas import ChatRequest, ChatResponse, Source, ToolTrace
from app.rag.parent_child import ParentChildIndexer
from app.rag.hybrid_store import HybridRagStore
from app.services.llm import LlmService
from app.services.deliverables_economics import DeliverablesEconomicsAnalyst
from app.services.entity_index import EntityIndex
from app.services.master_repository import MasterRepository
from app.services.master_stats_analyst import MasterStatsAnalyst
from app.services.personal_memory import PersonalMemoryService
from app.services.proposal_index import ProposalIndexService
from app.services.proposal_support_advisor import ProposalSupportAdvisor
from app.services.query_planner import QueryPlanner
from app.services.rag_client import RagClient
from app.services.rag_store import RagStore
from app.services.sharepoint_client import SharePointClient
from app.services.structured_wiki import StructuredWikiService
from app.services.wiki_client import WikiClient


class AgentOrchestrator:
    def __init__(self) -> None:
        self.llm = LlmService()
        self.economics = DeliverablesEconomicsAnalyst()
        self.entity_index = EntityIndex()
        self.master = MasterRepository()
        self.master_stats = MasterStatsAnalyst()
        self.personal_memory = PersonalMemoryService()
        self.proposal_index = ProposalIndexService()
        self.proposal_support = ProposalSupportAdvisor()
        self.query_planner = QueryPlanner()
        self.rag = RagClient()
        self.local_rag = RagStore()
        self.parent_child_rag = ParentChildIndexer()
        self.hybrid_rag = HybridRagStore()
        self.wiki = WikiClient()
        self.local_wiki = StructuredWikiService()
        self.sharepoint = SharePointClient()

    async def run(self, request: ChatRequest) -> ChatResponse:
        """Delega a AgentLoop (tool calling). Mantiene memory y working_context."""
        trace: list[ToolTrace] = []
        memory = self._memory(request)
        personal_memory_summary = self.personal_memory.summary()
        if personal_memory_summary:
            memory["summary"] = "\n".join([memory["summary"], "Memoria personal persistente:", personal_memory_summary]).strip()
            trace.append(ToolTrace(tool="memory.personal", status="ok", detail="memoria personal cargada"))

        candidate_seed = list(dict.fromkeys([*request.selected_codes, *memory["codes"]]))
        loop = AgentLoop(max_iterations=6)
        try:
            result = await loop.run(
                question=request.message,
                history=request.history,
                filters=request.filters,
                memory_summary=memory["summary"],
                candidate_codes=candidate_seed,
            )
        except Exception as exc:  # noqa: BLE001
            trace.append(ToolTrace(tool="agent.loop", status="error", detail=str(exc)))
            return ChatResponse(
                answer=f"Fallo en agente: {exc}",
                trace=trace,
                suggested_codes=candidate_seed,
                working_context=request.working_context or {},
            )

        trace.extend(result.trace)
        # Working context y suggested codes
        sources = result.sources
        suggested = result.suggested_codes or candidate_seed
        working_context = self._working_context(
            request=request,
            codes=suggested,
            rows=[],
            sources=sources,
            keywords=[],
            alternatives=[],
        )
        return ChatResponse(
            answer=result.answer,
            tables=result.tables,
            charts=result.charts,
            sources=sources,
            trace=trace,
            suggested_codes=suggested,
            working_context=working_context,
        )

    async def _legacy_run(self, request: ChatRequest) -> ChatResponse:
        """Implementación previa (forzada, secuencial). Conservada por si se necesita debugging."""
        trace: list[ToolTrace] = []
        memory = self._memory(request)
        personal_memory_summary = self.personal_memory.summary()
        if personal_memory_summary:
            memory["summary"] = "\n".join([memory["summary"], "Memoria personal persistente:", personal_memory_summary]).strip()
            trace.append(ToolTrace(tool="memory.personal", status="ok", detail="memoria personal cargada"))
        planning_text = "\n".join([memory["summary"], f"Pregunta actual: {request.message}"]).strip()
        try:
            plan = await asyncio.wait_for(self.llm.plan_query(planning_text), timeout=5)
        except Exception:
            plan = {"keywords": self.llm.extract_keywords(planning_text), "alternatives": [], "intent": "busqueda", "needs_full_pdf": False}
            trace.append(ToolTrace(tool="planner.nano", status="warning", detail="timeout; fallback lexical"))
        expanded_plan = self.query_planner.expand(planning_text, plan)
        keywords = expanded_plan["keywords"] or self.llm.extract_keywords(request.message)
        alternatives = expanded_plan["alternatives"]
        trace.append(ToolTrace(tool="planner.nano", status="ok", detail=", ".join(keywords[:16])))
        if memory["codes"]:
            trace.append(ToolTrace(tool="memory.working_set", status="ok", detail=", ".join(memory["codes"][:10])))
        if alternatives:
            trace.append(ToolTrace(tool="planner.alternatives", status="ok", detail=" | ".join(alternatives[:6])))

        entity_hits = []
        try:
            entity_query = " ".join([request.message, *keywords, *alternatives, *memory["topics"]])
            entity_expansions = self.entity_index.expand_query(entity_query, limit=12)
            entity_hits = self.entity_index.search(entity_query, limit=12)
            keywords = list(dict.fromkeys([*keywords, *entity_expansions]))[:26]
            trace.append(ToolTrace(tool="entity_index.expand", status="ok", detail=", ".join(entity_expansions[:12]) or "sin expansiones"))
        except Exception as exc:
            trace.append(ToolTrace(tool="entity_index.expand", status="error", detail=str(exc)))

        try:
            master_rows = self.master.search_many([*alternatives, " ".join(keywords), *memory["topics"]], limit=16)
            master_rows = self._enrich_rows(master_rows)
            trace.append(ToolTrace(tool="master.search", status="ok", detail=f"{len(master_rows)} filas"))
        except Exception as exc:
            master_rows = []
            trace.append(ToolTrace(tool="master.search", status="error", detail=str(exc)))

        entity_codes = [hit["codigo"] for hit in entity_hits if hit.get("codigo")]
        candidate_codes = self._candidate_codes([*request.selected_codes, *memory["codes"], *entity_codes[:8]], master_rows)
        try:
            proposal_hits = self.proposal_index.search(request.message, codes=candidate_codes or None, limit=8)
            trace.append(ToolTrace(tool="proposal_index.search", status="ok", detail=f"{len(proposal_hits)} indices"))
        except Exception as exc:
            proposal_hits = []
            trace.append(ToolTrace(tool="proposal_index.search", status="error", detail=str(exc)))

        try:
            rag_hits = await asyncio.wait_for(self.rag.search(request.message, keywords=keywords, codes=candidate_codes), timeout=10)
            trace.append(ToolTrace(tool="rag.search", status="ok", detail=f"{len(rag_hits)} resultados"))
        except Exception as exc:
            rag_hits = []
            trace.append(ToolTrace(tool="rag.search", status="error", detail=str(exc)))

        try:
            local_rag_hits = self.local_rag.search(" ".join([request.message, *keywords]), codes=candidate_codes or None, limit=8)
            trace.append(ToolTrace(tool="rag.local_chunks", status="ok", detail=f"{len(local_rag_hits)} chunks"))
        except Exception as exc:
            local_rag_hits = []
            trace.append(ToolTrace(tool="rag.local_chunks", status="error", detail=str(exc)))

        try:
            hybrid_hits = await asyncio.wait_for(
                self.hybrid_rag.search(" ".join([request.message, *keywords]), codes=candidate_codes or None, limit=10),
                timeout=18,
            )
            trace.append(ToolTrace(tool="rag.hybrid", status="ok", detail=f"{len(hybrid_hits)} chunks vector+lexical"))
        except Exception as exc:
            hybrid_hits = []
            trace.append(ToolTrace(tool="rag.hybrid", status="error", detail=str(exc)))

        try:
            parent_child_hits = self.parent_child_rag.search(" ".join([request.message, *keywords]), codes=candidate_codes or None, limit=8)
            trace.append(ToolTrace(tool="rag.parent_child", status="ok", detail=f"{len(parent_child_hits)} chunks"))
        except Exception as exc:
            parent_child_hits = []
            trace.append(ToolTrace(tool="rag.parent_child", status="error", detail=str(exc)))

        try:
            wiki_hits = await asyncio.wait_for(self.wiki.search(request.message, keywords=keywords), timeout=8)
            trace.append(ToolTrace(tool="wiki.search", status="ok", detail=f"{len(wiki_hits)} resultados"))
        except Exception as exc:
            wiki_hits = []
            trace.append(ToolTrace(tool="wiki.search", status="error", detail=str(exc)))

        try:
            local_wiki_hits = self.local_wiki.search(" ".join([request.message, *keywords]), mode="content", limit=8)
            trace.append(ToolTrace(tool="wiki.local", status="ok", detail=f"{len(local_wiki_hits)} secciones"))
        except Exception as exc:
            local_wiki_hits = []
            trace.append(ToolTrace(tool="wiki.local", status="error", detail=str(exc)))

        pdf_contexts = []
        if request.deep_pdf_read and candidate_codes:
            try:
                pdf_contexts = await asyncio.wait_for(self.sharepoint.fetch_relevant_pdf_text(candidate_codes[:3], request.message), timeout=25)
                trace.append(ToolTrace(tool="sharepoint.pdf_read", status="ok", detail=f"{len(pdf_contexts)} PDFs leidos"))
            except Exception as exc:
                trace.append(ToolTrace(tool="sharepoint.pdf_read", status="error", detail=str(exc)))

        tool_coverage = self._tool_coverage()
        if tool_coverage.get("rag_parent_child", {}).get("coverage_label"):
            trace.append(ToolTrace(tool="coverage", status="ok", detail=self._coverage_detail(tool_coverage)))
        for alarm in self._coverage_alarms(tool_coverage):
            trace.append(ToolTrace(tool="coverage.alarm", status="warning", detail=alarm))

        economics_analysis = {"rows": []}
        if self._needs_economics(request.message):
            try:
                economics_analysis = await asyncio.wait_for(self.economics.analyze(master_rows, limit=6), timeout=12)
                trace.append(ToolTrace(tool="analyst.deliverables_hours_rates", status="ok", detail=f"{len(economics_analysis.get('rows', []))} propuestas analizadas"))
            except Exception as exc:
                trace.append(ToolTrace(tool="analyst.deliverables_hours_rates", status="error", detail=str(exc)))

        proposal_support = {}
        if self._needs_proposal_support(request.message):
            try:
                proposal_support = await asyncio.wait_for(
                    asyncio.to_thread(self.proposal_support.advise, request.message, candidate_codes[:6], 10),
                    timeout=18,
                )
                trace.append(
                    ToolTrace(
                        tool="proposal_support.advisor",
                        status="ok",
                        detail=(
                            f"directas={len(proposal_support.get('referencias_directas', []))}, "
                            f"comparables={len(proposal_support.get('referencias_comparables', []))}, "
                            f"metodologicas={len(proposal_support.get('referencias_metodologicas', []))}"
                        ),
                    )
                )
            except Exception as exc:
                trace.append(ToolTrace(tool="proposal_support.advisor", status="error", detail=str(exc)))

        master_stats = {}
        if self.master_stats.should_run(request.message):
            try:
                master_stats = await asyncio.wait_for(asyncio.to_thread(self.master_stats.analyze, query=None, limit=20), timeout=12)
                trace.append(
                    ToolTrace(
                        tool="analyst.master_statistics",
                        status="ok",
                        detail=f"{master_stats.get('summary', {}).get('ofertas_analizadas', 0)} ofertas analizadas",
                    )
                )
            except Exception as exc:
                trace.append(ToolTrace(tool="analyst.master_statistics", status="error", detail=str(exc)))

        answer = await self.llm.compose_answer(
            question=request.message,
            master_rows=master_rows,
            rag_hits=[*proposal_hits, *self._entity_context_hits(entity_hits), *hybrid_hits, *parent_child_hits, *local_rag_hits, *rag_hits],
            wiki_hits=[*local_wiki_hits, *wiki_hits],
            pdf_contexts=pdf_contexts,
            conversation_context={
                "previous_codes": memory["codes"],
                "previous_topics": memory["topics"],
                "previous_summary": memory["summary"],
                "current_candidates": candidate_codes,
                "status_legend": self._status_legend(),
                "deliverables_hours_rates": economics_analysis,
                "entity_hits": entity_hits[:12],
                "proposal_support": proposal_support,
                "master_statistics": master_stats,
            },
            tool_coverage=tool_coverage,
        )

        sources = self._sources(master_rows, [*proposal_hits, *self._entity_context_hits(entity_hits), *hybrid_hits, *parent_child_hits, *local_rag_hits, *rag_hits], [*local_wiki_hits, *wiki_hits], pdf_contexts)
        tables = []
        if master_rows:
            tables.append({"name": "Master", "rows": master_rows})
        if economics_analysis.get("rows"):
            tables.append({"name": "Entregables HH Tarifas", "rows": economics_analysis["rows"]})
        if proposal_support.get("tables"):
            tables.extend(proposal_support["tables"])
        if master_stats.get("tables"):
            tables.extend(master_stats["tables"])
        charts = master_stats.get("charts", [])
        working_context = self._working_context(request, candidate_codes, master_rows, sources, keywords, alternatives)
        return ChatResponse(
            answer=answer,
            tables=tables,
            charts=charts,
            sources=sources,
            trace=trace,
            suggested_codes=candidate_codes,
            working_context=working_context,
        )

    def _memory(self, request: ChatRequest) -> dict:
        context = request.working_context or {}
        history_tail = request.history[-6:]
        history_text = "\n".join(f"{msg.role}: {msg.content[:900]}" for msg in history_tail)
        codes = [str(code).upper() for code in context.get("suggested_codes", []) if str(code).strip()]
        topics = [str(topic) for topic in context.get("topics", []) if str(topic).strip()]
        active_topic = str(context.get("active_topic", "")).strip()
        if active_topic:
            topics.insert(0, active_topic)
        summary = "\n".join(
            part
            for part in [
                f"Tema anterior: {active_topic}" if active_topic else "",
                f"Codigos activos: {', '.join(codes[:12])}" if codes else "",
                f"Topicos activos: {', '.join(topics[:10])}" if topics else "",
                f"Historial reciente:\n{history_text}" if history_text else "",
            ]
            if part
        )
        return {"codes": list(dict.fromkeys(codes)), "topics": list(dict.fromkeys(topics)), "summary": summary}

    def _candidate_codes(self, selected_codes: list[str], rows: list[dict]) -> list[str]:
        codes = [code.strip().upper() for code in selected_codes if code.strip()]
        for row in rows:
            code = str(row.get("codigo", "")).strip().upper()
            if code and code not in codes:
                codes.append(code)
        return codes[:10]

    def _needs_proposal_support(self, message: str) -> bool:
        text = message.lower()
        triggers = [
            "armando una propuesta",
            "armar propuesta",
            "preparar propuesta",
            "base para",
            "mencionar",
            "experiencia",
            "referencia",
            "sirve para",
            "usar como",
            "texto sugerido",
        ]
        return any(trigger in text for trigger in triggers)

    def _needs_economics(self, message: str) -> bool:
        text = message.lower()
        triggers = [
            "hh",
            "horas",
            "tarifa",
            "tarifas",
            "monto",
            "montos",
            "precio",
            "costos",
            "costo",
            "entregables",
            "actividades",
            "estimacion",
            "estimación",
        ]
        return any(trigger in text for trigger in triggers)

    def _entity_context_hits(self, entity_hits: list[dict]) -> list[dict]:
        return [
            {
                "codigo": hit.get("codigo"),
                "title": f"Entidad: {hit.get('entity_value')}",
                "summary": f"{hit.get('entity_group')} detectado en seccion: {hit.get('section_title')}",
                "score": hit.get("score"),
                "metadata": hit,
            }
            for hit in entity_hits[:12]
        ]

    def _working_context(self, request: ChatRequest, codes: list[str], rows: list[dict], sources: list[Source], keywords: list[str], alternatives: list[str]) -> dict:
        titles = [str(row.get("titulo", "")) for row in rows[:5] if row.get("titulo")]
        return {
            "active_topic": request.message,
            "suggested_codes": codes,
            "topics": list(dict.fromkeys([*keywords[:10], *alternatives[:5], *titles[:3]])),
            "last_status_breakdown": self._status_breakdown(rows),
            "last_sources": [source.model_dump() for source in sources[:8]],
        }

    def _enrich_rows(self, rows: list[dict]) -> list[dict]:
        for row in rows:
            estado = str(row.get("estado", "")).strip().upper()
            row["estado_categoria"] = self._status_category(estado)
        return rows

    def _status_category(self, estado: str) -> str:
        if estado == "PG":
            return "ganada"
        if estado in {"PL", "PE", "NP", "NL"}:
            return "perdida/no adjudicada"
        if estado in {"PP", "EP", "DP", "PD"}:
            return "en proceso/presentada"
        return "sin clasificar"

    def _status_breakdown(self, rows: list[dict]) -> dict:
        breakdown: dict[str, int] = {}
        for row in rows:
            category = str(row.get("estado_categoria") or self._status_category(str(row.get("estado", "")).upper()))
            breakdown[category] = breakdown.get(category, 0) + 1
        return breakdown

    def _status_legend(self) -> dict:
        return {
            "PG": "ganada",
            "NL/NP/PE/PL": "perdida o no adjudicada segun convencion local",
            "PP/EP/DP/PD": "presentada, en preparacion o en proceso",
        }

    def _tool_coverage(self) -> dict:
        try:
            total_offers = self.master.count_offers()
        except Exception:
            total_offers = 0
        rag_status = self.local_rag.status()
        parent_status = self.parent_child_rag.status()
        hybrid_status = self.hybrid_rag.fast_status()
        wiki_status = self.local_wiki.status()

        def label(count: int) -> str:
            if not total_offers:
                return "desconocida"
            ratio = count / total_offers
            if ratio < 0.1:
                return "baja"
            if ratio < 0.5:
                return "parcial"
            return "alta"

        return {
            "master": {"offer_count": total_offers, "coverage_label": "alta"},
            "rag_local": {**rag_status, "coverage_label": label(rag_status.get("proposal_count", 0))},
            "rag_parent_child": {**parent_status, "coverage_label": label(parent_status.get("proposal_count", 0))},
            "rag_hybrid": {**hybrid_status, "coverage_label": label(hybrid_status.get("proposal_count", 0))},
            "llm_wiki": {**wiki_status, "coverage_label": label(wiki_status.get("proposal_pages", 0))},
        }

    def _coverage_detail(self, coverage: dict) -> str:
        parent = coverage.get("rag_parent_child", {})
        wiki = coverage.get("llm_wiki", {})
        total = coverage.get("master", {}).get("offer_count", 0)
        return (
            f"Master={total} ofertas; "
            f"RAG parent-child={parent.get('proposal_count', 0)} propuestas ({parent.get('coverage_label')}); "
            f"LLM Wiki={wiki.get('proposal_pages', 0)} propuestas ({wiki.get('coverage_label')})"
        )

    def _coverage_alarms(self, coverage: dict) -> list[str]:
        alarms = []
        total = coverage.get("master", {}).get("offer_count", 0)
        for key, label in [("rag_parent_child", "RAG parent-child"), ("llm_wiki", "LLM Wiki")]:
            item = coverage.get(key, {})
            count = item.get("proposal_count", item.get("proposal_pages", 0))
            if item.get("coverage_label") == "baja":
                alarms.append(
                    f"{label} tiene cobertura baja: {count}/{total} propuestas. Conviene alimentar este indice antes de usarlo como evidencia principal."
                )
        return alarms

    def _sources(self, master_rows: list[dict], rag_hits: list[dict], wiki_hits: list[dict], pdf_contexts: list[dict]) -> list[Source]:
        sources: list[Source] = []
        for row in master_rows[:5]:
            sources.append(Source(kind="master", title=str(row.get("titulo") or row.get("codigo")), codigo=str(row.get("codigo", ""))))
        for hit in rag_hits[:5]:
            sources.append(Source(kind="rag", title=hit.get("title", "RAG"), url=hit.get("url"), codigo=hit.get("codigo"), score=hit.get("score")))
        for hit in wiki_hits[:3]:
            sources.append(Source(kind="wiki", title=hit.get("title", "LLM Wiki"), url=hit.get("url"), score=hit.get("score")))
        for ctx in pdf_contexts[:3]:
            sources.append(Source(kind="pdf", title=ctx.get("name", "PDF"), url=ctx.get("url"), codigo=ctx.get("codigo")))
        return sources
