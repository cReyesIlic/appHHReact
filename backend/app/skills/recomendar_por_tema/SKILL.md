---
name: recomendar_por_tema
description: Úsala cuando el usuario quiere SABER QUÉ PROPUESTAS HAY sobre un tema, dominio técnico, cliente, disciplina o tipo de obra — y quiere recomendaciones con explicación del POR QUÉ cada una sirve. Triggers típicos: "qué propuestas hay de X", "muéstrame propuestas de X", "casos de X", "experiencia en X", "ejemplos de X", "tenemos algo sobre X", "qué se ha hecho con X", "qué tenemos de X". Diferencia con armar_propuesta: aquí el usuario NO está preparando una propuesta nueva, solo quiere explorar el corpus por tema.
allowed-tools: search_wiki_entries, search_master, search_rag, search_entities, get_proposal_detail
---

# Recomendar propuestas por tema con explicación

Tu objetivo: dado un tema (concepto técnico, cliente, obra, disciplina), entregar **5-10 propuestas recomendadas**, cada una con su **rol** y una **explicación específica de por qué es relevante**.

## Flujo de trabajo

### Paso 1 — Expandir el tema con sinónimos (CRÍTICO)
Antes de buscar nada, expande mentalmente el tema con sinónimos del dominio minero. Ejemplos:
- "depósito de relaves" → tranque, relavera, embalse de relaves, deposición de relaves
- "dewatering" → desagüe mina, drenaje mina, abatimiento, agua mina
- "bombeo" → impulsión, estación de bombeo, piping de bombas
- "espesado" → pasta, filtrado, disposición filtrada
- "ingeniería de detalles" → ID, detalle, ingeniería de proyecto
- "ingeniería conceptual" → IC, perfil, prefactibilidad
- "construcción" → EPC, EPCM, administración de construcción

Si el tema es un cliente (CODELCO, VALE, etc.), úsalo como filtro `clientes` además de buscar el tema técnico.

### Paso 2 — Buscar en wiki primero (capa intermedia)
`search_wiki_entries(query="<tema OR sinonimo1 OR sinonimo2>", limit=8)`. Las páginas wiki YA tienen un resumen sintetizado del alcance de cada propuesta — eso te da el "por qué" sin tener que leer el PDF.

### Paso 3 — Complementar con Master para cobertura amplia
`search_master(queries=["<tema>", "<sinonimo1>", "<sinonimo2>"], limit=15)` — esto trae propuestas que quizá no tienen wiki page o cuyo título contiene el tema.

### Paso 4 — Para 2-3 que parezcan más relevantes pero no tengas claro su alcance
`search_rag(query="<tema>", filters={"codigos": [...]}, limit=4)` — devuelve chunks textuales del PDF para confirmar el alcance.

### Paso 5 — Clasificar y explicar
Agrupa las propuestas en tres niveles:
1. **Directas** — el tema es el objeto principal de la propuesta (mismo concepto, mismo tipo de obra).
2. **Comparables** — la propuesta toca el tema pero como parte de un alcance más amplio, o lo aplica en otro contexto.
3. **Metodológicas / Tangenciales** — sirven como antecedente (misma disciplina, misma etapa, mismo tipo de cliente) aunque el tema no sea central.

## Estructura de la respuesta

### Tema interpretado
1 línea: *"He interpretado '{tema del usuario}' como búsqueda sobre {sinónimos expandidos}."*

### Tabla principal con el POR QUÉ
| Código | Título | Cliente | Estado | Por qué te sirve |
|---|---|---|---|---|
| O-XXXX | Título corto | Cliente | PG/PP/... | **Rol específico**: explicación concreta basada en evidencia. Ej: *"Trata exactamente el dimensionamiento de relaveducto Aikan-Esmeralda, alcance idéntico"* o *"Aborda dewatering pero en rajo Codelco, sirve como comparable de metodología en otro mineral"* |

Min 5 filas, max 10. Ordena por relevancia descendente (directas primero).

### Agrupación por rol (corto)
- **Directas (1-3)**: códigos
- **Comparables (2-5)**: códigos
- **Metodológicas (1-3)**: códigos

### Próximos pasos sugeridos
2-3 acciones concretas: *"Si quieres profundizar en O-XXXX, puedo darte alcance y HH"* / *"Si te interesa solo las ganadas, dilo"* / *"Para texto sugerido para una propuesta nueva, pídeme `armar_propuesta`"*.

## Reglas duras

- **El "por qué" debe ser específico**, no genérico. NO digas "es relevante porque trata el tema". SÍ di "incluye dimensionamiento de bombas para impulsión de relaves a 6 km, mismo orden de magnitud que tu necesidad".
- **Cita la fuente del por qué**: wiki (si la entrada lo describe) / master (si solo es título+metadata) / RAG (si es evidencia textual del PDF).
- **Marca ganadas y perdidas explícitamente** con `✅ PG` / `❌ PP`.
- **Jerarquía Ganada/Perdida** (importante para propuestas comerciales):
  - **Ganadas (PG)**: tienen valor pleno — fueron adjudicadas, tienen HH reales en staffing (SH-XXXX), monto defendible.
  - **Perdidas (PP)**: sirven para alcance/ideas de metodología, **pero NO para benchmark de HH ni monto**. Su cotización fue rechazada, así que no es referencia comercial defendible.
  - Si el usuario pregunta sobre "experiencia SHIMIN" o "qué propuestas sirven de base", **prioriza explícitamente las ganadas** y márcalo en la respuesta.
- **Si el tema es muy amplio** (ej: "agua"), pide al usuario un sub-foco antes de listar 20 propuestas inútiles.
- **Si la búsqueda devuelve cero**, dilo claramente y propone variantes del término.
- **No inventes códigos**. Solo cita propuestas que aparecieron en las tools.
- **Distingue evidencia de inferencia**: si dices que O-XXXX "incluye dimensionamiento", debe venir de wiki/RAG. Si dices "probablemente toca X", márcalo como inferencia.
