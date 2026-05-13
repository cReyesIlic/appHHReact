from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from hashlib import sha1

from app.core.config import settings
from app.services.user_context import CurrentUser, get_current_user


class PersonalMemoryService:
    def __init__(self) -> None:
        self._ensure_table()

    def list(self, user: CurrentUser | None = None, limit: int = 50) -> list[dict]:
        user = user or get_current_user()
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                select id, scope, key, value, tags, updated_at from agent_memory
                where user_id = ?
                order by updated_at desc limit ?
                """,
                (user.id, limit),
            ).fetchall()
        return [{**dict(row), "tags": json.loads(row["tags"] or "[]")} for row in rows]

    def upsert(self, key: str, value: str, scope: str = "personal", tags: list[str] | None = None, user: CurrentUser | None = None) -> dict:
        user = user or get_current_user()
        entry_id = sha1(f"{user.id}:{scope}:{key}".encode("utf-8")).hexdigest()[:18]
        now = datetime.now().isoformat(timespec="seconds")
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                insert or replace into agent_memory
                (id, user_id, scope, key, value, tags, updated_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (entry_id, user.id, scope, key, value, json.dumps(tags or [], ensure_ascii=False), now),
            )
        return {"id": entry_id, "scope": scope, "key": key, "value": value, "tags": tags or [], "updated_at": now}

    def delete(self, entry_id: str, user: CurrentUser | None = None) -> dict:
        user = user or get_current_user()
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute("delete from agent_memory where id = ? and user_id = ?", (entry_id, user.id))
        return {"deleted": entry_id}

    def summary(self, user: CurrentUser | None = None, limit: int = 8) -> str:
        rows = self.list(user=user, limit=limit)
        if not rows:
            return ""
        return "\n".join(f"- {row['key']}: {row['value']}" for row in rows)

    def _ensure_table(self) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                create table if not exists agent_memory (
                    id text primary key,
                    user_id text,
                    scope text,
                    key text,
                    value text,
                    tags text,
                    updated_at text
                )
                """
            )
