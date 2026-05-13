# Plan de ingesta RAG / LLM Wiki

## Objetivo

Construir una base documental consultable que no dependa de coincidencia exacta en la Planilla Master.

## Flujo

1. Descubrir carpetas comerciales en SharePoint:
   - Sitio comercial.
   - Carpeta `01 Ofertas`.
   - Extraer codigo `O-XXXX`.

2. Para cada oferta:
   - Navegar `03 Oferta` o `03 Propuesta`.
   - Preferir `02 Emitido`.
   - Fallback controlado a `01 En Trabajo`.
   - Listar PDFs.
   - Elegir ultima version por revision y fecha de modificacion.

3. Descargar PDF:
   - Guardar copia en `storage/proposals/O-XXXX/`.
   - Extraer primeras 5 paginas para indice rapido.
   - Extraer texto completo para RAG.

4. Extraer conocimiento estructurado:
   - Usar modelo Pydantic `ProposalKnowledge`.
   - Campos: objetivo, alcance, entregables, disciplinas, equipos/sistemas, keywords, criterios de busqueda, utilidad y limitaciones.
   - El extractor usa Azure OpenAI `gpt-5.4-mini`.

5. Persistir:
   - `proposal_knowledge`: metadata + conocimiento estructurado.
   - `rag_chunks`: chunks de texto completo con metadata para filtros.
   - `proposal_index`: indice de primeras 5 paginas.

6. Consulta:
   - Planner expande conceptos y sinonimos.
   - Master entrega candidatos estructurados.
   - RAG busca por similitud semantica/textual.
   - LLM Wiki entrega conocimiento estructurado.
   - PDFs completos se leen solo para candidatos relevantes.

## Endpoints

- `GET /api/ingestion/offers?limit=50`: descubre ofertas.
- `POST /api/ingestion/offers/O-2606`: ingesta una oferta.
- `POST /api/ingestion/batch` con `{ "limit": 10 }`: ingesta lote controlado.

## Regla importante

No lanzar ingesta total sin limite desde la UI. Primero probar lotes pequenos, revisar calidad, y luego escalar.

