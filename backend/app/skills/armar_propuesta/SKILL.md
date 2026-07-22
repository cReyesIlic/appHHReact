---
name: armar_propuesta
description: Úsala cuando el usuario está preparando o armando una NUEVA propuesta y necesita referencias, alcance sugerido, HH estimadas y exclusiones. Triggers típicos: "estoy armando", "preparar propuesta", "base para", "alcance similar", "experiencia previa", "qué propuestas sirven", "draft de propuesta", "mi propuesta nueva".
allowed-tools: search_wiki_entries, compute_proposal_support, search_master, search_rag, compute_economics, get_proposal_detail, save_library_entry, search_entregables_hh, get_proyecto_staffing, list_my_drafts, get_draft_context, search_draft_chunks, import_draft_from_sharepoint
---

# Armar una nueva propuesta SHIMIN

Tu objetivo es entregar al usuario un **dossier de referencias** para armar la propuesta nueva, con tres capas: comercial (Master), técnica (RAG/Wiki), ejecución real (Staffing) — y **opcionalmente los antecedentes del cliente** que el usuario subió como draft.

## ⚡ Detectar si hay DRAFT ACTIVO

Antes de buscar referencias internas, **revisa si el usuario está trabajando en un draft con antecedentes del cliente**:

1. Si el usuario menciona "mi draft", "estoy armando X propuesta", "la nueva propuesta", "los antecedentes que subí", "el RFP del cliente":
   - Llama `list_my_drafts()` para ver sus drafts
   - Si hay uno reciente o el usuario lo menciona por título: `get_draft_context(slug, include_guide=true)`
   - La GUÍA generada del draft tiene los puntos clave del cliente: alcance, plazo, exclusiones, criterios. Úsalos para guiar tus búsquedas.
2. Para citas específicas del RFP/antecedentes: `search_draft_chunks(slug, query="<concepto>")`.
3. **Combina**: usa la guía del draft para entender qué pide el cliente + tu búsqueda en master/RAG/staffing para traer experiencia SHIMIN relevante.

### Modo interactivo con draft activo

Cuando `draft_activo` y `contexto_draft` ya vienen precargados, no vuelvas a listar ni a abrir el
draft de forma genérica. Para una petición como “ayúdame a armarla”:

- usa los antecedentes del cliente como fuente principal;
- selecciona solo 2–4 consultas históricas que realmente aporten;
- entrega en este turno un primer armado accionable (alcance, metodología, entregables, plan,
  equipo preliminar, supuestos/exclusiones y preguntas pendientes);
- no ejecutes economía, staffing ni desglose HH salvo que el usuario los pida explícitamente.

La profundidad adicional se trabaja en las siguientes preguntas del mismo chat; no bloquees el
primer armado intentando completar todo el dossier de ocho secciones en una sola respuesta.

## REGLA DE ORO — jerarquía de búsqueda

Las propuestas no son todas iguales. Para una nueva propuesta:

1. **PRIORIDAD 1 — Ganadas del mismo cliente** (`estado_categoria=ganada` + `clientes=[<cliente del usuario>]`). Son el oro: el cliente las aceptó, hay HH reales y se conoce su tolerancia comercial.
2. **PRIORIDAD 2 — Ganadas de otros clientes con tema similar** (`estado_categoria=ganada`, sin filtro de cliente). También tienen HH reales y validan el enfoque metodológico.
3. **Perdidas (PP) — SOLO IDEAS DE ALCANCE**: úsalas únicamente para extraer ideas de cómo plantear el alcance/metodología. **NUNCA cites HH de propuestas perdidas como referencia real** — fueron solo cotizadas, no ejecutadas, no hay datos en staffing.

## Conexión Oferta (O-XXXX) ↔ Proyecto (SH-XXXX)

- Una propuesta **O-XXXX en estado PG** se transformó en un **proyecto SH-XXXX** que se ejecutó → tiene HH reales en staffing.
- Una propuesta **O-XXXX en estado PP** quedó solo en master → no tiene HH reales.
- El staffing API devuelve `codigo_prop` (O-XXXX) cuando hay match → ese es el puente entre los dos mundos.

## Flujo recomendado

### Paso 1 — Wiki primero
`search_wiki_entries(query=<resumen del trabajo>, codigos=<si el usuario mencionó alguno>)`. Si hay entradas con `propuestas_referenciadas` ganadas que cubran el alcance, esas van de cabeza al dossier.

### Paso 2 — Master: priorizar GANADAS del mismo cliente
```
search_master(
  queries=[<sinónimos del tema en ES/PT/EN>],
  filters={
    estado_categoria: ["ganada"],
    clientes: [<cliente del usuario>],   ← prioridad 1
  },
  limit=8,
)
```
Si encuentras 3+ ganadas con ese cliente → úsalas como **referencias directas**. Si encuentras 0-2 → relaja el filtro:

### Paso 3 — Master: ganadas de otros clientes (mismo tema)
```
search_master(
  queries=[<sinónimos>],
  filters={
    estado_categoria: ["ganada"],   ← sigue restringido a ganadas
    # SIN filtro de cliente
  },
  limit=10,
)
```
Estas son **referencias comparables**. Para cada una, anota explícitamente por qué sirve a pesar de ser otro cliente.

