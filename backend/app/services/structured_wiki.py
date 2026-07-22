import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime
from hashlib import sha1
from pathlib import Path

from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas import WikiSection


class WikiDocument(BaseModel):
    title: str = "LLM Wiki"
    sections: list[WikiSection] = Field(default_factory=list)


class StructuredWikiService:
    # Cache de proceso: evita re-sincronizar 646 .md en cada llamada a list_entries/get_entry.
    # Se invalida al hacer upsert_entry/delete_entry (vuelve a sincronizar tras esos cambios).
    _sync_done: bool = False

    def __init__(self) -> None:
        self._ensure_table()

    @classmethod
    def invalidate_sync_cache(cls) -> None:
        cls._sync_done = False

    @property
    def wiki_path(self) -> Path:
        return settings.resolve_path("storage/llm_wiki.md")

    @property
    def entries_dir(self) -> Path:
        return settings.resolve_path("storage/llm_wiki/entries")

    def build(self, markdown: str) -> dict:
        document = self.parse(markdown)
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn, conn:
            conn.execute("delete from wiki_sections")
            for section in document.sections:
                conn.execute(
                    """
                    insert or replace into wiki_sections (id, title, level, path, content, keywords)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        section.id,
                        section.title,
                        section.level,
                        json.dumps(section.path, ensure_ascii=False),
                        section.content,
                        json.dumps(section.keywords, ensure_ascii=False),
                    ),
                )
        wiki_path = settings.resolve_path("storage/llm_wiki.md")
        wiki_path.parent.mkdir(parents=True, exist_ok=True)
        wiki_path.write_text(markdown, encoding="utf-8")
        return {"title": document.title, "sections": len(document.sections)}

    def markdown(self) -> dict:
        path = self.wiki_path
        return {"markdown": path.read_text(encoding="utf-8") if path.exists() else "# LLM Wiki SHIMIN\n", "path": str(path)}

    _ENTRY_COLUMNS = (
        "id, title, category, tags, content, source, pinned, file_path, created_at, updated_at, "
        "propuestas_referenciadas, filtros_aplicables, times_used, validated_at, validation_status"
    )

    _ENTRY_SUMMARY_COLUMNS = (
        "id, title, category, tags, source, pinned, created_at, updated_at, "
        "propuestas_referenciadas, filtros_aplicables, times_used, validated_at, "
        "validation_status, length(coalesce(content, ''))"
    )

    def list_entry_summaries(
        self,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Lista metadata paginada; el Markdown se obtiene solo con get_entry()."""
        self._sync_entries_from_files()
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        term = str(query or "").strip()
        where = ""
        params: list[object] = []
        if term:
            where = (
                "where title like ? collate nocase or category like ? collate nocase "
                "or tags like ? collate nocase or propuestas_referenciadas like ? collate nocase "
                "or source like ? collate nocase"
            )
            like = f"%{term}%"
            params = [like] * 5
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn:
            total = int(
                conn.execute(f"select count(*) from wiki_entries {where}", params).fetchone()[0]
            )
            rows = conn.execute(
                f"""
                select {self._ENTRY_SUMMARY_COLUMNS}
                from wiki_entries
                {where}
                order by pinned desc, updated_at desc, title
                limit ? offset ?
                """,
                (*params, limit, offset),
            ).fetchall()
        entries = [self._entry_summary_row(row) for row in rows]
        return {
            "entries": entries,
            "count": len(entries),
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(entries) < total,
        }

    def list_entries(self) -> list[dict]:
        self._sync_entries_from_files()
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn:
            rows = conn.execute(
                f"""
                select {self._ENTRY_COLUMNS}
                from wiki_entries
                order by pinned desc, updated_at desc, title
                """
            ).fetchall()
        return [self._entry_row(row) for row in rows]

    def get_entry(self, entry_id: str) -> dict:
        self._sync_entries_from_files()
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn:
            row = conn.execute(
                f"select {self._ENTRY_COLUMNS} from wiki_entries where id = ?",
                (entry_id,),
            ).fetchone()
        if not row:
            raise KeyError(entry_id)
        return self._entry_row(row)

    def upsert_entry(
        self,
        title: str,
        content: str,
        category: str = "general",
        tags: list[str] | None = None,
        pinned: bool = False,
        source: str | None = None,
        entry_id: str | None = None,
        propuestas_referenciadas: list[str] | None = None,
        filtros_aplicables: dict | None = None,
        skip_reindex: bool = False,
    ) -> dict:
        now = datetime.now().isoformat(timespec="seconds")
        clean_title = title.strip()
        entry_id = entry_id or sha1(f"{category}:{clean_title}".encode("utf-8")).hexdigest()[:12]
        tags = [str(tag).strip() for tag in tags or [] if str(tag).strip()]
        propuestas_norm = [str(c).strip().upper() for c in propuestas_referenciadas or [] if str(c).strip()]
        filtros_norm = filtros_aplicables or {}
        existing = None
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn:
            existing = conn.execute(
                "select created_at, propuestas_referenciadas, filtros_aplicables, times_used, file_path "
                "from wiki_entries where id = ?",
                (entry_id,),
            ).fetchone()
        created_at = existing[0] if existing else now
        self.entries_dir.mkdir(parents=True, exist_ok=True)
        file_path = (
            Path(existing[4])
            if existing and len(existing) > 4 and existing[4]
            else self.entries_dir / f"{self._slug(clean_title)}-{entry_id}.md"
        )
        file_path.write_text(
            self._entry_markdown(
                {
                    "id": entry_id,
                    "title": clean_title,
                    "category": category.strip() or "general",
                    "tags": tags,
                    "source": source or "",
                    "pinned": bool(pinned),
                    "created_at": created_at,
                    "updated_at": now,
                    "content": content.strip(),
                    "propuestas_referenciadas": propuestas_norm,
                    "filtros_aplicables": filtros_norm,
                }
            ),
            encoding="utf-8",
        )
        prev_times_used = int(existing[3]) if existing and len(existing) > 3 and existing[3] is not None else 0
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn, conn:
            conn.execute(
                """
                insert or replace into wiki_entries
                (id, title, category, tags, content, source, pinned, file_path, created_at, updated_at,
                 propuestas_referenciadas, filtros_aplicables, times_used, validated_at, validation_status)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    clean_title,
                    category.strip() or "general",
                    json.dumps(tags, ensure_ascii=False),
                    content.strip(),
                    source or "",
                    1 if pinned else 0,
                    str(file_path),
                    created_at,
                    now,
                    json.dumps(propuestas_norm, ensure_ascii=False),
                    json.dumps(filtros_norm, ensure_ascii=False),
                    prev_times_used,
                    None,
                    "unchecked",
                ),
            )
        if skip_reindex:
            # Path rápido para backfill masivo. No reindexa wiki_sections ni re-sync .md.
            return {
                "id": entry_id,
                "title": clean_title,
                "category": category.strip() or "general",
                "tags": tags,
                "content": content.strip(),
                "source": source or "",
                "pinned": bool(pinned),
                "file_path": str(file_path),
                "created_at": created_at,
                "updated_at": now,
                "propuestas_referenciadas": propuestas_norm,
                "filtros_aplicables": filtros_norm,
                "times_used": prev_times_used,
                "validated_at": None,
                "validation_status": "unchecked",
            }
        self.reindex_entries()
        return self.get_entry(entry_id)

    def delete_entry(self, entry_id: str) -> dict:
        entry = self.get_entry(entry_id)
        path = Path(entry.get("file_path") or "")
        if path.exists() and path.is_file():
            path.unlink()
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn, conn:
            conn.execute("delete from wiki_entries where id = ?", (entry_id,))
        self.reindex_entries()
        return {"deleted": entry_id}

    def remove_duplicate_proposal_entries(
        self,
        codigo: str,
        keep_entry_id: str,
        *,
        protected_paths: list[Path] | None = None,
    ) -> dict:
        """Retira autocompilados duplicados sin borrar la página canónica protegida."""
        codigo = codigo.strip().upper()
        protected = {
            Path(path).resolve(strict=False)
            for path in protected_paths or []
        }
        entries_root = self.entries_dir.resolve(strict=False)
        removed_ids: list[str] = []
        removed_files: list[str] = []
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn, conn:
            rows = conn.execute(
                """
                select id, file_path, propuestas_referenciadas
                from wiki_entries
                where source = 'rag_autocompile' and id != ?
                """,
                (keep_entry_id,),
            ).fetchall()
            for entry_id, file_path, refs_raw in rows:
                try:
                    refs = [str(value).strip().upper() for value in json.loads(refs_raw or "[]")]
                except (json.JSONDecodeError, TypeError):
                    refs = []
                if codigo not in refs:
                    continue
                path = Path(file_path or "").resolve(strict=False) if file_path else None
                if path and path not in protected and path.is_relative_to(entries_root) and path.is_file():
                    path.unlink()
                    removed_files.append(str(path))
                conn.execute("delete from wiki_entries where id = ?", (entry_id,))
                removed_ids.append(str(entry_id))
        return {"removed": len(removed_ids), "entry_ids": removed_ids, "files": removed_files}

    def reindex_entries(self) -> dict:
        self._sync_entries_from_files()
        entries = self.list_entries()
        if not entries:
            return self.build(self.markdown()["markdown"])
        lines = ["# LLM Wiki SHIMIN", "", "## Accesos rapidos", ""]
        for entry in entries:
            if entry.get("pinned"):
                lines.append(f"- [[{entry['title']}]] ({entry['category']})")
        lines.extend(["", "## Entradas", ""])
        for entry in entries:
            tags = ", ".join(entry.get("tags") or [])
            lines.extend(
                [
                    f"### {entry['title']}",
                    f"- Categoria: {entry['category']}",
                    f"- Tags: {tags}",
                    f"- Fuente: {entry.get('source') or 'manual'}",
                    "",
                    self._demote_headings(entry.get("content") or "", levels=2),
                    "",
                ]
            )
        return self.build("\n".join(lines))

    def quick_access(self) -> dict:
        self._sync_entries_from_files()
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn:
            pinned_rows = conn.execute(
                f"select {self._ENTRY_SUMMARY_COLUMNS} from wiki_entries "
                "where pinned = 1 order by updated_at desc limit 12"
            ).fetchall()
            recent_rows = conn.execute(
                f"select {self._ENTRY_SUMMARY_COLUMNS} from wiki_entries "
                "order by updated_at desc limit 10"
            ).fetchall()
            categories = conn.execute(
                "select category, count(*) from wiki_entries group by category order by category"
            ).fetchall()
        return {
            "pinned": [self._entry_summary_row(row) for row in pinned_rows],
            "categories": [{"category": row[0], "count": int(row[1])} for row in categories],
            "recent": [self._entry_summary_row(row) for row in recent_rows],
        }

    def append_proposal_knowledge(self, codigo: str, title: str, markdown: str) -> dict:
        wiki_path = settings.resolve_path("storage/llm_wiki.md")
        existing = wiki_path.read_text(encoding="utf-8") if wiki_path.exists() else "# LLM Wiki SHIMIN\n"
        marker = f"<!-- proposal:{codigo} -->"
        block = f"\n\n{marker}\n## {codigo} - {title}\n\n{markdown.strip()}\n"
        if marker in existing:
            before, _, rest = existing.partition(marker)
            next_marker = rest.find("\n\n<!-- proposal:")
            if next_marker >= 0:
                existing = before + block + rest[next_marker:]
            else:
                existing = before + block
        else:
            existing += block
        return self.build(existing)

    def parse(self, markdown: str) -> WikiDocument:
        heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
        sections: list[WikiSection] = []
        current: dict | None = None
        stack: list[tuple[int, str]] = []
        title = "LLM Wiki"

        for line in markdown.splitlines():
            match = heading_re.match(line)
            if match:
                if current:
                    sections.append(self._section(current))
                level = len(match.group(1))
                heading = match.group(2).strip()
                if not sections and current is None:
                    title = heading
                stack = [(lvl, name) for lvl, name in stack if lvl < level]
                stack.append((level, heading))
                current = {"title": heading, "level": level, "path": [name for _, name in stack], "lines": []}
            elif current:
                current["lines"].append(line)

        if current:
            sections.append(self._section(current))
        return WikiDocument(title=title, sections=sections)

    def list_sections(self) -> list[dict]:
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn:
            rows = conn.execute("select id, title, level, path, content, keywords from wiki_sections order by rowid").fetchall()
        return [self._row(row).model_dump() for row in rows]

    def search(self, query: str, mode: str = "content", limit: int = 8) -> list[dict]:
        terms = [self._norm(term) for term in query.split() if len(term) >= 2]
        if not terms:
            return []
        rows = self.list_sections()
        ranked = []
        for row in rows:
            if mode == "title":
                haystack = self._norm(" ".join([row["title"], " ".join(row["path"])]))
            else:
                haystack = self._norm(" ".join([row["title"], row["content"], " ".join(row["keywords"])]))
            score = sum(3 if term in self._norm(row["title"]) else 1 for term in terms if term in haystack)
            if score:
                ranked.append({**row, "score": float(score)})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:limit]

    def answer(self, query: str) -> dict:
        hits = self.search(query, mode="content", limit=5)
        if not hits:
            return {"answer": "No encontre secciones relacionadas en el LLM Wiki.", "hits": []}
        lines = ["Secciones relevantes del LLM Wiki:"]
        for hit in hits:
            path = " > ".join(hit["path"])
            snippet = " ".join(hit["content"].split())[:320]
            lines.append(f"- {path}: {snippet}")
        return {"answer": "\n".join(lines), "hits": hits}

    def search_entries(
        self,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        codigos: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Búsqueda sobre las entradas de la biblioteca curada.

        - `query`: texto libre (matchea title, content, tags y propuestas_referenciadas).
        - `category`: filtro exacto.
        - `tags`: cualquier coincidencia.
        - `codigos`: entradas que referencian esos códigos.
        """
        entries = self.list_entries()
        terms = [self._norm(t) for t in (query or "").split() if len(t) >= 2]
        tags_norm = [self._norm(t) for t in tags or []]
        codigos_norm = [c.strip().upper() for c in codigos or [] if c.strip()]

        ranked: list[dict] = []
        for entry in entries:
            if category and self._norm(entry.get("category")) != self._norm(category):
                continue
            entry_tags = [self._norm(t) for t in entry.get("tags") or []]
            if tags_norm and not any(tag in entry_tags for tag in tags_norm):
                continue
            entry_propuestas = [str(c).upper() for c in entry.get("propuestas_referenciadas") or []]
            if codigos_norm and not any(code in entry_propuestas for code in codigos_norm):
                continue
            haystack = self._norm(
                " ".join(
                    [
                        entry.get("title", ""),
                        entry.get("content", ""),
                        " ".join(entry.get("tags") or []),
                        " ".join(entry.get("propuestas_referenciadas") or []),
                        entry.get("category", ""),
                    ]
                )
            )
            score = 0.0
            for term in terms:
                if term in self._norm(entry.get("title", "")):
                    score += 3
                elif term in haystack:
                    score += 1
            if not terms and (category or tags_norm or codigos_norm):
                score = 1.0
            if score > 0:
                ranked.append({**entry, "score": float(score)})
        ranked.sort(key=lambda e: (-(e["score"]), -int(e.get("pinned", False)), -int(e.get("times_used", 0))))
        return ranked[:limit]

    def bump_usage(self, entry_id: str) -> dict:
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn, conn:
            conn.execute(
                "update wiki_entries set times_used = coalesce(times_used, 0) + 1 where id = ?",
                (entry_id,),
            )
        return {"entry_id": entry_id, "bumped": True}

    def validate_proposals(self, entry_id: str, master_codigos: list[str]) -> dict:
        """Valida los códigos referenciados de una entrada contra el listado activo del master.

        `master_codigos` debe traer todos los códigos válidos (uppercased).
        Marca `validation_status` = 'ok' / 'partial' / 'broken'.
        """
        entry = self.get_entry(entry_id)
        refs = [str(c).upper() for c in entry.get("propuestas_referenciadas") or []]
        valid_set = {str(c).upper() for c in master_codigos}
        existing = [c for c in refs if c in valid_set]
        missing = [c for c in refs if c not in valid_set]
        status = "ok" if not refs or not missing else ("partial" if existing else "broken")
        now = datetime.now().isoformat(timespec="seconds")
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn, conn:
            conn.execute(
                "update wiki_entries set validated_at = ?, validation_status = ? where id = ?",
                (now, status, entry_id),
            )
        return {
            "entry_id": entry_id,
            "validated_at": now,
            "status": status,
            "existing": existing,
            "missing": missing,
        }

    def status(self) -> dict:
        sections = self.list_sections()
        self._sync_entries_from_files()
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn:
            entries, pinned = conn.execute(
                "select count(*), coalesce(sum(case when pinned = 1 then 1 else 0 end), 0) "
                "from wiki_entries"
            ).fetchone()
        wiki_path = settings.resolve_path("storage/llm_wiki.md")
        proposal_pages = list(settings.resolve_path("storage/llm_wiki/proposals").glob("O-*.md"))
        return {
            "sections": len(sections),
            "entries": int(entries),
            "pinned": int(pinned),
            "proposal_pages": len(proposal_pages),
            "has_markdown": wiki_path.exists(),
            "path": str(wiki_path),
        }

    def _section(self, raw: dict) -> WikiSection:
        content = "\n".join(raw["lines"]).strip()
        title = raw["title"]
        section_id = sha1((">".join(raw["path"]) + content[:200]).encode("utf-8")).hexdigest()[:12]
        return WikiSection(
            id=section_id,
            title=title,
            level=raw["level"],
            path=raw["path"],
            content=content,
            keywords=self._keywords(title + " " + content),
        )

    def _row(self, row: tuple) -> WikiSection:
        return WikiSection(
            id=row[0],
            title=row[1],
            level=row[2],
            path=json.loads(row[3] or "[]"),
            content=row[4] or "",
            keywords=json.loads(row[5] or "[]"),
        )

    def _ensure_table(self) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn, conn:
            conn.execute(
                """
                create table if not exists wiki_sections (
                    id text primary key,
                    title text not null,
                    level integer not null,
                    path text not null,
                    content text,
                    keywords text
                )
                """
            )
            conn.execute(
                """
                create table if not exists wiki_entries (
                    id text primary key,
                    title text not null,
                    category text not null,
                    tags text not null,
                    content text,
                    source text,
                    pinned integer default 0,
                    file_path text,
                    created_at text,
                    updated_at text
                )
                """
            )
            # Migración: columnas nuevas para librería curada
            existing_cols = {row[1] for row in conn.execute("pragma table_info(wiki_entries)").fetchall()}
            if "propuestas_referenciadas" not in existing_cols:
                conn.execute("alter table wiki_entries add column propuestas_referenciadas text default '[]'")
            if "filtros_aplicables" not in existing_cols:
                conn.execute("alter table wiki_entries add column filtros_aplicables text default '{}'")
            if "times_used" not in existing_cols:
                conn.execute("alter table wiki_entries add column times_used integer default 0")
            if "validated_at" not in existing_cols:
                conn.execute("alter table wiki_entries add column validated_at text")
            if "validation_status" not in existing_cols:
                conn.execute("alter table wiki_entries add column validation_status text default 'unchecked'")

    def _keywords(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9-]{3,}", self._norm(text))
        stop = {"para", "con", "del", "las", "los", "una", "que", "como", "por", "este", "esta"}
        return list(dict.fromkeys(token for token in tokens if token not in stop))[:12]

    def _norm(self, value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value).lower())
        return "".join(ch for ch in text if not unicodedata.combining(ch))

    def _entry_row(self, row: tuple) -> dict:
        try:
            propuestas = json.loads(row[10] or "[]") if len(row) > 10 else []
        except (json.JSONDecodeError, TypeError):
            propuestas = []
        try:
            filtros = json.loads(row[11] or "{}") if len(row) > 11 else {}
        except (json.JSONDecodeError, TypeError):
            filtros = {}
        return {
            "id": row[0],
            "title": row[1],
            "category": row[2],
            "tags": json.loads(row[3] or "[]"),
            "content": row[4] or "",
            "source": row[5] or "",
            "pinned": bool(row[6]),
            "file_path": row[7] or "",
            "created_at": row[8] or "",
            "updated_at": row[9] or "",
            "propuestas_referenciadas": propuestas,
            "filtros_aplicables": filtros,
            "times_used": int(row[12] or 0) if len(row) > 12 else 0,
            "validated_at": (row[13] if len(row) > 13 else None) or None,
            "validation_status": (row[14] if len(row) > 14 else "unchecked") or "unchecked",
        }

    def _entry_summary_row(self, row: tuple) -> dict:
        try:
            tags = json.loads(row[3] or "[]")
        except (json.JSONDecodeError, TypeError):
            tags = []
        try:
            propuestas = json.loads(row[8] or "[]")
        except (json.JSONDecodeError, TypeError):
            propuestas = []
        try:
            filtros = json.loads(row[9] or "{}")
        except (json.JSONDecodeError, TypeError):
            filtros = {}
        return {
            "id": row[0],
            "title": row[1],
            "category": row[2],
            "tags": tags,
            "source": row[4] or "",
            "pinned": bool(row[5]),
            "created_at": row[6] or "",
            "updated_at": row[7] or "",
            "propuestas_referenciadas": propuestas,
            "filtros_aplicables": filtros,
            "times_used": int(row[10] or 0),
            "validated_at": row[11] or None,
            "validation_status": row[12] or "unchecked",
            "content_chars": int(row[13] or 0),
        }

    def _entry_markdown(self, entry: dict) -> str:
        return "\n".join(
            [
                "---",
                f"id: {entry['id']}",
                f"title: {entry['title']}",
                f"category: {entry['category']}",
                f"tags: {json.dumps(entry['tags'], ensure_ascii=False)}",
                f"source: {entry['source']}",
                f"pinned: {str(entry['pinned']).lower()}",
                f"created_at: {entry['created_at']}",
                f"updated_at: {entry['updated_at']}",
                f"propuestas_referenciadas: {json.dumps(entry.get('propuestas_referenciadas') or [], ensure_ascii=False)}",
                f"filtros_aplicables: {json.dumps(entry.get('filtros_aplicables') or {}, ensure_ascii=False)}",
                "---",
                "",
                entry["content"],
                "",
            ]
        )

    def _sync_entries_from_files(self) -> None:
        # Run-once por proceso: re-leer cientos de .md en cada list_entries() es ineficiente.
        if StructuredWikiService._sync_done:
            return
        if not self.entries_dir.exists():
            StructuredWikiService._sync_done = True
            return
        # Si la BD ya tiene entries, no re-sincronizar al arrancar (evita lock con 800+ archivos).
        # El sync solo corre si la BD está vacía (caso primer arranque tras reset).
        try:
            with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn:
                count = conn.execute("select count(*) from wiki_entries").fetchone()[0]
            if count > 0:
                StructuredWikiService._sync_done = True
                return
        except Exception:
            pass
        for path in self.entries_dir.glob("*.md"):
            parsed = self._parse_entry_file(path)
            if not parsed:
                continue
            with closing(sqlite3.connect(settings.sqlite_path, timeout=30)) as conn, conn:
                # Conservar times_used / validated_at si la entrada ya existía
                existing = conn.execute(
                    "select times_used, validated_at, validation_status from wiki_entries where id = ?",
                    (parsed["id"],),
                ).fetchone()
                times_used = int(existing[0]) if existing and existing[0] is not None else 0
                validated_at = existing[1] if existing else None
                validation_status = (existing[2] if existing else None) or "unchecked"
                conn.execute(
                    """
                    insert or replace into wiki_entries
                    (id, title, category, tags, content, source, pinned, file_path, created_at, updated_at,
                     propuestas_referenciadas, filtros_aplicables, times_used, validated_at, validation_status)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        parsed["id"],
                        parsed["title"],
                        parsed["category"],
                        json.dumps(parsed["tags"], ensure_ascii=False),
                        parsed["content"],
                        parsed["source"],
                        1 if parsed["pinned"] else 0,
                        str(path),
                        parsed["created_at"],
                        parsed["updated_at"],
                        json.dumps(parsed.get("propuestas_referenciadas") or [], ensure_ascii=False),
                        json.dumps(parsed.get("filtros_aplicables") or {}, ensure_ascii=False),
                        times_used,
                        validated_at,
                        validation_status,
                    ),
                )
        StructuredWikiService._sync_done = True

    def _parse_entry_file(self, path: Path) -> dict | None:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        _, _, rest = text.partition("---")
        frontmatter, _, content = rest.partition("---")
        meta: dict[str, str] = {}
        for line in frontmatter.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
        tags = []
        try:
            tags = json.loads(meta.get("tags", "[]"))
        except json.JSONDecodeError:
            tags = [tag.strip() for tag in meta.get("tags", "").split(",") if tag.strip()]
        propuestas: list[str] = []
        try:
            propuestas = json.loads(meta.get("propuestas_referenciadas", "[]"))
        except json.JSONDecodeError:
            propuestas = [p.strip().upper() for p in meta.get("propuestas_referenciadas", "").split(",") if p.strip()]
        filtros: dict = {}
        try:
            filtros = json.loads(meta.get("filtros_aplicables", "{}")) or {}
        except json.JSONDecodeError:
            filtros = {}
        title = meta.get("title") or path.stem
        return {
            "id": meta.get("id") or sha1(str(path).encode("utf-8")).hexdigest()[:12],
            "title": title,
            "category": meta.get("category") or "general",
            "tags": tags,
            "source": meta.get("source") or "",
            "pinned": meta.get("pinned", "false").lower() == "true",
            "created_at": meta.get("created_at") or "",
            "updated_at": meta.get("updated_at") or "",
            "content": content.strip(),
            "propuestas_referenciadas": [str(p).strip().upper() for p in propuestas if str(p).strip()],
            "filtros_aplicables": filtros,
        }

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", self._norm(value)).strip("-")
        return (slug or "entry")[:70]

    def _demote_headings(self, markdown: str, levels: int = 1) -> str:
        lines = []
        for line in markdown.splitlines():
            match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if not match:
                lines.append(line)
                continue
            level = min(6, len(match.group(1)) + levels)
            lines.append("#" * level + " " + match.group(2))
        return "\n".join(lines)
