import json
import logging
import re
import unicodedata
import asyncio

from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.core.config import settings
from app.services.credits import CreditService

logger = logging.getLogger("shimin.llm")


class LlmService:
    def __init__(self) -> None:
        self.azure = bool(settings.azure_openai_endpoint and settings.openai_key)
        if self.azure:
            self.client = AsyncAzureOpenAI(
                api_key=settings.openai_key,
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
            )
        else:
            self.client = AsyncOpenAI(api_key=settings.openai_key) if settings.openai_key else None

    def extract_keywords(self, text: str) -> list[str]:
        normalized = self._norm(text)
        tokens = re.findall(r"[a-z0-9-]{3,}", normalized)
        stop = {
            "para",
            "con",
            "del",
            "las",
            "los",
            "una",
            "que",
            "como",
            "cual",
            "cuales",
            "sobre",
            "dime",
            "busca",
            "propuestas",
            "propuesta",
        }
        return list(dict.fromkeys(token for token in tokens if token not in stop))[:14]

    async def plan_query(self, text: str) -> dict:
        fallback = {
            "keywords": self.extract_keywords(text),
            "alternatives": [],
            "intent": "busqueda",
            "needs_full_pdf": any(word in self._norm(text) for word in ["detalle", "profundiza", "completo", "reporte"]),
        }
        if not self.client:
            return fallback

        try:
            content = await self._chat(
                deployment=settings.planner_deployment,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres un planner de busqueda para propuestas de ingenieria. "
                            "Devuelve solo JSON con keys: keywords, alternatives, intent, needs_full_pdf. "
                            "keywords debe contener conceptos utiles de negocio, no palabras conversacionales."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                max_completion_tokens=2048,
                response_format={"type": "json_object"},
            )
            data = json.loads(content)
            keywords = [self._norm(str(item)) for item in data.get("keywords", []) if str(item).strip()]
            return {**fallback, **data, "keywords": keywords[:14] or fallback["keywords"]}
        except Exception as exc:
            logger.warning("[llm] plan_query fallback: %s", exc)
            return fallback

    async def compose_answer(
        self,
        question: str,
        master_rows: list[dict],
        rag_hits: list[dict],
        wiki_hits: list[dict],
        pdf_contexts: list[dict],
        conversation_context: dict | None = None,
        tool_coverage: dict | None = None,
    ) -> str:
        if not self.client:
            return self._fallback_answer(question, master_rows, rag_hits, wiki_hits, pdf_contexts)

        context = {
            "master_rows": [self._compact_master_row(row) for row in master_rows[:12]],
            "proposal_index_and_rag_hits": [self._compact_rag_hit(hit) for hit in rag_hits[:12]],
            "wiki_hits": [self._compact_wiki_hit(hit) for hit in wiki_hits[:5]],
            "pdf_contexts": [{**ctx, "text": ctx.get("text", "")[:8000]} for ctx in pdf_contexts[:3]],
            "conversation_context": self._compact_conversation_context(conversation_context or {}),
            "tool_coverage": tool_coverage or {},
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "Eres un agente senior de consulta de propuestas SHIMIN. Responde en espanol. "
                    "Prioriza evidencia: Master para datos estructurados, indice de primeras paginas para alcance, "
                    "RAG/Wiki para similitud y PDFs completos para detalle. Distingue evidencia de inferencia. "
                    "Destaca propuestas ganadas y perdidas cuando existan. Para cada alternativa relevante explica "
                    "por que sirve: similitud directa, similitud parcial, capacidad metodologica reutilizable, "
                    "o evidencia complementaria. Incluye propuestas que no son iguales pero sirven, indicando "
                    "exactamente que parte sirve y que limite tienen. Si tool_coverage muestra baja cobertura, "
                    "dilo brevemente y usa esa fuente solo como apoyo parcial. Si conversation_context trae "
                    "proposal_support, usalo como guia principal para separar referencias directas, comparables, "
                    "metodologicas, HH/entregables, texto sugerido para PDF y gaps a validar."
                ),
            },
            {"role": "user", "content": f"Pregunta: {question}\nContexto JSON:\n{json.dumps(context, ensure_ascii=False)}"},
        ]
        for deployment, timeout, tokens in [
            (settings.answer_deployment if self.azure else "gpt-4o-mini", 18, 3072),
            (settings.index_deployment if self.azure else "gpt-4o-mini", 22, 3072),
        ]:
            try:
                return await asyncio.wait_for(
                    self._chat(deployment=deployment, messages=messages, max_completion_tokens=tokens),
                    timeout=timeout,
                )
            except Exception:
                continue
        return self._fallback_answer(question, master_rows, rag_hits, wiki_hits, pdf_contexts)

    async def summarize_proposal_index(self, codigo: str, pdf_name: str, first_pages_text: str) -> dict:
        if not self.client:
            return {"summary": first_pages_text[:1200], "keywords": self.extract_keywords(first_pages_text)}

        try:
            content = await self._chat(
                deployment=settings.index_deployment if self.azure else "gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Resume una propuesta para usarla como indice de busqueda. "
                            "Devuelve solo JSON con keys: summary, keywords, client, scope, deliverables, useful_for."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Codigo: {codigo}\nPDF: {pdf_name}\nPrimeras 5 paginas:\n{first_pages_text[:14000]}",
                    },
                ],
                max_completion_tokens=4096,
                response_format={"type": "json_object"},
            )
            data = json.loads(content)
            return {
                "summary": str(data.get("summary", "")),
                "keywords": data.get("keywords", []),
                "client": data.get("client"),
                "scope": data.get("scope"),
                "deliverables": data.get("deliverables"),
                "useful_for": data.get("useful_for"),
            }
        except Exception:
            return {"summary": first_pages_text[:1200], "keywords": self.extract_keywords(first_pages_text)}

    async def classify_offer_pdf(self, codigo: str, pdf_name: str, first_page_text: str) -> dict:
        name_norm = self._norm(pdf_name)
        reject_by_name = [
            "cv ",
            "curriculum",
            "certificado",
            "anexo",
            "boleta",
            "orden de compra",
            "oferta de precios",
            "precio",
            "precios",
            "economica",
            "cotizacion",
            "carta",
            "formulario",
            "declaracion",
            "aclaracion",
            "exclusion",
            "exclusiones",
            "curva s",
            "programa preliminar",
            "cronograma",
            "tabla resumen",
            "perfil del personal",
            "experiencia en trabajos",
            "orden de servicio",
            "noc-",
            "ods-",
        ]
        if any(bad in name_norm for bad in reject_by_name):
            return {"is_offer": False, "confidence": 0.95, "reason": "Nombre de archivo parece CV/anexo/no oferta"}
        if any(good in name_norm for good in ["oferta tecnica", "oferta tecnica", "propuesta tecnica", "oferta tecnico", "proposta"]):
            return {"is_offer": True, "confidence": 0.75, "reason": "Nombre de archivo parece oferta/propuesta"}
        if not self.client:
            return {"is_offer": True, "confidence": 0.3, "reason": "Sin LLM; aceptado con baja confianza"}

        try:
            content = await self._chat(
                deployment=settings.planner_deployment,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Clasifica si un PDF corresponde a una oferta tecnica/comercial o propuesta de servicios. "
                            "Devuelve solo JSON: is_offer boolean, confidence numero 0-1, reason string. "
                            "Rechaza CVs, certificados, anexos administrativos, OCs, cartas sueltas, formularios, "
                            "ofertas economicas/precios, curvas S, cronogramas, NOC/ODS y documentos personales. "
                            "Acepta solo si contiene propuesta tecnica, alcance, metodologia, equipo, entregables o enfoque de servicio."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Codigo: {codigo}\nArchivo: {pdf_name}\nPrimera pagina:\n{first_page_text[:5000]}",
                    },
                ],
                max_completion_tokens=1024,
                response_format={"type": "json_object"},
            )
            data = json.loads(content)
            return {
                "is_offer": bool(data.get("is_offer")),
                "confidence": float(data.get("confidence", 0)),
                "reason": str(data.get("reason", "")),
            }
        except Exception as exc:
            return {"is_offer": False, "confidence": 0.0, "reason": f"Error clasificando: {exc}"}

    async def _chat(
        self,
        deployment: str,
        messages: list[dict],
        max_completion_tokens: int,
        response_format: dict | None = None,
    ) -> str:
        kwargs = {
            "model": deployment,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format
        response = await self.client.chat.completions.create(**kwargs)
        usage = getattr(response, "usage", None)
        if usage:
            try:
                CreditService().record_llm_usage(
                    model=deployment,
                    usage=usage,
                    action="llm.chat",
                    metadata={"response_format": bool(response_format)},
                )
            except Exception:
                pass
        return response.choices[0].message.content or ""

    async def chat_with_tools(
        self,
        deployment: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str | dict = "auto",
        max_completion_tokens: int = 4096,
    ):
        """Versión de _chat que soporta tool calling.

        Devuelve el objeto `choices[0].message` completo. El caller debe inspeccionar
        `.tool_calls` y `.content`.
        """
        if not self.client:
            return None
        kwargs = {
            "model": deployment,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens,
            "tools": tools,
            "tool_choice": tool_choice,
        }
        response = await self.client.chat.completions.create(**kwargs)
        usage = getattr(response, "usage", None)
        if usage:
            try:
                CreditService().record_llm_usage(
                    model=deployment,
                    usage=usage,
                    action="llm.tool_chat",
                    metadata={"tools": len(tools)},
                )
            except Exception:
                pass
        return response.choices[0].message

    def _fallback_answer(
        self,
        question: str,
        master_rows: list[dict],
        rag_hits: list[dict],
        wiki_hits: list[dict],
        pdf_contexts: list[dict],
    ) -> str:
        lines = [
            f"Pregunta entendida: {question}",
            "",
            "Resultados encontrados:",
            f"- Master: {len(master_rows)} coincidencias",
            f"- Indice/RAG: {len(rag_hits)} coincidencias",
            f"- LLM Wiki: {len(wiki_hits)} coincidencias",
            f"- PDFs completos: {len(pdf_contexts)} documentos leidos",
        ]
        if master_rows:
            top = master_rows[0]
            lines.extend(["", f"Mejor candidato Master: {top.get('codigo', '')} - {top.get('titulo', '')}"])
        return "\n".join(lines)

    def _compact_master_row(self, row: dict) -> dict:
        keys = ["codigo", "titulo", "estado", "estado_categoria", "cliente_directo", "cliente_final", "tipo_servicio", "cod_proy", "monto", "horas_lic", "tarifa_prom"]
        return {key: row.get(key) for key in keys if key in row}

    def _compact_rag_hit(self, hit: dict) -> dict:
        metadata = hit.get("metadata") or {}
        compact_meta = {
            key: metadata.get(key)
            for key in [
                "estado",
                "estado_categoria",
                "propuesta_ganada",
                "propuesta_perdida",
                "cliente",
                "cliente_final",
                "titulo",
                "section_title",
                "page_start",
                "page_end",
                "section_entities",
                "search_modes",
            ]
            if key in metadata
        }
        return {
            "codigo": hit.get("codigo"),
            "title": hit.get("title"),
            "score": hit.get("score"),
            "summary": str(hit.get("summary") or "")[:700],
            "metadata": compact_meta,
        }

    def _compact_wiki_hit(self, hit: dict) -> dict:
        return {
            "title": hit.get("title"),
            "path": hit.get("path"),
            "score": hit.get("score"),
            "content": str(hit.get("content") or hit.get("summary") or "")[:700],
        }

    def _compact_conversation_context(self, context: dict) -> dict:
        result = {
            "previous_codes": context.get("previous_codes", [])[:10],
            "previous_topics": context.get("previous_topics", [])[:8],
            "previous_summary": str(context.get("previous_summary", ""))[:1200],
            "current_candidates": context.get("current_candidates", [])[:10],
            "status_legend": context.get("status_legend", {}),
            "entity_hits": context.get("entity_hits", [])[:8],
            "master_statistics": context.get("master_statistics", {}),
        }
        economics = context.get("deliverables_hours_rates") or {}
        result["deliverables_hours_rates"] = {**economics, "rows": economics.get("rows", [])[:8]} if isinstance(economics, dict) else economics
        support = context.get("proposal_support") or {}
        if isinstance(support, dict):
            result["proposal_support"] = {
                key: support.get(key, [])[:5] if isinstance(support.get(key), list) else support.get(key)
                for key in [
                    "referencias_directas",
                    "referencias_comparables",
                    "referencias_metodologicas",
                    "referencias_hh_entregables",
                    "texto_sugerido_pdf",
                    "gaps_a_validar",
                    "coverage",
                ]
            }
        return result

    def _norm(self, value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value).lower())
        return "".join(ch for ch in text if not unicodedata.combining(ch))
