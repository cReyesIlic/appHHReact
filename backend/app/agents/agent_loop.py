"""Loop agéntico de tool calling.

El LLM recibe el schema de tools, decide qué llamar, vuelve a recibir el resultado,
y repite hasta producir una respuesta final (sin más tool_calls) o agotar el cupo
de iteraciones.

Diseñado para ser invocado desde `AgentOrchestrator.run`.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from app.agents.tools import TOOL_SCHEMAS, ToolDispatcher
from app.agents.tools.handlers import ToolContext
from app.core.config import settings
from app.schemas import ChatMessage, Source, ToolTrace
from app.services.llm import LlmService
from app.services.search_filters import SearchFilters
from app.skills import SkillRegistry


BASE_SYSTEM_PROMPT = """Eres un agente senior de propuestas SHIMIN. Tu objetivo es responder con precisión cualquier pregunta sobre proyectos, propuestas, estadísticas, alcances, montos, lecciones aprendidas, planes o referencias.

# ARQUITECTURA DE FUENTES (úsalas en orden cuando aplique)

**Capa intermedia primero (WIKI / LIBRERÍA CURADA)** — ANTES de buscar en RAG o Master, consulta `search_wiki_entries`. La wiki tiene ~650 páginas curadas (una por propuesta + entradas de lecciones / criterios SHIMIN). Si una entrada wiki ya cubre la pregunta, úsala como respuesta principal y solo complementa con master/rag para verificar.

**Datos tabulares (MASTER)** — `search_master(filters=...)` para cuántas/listar/montos/estados/clientes. Acepta filtros estructurados: estado_categoria, clientes, tipos_servicio, disciplinas, fechas, monto_min/max.

**Evidencia textual (RAG)** — `search_rag(filters=...)` cuando necesitas alcance, metodología, criterios o citas literales del PDF. Devuelve chunks con páginas.

**Análisis especializados** — `compute_master_stats`, `compute_economics`, `compute_proposal_support`, `get_proposal_detail`, `read_pdf_deep`.

# SKILLS DISPONIBLES (playbooks específicos)

Para tipos de pregunta comunes hay skills que entregan flujo + estructura de respuesta. Si la pregunta del usuario calza con alguna, **llama `load_skill(name)` PRIMERO** y sigue al pie de la letra el playbook que devuelve.

{skills_catalog}

Si ninguna skill aplica claramente, procede con tu juicio usando los principios de abajo.

# PRINCIPIOS

1. **Wiki como capa intermedia preferida**: la librería curada existe precisamente para evitar releer RAG en cada pregunta. Úsala.
2. **Evidencia vs inferencia**: cita con `código + título + fuente (master/rag/wiki)`. Marca ganadas/perdidas explícitamente. Si infieres, dilo.
3. **Filtros estructurados** siempre que el usuario mencione estado/cliente/tipo/disciplina. No hagas búsquedas amplias cuando hay filtros disponibles.
4. **Encadena pero no abuses**: máximo 6 tool_calls. No repitas la misma búsqueda. Si search_wiki responde, no llames search_rag salvo que necesites detalle adicional.
5. **Idioma**: español, conciso, con tablas cuando aporten.
6. **No inventes datos**: si master/rag/wiki no tienen la información, dilo y propone una vía.
7. **Expande la búsqueda con sinónimos del dominio MINERO** — NO hagas una sola búsqueda literal: la primera tool de búsqueda debe usar varios términos equivalentes en `query`. Diccionario base:
   - **depósito de relaves** ↔ tranque de relaves ↔ relavera ↔ embalse de relaves ↔ deposición de relaves
   - **rajo** ↔ pit ↔ open pit ↔ mina rajo abierto
   - **dewatering** ↔ desagüe ↔ drenaje de mina ↔ abatimiento
   - **bombeo** ↔ impulsión ↔ estación de bombeo ↔ piping de bombas
   - **relaves espesados** ↔ pasta ↔ filtrado ↔ disposición filtrada
   - **agua mina** ↔ aguas de contacto ↔ aguas recuperadas ↔ agua de proceso
   - **tubería** ↔ ducto ↔ piping ↔ relaveducto ↔ acueducto
   - **planta** ↔ planta concentradora ↔ chancado ↔ molienda
   - **ingeniería conceptual** ↔ perfil ↔ prefactibilidad
   - **ingeniería de detalles** ↔ ID ↔ ingeniería básica ↔ EB ↔ ingeniería de detalle
   - **EPCM** ↔ EPC ↔ administración de construcción
   Cuando el usuario pregunta por uno de estos términos, la query inicial a search_master/search_rag debe combinar 2-3 sinónimos relevantes para maximizar cobertura. Ejemplo: si pregunta por "depósito de relaves", busca `query="depósito relaves OR tranque relaves OR relavera"`.

