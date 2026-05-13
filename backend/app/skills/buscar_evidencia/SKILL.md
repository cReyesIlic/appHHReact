---
name: buscar_evidencia
description: Úsala cuando el usuario quiere EVIDENCIA TEXTUAL de un PDF de propuesta: alcance, metodología, criterios técnicos, exclusiones, supuestos, entregables exactos. Triggers típicos: "qué dice el alcance", "metodología", "criterios", "exclusiones", "qué se entrega", "cita exacta".
allowed-tools: search_rag, search_wiki_entries, get_proposal_detail, read_pdf_deep
---

# Buscar evidencia textual en propuestas

Tu objetivo es entregar **citas literales o cuasi-literales** del documento original, con código + sección + página.

## Flujo

1. Si conoces la propuesta (`codigo`): primero **`search_wiki_entries(codigos=[codigo])`** — si hay página wiki, ya tiene el resumen con citas.
2. **`search_rag(query=<concepto>, filters={codigos: [codigo]})`** para citas específicas. Devuelve chunks con `page_start/page_end`.
3. Si la respuesta no aparece en chunks (probablemente alcance muy específico): **`read_pdf_deep(codigo, focus=<subtema>)`**. Esto es costoso — solo cuando search_rag no alcanza.
4. **`get_proposal_detail(codigo)`** si quieres un panorama amplio (master + wiki + RAG juntos).

## Estructura

### Cita principal
> "Texto literal del chunk RAG"
**Fuente:** O-XXXX · Sección "Título de la sección" · páginas N-M · (RAG)

### Citas complementarias (opcional)
Si hay 2-3 chunks que aporten ángulos distintos. Cada uno con su fuente.

### Síntesis breve
1-2 frases que respondan la pregunta concreta del usuario, basadas en las citas. Si hay ambigüedad, dilo.

## Reglas

- **Nada de paráfrasis disfrazada de cita**. Si el texto del chunk no responde, dilo y propone leer el PDF profundo.
- **No mezcles documentos**: una cita = una propuesta. Si hay evidencia contradictoria entre propuestas, sepáralas explícitamente.
- **Páginas siempre que estén disponibles** (`page_start`/`page_end` del metadata del chunk).
