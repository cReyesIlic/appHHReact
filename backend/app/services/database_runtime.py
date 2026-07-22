"""Preparacion de SQLite para el volumen Azure Files de produccion."""

from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import closing

from app.core.config import settings


logger = logging.getLogger("shimin.database")


def runtime_database_status() -> dict:
    path = settings.sqlite_path
    with closing(sqlite3.connect(path, timeout=10)) as conn:
        journal_mode = str(conn.execute("pragma journal_mode").fetchone()[0]).lower()
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "journal_mode": journal_mode,
        "network_safe": journal_mode != "wal",
    }


def prepare_runtime_database(attempts: int = 5) -> dict:
    """Fuerza un journal compatible con filesystem de red antes del trafico.

    SQLite WAL depende de memoria compartida y no es compatible con Azure Files
    (SMB). El modo DELETE conserva transacciones atomicas sin archivos SHM.
    """
    path = settings.sqlite_path
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None

    for attempt in range(1, max(1, attempts) + 1):
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(path, timeout=60)
            conn.execute("pragma busy_timeout = 60000")
            before = str(conn.execute("pragma journal_mode").fetchone()[0]).lower()
            if before == "wal":
                conn.execute("pragma wal_checkpoint(truncate)")
                after = str(conn.execute("pragma journal_mode=delete").fetchone()[0]).lower()
            else:
                after = before
            conn.execute("pragma locking_mode=normal")
            conn.commit()
            logger.info("SQLite listo path=%s journal=%s->%s", path, before, after)
            return {"path": str(path), "journal_before": before, "journal_mode": after}
        except sqlite3.Error as exc:
            last_error = exc
            logger.warning("SQLite prepare intento %s/%s: %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(1)
        finally:
            if conn is not None:
                conn.close()

    raise RuntimeError(f"No se pudo preparar SQLite en {path}: {last_error}")