# CUIDADOS

- `read_pdf_deep` es caro: úsalo solo si `search_rag` no alcanza.
- Si los filtros vacían el resultado, dilo y propone relajarlos.
- Si te quedas sin cupo de tools, responde con lo que tengas y avisa qué falta.
"""


def build_system_prompt(skill_registry: SkillRegistry) -> str:
    catalog = skill_registry.catalog() or "_(sin skills cargadas)_"
    return BASE_SYSTEM_PROMPT.format(skills_catalog=catalog)


@dataclass
class AgentRunResult:
    answer: str
    trace: list[ToolTrace] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    charts: list[dict] = field(default_factory=list)
    suggested_codes: list[str] = field(default_factory=list)


class AgentLoop:
    def __init__(self, max_iterations: int = 6) -> None:
        self.llm = LlmService()
        self.max_iterations = max_iterations
        self.skill_registry = SkillRegistry()

    async def run(
        self,
        question: str,
        history: list[ChatMessage] | None = None,
        filters: SearchFilters | None = None,
        memory_summary: str = "",
        candidate_codes: list[str] | None = None,
    ) -> AgentRunResult:
        ctx = ToolContext.build()
        dispatcher = ToolDispatcher(ctx, skill_registry=self.skill_registry)
        trace: list[ToolTrace] = []
        sources: list[Source] = []
        tables: list[dict] = []
        charts: list[dict] = []
        seen_codes: list[str] = list(candidate_codes or [])

        seed_filters_dict = filters.model_dump(exclude_none=True) if filters and not filters.is_empty() else None
        user_payload: dict[str, Any] = {"pregunta": question}
        if seed_filters_dict:
            user_payload["filtros_iniciales"] = seed_filters_dict
        if memory_summary:
            user_payload["memoria"] = memory_summary[:2000]
        if candidate_codes:
            user_payload["candidatos_de_contexto"] = candidate_codes[:8]

        messages: list[dict] = [
            {"role": "system", "content": build_system_prompt(self.skill_registry)},
        ]
        for past in (history or [])[-6:]:
            if past.role in {"user", "assistant"}:
                messages.append({"role": past.role, "content": past.content[:2000]})
        messages.append(
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            }
        )

        if not self.llm.client:
            trace.append(ToolTrace(tool="agent.loop", status="warning", detail="sin cliente LLM; fallback"))
            return AgentRunResult(
                answer=f"Sin LLM disponible. Pregunta recibida: {question}",
                trace=trace,
            )

        deployment = settings.answer_deployment if self.llm.azure else "gpt-4o-mini"

        for iteration in range(self.max_iterations):
            t0 = time.time()
            try:
                message = await asyncio.wait_for(
                    self.llm.chat_with_tools(
                        deployment=deployment,
                        messages=messages,
                        tools=TOOL_SCHEMAS,
                        tool_choice="auto",
                        max_completion_tokens=3072,
                    ),
                    timeout=45,
                )
            except Exception as exc:  # noqa: BLE001
                trace.append(ToolTrace(tool="agent.llm", status="error", detail=f"iter {iteration}: {exc}"))
                break

            if message is None:
                trace.append(ToolTrace(tool="agent.llm", status="error", detail="respuesta vacía"))
                break

            tool_calls = getattr(message, "tool_calls", None) or []
            content = getattr(message, "content", None) or ""

            if not tool_calls:
                trace.append(ToolTrace(tool="agent.llm", status="ok", detail=f"iter {iteration}: respuesta final"))
                self._collect_outputs(messages, sources, tables, charts, seen_codes)
                return AgentRunResult(
                    answer=content.strip() or "(respuesta vacía)",
                    trace=trace,
                    sources=sources,
                    tables=tables,
                    charts=charts,
                    suggested_codes=list(dict.fromkeys(seen_codes))[:20],
                )

            # Añadir el assistant message con tool_calls al historial
            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in tool_calls
                    ],
                }
            )

            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                # Inyectar filtros seed si la tool acepta filtros y el LLM no los pasó
                if seed_filters_dict and "filters" in (args or {}).get("__skip__", {}):
                    pass
                if seed_filters_dict and name in {"search_master", "search_rag", "search_entities"} and not args.get("filters"):
                    args["filters"] = seed_filters_dict
                detail = ", ".join(f"{k}={self._truncate_value(v)}" for k, v in (args or {}).items())
                t_start = time.time()
                result = await dispatcher.dispatch(name, args)
                latency_ms = int((time.time() - t_start) * 1000)
                status = "error" if isinstance(result, dict) and result.get("error") else "ok"
                trace.append(ToolTrace(tool=f"agent.{name}", status=status, detail=f"{detail} ({latency_ms}ms)"))
                self._absorb_codes(result, seen_codes)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": json.dumps(self._truncate_result(result), ensure_ascii=False),
                    }
                )
            trace.append(ToolTrace(tool="agent.iter", status="ok", detail=f"iter {iteration} en {int((time.time()-t0)*1000)}ms"))

        trace.append(ToolTrace(tool="agent.loop", status="warning", detail="max_iterations alcanzado"))
        # Fallback: pedir respuesta final sin tools
        try:
            messages.append({"role": "user", "content": "Responde ahora con lo recogido. No llames más herramientas."})
            final = await asyncio.wait_for(
                self.llm.chat_with_tools(
                    deployment=deployment,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="none",
                    max_completion_tokens=2048,
                ),
                timeout=30,
            )
            answer = (final.content if final else "") or "(respuesta vacía)"
        except Exception as exc:  # noqa: BLE001
            trace.append(ToolTrace(tool="agent.finalize", status="error", detail=str(exc)))
            answer = "No fue posible cerrar la respuesta dentro del cupo. Datos recolectados disponibles en sources."

        return AgentRunResult(
            answer=answer,
            trace=trace,
            sources=sources,
            tables=tables,
            charts=charts,
            suggested_codes=list(dict.fromkeys(seen_codes))[:20],
        )

    def _truncate_value(self, value: Any) -> str:
        text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        return text if len(text) <= 80 else text[:77] + "..."

    def _truncate_result(self, result: dict, max_chars: int = 14000) -> dict:
        if not isinstance(result, dict):
            return {"result": str(result)[:max_chars]}
        serialized = json.dumps(result, ensure_ascii=False)
        if len(serialized) <= max_chars:
            return result
        # Truncar listas largas a 6 elementos
        clipped: dict[str, Any] = {}
        for key, value in result.items():
            if isinstance(value, list) and len(value) > 6:
                clipped[key] = value[:6] + [{"_truncated": len(value) - 6}]
            else:
                clipped[key] = value
        return clipped

    def _absorb_codes(self, result: Any, seen_codes: list[str]) -> None:
        if not isinstance(result, dict):
            return
        for key in ("rows", "hits", "entries"):
            items = result.get(key) or []
            for item in items if isinstance(items, list) else []:
                codigo = (item or {}).get("codigo") if isinstance(item, dict) else None
                if codigo and codigo not in seen_codes:
                    seen_codes.append(str(codigo).upper())
        codigos_top = result.get("codigos_top") or []
        for codigo in codigos_top if isinstance(codigos_top, list) else []:
            if codigo and codigo not in seen_codes:
                seen_codes.append(str(codigo).upper())

    def _collect_outputs(
        self,
        messages: list[dict],
        sources: list[Source],
        tables: list[dict],
        charts: list[dict],
        seen_codes: list[str],
    ) -> None:
        """Recoge sources/tables/charts de los resultados de tool en el historial."""
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            try:
                payload = json.loads(msg.get("content") or "{}")
            except json.JSONDecodeError:
                continue
            tool_name = msg.get("name") or ""
            # Sources
            for hit in payload.get("hits") or []:
                if not isinstance(hit, dict):
                    continue
                sources.append(
                    Source(
                        kind=tool_name,
                        title=str(hit.get("title") or hit.get("section_title") or hit.get("codigo") or "")[:200],
                        url=hit.get("url"),
                        codigo=hit.get("codigo"),
                        score=hit.get("score"),
                    )
                )
            for entry in payload.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                sources.append(
                    Source(
                        kind=tool_name,
                        title=str(entry.get("title") or entry.get("id") or "")[:200],
                        codigo=None,
                        score=entry.get("score"),
                    )
                )
            for row in payload.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                codigo = row.get("codigo")
                if codigo:
                    sources.append(
                        Source(
                            kind=tool_name,
                            title=str(row.get("titulo") or codigo)[:200],
                            codigo=str(codigo),
                        )
                    )
            # Tables
            tabs = payload.get("tables") or []
            for tab in tabs if isinstance(tabs, list) else []:
                if isinstance(tab, dict):
                    tables.append(tab)
            chs = payload.get("charts") or []
            for ch in chs if isinstance(chs, list) else []:
                if isinstance(ch, dict):
                    charts.append(ch)
