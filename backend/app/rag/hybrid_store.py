import json
import sqlite3
import unicodedata
import asyncio

import numpy as np

from app.core.config import settings
from app.rag.parent_child import ParentChildIndexer
from app.services.embedding_service import EmbeddingService
from app.services.search_filters import SearchFilters


class HybridRagStore:
    def __init__(self) -> None:
        self.embeddings = EmbeddingService()
        self.lexical = ParentChildIndexer()
        self._ensure_tables()

    async def build(self, limit: int = 0, force: bool = False, batch_size: int = 32) -> dict:
        rows = self._pending_rows(limit=limit, force=force)
        processed = 0
        errors = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            try:
                vectors = await self.embeddings.embed_texts([row["embedding_text"] for row in batch])
                self._save_batch(batch, vectors)
                processed += len(batch)
            except Exception:
                errors += len(batch)
        return {"selected": len(rows), "processed": processed, "errors": errors, "status": self.status()}

    async def search(
        self,
        query: str,
        codes: list[str] | None = None,
        limit: int = 8,
        vector_candidates: int = 80,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        effective = filters or SearchFilters.from_codes(codes)
        if codes and not filters:
            effective = SearchFilters.from_codes(codes)
        if filters and codes and not filters.codigos:
            effective = filters.model_copy(update={"codigos": [c.upper() for c in codes]})
        query_text = (query or effective.query or "").strip()
        lexical_hits = self.lexical.search(query_text, filters=effective, limit=vector_candidates)
        candidate_ids = [hit.get("metadata", {}).get("child_id") for hit in lexical_hits if hit.get("metadata", {}).get("child_id")]
        try:
            query_embedding = await asyncio.wait_for(self.embeddings.embed_query(query_text or "consulta"), timeout=12)
            query_vector = np.asarray(query_embedding, dtype=np.float32)
            norm = np.linalg.norm(query_vector)
            if norm:
                query_vector = query_vector / norm
            vector_hits = self._vector_search(query_vector, filters=effective, limit=vector_candidates, child_ids=candidate_ids or None)
        except Exception:
            vector_hits = []
        return self._merge_hits(query_text, vector_hits, lexical_hits, limit)

    def status(self) -> dict:
        return self.fast_status()

    def fast_status(self) -> dict:
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            total = conn.execute("select count(*) from rag_child_embeddings").fetchone()[0]
            proposals = conn.execute("select count(distinct codigo) from rag_child_embeddings").fetchone()[0]
            source_children = conn.execute("select count(*) from rag_child_chunks").fetchone()[0]
            by_model = {
                f"{model}:{dim}": count
                for model, dim, count in conn.execute("select model, dim, count(*) from rag_child_embeddings group by model, dim").fetchall()
            }
            active_chunks = conn.execute("select count(*) from rag_child_embeddings where model = ?", (self.embeddings.deployment,)).fetchone()[0]
            active_proposals = conn.execute("select count(distinct codigo) from rag_child_embeddings where model = ?", (self.embeddings.deployment,)).fetchone()[0]
        return {
            "embedded_chunks": total,
            "proposal_count": proposals,
            "active_model_chunks": active_chunks,
            "active_model_proposal_count": active_proposals,
            "source_child_chunks": source_children,
            "embedding_model": self.embeddings.deployment,
            "embedding_mode": "fallback_hash" if self.embeddings.using_fallback else "azure_openai",
            "needs_embedding_deployment": self.embeddings.using_fallback,
            "by_model": by_model,
        }

    def _pending_rows(self, limit: int, force: bool) -> list[dict]:
        sql = """
            select c.child_id, c.parent_id, c.codigo, c.text, c.page_start, c.page_end, c.metadata,
                   p.title, p.text as parent_text, p.metadata as parent_metadata
            from rag_child_chunks c
            join rag_parent_sections p on p.parent_id = c.parent_id
        """
        params: list[object] = []
        if not force:
            sql += " left join rag_child_embeddings e on e.child_id = c.child_id and e.model = ? where e.child_id is null"
            params.append(self.embeddings.deployment)
        sql += " order by c.codigo, c.parent_id, c.child_id"
        if limit:
            sql += " limit ?"
            params.append(limit)
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        for row in rows:
            metadata = json.loads(row.get("metadata") or "{}")
            parent_metadata = json.loads(row.get("parent_metadata") or "{}")
            row["metadata_dict"] = metadata
            row["parent_metadata_dict"] = parent_metadata
            row["embedding_text"] = self._embedding_text(row, metadata, parent_metadata)
            row["content_hash"] = self.embeddings.content_hash(row["embedding_text"])
        return rows

    def _embedding_text(self, row: dict, metadata: dict, parent_metadata: dict) -> str:
        entities = parent_metadata.get("section_entities") or metadata.get("section_entities") or {}
        parts = [
            f"Codigo: {row['codigo']}",
            f"Titulo seccion: {row.get('title') or ''}",
            f"Documento: {metadata.get('document_title') or metadata.get('titulo') or metadata.get('archivo_nombre') or ''}",
            f"Cliente: {metadata.get('cliente') or ''} {metadata.get('cliente_final') or ''}",
            f"Estado: {metadata.get('estado') or ''} {metadata.get('estado_categoria') or ''}",
            f"Tipo servicio: {metadata.get('tipo_servicio') or ''}",
            f"Entidades: {json.dumps(entities, ensure_ascii=False)}",
            f"Texto: {row.get('text') or ''}",
        ]
        return "\n".join(parts)

    def _save_batch(self, rows: list[dict], vectors: list[list[float]]) -> None:
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            for row, vector in zip(rows, vectors):
                blob = self.embeddings.vector_to_blob(vector)
                conn.execute(
                    """
                    insert or replace into rag_child_embeddings
                    (child_id, parent_id, codigo, embedding, dim, model, content_hash)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["child_id"],
                        row["parent_id"],
                        row["codigo"],
                        blob,
                        len(vector),
                        self.embeddings.deployment,
                        row["content_hash"],
                    ),
                )

    def _vector_search(
        self,
        query_vector: np.ndarray,
        limit: int,
        filters: SearchFilters | None = None,
        child_ids: list[str] | None = None,
    ) -> list[dict]:
        sql = """
            select e.child_id, e.parent_id, e.codigo, e.embedding,
                   c.text, c.page_start, c.page_end, c.metadata,
                   p.title, p.text as parent_text, p.metadata as parent_metadata
            from rag_child_embeddings e
            join rag_child_chunks c on c.child_id = e.child_id
            join rag_parent_sections p on p.parent_id = e.parent_id
        """
        params: list = []
        clauses: list[str] = []
        if filters and filters.has_metadata_filters():
            filter_clauses, filter_params = filters.sql_clauses(table_alias="c")
            clauses.extend(filter_clauses)
            params.extend(filter_params)
            if filters.codigos:
                clauses.append("e.codigo in (" + ",".join("?" for _ in filters.codigos) + ")")
                params.extend(filters.codigos)
        if child_ids:
            placeholders = ",".join("?" for _ in child_ids)
            clauses.append(f"e.child_id in ({placeholders})")
            params.extend(child_ids)
        if clauses:
            sql += " where " + " and ".join(clauses)
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        hits = []
        for row in rows:
            vector = self.embeddings.blob_to_vector(row["embedding"])
            if vector.shape != query_vector.shape:
                continue
            score = float(np.dot(query_vector, vector))
            if score > 0:
                metadata = json.loads(row.get("metadata") or "{}")
                parent_metadata = json.loads(row.get("parent_metadata") or "{}")
                hits.append(
                    {
                        "codigo": row["codigo"],
                        "title": row["title"],
                        "url": metadata.get("url") or metadata.get("source_path"),
                        "summary": row["text"][:900],
                        "score": score,
                        "vector_score": score,
                        "lexical_score": 0.0,
                        "metadata": {
                            **parent_metadata,
                            **metadata,
                            "parent_id": row["parent_id"],
                            "child_id": row["child_id"],
                            "page_start": row["page_start"],
                            "page_end": row["page_end"],
                            "parent_preview": row["parent_text"][:1200],
                        },
                    }
                )
        hits.sort(key=lambda item: item["vector_score"], reverse=True)
        return hits[:limit]

    def _merge_hits(self, query: str, vector_hits: list[dict], lexical_hits: list[dict], limit: int) -> list[dict]:
        terms = [term for term in self._norm(query).split() if len(term) >= 3]
        merged: dict[str, dict] = {}
        for hit in vector_hits:
            key = hit["metadata"]["child_id"]
            merged[key] = {**hit, "search_modes": ["vector"]}
        for hit in lexical_hits:
            key = hit.get("metadata", {}).get("child_id")
            if not key:
                continue
            lexical_score = float(hit.get("score") or 0.0)
            if key in merged:
                merged[key]["lexical_score"] = lexical_score
                merged[key]["search_modes"].append("lexical")
                merged[key]["summary"] = hit.get("summary") or merged[key]["summary"]
            else:
                merged[key] = {**hit, "vector_score": 0.0, "lexical_score": lexical_score, "search_modes": ["lexical"]}

        for hit in merged.values():
            metadata_text = json.dumps(hit.get("metadata", {}), ensure_ascii=False)
            entity_bonus = sum(1 for term in terms if term in self._norm(metadata_text)) * 0.05
            hit["score"] = round(float(hit.get("vector_score", 0.0)) * 0.7 + min(float(hit.get("lexical_score", 0.0)), 10.0) * 0.3 + entity_bonus, 6)
            hit["metadata"]["search_modes"] = hit["search_modes"]
            hit["metadata"]["vector_score"] = hit.get("vector_score", 0.0)
            hit["metadata"]["lexical_score"] = hit.get("lexical_score", 0.0)
        hits = list(merged.values())
        hits.sort(key=lambda item: item["score"], reverse=True)
        return self._diversify(hits, limit=limit)

    def _diversify(self, hits: list[dict], limit: int, max_per_code: int = 2) -> list[dict]:
        selected = []
        counts: dict[str, int] = {}
        for hit in hits:
            code = str(hit.get("codigo") or "")
            if counts.get(code, 0) >= max_per_code:
                continue
            selected.append(hit)
            counts[code] = counts.get(code, 0) + 1
            if len(selected) >= limit:
                return selected
        return selected

    def _ensure_tables(self) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                create table if not exists rag_child_embeddings (
                    child_id text primary key,
                    parent_id text not null,
                    codigo text not null,
                    embedding blob not null,
                    dim integer not null,
                    model text not null,
                    content_hash text not null
                )
                """
            )
            conn.execute("create index if not exists idx_rag_child_embeddings_codigo on rag_child_embeddings(codigo)")
            conn.execute("create index if not exists idx_rag_child_embeddings_model on rag_child_embeddings(model)")
            conn.execute("create index if not exists idx_rag_child_embeddings_model_codigo on rag_child_embeddings(model, codigo)")

    def _norm(self, value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").lower())
        return "".join(ch for ch in text if not unicodedata.combining(ch))
