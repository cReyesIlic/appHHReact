"""Estado durable por propuesta para sincronizacion, calidad y reproceso."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.core.config import settings


PIPELINE_VERSION = "2026.07.22.1"
RAG_PIPELINE_VERSION = "parent-child-v2"
WIKI_PIPELINE_VERSION = "wiki-evidence-v3"


def compact_source_files(files: list[dict] | None) -> list[dict]:
    """Quita download URLs y deja solo metadata estable/auditable."""
    compact: list[dict] = []
    for item in files or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        kind = str(item.get("kind") or "").lower().strip()
        if not kind and "." in name:
            kind = name.lower().rsplit(".", 1)[-1]
        compact.append(
            {
                "id": str(item.get("id") or ""),
                "name": name,
                "kind": kind,
                "size": int(item.get("size") or 0),
                "last_modified": str(item.get("lastModifiedDateTime") or item.get("last_modified") or ""),
                "etag": str(item.get("eTag") or item.get("etag") or ""),
                "web_url": item.get("webUrl") or item.get("web_url"),
                "source_offer_code": item.get("sourceOfferCode") or item.get("source_offer_code"),
                "source_offer_name": item.get("sourceOfferName") or item.get("source_offer_name"),
            }
        )
    return sorted(compact, key=lambda row: (row["name"].casefold(), row["id"]))


def source_signature(files: list[dict] | None) -> str:
    payload = compact_source_files(files)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def local_source_shape(codigo: str) -> list[dict]:
    """Inventario name/size del cache previo, util para bootstrap de cambios."""
    folder = settings.resolve_path(f"storage/proposals/{codigo.upper()}")
    if not folder.exists():
        return []
    rows = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        rows.append({"name": path.name, "size": path.stat().st_size})
    return sorted(rows, key=lambda row: row["name"].casefold())


def remote_source_shape(files: list[dict] | None) -> list[dict]:
    return [
        {"name": row["name"], "size": row["size"]}
        for row in compact_source_files(files)
    ]


class PipelineRegistry:
    def __init__(self) -> None:
        self._ensure_table()

    def get(self, codigo: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "select * from proposal_pipeline_registry where codigo = ?",
                (codigo.upper(),),
            ).fetchone()
            return self._row(row) if row else None
        finally:
            conn.close()

    def by_codes(self, codigos: list[str] | set[str]) -> dict[str, dict]:
        normalized = sorted({str(code).upper() for code in codigos if code})
        if not normalized:
            return {}
        placeholders = ",".join("?" for _ in normalized)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"select * from proposal_pipeline_registry where codigo in ({placeholders})",
                normalized,
            ).fetchall()
            return {row["codigo"]: self._row(row) for row in rows}
        finally:
            conn.close()

    def list(self, limit: int = 5000) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "select * from proposal_pipeline_registry order by coalesce(last_processed_at, '') desc limit ?",
                (max(1, int(limit)),),
            ).fetchall()
            return [self._row(row) for row in rows]
        finally:
            conn.close()

    def mark_checked(self, codigo: str, files: list[dict], *, establish_baseline: bool = False) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        compact = compact_source_files(files)
        signature = source_signature(files)
        last_modified = max((row["last_modified"] for row in compact), default="")
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    insert into proposal_pipeline_registry
                        (codigo, source_signature, source_files, source_file_count, pdf_count, docx_count,
                         excel_count, source_last_modified, source_checked_at, source_synced_at,
                         pipeline_version, rag_pipeline_version, wiki_pipeline_version,
                         status, needs_reprocess, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '', 'baseline', 0, ?, ?)
                    on conflict(codigo) do update set
                        source_checked_at = excluded.source_checked_at,
                        source_signature = case when ? then excluded.source_signature else source_signature end,
                        source_files = case when ? then excluded.source_files else source_files end,
                        source_file_count = case when ? then excluded.source_file_count else source_file_count end,
                        pdf_count = case when ? then excluded.pdf_count else pdf_count end,
                        docx_count = case when ? then excluded.docx_count else docx_count end,
                        excel_count = case when ? then excluded.excel_count else excel_count end,
                        source_last_modified = case when ? then excluded.source_last_modified else source_last_modified end,
                        updated_at = excluded.updated_at
                    """,
                    (
                        codigo.upper(), signature, json.dumps(compact, ensure_ascii=False), len(compact),
                        self._count_kind(compact, {"pdf"}), self._count_kind(compact, {"docx"}),
                        self._count_kind(compact, {"xlsx", "xls", "xlsm"}), last_modified, now,
                        now if establish_baseline else None, now, now,
                        *([1 if establish_baseline else 0] * 7),
                    ),
                )
        finally:
            conn.close()

    def record_success(self, codigo: str, files: list[dict], result: dict) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        compact = compact_source_files(files)
        quality = result.get("quality") or {}
        last_modified = max((row["last_modified"] for row in compact), default="")
        status = (
            "ok"
            if result.get("wiki_status") in {"ok", "skipped"}
            and not result.get("embedding_error")
            and not result.get("file_errors")
            and not result.get("excel_errors")
            else "partial"
        )
        needs_reprocess = bool(
            result.get("wiki_status") not in {"ok", "skipped"}
            or result.get("embedding_error")
            or result.get("excel_errors")
        )
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    insert into proposal_pipeline_registry
                        (codigo, source_signature, source_files, source_file_count, pdf_count, docx_count,
                         excel_count, source_last_modified, source_checked_at, source_synced_at,
                         pipeline_version, rag_pipeline_version, wiki_pipeline_version,
                         rag_status, parent_count, child_count, embedding_count, rag_quality_score,
                         wiki_status, wiki_path, wiki_entry_id, wiki_quality_score,
                         quality_mode, quality_summary, quality_details, status, error,
                         needs_reprocess, last_processed_at, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)
                    on conflict(codigo) do update set
                        source_signature=excluded.source_signature,
                        source_files=excluded.source_files,
                        source_file_count=excluded.source_file_count,
                        pdf_count=excluded.pdf_count,
                        docx_count=excluded.docx_count,
                        excel_count=excluded.excel_count,
                        source_last_modified=excluded.source_last_modified,
                        source_checked_at=excluded.source_checked_at,
                        source_synced_at=excluded.source_synced_at,
                        pipeline_version=excluded.pipeline_version,
                        rag_pipeline_version=excluded.rag_pipeline_version,
                        wiki_pipeline_version=excluded.wiki_pipeline_version,
                        rag_status=excluded.rag_status,
                        parent_count=excluded.parent_count,
                        child_count=excluded.child_count,
                        embedding_count=excluded.embedding_count,
                        rag_quality_score=excluded.rag_quality_score,
                        wiki_status=excluded.wiki_status,
                        wiki_path=excluded.wiki_path,
                        wiki_entry_id=excluded.wiki_entry_id,
                        wiki_quality_score=excluded.wiki_quality_score,
                        quality_mode=excluded.quality_mode,
                        quality_summary=excluded.quality_summary,
                        quality_details=excluded.quality_details,
                        status=excluded.status,
                        error='',
                        needs_reprocess=excluded.needs_reprocess,
                        last_processed_at=excluded.last_processed_at,
                        updated_at=excluded.updated_at
                    """,
                    (
                        codigo.upper(), source_signature(files), json.dumps(compact, ensure_ascii=False), len(compact),
                        self._count_kind(compact, {"pdf"}), self._count_kind(compact, {"docx"}),
                        self._count_kind(compact, {"xlsx", "xls", "xlsm"}), last_modified, now, now,
                        PIPELINE_VERSION, RAG_PIPELINE_VERSION, WIKI_PIPELINE_VERSION,
                        "ok", int(result.get("chunks_parent") or 0), int(result.get("chunks_child") or 0),
                        int(result.get("embedding_count") or 0), self._score(quality.get("rag_score")),
                        str(result.get("wiki_status") or ""), str(result.get("wiki_path") or ""),
                        str(result.get("wiki_entry_id") or ""), self._score(quality.get("wiki_score")),
                        str(quality.get("mode") or "heuristic"), str(quality.get("summary") or ""),
                        json.dumps(quality, ensure_ascii=False), status, int(needs_reprocess), now, now, now,
                    ),
                )
        finally:
            conn.close()

    def record_wiki_success(self, codigo: str, result: dict) -> None:
        """Cierra un reproceso Wiki sin perder el estado RAG ya persistido."""
        now = datetime.now().isoformat(timespec="seconds")
        quality = result.get("quality") or {}
        codigo = codigo.upper()
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    insert or ignore into proposal_pipeline_registry
                        (codigo, status, needs_reprocess, created_at, updated_at)
                    values (?, 'partial', 1, ?, ?)
                    """,
                    (codigo, now, now),
                )
                current = conn.execute(
                    "select * from proposal_pipeline_registry where codigo = ?",
                    (codigo,),
                ).fetchone()
                rag_current = bool(
                    current
                    and current["rag_status"] == "ok"
                    and current["pipeline_version"] == PIPELINE_VERSION
                    and current["rag_pipeline_version"] == RAG_PIPELINE_VERSION
                )
                conn.execute(
                    """
                    update proposal_pipeline_registry set
                        wiki_pipeline_version=?, wiki_status='ok', wiki_path=?, wiki_entry_id=?,
                        rag_quality_score=coalesce(?, rag_quality_score),
                        wiki_quality_score=?, quality_mode=?, quality_summary=?, quality_details=?,
                        status=?, error=case when ? then '' else error end,
                        needs_reprocess=?, last_processed_at=?, updated_at=?
                    where codigo=?
                    """,
                    (
                        WIKI_PIPELINE_VERSION, str(result.get("path") or ""),
                        str(result.get("entry_id") or ""), self._score(quality.get("rag_score")),
                        self._score(quality.get("wiki_score")), str(quality.get("mode") or "heuristic"),
                        str(quality.get("summary") or ""), json.dumps(quality, ensure_ascii=False),
                        "ok" if rag_current else "partial", int(rag_current),
                        0 if rag_current else 1, now, now, codigo,
                    ),
                )
        finally:
            conn.close()

    def record_failure(self, codigo: str, result: dict) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    insert into proposal_pipeline_registry
                        (codigo, status, error, needs_reprocess, created_at, updated_at)
                    values (?, ?, ?, 1, ?, ?)
                    on conflict(codigo) do update set
                        status=excluded.status, error=excluded.error, needs_reprocess=1, updated_at=excluded.updated_at
                    """,
                    (
                        codigo.upper(), str(result.get("status") or "error"),
                        str(result.get("error") or result.get("note") or ""), now, now,
                    ),
                )
        finally:
            conn.close()

    def record_invalidated(self, codigo: str, error: str) -> None:
        """Registra que se retiro un indice cuya fuente pertenecia a otro codigo."""
        now = datetime.now().isoformat(timespec="seconds")
        details = json.dumps({"reason": error}, ensure_ascii=False)
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    insert or ignore into proposal_pipeline_registry
                        (codigo, created_at, updated_at)
                    values (?, ?, ?)
                    """,
                    (codigo.upper(), now, now),
                )
                conn.execute(
                    """
                    update proposal_pipeline_registry set
                        source_signature='', source_files='[]', source_file_count=0,
                        pdf_count=0, docx_count=0, excel_count=0,
                        source_last_modified=null, source_checked_at=?, source_synced_at=null,
                        pipeline_version=?, rag_pipeline_version=?, wiki_pipeline_version=?,
                        rag_status='removed_invalid_source', parent_count=0, child_count=0,
                        embedding_count=0, rag_quality_score=null,
                        wiki_status='removed_invalid_source', wiki_path='', wiki_entry_id='',
                        wiki_quality_score=null, quality_mode='', quality_summary='',
                        quality_details=?, status='invalid_source_removed', error=?,
                        needs_reprocess=1, last_processed_at=?, updated_at=?
                    where codigo=?
                    """,
                    (
                        now, PIPELINE_VERSION, RAG_PIPELINE_VERSION, WIKI_PIPELINE_VERSION,
                        details, error, now, now, codigo.upper(),
                    ),
                )
        finally:
            conn.close()

    def status(self) -> dict:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                select count(*) total,
                       sum(case when status = 'ok' then 1 else 0 end) ok,
                       sum(case when needs_reprocess = 1 or pipeline_version != ?
                                     or rag_pipeline_version != ? or wiki_pipeline_version != ?
                                then 1 else 0 end) needs_reprocess,
                       avg(rag_quality_score) avg_rag_quality,
                       avg(wiki_quality_score) avg_wiki_quality
                from proposal_pipeline_registry
                """,
                (PIPELINE_VERSION, RAG_PIPELINE_VERSION, WIKI_PIPELINE_VERSION),
            ).fetchone()
            return {
                "pipeline_version": PIPELINE_VERSION,
                "rag_pipeline_version": RAG_PIPELINE_VERSION,
                "wiki_pipeline_version": WIKI_PIPELINE_VERSION,
                "rows": int(row["total"] or 0),
                "ok": int(row["ok"] or 0),
                "needs_reprocess": int(row["needs_reprocess"] or 0),
                "avg_rag_quality": round(float(row["avg_rag_quality"] or 0), 1),
                "avg_wiki_quality": round(float(row["avg_wiki_quality"] or 0), 1),
            }
        finally:
            conn.close()

    def _ensure_table(self) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    create table if not exists proposal_pipeline_registry (
                        codigo text primary key,
                        source_signature text default '',
                        source_files text default '[]',
                        source_file_count integer default 0,
                        pdf_count integer default 0,
                        docx_count integer default 0,
                        excel_count integer default 0,
                        source_last_modified text,
                        source_checked_at text,
                        source_synced_at text,
                        pipeline_version text default '',
                        rag_pipeline_version text default '',
                        wiki_pipeline_version text default '',
                        rag_status text default '',
                        parent_count integer default 0,
                        child_count integer default 0,
                        embedding_count integer default 0,
                        rag_quality_score real,
                        wiki_status text default '',
                        wiki_path text default '',
                        wiki_entry_id text default '',
                        wiki_quality_score real,
                        quality_mode text default '',
                        quality_summary text default '',
                        quality_details text default '{}',
                        status text default '',
                        error text default '',
                        needs_reprocess integer default 0,
                        last_processed_at text,
                        created_at text not null,
                        updated_at text not null
                    )
                    """
                )
                conn.execute(
                    "create index if not exists idx_pipeline_registry_reprocess "
                    "on proposal_pipeline_registry(needs_reprocess, pipeline_version, source_checked_at)"
                )
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(settings.sqlite_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _row(self, row: sqlite3.Row) -> dict:
        data = dict(row)
        for key, fallback in (("source_files", []), ("quality_details", {})):
            try:
                data[key] = json.loads(data.get(key) or "")
            except (json.JSONDecodeError, TypeError):
                data[key] = fallback
        data["needs_reprocess"] = bool(data.get("needs_reprocess"))
        return data

    def _count_kind(self, files: list[dict], kinds: set[str]) -> int:
        return sum(1 for row in files if row.get("kind") in kinds)

    def _score(self, value: object) -> float | None:
        try:
            return max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return None
