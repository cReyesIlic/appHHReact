# Hybrid RAG Embeddings

Estado actual:

- Parent-child RAG ya existe en SQLite.
- Embeddings se guardan en `rag_child_embeddings`.
- Busqueda hibrida combina:
  - vector score;
  - lexical score;
  - bonus por metadata/entidades.

Endpoints:

```http
GET /api/rag/hybrid/status
GET /api/rag/hybrid/search?q=...&codes=O-2370,O-2609&limit=8
```

Scripts:

```bash
backend/.venv/Scripts/python.exe backend/scripts/build_hybrid_rag_embeddings.py --limit 0 --batch-size 128
backend/.venv/Scripts/python.exe backend/scripts/test_hybrid_rag.py "factibilidad disposicion alternativa relaves"
```

## Importante

Si `.env` no define:

```env
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=
```

el sistema usa `local-hash-fallback`. Eso permite probar el flujo y la UI, pero no es embedding semantico real.

Para produccion:

1. Desplegar un modelo de embeddings en Azure OpenAI, por ejemplo `text-embedding-3-small` o equivalente disponible.
2. Agregar al `.env`:

```env
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=<nombre-del-deployment>
```

3. Reconstruir embeddings:

```bash
backend/.venv/Scripts/python.exe backend/scripts/build_hybrid_rag_embeddings.py --limit 0 --batch-size 32 --force
```

El `--force` es necesario porque reemplaza los vectores fallback por embeddings reales.
