"""Drafts de propuestas: el usuario sube antecedentes (PDF/DOCX), el sistema extrae texto,
genera una guía .md con puntos principales y los indexa para que el agente los consuma.

Storage:
  storage/proposal_drafts/<slug>/antecedentes/*.pdf|*.docx
  storage/proposal_drafts/<slug>/texts/*.txt              (texto extraído)
  storage/proposal_drafts/<slug>/guia.md                  (resumen LLM)
  storage/proposal_drafts/<slug>/metadata.json

SQLite:
  proposal_drafts(slug, owner_id, title, cliente, status, created_at, updated_at)
  proposal_draft_files(id, slug, filename, kind, size, chars_extracted, uploaded_at)
  proposal_draft_chunks(id, slug, source_file, text, char_start)
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from io import BytesIO
from pathlib import Path

from app.core.config import settings


@dataclass
class DraftFileInfo:
    filename: str
    kind: str
    size: int
    chars_extracted: int


class ProposalDraftService:
    def __init__(self) -> None:
        self._ensure_tables()

    # ---- paths ----
    # Los archivos viven en storage/proposal_drafts/<owner_id_safe>/<slug>/...
    # Cada usuario tiene su propio espacio aislado en disco.

    def _owner_root(self, owner_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(owner_id or "anonymous"))[:80]
        return settings.resolve_path("storage/proposal_drafts") / safe

    def _draft_dir(self, owner_id: str, slug: str) -> Path:
        return self._owner_root(owner_id) / slug

    def _antecedentes_dir(self, owner_id: str, slug: str) -> Path:
        return self._draft_dir(owner_id, slug) / "antecedentes"

    def _texts_dir(self, owner_id: str, slug: str) -> Path:
        return self._draft_dir(owner_id, slug) / "texts"

    def _guia_path(self, owner_id: str, slug: str) -> Path:
        return self._draft_dir(owner_id, slug) / "guia.md"

    def _owner_for_slug(self, slug: str) -> str | None:
        """Resuelve el owner_id de un slug (consultando BD). Usar en métodos que reciben solo slug."""
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            row = conn.execute(
                "select owner_id from proposal_drafts where slug = ?", (slug,)
            ).fetchone()
        return row[0] if row else None

    # ---- CRUD ----

    def create_draft(self, owner_id: str, title: str, cliente: str | None = None) -> dict:
        slug = self._slug(title, owner_id)
        now = datetime.now().isoformat(timespec="seconds")
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            conn.execute(
                """
                insert or ignore into proposal_drafts
                (slug, owner_id, title, cliente, status, created_at, updated_at)
                values (?, ?, ?, ?, 'draft', ?, ?)
                """,
                (slug, owner_id, title.strip()[:200], (cliente or "").strip()[:120], now, now),
            )
        self._draft_dir(owner_id, slug).mkdir(parents=True, exist_ok=True)
        self._antecedentes_dir(owner_id, slug).mkdir(parents=True, exist_ok=True)
        self._texts_dir(owner_id, slug).mkdir(parents=True, exist_ok=True)
        return self.get_draft(owner_id, slug)

    def list_drafts(self, owner_id: str, limit: int = 100) -> list[dict]:
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            rows = conn.execute(
                """
                select slug, title, cliente, status, created_at, updated_at,
                       (select count(*) from proposal_draft_files f where f.slug = d.slug) as files_count
                from proposal_drafts d
                where owner_id = ?
                order by updated_at desc
                limit ?
                """,
                (owner_id, limit),
            ).fetchall()
        return [
            {
                "slug": r[0], "title": r[1], "cliente": r[2], "status": r[3],
                "created_at": r[4], "updated_at": r[5], "files_count": r[6] or 0,
            }
            for r in rows
        ]

    def get_draft(self, owner_id: str, slug: str) -> dict:
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            row = conn.execute(
                "select slug, title, cliente, status, created_at, updated_at from proposal_drafts "
                "where slug = ? and owner_id = ?",
                (slug, owner_id),
            ).fetchone()
        if not row:
            raise KeyError(slug)
        files = self.list_files(slug)
        guia = self._guia_path(owner_id, slug)
        return {
            "slug": row[0], "title": row[1], "cliente": row[2], "status": row[3],
            "created_at": row[4], "updated_at": row[5],
            "files": files,
            "guide_exists": guia.exists(),
            "guide_path": str(guia) if guia.exists() else None,
        }

    def get_guide(self, owner_id: str, slug: str) -> str:
        path = self._guia_path(owner_id, slug)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def delete_draft(self, owner_id: str, slug: str) -> dict:
        # Borrar BD primero (rápido)
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            n = conn.execute(
                "delete from proposal_drafts where slug = ? and owner_id = ?",
                (slug, owner_id),
            ).rowcount
            conn.execute("delete from proposal_draft_files where slug = ?", (slug,))
            conn.execute("delete from proposal_draft_chunks where slug = ?", (slug,))
        if not n:
            return {"deleted": False}
        # Borrar archivos en disco
        import shutil
        d = self._draft_dir(owner_id, slug)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        return {"deleted": True, "slug": slug}

    # ---- Files ----

    def list_files(self, slug: str) -> list[dict]:
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            rows = conn.execute(
                """
                select id, filename, kind, size, chars_extracted, uploaded_at
                from proposal_draft_files where slug = ? order by uploaded_at desc
                """,
                (slug,),
            ).fetchall()
        return [
            {"id": r[0], "filename": r[1], "kind": r[2], "size": r[3],
             "chars_extracted": r[4], "uploaded_at": r[5]}
            for r in rows
        ]

    def add_file(self, owner_id: str, slug: str, filename: str, content: bytes) -> dict:
        """Guarda el archivo, extrae texto, indexa en chunks."""
        # Verificar ownership
        self.get_draft(owner_id, slug)
        clean_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
        kind = self._detect_kind(clean_name)
        if kind not in {"pdf", "docx"}:
            raise ValueError("Solo se aceptan archivos PDF y DOCX")

        target = self._antecedentes_dir(owner_id, slug) / clean_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

        # Extraer texto
        text = self._extract_text(content, kind, clean_name)
        text_dir = self._texts_dir(owner_id, slug)
        text_dir.mkdir(parents=True, exist_ok=True)
        text_path = text_dir / f"{Path(clean_name).stem}.txt"
        text_path.write_text(text, encoding="utf-8")

        # Index en chunks
        chunks = self._chunkify(text, max_chars=1600, overlap=200)
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            conn.execute(
                """
                insert into proposal_draft_files (slug, filename, kind, size, chars_extracted, uploaded_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (slug, clean_name, kind, len(content), len(text), datetime.now().isoformat(timespec="seconds")),
            )
            # Reemplazar chunks de este archivo
            conn.execute(
                "delete from proposal_draft_chunks where slug = ? and source_file = ?",
                (slug, clean_name),
            )
            for idx, chunk_text in enumerate(chunks):
                conn.execute(
                    """
                    insert into proposal_draft_chunks (slug, source_file, text, char_start, chunk_index)
                    values (?, ?, ?, ?, ?)
                    """,
                    (slug, clean_name, chunk_text, idx * (1600 - 200), idx),
                )
            conn.execute(
                "update proposal_drafts set updated_at = ? where slug = ?",
                (datetime.now().isoformat(timespec="seconds"), slug),
            )

        return {
            "filename": clean_name,
            "kind": kind,
            "size": len(content),
            "chars_extracted": len(text),
            "chunks_created": len(chunks),
        }

    def file_path(self, owner_id: str, slug: str, filename: str) -> Path:
        return self._antecedentes_dir(owner_id, slug) / re.sub(r"[^A-Za-z0-9._-]+", "_", filename)

    # ---- Search dentro del draft ----

    def search_chunks(self, slug: str, query: str, limit: int = 8) -> list[dict]:
        terms = [self._norm(t) for t in (query or "").split() if len(t) >= 3]
        if not terms:
            return []
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            rows = conn.execute(
                "select id, source_file, text, char_start from proposal_draft_chunks where slug = ?",
                (slug,),
            ).fetchall()
        hits: list[dict] = []
        for cid, source, text, char_start in rows:
            haystack = self._norm(text)
            score = sum(1 for t in terms if t in haystack)
            if score:
                hits.append({
                    "id": cid, "source_file": source,
                    "char_start": char_start,
                    "snippet": text[:800], "score": float(score),
                })
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:limit]

    def all_text(self, slug: str, max_chars: int = 80000) -> str:
        """Texto completo concatenado (truncado) para enviar al LLM."""
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            rows = conn.execute(
                """
                select source_file, text from proposal_draft_chunks
                where slug = ? order by source_file, chunk_index
                """,
                (slug,),
            ).fetchall()
        parts: list[str] = []
        current = ""
        total = 0
        for source, text in rows:
            if source != current:
                parts.append(f"\n\n## Fuente: {source}\n")
                current = source
            parts.append(text)
            total += len(text)
            if total >= max_chars:
                parts.append("\n\n[...truncado...]")
                break
        return "".join(parts)

    def save_guide(self, owner_id: str, slug: str, markdown: str) -> Path:
        path = self._guia_path(owner_id, slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            conn.execute(
                "update proposal_drafts set status = 'guided', updated_at = ? where slug = ? and owner_id = ?",
                (datetime.now().isoformat(timespec="seconds"), slug, owner_id),
            )
        return path

    # ---- Internals ----

    def _detect_kind(self, filename: str) -> str:
        lower = filename.lower()
        if lower.endswith(".pdf"):
            return "pdf"
        if lower.endswith(".docx"):
            return "docx"
        return "unknown"

    def _extract_text(self, content: bytes, kind: str, filename: str) -> str:
        try:
            if kind == "pdf":
                from PyPDF2 import PdfReader
                reader = PdfReader(BytesIO(content))
                pages = []
                for idx, page in enumerate(reader.pages, start=1):
                    try:
                        pages.append(f"[página {idx}]\n{page.extract_text() or ''}")
                    except Exception:
                        continue
                return "\n\n".join(pages)
            if kind == "docx":
                from docx import Document
                doc = Document(BytesIO(content))
                blocks = []
                for para in doc.paragraphs:
                    text = (para.text or "").strip()
                    if text:
                        blocks.append(text)
                for table in doc.tables:
                    for row in table.rows:
                        cells = [c.text.strip() for c in row.cells if c.text.strip()]
                        if cells:
                            blocks.append(" | ".join(cells))
                return "\n".join(blocks)
        except Exception as exc:
            return f"[error extrayendo {filename}: {exc}]"
        return ""

    def _chunkify(self, text: str, max_chars: int = 1600, overlap: int = 200) -> list[str]:
        if not text:
            return []
        chunks = []
        start = 0
        while start < len(text):
            piece = text[start:start + max_chars].strip()
            if piece:
                chunks.append(piece)
            start += max_chars - overlap
            if start >= len(text):
                break
        return chunks[:200]  # safety cap

    def _slug(self, title: str, owner_id: str) -> str:
        base = re.sub(r"[^a-z0-9-]+", "-", self._norm(title)).strip("-")[:50] or "draft"
        suffix = sha1(f"{owner_id}:{title}:{datetime.now().isoformat()}".encode()).hexdigest()[:6]
        return f"{base}-{suffix}"

    def _norm(self, value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").lower())
        return "".join(ch for ch in text if not unicodedata.combining(ch))

    def _ensure_tables(self) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                create table if not exists proposal_drafts (
                    slug text primary key,
                    owner_id text not null,
                    title text not null,
                    cliente text,
                    status text default 'draft',
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists proposal_draft_files (
                    id integer primary key autoincrement,
                    slug text not null,
                    filename text not null,
                    kind text not null,
                    size integer not null,
                    chars_extracted integer default 0,
                    uploaded_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists proposal_draft_chunks (
                    id integer primary key autoincrement,
                    slug text not null,
                    source_file text not null,
                    text text not null,
                    char_start integer,
                    chunk_index integer
                )
                """
            )
            conn.execute("create index if not exists idx_drafts_owner on proposal_drafts(owner_id, updated_at)")
            conn.execute("create index if not exists idx_draft_files_slug on proposal_draft_files(slug)")
            conn.execute("create index if not exists idx_draft_chunks_slug on proposal_draft_chunks(slug, source_file)")
