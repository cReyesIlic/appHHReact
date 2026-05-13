"""Registry de tools que expone el agente al LLM.

Cada entry es un schema en formato OpenAI tools. `ToolDispatcher` traduce el
nombre + args JSON a una llamada al handler correspondiente.
"""

from __future__ import annotations

import inspect
from typing import Any

from app.agents.tools import handlers
from app.services.search_filters import valid_categorias, valid_estados, valid_tipos_servicio
from app.skills import SkillRegistry


SEARCH_FILTERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Filtros estructurados sobre propuestas. Combinables. Vacío = sin filtro.",
    "properties": {
        "codigos": {"type": "array", "items": {"type": "string"}, "description": "Códigos exactos (O-1376)"},
        "estados": {
            "type": "array",
            "items": {"type": "string", "enum": valid_estados()},
            "description": "Códigos de estado: PG=ganada, PP=perdida, EP=en preparación, ...",
        },
        "estado_categoria": {
            "type": "array",
            "items": {"type": "string", "enum": valid_categorias()},
            "description": "Alternativa más legible al estado: ganada, perdida, etc.",
        },
        "clientes": {"type": "array", "items": {"type": "string"}, "description": "Nombre del cliente (match parcial)"},
        "tipos_servicio": {
            "type": "array",
            "items": {"type": "string", "enum": valid_tipos_servicio()},
            "description": "Códigos de tipo de servicio: IP, IC, IB, ID, ...",
        },
        "disciplinas": {"type": "array", "items": {"type": "string"}, "description": "civil, hidraulica, mecanica, geotecnia, ..."},
        "componentes": {"type": "array", "items": {"type": "string"}, "description": "bombas, tuberías, ..."},
        "instalaciones": {"type": "array", "items": {"type": "string"}, "description": "tranque, deposito, planta concentradora, ..."},
        "procesos_sistemas": {"type": "array", "items": {"type": "string"}, "description": "dewatering, relaves, bombeo, ..."},
        "fecha_desde": {"type": "string", "format": "date"},
        "fecha_hasta": {"type": "string", "format": "date"},
        "monto_min": {"type": "number"},
        "monto_max": {"type": "number"},
    },
}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_master",
            "description": (
                "Busca propuestas en la planilla Master. Pasa **`queries`** (lista de SINÓNIMOS) para "
                "ampliar cobertura — ej: ['depósito relaves', 'tranque relaves', 'relavera']. Usa `query` "
                "solo para una búsqueda simple. Combina con `filters` (estado_categoria, clientes, "
                "tipos_servicio, etc.) para acotar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto único (alternativa a queries)"},
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista de sinónimos / variantes (OR semántico). Preferido.",
                    },
                    "filters": SEARCH_FILTERS_SCHEMA,
                    "limit": {"type": "integer", "default": 12},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_rag",
            "description": (
                "Búsqueda semántica + lexical en chunks de PDFs de propuestas con filtros estructurados. "
                "Devuelve fragmentos textuales con metadata (codigo, estado, cliente, sección, página). "
                "Úsala cuando necesites EVIDENCIA TEXTUAL: alcance, metodología, entregables, criterios. "
                "Si query está vacío y hay filtros, devuelve los chunks más relevantes del subconjunto filtrado."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "filters": SEARCH_FILTERS_SCHEMA,
                    "limit": {"type": "integer", "default": 8},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_proposal_index",
            "description": (
                "Busca en el índice de RESÚMENES de primeras páginas (un resumen LLM por PDF: alcance "
                "general, cliente, scope, deliverables). Más rápido y menos ruidoso que search_rag cuando "
                "buscas propuestas similares a nivel macro."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "codigos": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "default": 8},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_wiki_entries",
            "description": (
                "Busca en la BIBLIOTECA CURADA (entradas Wiki SHIMIN). Cada entrada es una lección, "
                "criterio o referencia validada manualmente. Puede tener propuestas referenciadas y "
                "categorías. Úsala antes de search_rag cuando la pregunta sea metodológica o sobre "
                "criterios SHIMIN."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "category": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "default": 6},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_entities",
            "description": (
                "Busca en el índice de entidades extraídas (disciplinas, componentes, procesos, instalaciones). "
                "Devuelve códigos de propuesta que contienen esas entidades, con sección donde aparecen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "filters": SEARCH_FILTERS_SCHEMA,
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_master_stats",
            "description": (
                "Calcula estadísticas agregadas sobre Master (conteos por estado/cliente/tipo, montos, "
                "horas, propuestas ganadas vs perdidas). Devuelve summary + tablas + charts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Foco opcional (ej: 'relaves')"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_economics",
            "description": (
                "Análisis de entregables, horas hombre (HH) y tarifas para uno o varios códigos. "
                "Útil cuando preguntan monto, HH, tarifa promedio, equipo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codigos": {"type": "array", "items": {"type": "string"}, "description": "Códigos de propuesta"},
                    "limit": {"type": "integer", "default": 6},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_proposal_support",
            "description": (
                "Genera referencias clasificadas (directas, comparables, metodológicas, HH/entregables, "
                "gaps a validar) para armar una NUEVA propuesta. Úsala cuando el usuario diga 'armando "
                "una propuesta', 'base para', 'similar a', 'referencias para'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "codigos": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_proposal_detail",
            "description": (
                "Obtiene metadata + resumen completo de una propuesta por código (todas las filas master "
                "que coinciden + chunks RAG top + entradas wiki que la referencian)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codigo": {"type": "string"},
                },
                "required": ["codigo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_pdf_deep",
            "description": (
                "Lee texto profundo del PDF original de una propuesta (vía SharePoint). Usar solo cuando "
                "los chunks de search_rag no alcanzan. Costoso."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codigo": {"type": "string"},
                    "focus": {"type": "string", "description": "Subtema a buscar dentro del PDF"},
                },
                "required": ["codigo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": (
                "Carga el playbook (SKILL.md) de una skill SHIMIN por nombre. Las skills definen flujos "
                "específicos para tipos de pregunta (armar propuesta, estadísticas, comparar, planificar, "
                "buscar evidencia, datos económicos). Llama esta tool CUANDO la pregunta del usuario calza "
                "con alguna skill del catálogo del system prompt. La respuesta es markdown con instrucciones "
                "detalladas que debes seguir para esa respuesta. NO inventes nombres de skills — usa solo "
                "las listadas en 'Skills disponibles'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre exacto de la skill"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_document",
            "description": (
                "Genera un documento descargable. Úsala cuando el usuario pida 'PDF', 'Word', 'Excel', "
                "'descargable', 'documento', 'exportar'. Pasa `content` con el markdown completo de la "
                "respuesta y `tables` con las tablas relevantes. La tool devuelve un `markdown_link` "
                "tipo '📥 [Descargar pdf](/api/exports/file/xxx.pdf)' — **inclúyelo TAL CUAL en tu respuesta** "
                "para que el usuario pueda descargar con un click. NO inventes URLs; usa el link que devuelve."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["docx", "pdf", "xlsx", "typst-pdf", "report"],
                        "description": "Formato. 'report' = 'typst-pdf' = PDF SHIMIN estilizado. 'docx' = Word.",
                    },
                    "title": {"type": "string", "default": "Respuesta SHIMIN"},
                    "content": {"type": "string", "description": "Contenido principal (markdown)"},
                    "tables": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Tablas: [{name, rows: [{col: val}]}]",
                    },
                    "sources": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["kind", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_library_entry",
            "description": (
                "Guarda una nueva entrada en la biblioteca curada SHIMIN. Úsala cuando el usuario diga "
                "'guarda esto', 'recordemos', 'agrega a wiki', o cuando una lección sea reutilizable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "category": {"type": "string", "default": "general"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "content": {"type": "string", "description": "Cuerpo markdown"},
                    "propuestas_referenciadas": {"type": "array", "items": {"type": "string"}},
                    "pinned": {"type": "boolean", "default": False},
                },
                "required": ["title", "content"],
            },
        },
    },
]


class ToolDispatcher:
    """Resuelve un tool_call de OpenAI a un handler de `app.agents.tools.handlers`.

    Se inicializa una vez por request del agente — guarda los servicios pesados
    (master, rag, etc.) para reusarlos entre tool_calls.
    """

    def __init__(self, ctx: handlers.ToolContext, skill_registry: SkillRegistry | None = None) -> None:
        self.ctx = ctx
        self.skill_registry = skill_registry or SkillRegistry()
        self._handlers = {
            "search_master": handlers.search_master,
            "search_rag": handlers.search_rag,
            "search_proposal_index": handlers.search_proposal_index,
            "search_wiki_entries": handlers.search_wiki_entries,
            "search_entities": handlers.search_entities,
            "compute_master_stats": handlers.compute_master_stats,
            "compute_economics": handlers.compute_economics,
            "compute_proposal_support": handlers.compute_proposal_support,
            "get_proposal_detail": handlers.get_proposal_detail,
            "read_pdf_deep": handlers.read_pdf_deep,
            "save_library_entry": handlers.save_library_entry,
            "generate_document": handlers.generate_document,
            "load_skill": self._load_skill,
        }

    async def _load_skill(self, _ctx: handlers.ToolContext, name: str) -> dict:
        return self.skill_registry.load(name)

    async def dispatch(self, name: str, args: dict) -> dict:
        handler = self._handlers.get(name)
        if not handler:
            return {"error": f"tool desconocida: {name}"}
        try:
            result = handler(self.ctx, **args) if not inspect.iscoroutinefunction(handler) else await handler(self.ctx, **args)
            return result if isinstance(result, dict) else {"result": result}
        except TypeError as exc:
            return {"error": f"argumentos inválidos: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"fallo {name}: {exc}"}
