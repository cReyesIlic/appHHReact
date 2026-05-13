---
name: armar_propuesta
description: Úsala cuando el usuario está preparando o armando una NUEVA propuesta y necesita referencias, alcance sugerido, HH estimadas y exclusiones. Triggers típicos: "estoy armando", "preparar propuesta", "base para", "alcance similar", "experiencia previa", "qué propuestas sirven".
allowed-tools: search_wiki_entries, compute_proposal_support, search_master, search_rag, compute_economics, get_proposal_detail, save_library_entry
---

# Armar una nueva propuesta SHIMIN

Tu objetivo es entregar al usuario un **dossier de referencias** para armar la propuesta nueva, con tres capas:

## Flujo recomendado

1. **Wiki primero** — `search_wiki_entries(query=<resumen del trabajo nuevo>)`. Si hay entradas con `propuestas_referenciadas` que cubran el alcance, úsalas como punto de partida — ya están curadas y sintetizadas.
2. **Soporte estructurado** — `compute_proposal_support(query=<descripción>, codigos=<si el usuario mencionó alguno>)`. Devuelve referencias clasificadas: directas, comparables, metodológicas, HH/entregables, texto sugerido para PDF, gaps a validar.
3. **Master + RAG complementarios** — si necesitas más cobertura o un cliente específico: `search_master(filters={...})` y `search_rag(filters={...})` con el mismo filtro estructurado.
4. **Validar y costear** — para los 2-3 códigos más cercanos: `compute_economics(codigos=[...])` (HH, monto, tarifa).
5. **Detalle profundo si hace falta** — `get_proposal_detail(codigo=<...>)` para una sola propuesta clave.

## Estructura de la respuesta

Devuelve siempre estas secciones, en este orden:

### 1. Referencias directas (1-3)
Propuestas cuyo alcance casi calza. Cita `código + título + estado (PG/PP) + cliente + monto si aplica`.

### 2. Comparables (2-4)
Propuestas con la misma metodología o disciplina, aunque el cliente o el activo sean distintos. Explica **por qué sirve** y **qué límite tiene**.

### 3. Metodológicas (1-3)
Propuestas que sirven como antecedente de enfoque (ej: misma etapa de ingeniería, disciplinas equivalentes).

### 4. HH y entregables sugeridos
Basado en `compute_economics`. Tabla compacta de:
- Código de referencia
- Entregables principales
- HH estimadas
- Tarifa de referencia

### 5. Texto sugerido para el PDF
Bloques cortos que el usuario pueda copiar/adaptar en su propuesta nueva (alcance, metodología). Saca esto de `proposal_support.texto_sugerido_pdf` o sintetiza de los chunks RAG.

### 6. Gaps a validar antes de cotizar
Lista breve de incógnitas: cliente, sitio, condiciones específicas, especificaciones técnicas faltantes.

### 7. ¿Vale guardar como entrada de wiki?
Si el usuario está consolidando aprendizajes reutilizables, ofrece guardar el resumen vía `save_library_entry`. Pregunta primero.

## Reglas

- **Distingue evidencia de inferencia**: lo que viene de un PDF/master es evidencia; lo que tú deduces de combinarlos es inferencia. Etiquétalo.
- **Cita siempre el código + fuente** (`master`, `rag`, `wiki`).
- Si el usuario dio cliente, **siempre filtra por él** además de buscar propuestas comparables de otros clientes.
- **Si el usuario menciona estado** (ganada/perdida), inclúyelo en el filtro — buscar ganadas tiene más valor para comerciales.
