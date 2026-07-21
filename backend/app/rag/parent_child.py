import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from hashlib import sha1

from app.core.config import settings
from app.services.proposal_taxonomy import extract_entities
from app.services.search_filters import SearchFilters


@dataclass
class ParentSection:
    parent_id: str
    codigo: str
    title: str
    text: str
    page_start: int | None
    page_end: int | None
    metadata: dict


@dataclass
class ChildChunk:
    child_id: str
    parent_id: str
    codigo: str
    text: str
    page_start: int | None
    page_end: int | None
    metadata: dict


class ParentChildIndexer:
    def __init__(self) -> None:
        self._ensure_tables()

    def index_parse_result(self, codigo: str, parse_result: dict, metadata: dict) -> dict:
        parents = self._markdown_sections(codigo, parse_result.get("text") or "", metadata)
        if not parents:
            parents = self._sections_from_pages(codigo, parse_result.get("pages") or [], metadata)
        if not parents:
            text = parse_result.get("text", "")
            parents = [self._parent(codigo, "Documento", text, None, None, metadata)]
        parents = self._unique_parents(parents)
        children = []
        for index, parent in enumerate(parents, start=1):
            parent.metadata.update({"section_index": index, "section_count": len(parents)})
            children.extend(self._children(parent))
        self.replace(codigo, parents, children)
        return {"codigo": codigo, "parents": len(parents), "children": len(children)}

    def index_markdown(self, codigo: str, markdown: str, metadata: dict) -> dict:
        parents = self._unique_parents(self._markdown_sections(codigo, markdown, metadata))
        children = []
        for index, parent in enumerate(parents, start=1):
            parent.metadata.update({"section_index": index, "section_count": len(parents)})
            children.extend(self._markdown_children(parent))
            if not any(child.parent_id == parent.parent_id for child in children):
                children.extend(self._children(parent))
        self.replace(codigo, parents, children)
        return {"codigo": codigo, "parents": len(parents), "children": len(children)}

    def replace(self, codigo: str, parents: list[ParentSection], children: list[ChildChunk]) -> None:
        conn = sqlite3.connect(settings.sqlite_path)
        try:
            with conn:
                # Los embeddings dependen de child_id. Eliminarlos dentro de la misma
                # transaccion evita dejar vectores huerfanos al reindexar un codigo.
                has_embeddings = conn.execute(
                    "select 1 from sqlite_master where type = 'table' and name = 'rag_child_embeddings'"
                ).fetchone()
                if has_embeddings:
                    conn.execute("delete from rag_child_embeddings where codigo = ?", (codigo,))
                conn.execute("delete from rag_child_chunks where codigo = ?", (codigo,))
                conn.execute("delete from rag_parent_sections where codigo = ?", (codigo,))
                for parent in parents:
                    conn.execute(
                        """
                        insert into rag_parent_sections (parent_id, codigo, title, text, page_start, page_end, metadata)
                        values (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            parent.parent_id,
                            parent.codigo,
                            parent.title,
                            parent.text,
                            parent.page_start,
                            parent.page_end,
                            json.dumps(parent.metadata, ensure_ascii=False),
                        ),
                    )
                for child in children:
                    conn.execute(
                        """
                        insert into rag_child_chunks (child_id, parent_id, codigo, text, page_start, page_end, metadata)
                        values (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            child.child_id,
                            child.parent_id,
                            child.codigo,
                            child.text,
                            child.page_start,
                            child.page_end,
                            json.dumps(child.metadata, ensure_ascii=False),
                        ),
                    )
        finally:
            conn.close()

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
        sql = """
            select c.child_id, c.parent_id, c.codigo, c.text, c.page_start, c.page_end, c.metadata,
                   p.title, p.text, p.metadata
            from rag_child_chunks c
            join rag_parent_sections p on p.parent_id = c.parent_id
        """
        params: list = []
        clauses: list[str] = []
        if effective.has_metadata_filters():
            filter_clauses, filter_params = effective.sql_clauses(table_alias="c")
            clauses.extend(filter_clauses)
            params.extend(filter_params)
        like_terms = terms[:6]
        if like_terms:
            clauses.append("(" + " or ".join(["c.text like ? or p.title like ? or c.metadata like ? or p.metadata like ?" for _ in like_terms]) + ")")
            for term in like_terms:
                pattern = f"%{term}%"
                params.extend([pattern, pattern, pattern, pattern])
        # Sin terms y sin filtros: nada que filtrar — devolver vacío para evitar full-scan inútil.
        if not clauses:
            return []
        if clauses:
            sql += " where " + " and ".join(clauses)
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            rows = conn.execute(sql, params).fetchall()
        hits = []
        for child_id, parent_id, codigo, child_text, page_start, page_end, child_meta, parent_title, parent_text, parent_meta in rows:
            haystack = self._norm(" ".join([child_text, parent_title, child_meta, parent_meta]))
            score = sum(1 for term in terms if term in haystack)
            # Si no hay terms pero los filtros estructurales pegan, damos base score = 1
            if not terms and effective.has_metadata_filters():
                score = 1
            if score:
                metadata = json.loads(child_meta or "{}")
                hits.append(
                    {
                        "codigo": codigo,
                        "title": parent_title,
                        "url": metadata.get("url") or metadata.get("source_path"),
                        "summary": child_text[:900],
                        "score": float(score),
                        "metadata": {
                            **metadata,
                            "parent_id": parent_id,
                            "child_id": child_id,
                            "page_start": page_start,
                            "page_end": page_end,
                            "parent_preview": parent_text[:1200],
                        },
                    }
                )
        hits.sort(key=lambda hit: hit["score"], reverse=True)
        return hits[:limit]

    def status(self) -> dict:
        with sqlite3.connect(settings.sqlite_path) as conn:
            parent_count = conn.execute("select count(*) from rag_parent_sections").fetchone()[0]
            child_count = conn.execute("select count(*) from rag_child_chunks").fetchone()[0]
            proposal_count = conn.execute("select count(distinct codigo) from rag_parent_sections").fetchone()[0]
        return {
            "proposal_count": proposal_count,
            "parent_count": parent_count,
            "child_count": child_count,
        }

    def _sections_from_pages(self, codigo: str, pages: list[dict], metadata: dict) -> list[ParentSection]:
        sections: list[ParentSection] = []
        current_title = "Portada / Resumen inicial"
        current_lines: list[str] = []
        page_start = None
        page_end = None
        for idx, page in enumerate(pages, start=1):
            page_number = page.get("pageNumber") or page.get("page") or idx
            text = page.get("text") or ""
            for line in text.splitlines():
                clean = line.strip()
                if not clean:
                    continue
                if self._looks_like_heading(clean):
                    if current_lines:
                        sections.append(self._parent(codigo, current_title, "\n".join(current_lines), page_start, page_end, metadata))
                    current_title = clean[:160]
                    current_lines = []
                    page_start = page_number
                else:
                    if page_start is None:
                        page_start = page_number
                    current_lines.append(clean)
                page_end = page_number
        if current_lines:
            sections.append(self._parent(codigo, current_title, "\n".join(current_lines), page_start, page_end, metadata))
        return [section for section in sections if len(section.text) > 80]

    def _markdown_sections(self, codigo: str, markdown: str, metadata: dict) -> list[ParentSection]:
        heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
        parents: list[ParentSection] = []
        current_title = ""
        current_lines: list[str] = []
        current_meta = dict(metadata)
        document_title = metadata.get("titulo") or metadata.get("archivo_nombre") or codigo

        for line in markdown.splitlines():
            match = heading_re.match(line.strip())
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
                if level == 1:
                    document_title = title
                    current_meta = {**current_meta, "document_title": document_title}
                    continue
                if level == 2:
                    if current_title and current_lines:
                        parents.append(self._parent(codigo, current_title, "\n".join(current_lines), None, None, current_meta))
                    current_title = title
                    current_lines = []
                    current_meta = {**metadata, "document_title": document_title, "section_level": 2, "section_title": title}
                    continue
                if level == 3 and not current_title:
                    current_title = "Detalle estructurado"
                    current_lines = [line]
                    current_meta = {**metadata, "document_title": document_title, "section_level": 2, "section_title": current_title}
                    continue
            if current_title:
                current_lines.append(line)

        if current_title and current_lines:
            parents.append(self._parent(codigo, current_title, "\n".join(current_lines), None, None, current_meta))
        return [parent for parent in parents if parent.text.strip()]

    def _markdown_children(self, parent: ParentSection) -> list[ChildChunk]:
        heading_re = re.compile(r"^(#{3,6})\s+(.+?)\s*$")
        children: list[ChildChunk] = []
        current_title = ""
        current_lines: list[str] = []
        child_index = 0

        def flush() -> None:
            nonlocal child_index
            if not current_title or not current_lines:
                return
            text = "\n".join(current_lines).strip()
            if not text:
                return
            child_index += 1
            child_id = sha1(f"{parent.parent_id}:{current_title}:{text[:100]}".encode("utf-8")).hexdigest()[:18]
            children.append(
                ChildChunk(
                    child_id=child_id,
                    parent_id=parent.parent_id,
                    codigo=parent.codigo,
                    text=text,
                    page_start=parent.page_start,
                    page_end=parent.page_end,
                    metadata={**parent.metadata, "child_index": child_index, "child_section_title": current_title, "child_section_level": 3},
                )
            )

        for line in parent.text.splitlines():
            match = heading_re.match(line.strip())
            if match:
                flush()
                current_title = match.group(2).strip()
                current_lines = []
            elif current_title:
                current_lines.append(line)
        flush()
        return children

    def _children(self, parent: ParentSection, max_chars: int = 1000, overlap: int = 150) -> list[ChildChunk]:
        chunks = []
        start = 0
        child_index = 0
        while start < len(parent.text):
            piece = parent.text[start : start + max_chars].strip()
            if piece:
                child_index += 1
                child_id = sha1(f"{parent.parent_id}:{start}:{piece[:80]}".encode("utf-8")).hexdigest()[:18]
                chunks.append(
                    ChildChunk(
                        child_id=child_id,
                        parent_id=parent.parent_id,
                        codigo=parent.codigo,
                        text=piece,
                        page_start=parent.page_start,
                        page_end=parent.page_end,
                        metadata={**parent.metadata, "child_index": child_index, "section_title": parent.title, "char_start": start},
                    )
                )
            start += max_chars - overlap
        return chunks

    def _parent(self, codigo: str, title: str, text: str, page_start: int | None, page_end: int | None, metadata: dict) -> ParentSection:
        parent_id = sha1(f"{codigo}:{title}:{page_start}:{text[:120]}".encode("utf-8")).hexdigest()[:18]
        parent_metadata = {
            **metadata,
            "section_entities": extract_entities(" ".join([title, text[:4000]])),
        }
        return ParentSection(parent_id, codigo, title, text.strip(), page_start, page_end, parent_metadata)

    def _unique_parents(self, parents: list[ParentSection]) -> list[ParentSection]:
        """Elimina duplicados exactos y desambigua colisiones de parent_id.

        El identificador historico usa los primeros 120 caracteres para mantener
        estabilidad. Ofertas con varios archivos pueden repetir titulo y prefijo;
        en ese caso conservamos el primer id y derivamos uno determinista usando
        el contenido completo de las secciones distintas.
        """
        unique: list[ParentSection] = []
        fingerprints: dict[str, str] = {}
        for parent in parents:
            fingerprint = sha1(
                f"{parent.title}:{parent.page_start}:{parent.page_end}:{parent.text}".encode("utf-8")
            ).hexdigest()
            existing = fingerprints.get(parent.parent_id)
            if existing == fingerprint:
                continue
            if existing is not None:
                base_id = parent.parent_id
                candidate = sha1(f"{base_id}:{fingerprint}".encode("utf-8")).hexdigest()[:18]
                suffix = 1
                while candidate in fingerprints and fingerprints[candidate] != fingerprint:
                    candidate = sha1(f"{base_id}:{fingerprint}:{suffix}".encode("utf-8")).hexdigest()[:18]
                    suffix += 1
                if fingerprints.get(candidate) == fingerprint:
                    continue
                parent.parent_id = candidate
            fingerprints[parent.parent_id] = fingerprint
            unique.append(parent)
        return unique

    def _looks_like_heading(self, line: str) -> bool:
        norm = self._norm(line)
        if len(line) > 110 or len(line) < 4:
            return False
        known = [
            "objetivo",
            "alcance",
            "antecedentes",
            "metodologia",
            "entregables",
            "plazo",
            "exclusiones",
            "propuesta economica",
            "oferta tecnica",
            "descripcion",
            "bases",
            "consideraciones",
        ]
        if any(term in norm for term in known):
            return True
        return bool(re.match(r"^(\d+(\.\d+)*|[A-Z])[\). -]+[A-ZÁÉÍÓÚÑ]", line))

    def _ensure_tables(self) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(settings.sqlite_path)
        try:
            with conn:
                conn.execute(
                    """
                    create table if not exists rag_parent_sections (
                        parent_id text primary key,
                        codigo text not null,
                        title text not null,
                        text text not null,
                        page_start integer,
                        page_end integer,
                        metadata text not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists rag_child_chunks (
                        child_id text primary key,
                        parent_id text not null,
                        codigo text not null,
                        text text not null,
                        page_start integer,
                        page_end integer,
                        metadata text not null
                    )
                    """
                )
        finally:
            conn.close()

    def _norm(self, value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value).lower())
        return "".join(ch for ch in text if not unicodedata.combining(ch))
