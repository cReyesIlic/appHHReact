---
name: planificar_proyecto
description: Úsala cuando el usuario pide un PLAN, cronograma, ruta, etapas, hitos, secuencia o cobertura de un proyecto/propuesta nuevo. Triggers típicos: "plan", "etapas", "cronograma", "hitos", "secuencia", "cómo abordar", "ruta", "qué pasos".
allowed-tools: search_wiki_entries, compute_proposal_support, search_master, search_rag, save_library_entry
---

# Planificar un proyecto o propuesta

Tu objetivo es entregar un **plan estructurado** anclado a precedentes reales SHIMIN.

## Flujo

1. **Buscar precedentes en wiki** primero — `search_wiki_entries(query=<tipo de proyecto>)`. Si hay entradas curadas con etapas, úsalas.
2. **`compute_proposal_support(query=<descripción>)`** para identificar 3-5 propuestas similares ya hechas, con sus alcances y entregables.
3. Para cada propuesta similar, recuperar el alcance/metodología (`search_rag(filters={codigos:[...]})`).
4. Sintetizar un plan **inspirado en lo que SHIMIN ya hizo**, no inventado desde cero.

## Estructura

### 1. Diagnóstico del proyecto
1-2 frases situando: cliente, tipo de obra, etapa de ingeniería, disciplinas involucradas.

### 2. Etapas propuestas
Lista numerada de etapas, cada una con:
- **Nombre + duración estimada** (basado en propuestas precedentes)
- **Entregable principal**
- **Disciplinas involucradas**
- **HH orden de magnitud** (si lo encuentras en compute_economics o precedentes)
- **Referencia SHIMIN** (código O-XXXX que sirvió de modelo)

### 3. Riesgos y supuestos
2-4 puntos clave. Incluye qué información del cliente hace falta para precisar.

### 4. Próximo paso recomendado
Una acción concreta para el usuario: pedir tal dato al cliente, validar alcance con tal disciplina, etc.

### 5. ¿Guardar como plantilla?
Si el plan es genérico y reutilizable, ofrece `save_library_entry` con categoría `planes_proyecto`.

## Reglas

- **Cada etapa con su referencia**: "Etapa 1 — Conceptual (4 sem) — modelo O-1791 (PG, VALE 2022)".
- **No inventes HH**: si no hay precedente claro, di "HH a definir por equipo técnico".
- **Distingue duración de propuesta vs duración del proyecto adjudicado** si los datos vienen del master.
