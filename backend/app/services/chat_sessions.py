"""Sesiones de chat persistentes por usuario.

Cada usuario puede tener N sesiones; cada sesión guarda message history + trace + sources.
Storage: SQLite con dos tablas: chat_sessions y chat_messages.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from uuid import uuid4

from app.core.config import settings


class ChatSessionService:
    def __init__(self) -> None:
        self._ensure_tables()

    # ---- Sessions ----

    def list_sessions(self, user_id: str, limit: int = 50) -> list[dict]:
        with closing(sqlite3.connect(settings.sqlite_path, timeout=5)) as conn:
            rows = conn.execute(
                """
                select id, title, created_at, updated_at, last_message_at, message_count
                from chat_sessions
                where user_id = ?
                order by coalesce(last_message_at, updated_at) desc
                limit ?
                """,
                (user_id, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "created_at": r[2],
                "updated_at": r[3],
                "last_message_at": r[4],
                "message_count": r[5] or 0,
            }
            for r in rows
        ]

    def get_session(self, user_id: str, session_id: str) -> dict:
        with closing(sqlite3.connect(settings.sqlite_path, timeout=5)) as conn:
            row = conn.execute(
                """
                select id, title, created_at, updated_at, last_message_at, message_count, working_context
                from chat_sessions
                where user_id = ? and id = ?
                """,
                (user_id, session_id),
            ).fetchone()
        if not row:
            raise KeyError(session_id)
        return {
            "id": row[0],
            "title": row[1],
            "created_at": row[2],
            "updated_at": row[3],
            "last_message_at": row[4],
            "message_count": row[5] or 0,
            "working_context": json.loads(row[6] or "{}"),
        }

    def create_session(self, user_id: str, title: str = "Nueva conversación") -> dict:
        now = datetime.now().isoformat(timespec="seconds")
        session_id = uuid4().hex
        with closing(sqlite3.connect(settings.sqlite_path, timeout=5)) as conn, conn:
            conn.execute(
                """
                insert into chat_sessions
                (id, user_id, title, created_at, updated_at, last_message_at, message_count, working_context)
                values (?, ?, ?, ?, ?, NULL, 0, '{}')
                """,
                (session_id, user_id, title.strip()[:200], now, now),
            )
        return self.get_session(user_id, session_id)

    def rename_session(self, user_id: str, session_id: str, title: str) -> dict:
        now = datetime.now().isoformat(timespec="seconds")
        with closing(sqlite3.connect(settings.sqlite_path, timeout=5)) as conn, conn:
            n = conn.execute(
                "update chat_sessions set title = ?, updated_at = ? where user_id = ? and id = ?",
                (title.strip()[:200], now, user_id, session_id),
            ).rowcount
        if not n:
            raise KeyError(session_id)
        return self.get_session(user_id, session_id)

    def delete_session(self, user_id: str, session_id: str) -> dict:
        with closing(sqlite3.connect(settings.sqlite_path, timeout=5)) as conn, conn:
            owned = conn.execute(
                "select 1 from chat_sessions where user_id = ? and id = ?",
                (user_id, session_id),
            ).fetchone()
            if not owned:
                raise KeyError(session_id)
            conn.execute(
                "delete from chat_messages where user_id = ? and session_id = ?",
                (user_id, session_id),
            )
            n = conn.execute(
                "delete from chat_sessions where user_id = ? and id = ?",
                (user_id, session_id),
            ).rowcount
        return {"deleted": session_id, "rows": n}

    def update_working_context(self, user_id: str, session_id: str, working_context: dict) -> None:
        with closing(sqlite3.connect(settings.sqlite_path, timeout=5)) as conn, conn:
            n = conn.execute(
                "update chat_sessions set working_context = ?, updated_at = ? where user_id = ? and id = ?",
                (
                    json.dumps(working_context, ensure_ascii=False),
                    datetime.now().isoformat(timespec="seconds"),
                    user_id,
                    session_id,
                ),
            ).rowcount
        if not n:
            raise KeyError(session_id)

    # ---- Messages ----

    def list_messages(self, user_id: str, session_id: str, limit: int = 200) -> list[dict]:
        # Verifica propiedad
        self.get_session(user_id, session_id)
        with closing(sqlite3.connect(settings.sqlite_path, timeout=5)) as conn:
            rows = conn.execute(
                """
                select id, role, content, trace, sources, tables, created_at
                from chat_messages
                where user_id = ? and session_id = ?
                order by created_at asc, id asc
                limit ?
                """,
                (user_id, session_id, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "role": r[1],
                "content": r[2],
                "trace": json.loads(r[3] or "[]"),
                "sources": json.loads(r[4] or "[]"),
                "tables": json.loads(r[5] or "[]"),
                "created_at": r[6],
            }
            for r in rows
        ]

    def append_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        trace: list | None = None,
        sources: list | None = None,
        tables: list | None = None,
    ) -> dict:
        # Verificar que la sesión existe y pertenece al user
        self.get_session(user_id, session_id)
        now = datetime.now().isoformat(timespec="seconds")
        with closing(sqlite3.connect(settings.sqlite_path, timeout=5)) as conn, conn:
            cursor = conn.execute(
                """
                insert into chat_messages
                (session_id, user_id, role, content, trace, sources, tables, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    role,
                    content,
                    json.dumps(trace or [], ensure_ascii=False),
                    json.dumps(sources or [], ensure_ascii=False),
                    json.dumps(tables or [], ensure_ascii=False),
                    now,
                ),
            )
            msg_id = cursor.lastrowid
            # Auto-titular sesión con primer user message si aún es default
            if role == "user":
                row = conn.execute(
                    "select title from chat_sessions where id = ? and user_id = ?",
                    (session_id, user_id),
                ).fetchone()
                if row and row[0] in {"Nueva conversación", "Nueva conversacion"}:
                    new_title = content.strip().split("\n")[0][:80]
                    conn.execute(
                        "update chat_sessions set title = ? where id = ? and user_id = ?",
                        (new_title or "Nueva conversación", session_id, user_id),
                    )
            conn.execute(
                """
                update chat_sessions
                set last_message_at = ?, updated_at = ?, message_count = message_count + 1
                where id = ? and user_id = ?
                """,
                (now, now, session_id, user_id),
            )
        return {"id": msg_id, "session_id": session_id, "role": role, "created_at": now}

    # ---- Schema ----

    def _ensure_tables(self) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(settings.sqlite_path)) as conn, conn:
            conn.execute(
                """
                create table if not exists chat_sessions (
                    id text primary key,
                    user_id text not null,
                    title text not null,
                    created_at text not null,
                    updated_at text not null,
                    last_message_at text,
                    message_count integer default 0,
                    working_context text default '{}'
                )
                """
            )
            conn.execute(
                """
                create table if not exists chat_messages (
                    id integer primary key autoincrement,
                    session_id text not null,
                    user_id text not null,
                    role text not null,
                    content text not null,
                    trace text default '[]',
                    sources text default '[]',
                    tables text default '[]',
                    created_at text not null
                )
                """
            )
            columns = {
                str(row[1]) for row in conn.execute("pragma table_info(chat_messages)").fetchall()
            }
            if "user_id" not in columns:
                conn.execute("alter table chat_messages add column user_id text not null default ''")
            conn.execute(
                """
                update chat_messages
                set user_id = coalesce(
                    (select s.user_id from chat_sessions s where s.id = chat_messages.session_id),
                    ''
                )
                where user_id = ''
                """
            )
            conn.execute("create index if not exists idx_chat_sessions_user on chat_sessions(user_id, last_message_at)")
            conn.execute("create index if not exists idx_chat_messages_session on chat_messages(session_id, created_at)")
            conn.execute("create index if not exists idx_chat_messages_user_session on chat_messages(user_id, session_id, created_at)")