### Paso 4 — Perdidas: SOLO para ideas de alcance
Solo si los pasos 2-3 dejaron poco material o si el usuario insiste en buscar referencias amplias:
```
search_rag(
  query=<concepto>,
  filters={
    estado_categoria: ["perdida"],
    clientes: [<cliente del usuario>],   ← si aplica
  },
  limit=4,
)
```
**Marca claramente** estas entradas como *"Perdida — solo para ideas, sin HH reales"*. NO menciones su monto licitado como referencia (era una cotización rechazada, no es benchmark).

### Paso 5 — Soporte estructurado (clasifica las referencias)
`compute_proposal_support(query=<descripción>, codigos=<top ganadas encontradas>)`. Devuelve: directas, comparables, metodológicas, HH/entregables, texto sugerido, gaps.

### Paso 6 — HH REALES desde Staffing (solo para ganadas)
Para las propuestas ganadas con peso (top 3-5), busca HH reales:
```
search_entregables_hh(
  q=<concepto del trabajo>,
  contexto=<cliente o tema>,
  disciplina=<si aplica: HI/PI/ME/EL>,
  incluir_personas=true,
  top=20,
)
```
Esto devuelve HH-persona reales acumuladas. **Recuerda**: son horas-persona totales, no horas calendario.

### Paso 7 — Costear (HH licitadas)
`compute_economics(codigos=[<top 3 ganadas>])` para ver montos, tarifas y HH licitadas. Si tienes ambas (licitadas + reales), **muestra gap** explícito.

### Paso 8 — Detalle profundo (opcional)
- `get_proposal_detail(codigo=O-XXXX)` para alcance/metodología de una propuesta clave.
- `get_proyecto_staffing(codigo=SH-XXXX)` si conoces el código del proyecto adjudicado: ve entregables + personas asignadas en el ciclo real.

## Estructura de la respuesta

### 0. Filtro aplicado (1 línea)
*"Busqué propuestas **ganadas** con cliente **Codelco** sobre **dewatering** (también desagüe/drenaje/mine drainage)."*

### 1. Referencias directas — GANADAS, mismo cliente (1-3)
| Código | Título | Estado | Cliente | Monto | Por qué sirve |
|---|---|---|---|---|---|
| O-XXXX | … | ✅ **PG** | <cliente> | … kUF | Alcance casi idéntico. Adjudicada → SH-YYYY (ver HH reales abajo). |

### 2. Comparables — GANADAS, otros clientes (2-4)
Mismo tema, otro cliente. Explica por qué sirve a pesar de ser otro cliente y qué límite tiene.

### 3. Ideas de alcance — PERDIDAS, solo si aporta (0-2 opcionales)
*"De propuestas perdidas (no son benchmark, solo para inspirar alcance):"*
- O-XXXX — alcance interesante: "incluye revisión X que podríamos considerar". **NO** cita su monto/HH.

### 4. HH reales y entregables (solo de ganadas / SH-XXXX)
Basado en `search_entregables_hh` y/o `get_proyecto_staffing`. Tabla:

| Proyecto (SH) | Entregable | HH reales (persona acumulada) | Personas | Licitadas (Master) | Gap |
|---|---|---:|---|---:|---:|
| SH-YYYY | MDC Hidráulica … | 261 (Sandra 152 + Ignacio 104 + Constanza 5) | 3 | 200 | +30 % |

**Promedio del corpus relevante**: si llamaste `search_entregables_hh` con top=20-50, indica también el promedio (ej. *"el promedio real de MDCs hidráulicas similares es 94 HH-persona"*). Esa es la cifra para estimar tu propuesta nueva, no los picos.

### 5. Equipo sugerido
A partir de `personas_detalle`: qué disciplinas/seniorities cargaron horas en propuestas similares. Ej. *"En SH-YYYY trabajaron 1 senior hidráulica + 1 mid + 1 junior. Considera equipo similar."*

### 6. Texto sugerido para el PDF
Bloques cortos (alcance, metodología, exclusiones) basados en `proposal_support.texto_sugerido_pdf` o sintetizado de chunks RAG de las ganadas.

### 7. Gaps a validar antes de cotizar
Lista breve: cliente, sitio, condiciones específicas, especificaciones técnicas faltantes.

### 8. ¿Guardar como entrada de wiki?
Si el dossier consolida aprendizaje reutilizable, ofrece guardar vía `save_library_entry`.

## Reglas duras

- **Las HH reales SOLO existen en propuestas ganadas (O→SH)**. Si una propuesta es PP, no busques `search_entregables_hh` para ella — no encontrará nada. Indica al usuario: *"Esta es perdida, no tiene ejecución real, solo monto licitado de referencia que no necesariamente es defendible."*
- **Si NO hay propuestas ganadas del mismo cliente sobre el tema**, dilo explícitamente: *"No encontré propuestas ganadas con <cliente> sobre <tema>. Las referencias son ganadas de otros clientes (ver tabla 2)."*
- **Distingue HH licitadas vs reales** siempre que muestres números económicos.
- **Cita código + estado + fuente** en cada referencia (`O-XXXX PG · master`, `SH-YYYY · staffing`, `O-XXXX PP · master`).
- **Distingue evidencia de inferencia**: lo que está en master/RAG/staffing es evidencia. Lo que tú deduces combinando, dilo.
- **Si el usuario dio cliente**, siempre arranca filtrando por él (paso 2). Solo amplia si los datos no alcanzan.
