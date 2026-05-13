import json
import sqlite3
from datetime import datetime
from hashlib import sha1
from typing import Any

from app.core.config import settings
from app.services.user_context import CurrentUser, get_current_user


DEFAULT_MONTHLY_CREDITS = 500.0
USD_PER_CREDIT = 0.01


MODEL_PRICES_USD_PER_1M = {
    "gpt-5.4": {"input": 2.50, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
    "gpt-5.4-nano": {"input": 0.20, "output": 1.25},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}


class CreditService:
    def __init__(self) -> None:
        self._ensure_tables()

    def ensure_user(self, user: CurrentUser | None = None) -> CurrentUser:
        user = user or get_current_user()
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                insert or ignore into users (id, email, name, role, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (user.id, user.email, user.name, user.role, datetime.now().isoformat(timespec="seconds")),
            )
        return user

    def ensure_wallet(self, user: CurrentUser | None = None, period: str | None = None) -> None:
        user = self.ensure_user(user)
        period = period or self.current_period()
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                insert or ignore into credit_wallets
                (user_id, period, monthly_credits, used_credits, reserved_credits, usd_budget, created_at)
                values (?, ?, ?, 0, 0, ?, ?)
                """,
                (user.id, period, DEFAULT_MONTHLY_CREDITS, DEFAULT_MONTHLY_CREDITS * USD_PER_CREDIT, datetime.now().isoformat(timespec="seconds")),
            )

    def status(self, user: CurrentUser | None = None, period: str | None = None) -> dict:
        user = user or get_current_user()
        period = period or self.current_period()
        self.ensure_user(user)
        self.ensure_wallet(user, period)
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            wallet = conn.execute(
                "select * from credit_wallets where user_id = ? and period = ?",
                (user.id, period),
            ).fetchone()
            recent = conn.execute(
                """
                select action, model, credits, estimated_usd, input_tokens, output_tokens, created_at
                from credit_ledger where user_id = ? and period = ?
                order by created_at desc limit 20
                """,
                (user.id, period),
            ).fetchall()
        monthly = float(wallet["monthly_credits"])
        used = float(wallet["used_credits"])
        remaining = max(0.0, monthly - used)
        usage_percent = (used / monthly) * 100 if monthly else 0.0
        return {
            "user": {"id": user.id, "email": user.email, "name": user.name, "role": user.role},
            "period": period,
            "monthly_credits": monthly,
            "used_credits": used,
            "remaining_credits": remaining,
            "usd_budget": float(wallet["usd_budget"]),
            "used_usd": used * USD_PER_CREDIT,
            "remaining_usd": remaining * USD_PER_CREDIT,
            "usage_percent": usage_percent,
            "low_credit_alarm": remaining <= monthly * 0.15,
            "exhausted": remaining <= 0,
            "recent": [dict(row) for row in recent],
        }

    def ledger(self, user: CurrentUser | None = None, period: str | None = None, limit: int = 100) -> list[dict]:
        user = user or get_current_user()
        period = period or self.current_period()
        self.ensure_user(user)
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                select * from credit_ledger where user_id = ? and period = ?
                order by created_at desc limit ?
                """,
                (user.id, period, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_llm_usage(
        self,
        model: str,
        usage: Any,
        action: str = "llm.chat",
        metadata: dict | None = None,
        user: CurrentUser | None = None,
    ) -> dict:
        user = self.ensure_user(user)
        period = self.current_period()
        self.ensure_wallet(user, period)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0) or 0)
        estimated_usd = self.estimate_usd(model, input_tokens, output_tokens)
        credits = estimated_usd / USD_PER_CREDIT
        entry_id = sha1(f"{user.id}:{period}:{action}:{model}:{datetime.now().isoformat()}".encode("utf-8")).hexdigest()[:18]
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                insert into credit_ledger
                (id, user_id, period, action, model, input_tokens, output_tokens, estimated_usd, credits, metadata, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    user.id,
                    period,
                    action,
                    model,
                    input_tokens,
                    output_tokens,
                    estimated_usd,
                    credits,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.execute(
                """
                update credit_wallets set used_credits = used_credits + ?
                where user_id = ? and period = ?
                """,
                (credits, user.id, period),
            )
        return {"id": entry_id, "credits": credits, "estimated_usd": estimated_usd}

    def estimate_usd(self, model: str, input_tokens: int, output_tokens: int = 0) -> float:
        normalized = model.lower()
        price = next((value for key, value in MODEL_PRICES_USD_PER_1M.items() if key in normalized), MODEL_PRICES_USD_PER_1M["gpt-5.4-mini"])
        return (input_tokens / 1_000_000) * price["input"] + (output_tokens / 1_000_000) * price["output"]

    def current_period(self) -> str:
        return datetime.now().strftime("%Y-%m")

    def _ensure_tables(self) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                create table if not exists users (
                    id text primary key,
                    email text unique,
                    name text,
                    role text,
                    created_at text
                )
                """
            )
            conn.execute(
                """
                create table if not exists credit_wallets (
                    user_id text,
                    period text,
                    monthly_credits real,
                    used_credits real,
                    reserved_credits real,
                    usd_budget real,
                    created_at text,
                    primary key (user_id, period)
                )
                """
            )
            conn.execute(
                """
                create table if not exists credit_ledger (
                    id text primary key,
                    user_id text,
                    period text,
                    action text,
                    model text,
                    input_tokens integer,
                    output_tokens integer,
                    estimated_usd real,
                    credits real,
                    metadata text,
                    created_at text
                )
                """
            )
