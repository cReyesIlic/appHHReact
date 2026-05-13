---
name: analizar_entregables_hh
description: Úsala cuando el usuario pregunta por ENTREGABLES con HH REALES cargadas (datos del sistema staffing SHIMIN), no estimaciones del Master. Triggers típicos: "memoria de cálculo en X proyecto", "MDC en Caserones", "planos de piping para Vale", "informes de hidráulica", "cuántas HH consumió tal entregable", "quién trabajó en X entregable", "cuántas horas cargó Fulano", "carga real vs propuesta", "experiencia en X disciplina con datos reales", "cuánto tomó hacer un entregable como Y".
allowed-tools: search_entregables_hh, get_horas_detalle, get_proyecto_staffing, get_persona_historial, search_master, search_wiki_entries
---

# Análisis de entregables con HH reales (Staffing)

Tu objetivo: entregar **datos reales de HH cargadas** sobre entregables, no estimaciones. La fuente es el sistema de control de horas SHIMIN, **NO el Master Excel**. Aquí los datos vienen de `hh_control` (semanal por persona).

## Cuándo SÍ usar esta skill

- *"Cuántas HH se cargaron en memorias de cálculo hidráulica en Caserones"*
- *"Quién trabajó en planos de piping para SH-0392"*
- *"Experiencia real de SHIMIN en informes de hidráulica con Codelco"*
- *"Para una propuesta de MDC similar, ¿cuántas HH son realistas?"*
- *"¿Cuánto cargó Fulano de Tal en X proyecto?"*

## Cuándo NO

- Si el usuario pregunta solo por **propuestas/ofertas O-XXXX** sin foco en HH reales → usa `recomendar_por_tema` o `armar_propuesta`.
- Si pregunta por **monto/tarifa cotizada** (no HH reales) → usa `datos_economicos`.
- Si pregunta por **estadísticas comerciales** (ganadas, distribución) → usa `estadisticas_propuestas`.

## Flujo

### Paso 1 — Identificar qué pide
- ¿Concepto técnico (entregable)? → `search_entregables_hh(q="<concepto>", ...)`
- ¿Persona específica? → `get_persona_historial(usuario_id)`
- ¿Proyecto específico SH-XXXX? → `get_proyecto_staffing(codigo)`
- ¿Auditoría detallada de quién/cuándo? → `get_horas_detalle(...)`

### Paso 2 — Búsqueda principal con sinónimos trilingües
Como en otras skills, expande términos:
- **memoria de cálculo** → MDC, MC, *memorial de cálculo* (PT), *calculation memo* (EN)
- **planos** → drawings, isométricos, P&ID
- **informe** → reporte, *relatório* (PT), *report* (EN)
- **piping** → tuberías, *tubulação* (PT)

Llamada típica:
```
search_entregables_hh(
  q="<concepto + sinónimos>",
  disciplina="<código si aplica>",
  contexto="<cliente o proyecto>",
  top=30,
  incluir_personas=true,
)
```

### Paso 3 — Si necesitas más detalle por persona/semana
`get_horas_detalle(...)` para auditar quién cargó qué semana.

### Paso 4 — Cross-link con Master (opcional)
Si el `detalle[].codigo_prop` viene resuelto, puedes complementar con `search_master(codigos=[...])` para ver el lado comercial.

## Estructura de la respuesta

### Resumen ejecutivo (1-2 líneas)
*"Encontré 23 entregables tipo MDC en Caserones con un total de 4 821 HH reales cargadas entre 2023-2025. Top disciplinas: Hidráulica (62%), Piping (24%)."*

### Distribuciones
Tabla compacta por:
- **Disciplina** (de `distribucion_disciplina`)
- **Cliente** (de `distribucion_cliente`)
- **Servicio / tipo ingeniería** (de `distribucion_servicio`)

### Top entregables (5-10)
| Proyecto | Entregable | HH | Disciplina | Cliente | Top persona |
|---|---|---:|---|---|---|
| SH-0392 | MDC-HI-001 Memoria hidráulica… | 312 | HI | Caserones | F.E. (180h) |

### Recomendación si el usuario está armando una propuesta
*"Para una propuesta similar de MDC hidráulica en Caserones, el promedio real es ~210 HH por entregable (rango 80-450). Considera 2 personas senior + 1 junior por 6-8 semanas."*

### Próximo paso
Sugerir: *"¿Quieres el detalle semanal de un entregable? Te puedo dar la auditoría con `get_horas_detalle`."*

## Reglas

- **HH son HORAS-PERSONA acumuladas, no horas calendario**: si reportas "MDC X = 261 h", aclara que son **horas-persona totales en el ciclo del entregable**, distribuidas entre 2-4 personas. Una MDC de 260 h no significa una persona trabajando 260 h sola.
- **Cuando reportes top entregables con HH altas (>150 h)**, llama con `incluir_personas=true` y muestra el desglose por persona. Si Sandra cargó 152 h e Ignacio 104 h, indícalo. Es la única forma de que el usuario entienda si es 1 persona-mes o 3 personas-semana cada una.
- **Promedio vs picos**: si pides 100 entregables y el promedio sale 94 h, **ese es el dato realista** para una MDC típica. Los top 5 son MDCs complejas (sistemas completos, transporte de relaves multi-disciplina) — no representativos del proyecto medio.
- **Distingue HH reales vs HH licitadas**: las HH licitadas viven en Master (cotización). Las HH reales son del sistema staffing. Si las dos están disponibles, **muéstralas en paralelo**: "MDC X — licitadas 200 vs reales 312 (+56%)".
- **Cita siempre la fuente**: `(Fuente: staffing/análisis_hh)`.
- **Privacidad**: si vas a mencionar personas, usa nombres como vienen del API (no des emails, no inventes contactos).
- **No fabricar promedios**: si el N es bajo (<5 entregables), avisa al usuario que la muestra es pequeña.
- **Cross-link Master si hay matches**: si `codigo_prop` viene resuelto, el agente puede traer también la oferta original con `search_master`.
