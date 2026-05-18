"""Sub-agente especializado en entregables y HH.

Responde preguntas en lenguaje natural sobre HH licitadas (local) y reales (staffing),
adaptando el output al `tipo_servicio` del contexto:
  - IP (Ingeniería Perfil)     → perfil de equipo, disciplinas dominantes
  - IC (Ingeniería Conceptual) → desglose por disciplina + entregables clave
  - IB (Ingeniería Básica)     → paquetes y HH por paquete
  - ID (Ingeniería Detalle)    → entregables fino + asignación por persona

Reutiliza el agent loop principal pero con un system prompt y herramientas restringidas:
  - aggregate_licitadas / aggregate_reales (vía EntregablesRepository)
  - search_entregables_hh (tool ya registrada)
  - get_horas_detalle, get_persona_historial (staffing)

Si el usuario no especifica el tipo_servicio, intenta inferirlo del código de propuesta
(consultando master) o pregunta de vuelta.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import settings
from app.services.entregables_repository import EntregablesRepository
from app.services.llm import LlmService
from app.services.master_repository import MasterRepository
from app.services.staffing_client import StaffingClient


SYSTEM_PROMPT = """Eres un sub-agente especializado en entregables y HH (horas hombre) para SHIMIN Ingeniería.

Tienes acceso a dos fuentes:
1. **HH LICITADAS** (local) — Excels de oferta procesados. Por proyecto, disciplina, rol, entregable. Sin nombres de persona.
2. **HH REALES** (staffing API) — cargas semanales reales con persona, entregable, semana.

REGLAS:
- Si el usuario pregunta por una persona específica → solo REALES tiene esa info.
- Si pregunta por "presupuesto inicial / cuánto se cotizó" → LICITADAS.
- Si compara → muestra ambas (licitado vs real, % desviación).
- Adapta la respuesta al **tipo de servicio** del proyecto:
  * IP (Perfil): foco en perfil de equipo y disciplinas dominantes.
  * IC (Conceptual): desglose por disciplina + entregables clave.
  * IB (Básica): paquetes/áreas y HH por paquete.
  * ID (Detalle): entregables granulares + asignación por persona.
- Cita los números con su fuente. Si la respuesta tiene tabla, devuélvela como JSON `tables`.
- Si te falta el tipo_servicio y la pregunta lo necesita, infierelo del código o pregúntalo.

Devuelve respuesta en MARKDOWN. Sé conciso. Cita códigos O-XXXX / SH-XXXX cuando aplique.
"""


def _extract_code(text: str) -> str | None:
    m = re.search(r"\b(O-?\d{3,5})\b", text, re.IGNORECASE)
    if m:
        c = m.group(1).upper().replace("O", "O-").replace("--", "-")
        if not c.startswith("O-"):
            c = "O-" + c[1:]
        return c
    return None


def _infer_tipo_servicio(codigo: str | None) -> str | None:
    if not codigo:
        return None
    try:
        rows = MasterRepository().search(codigo=codigo, limit=1)
        if rows:
            return (rows[0].get("tipo_servicio") or "").upper() or None
    except Exception:
        pass
    return None


class EntregablesAgent:
    def __init__(self) -> None:
        self.llm = LlmService()
        self.repo = EntregablesRepository()
        self.staffing = StaffingClient()

    async def ask(self, question: str, codigo: str | None = None, tipo_servicio: str | None = None) -> dict:
        """Punto de entrada conversacional. Devuelve {answer, data, tipo_servicio, codigo}."""
        codigo = codigo or _extract_code(question)
        tipo_servicio = (tipo_servicio or _infer_tipo_servicio(codigo) or "").upper() or None

        # Recolecta datos de las fuentes según la pregunta
        ctx: dict[str, Any] = {"codigo": codigo, "tipo_servicio": tipo_servicio}
        q_lower = question.lower()

        # Heurística de fuentes a consultar
        wants_persona = any(k in q_lower for k in ["persona", "profesional", "quién", "quien", "nombre", "responsable"])
        wants_real = any(k in q_lower for k in ["real", "cargada", "ejecuta", "carga", "semanal", "staffing"])
        wants_licit = any(k in q_lower for k in ["licit", "presupuesto", "oferta", "cotiz", "estim"])
        if not wants_real and not wants_licit:
            wants_licit = True
            wants_real = wants_persona  # si pregunta por persona, sí o sí reales

        # 1. Licitadas
        if wants_licit:
            view = "role" if any(k in q_lower for k in ["rol", "cargo", "profesional"]) else (
                "disciplina" if "disciplina" in q_lower else (
                    "entregable" if "entregable" in q_lower else "proyecto"
                )
            )
            ctx["licitadas"] = self.repo.aggregate_licitadas(
                view=view,
                codigo=codigo,
                disciplina=self._extract_disciplina(question),
                text=None,
                limit=30,
            )

        # 2. Reales (si aplica)
        if wants_real:
            if codigo and wants_persona:
                ctx["reales_personas"] = await self.repo.aggregate_reales(view="persona", codigo=codigo, top=30)
            elif codigo:
                ctx["reales_entregables"] = await self.repo.aggregate_reales(view="entregable", codigo=codigo, top=30)
            else:
                ctx["reales_busqueda"] = await self.repo.aggregate_reales(
                    view="entregable",
                    text=question[:160],
                    disciplina=self._extract_disciplina(question),
                    top=30,
                )

        # 3. LLM compone respuesta
        adaptacion = self._adaptacion_tipo_servicio(tipo_servicio)
        user_msg = (
            f"Pregunta: {question}\n\n"
            f"Código identificado: {codigo or '(ninguno)'}\n"
            f"Tipo de servicio: {tipo_servicio or '(desconocido)'}\n"
            f"Adaptación esperada: {adaptacion}\n\n"
            f"Datos disponibles (resumir y citar, no enumerar todo):\n"
            f"```json\n{json.dumps({k: v for k, v in ctx.items() if k not in ('codigo','tipo_servicio')}, ensure_ascii=False, default=str)[:18000]}\n```"
        )

        try:
            answer = await self.llm._chat(
                deployment=settings.answer_deployment,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_completion_tokens=2000,
            )
        except Exception as exc:  # noqa: BLE001
            answer = f"_(LLM no disponible: {exc})_\n\nDatos crudos abajo. Revisa el panel para ver tablas."

        return {
            "answer": answer,
            "codigo": codigo,
            "tipo_servicio": tipo_servicio,
            "adaptacion": adaptacion,
            "licitadas": ctx.get("licitadas"),
            "reales_personas": ctx.get("reales_personas"),
            "reales_entregables": ctx.get("reales_entregables"),
            "reales_busqueda": ctx.get("reales_busqueda"),
        }

    def _adaptacion_tipo_servicio(self, ts: str | None) -> str:
        if not ts:
            return "general (sin tipo de servicio identificado)"
        if ts.startswith("IP"):
            return "Perfil de equipo + disciplinas dominantes (escala alta, equipo chico)"
        if ts.startswith("IC"):
            return "Disciplinas + entregables clave del concepto"
        if ts.startswith("IB"):
            return "Paquetes/áreas + HH por paquete"
        if ts.startswith("ID"):
            return "Entregables granulares + asignación por persona"
        return f"general ({ts})"

    def _extract_disciplina(self, text: str) -> str | None:
        for d in self.repo.list_disciplines(limit=80):
            if d and d.lower()[:8] in text.lower():
                return d
        return None
