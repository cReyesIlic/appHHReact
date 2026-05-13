import json
import sqlite3
import unicodedata
from hashlib import sha1

from app.core.config import settings
from app.services.knowledge_models import ProposalKnowledge, ProposalMetadata, RagChunk
from app.services.search_filters import SearchFilters


class RagStore:
    def __init__(self) -> None:
        self._ensure_tables()

    def upsert_proposal(self, metadata: ProposalMetadata, knowledge: ProposalKnowledge) -> None:
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                insert into proposal_knowledge (codigo, metadata, knowledge, updated_at)
                values (?, ?, ?, current_timestamp)
                on conflict(codigo) do update set
                    metadata = excluded.metadata,
                    knowledge = excluded.knowledge,
                    updated_at = current_timestamp
                """,
                (
                    metadata.codigo,
                    json.dumps(metadata.model_dump(), ensure_ascii=False),
                    json.dumps(knowledge.model_dump(), ensure_ascii=False),
                ),
            )

    def replace_chunks(self, codigo: str, chunks: list[RagChunk]) -> None:
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute("delete from rag_chunks where codigo = ?", (codigo,))
            for chunk in chunks:
                conn.execute(
                    """
                    insert into rag_chunks (codigo, chunk_id, text, source, metadata)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.codigo,
                        chunk.chunk_id,
                        chunk.text,
                        chunk.source,
                        json.dumps(chunk.metadata, ensure_ascii=False),
                    ),
                )

    def search(
        self,
        query: str,
        codes: list[str] | None = None,
        limit: int = 8,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        effective = filters or SearchFilters.from_codes(codes)
        if filters and codes and not filters.codigos:
            effective = filters.model_copy(update={"codigos": [c.upper() for c in codes]})
        terms = [term for term in self._norm(query).split() if len(term) >= 3]
        if not terms and not effective.has_metadata_filters():
            return []
        sql = "select codigo, chunk_id, text, source, metadata from rag_chunks"
        params: list = []
        clauses: list[str] = []
        if effective.has_metadata_filters():
            filter_clauses, filter_params = effective.sql_clauses(table_alias="rag_chunks")
            clauses.extend(filter_clauses)
            params.extend(filter_params)
        if clauses:
            sql += " where " + " and ".join(clauses)
        with sqlite3.connect(settings.sqlite_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        hits = []
        for codigo, chunk_id, text, source, metadata_json in rows:
            haystack = self._norm(text + " " + metadata_json)
            score = sum(1 for term in terms if term in haystack)
            if not terms and effective.has_metadata_filters():
                score = 1
            if score:
                metadata = json.loads(metadata_json or "{}")
                hits.append(
                    {
                        "codigo": codigo,
                        "title": metadata.get("titulo") or metadata.get("pdf_name") or chunk_id,
                        "url": metadata.get("url") or source,
                        "summary": text[:700],
                        "score": float(score),
                        "metadata": metadata,
                    }
                )
        hits.sort(key=lambda item: item["score"], reverse=True)
        return hits[:limit]

    def status(self) -> dict:
        with sqlite3.connect(settings.sqlite_path) as conn:
            chunk_count = conn.execute("select count(*) from rag_chunks").fetchone()[0]
            proposal_count = conn.execute("select count(distinct codigo) from rag_chunks").fetchone()[0]
            knowledge_count = conn.execute("select count(*) from proposal_knowledge").fetchone()[0]
        return {
            "proposal_count": proposal_count,
            "chunk_count": chunk_count,
            "knowledge_count": knowledge_count,
        }

    def make_chunks(self, codigo: str, text: str, source: str, metadata: dict, max_chars: int = 2200, overlap: int = 250) -> list[RagChunk]:
        clean = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        chunks: list[RagChunk] = []
        start = 0
        while start < len(clean):
            piece = clean[start : start + max_chars]
            if piece.strip():
                chunk_id = sha1(f"{codigo}:{source}:{start}:{piece[:80]}".encode("utf-8")).hexdigest()[:16]
                chunks.append(
                    RagChunk(
                        codigo=codigo,
                        chunk_id=chunk_id,
                        text=piece,
                        source=source,
                        metadata={**metadata, "char_start": start, "char_end": start + len(piece)},
                    )
                )
            start += max_chars - overlap
        return chunks

    def _ensure_tables(self) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                create table if not exists proposal_knowledge (
                    codigo text primary key,
                    metadata text not null,
                    knowledge text not null,
                    updated_at text default current_timestamp
                )
                """
            )
            conn.execute(
                """
                create table if not exists rag_chunks (
                    codigo text not null,
                    chunk_id text primary key,
                    text text not null,
                    source text not null,
                    metadata text not null
                )
                """
            )

    def _norm(self, value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value).lower())
        return "".join(ch for ch in text if not unicodedata.combining(ch))
