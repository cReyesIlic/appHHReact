"""Scheduler embebido en el backend (APScheduler) — sin dependencias externas.

Reemplaza al workflow `sync-daily.yml` de GitHub Actions. La app es autónoma:
arranca con uvicorn, levanta un BackgroundScheduler en el mismo proceso, y dispara
`sync_ganadas` cada N días (por defecto 2) a las 02:00 hora Chile.

Config via env:
  SYNC_SCHEDULE_ENABLED   = "true" / "false"  (default true)
  SYNC_SCHEDULE_HOUR      = hora local del trigger (default 2)
  SYNC_SCHEDULE_MINUTE    = minuto local (default 15)
  SYNC_SCHEDULE_EVERY_DAYS = cada cuántos días (default 2)
  SYNC_SCHEDULE_LIMIT     = máximo de propuestas por corrida (default 20)
  SYNC_SCHEDULE_TZ        = zona horaria IANA (default America/Santiago)

El scheduler es **idempotente**: si el App Service reinicia, la próxima corrida
agendada al ciclo siguiente seguirá funcionando. No requiere job store persistente
porque el cron es determinístico (no acumula misfires importantes).

Endpoints de control en /api/admin/scheduler/* (status, trigger, pause, resume).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger("shimin.scheduler")

_scheduler: Any = None
_last_run: dict | None = None


def _bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


async def _run_sync_ganadas() -> None:
    """Job principal: sincroniza ganadas pendientes y envía email de resumen."""
    from app.services.proposal_sync_service import ProposalSyncService

    global _last_run
    limit = _int_env("SYNC_SCHEDULE_LIMIT", 20)
    started_at = datetime.now()
    logger.info("[scheduler] sync_ganadas start (limit=%s)", limit)
    try:
        svc = ProposalSyncService()
        result = await svc.sync_ganadas(limit=limit)
        _last_run = {
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "ok": True,
            "ingested": result.get("ingested"),
            "errors": result.get("errors"),
            "wiki_ok": result.get("wiki_ok"),
            "objetivo": result.get("objetivo_corrida"),
            "email": result.get("email"),
        }
        logger.info(
            "[scheduler] sync_ganadas done: ingested=%s errors=%s wiki_ok=%s",
            result.get("ingested"), result.get("errors"), result.get("wiki_ok"),
        )
    except Exception as exc:  # noqa: BLE001
        _last_run = {
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        logger.exception("[scheduler] sync_ganadas failed")


async def _run_master_refresh() -> None:
    """Job secundario: refresca el master Excel (también envía email)."""
    from app.services.email_client import EmailClient
    from app.services.ingestion_reporter import master_refresh_report
    from app.services.master_repository import MasterRepository

    logger.info("[scheduler] master_refresh start")
    try:
        rows = MasterRepository().refresh_from_excel()
        email = EmailClient()
        if email.configured:
            subject, text, html = master_refresh_report(rows)
            email.send(subject, text, html)
        logger.info("[scheduler] master_refresh done: %s rows", rows)
    except Exception:  # noqa: BLE001
        logger.exception("[scheduler] master_refresh failed")


def start_scheduler() -> dict:
    """Arranca el scheduler. Se llama desde FastAPI startup event.

    No-op si ya está corriendo o si está deshabilitado por env var.
    """
    global _scheduler

    if not _bool_env("SYNC_SCHEDULE_ENABLED", True):
        logger.info("[scheduler] deshabilitado por SYNC_SCHEDULE_ENABLED=false")
        return {"enabled": False, "reason": "SYNC_SCHEDULE_ENABLED=false"}

    if _scheduler is not None and getattr(_scheduler, "running", False):
        return {"enabled": True, "already_running": True}

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning("[scheduler] APScheduler no instalado, scheduler deshabilitado")
        return {"enabled": False, "reason": "APScheduler no instalado"}

    tz = os.getenv("SYNC_SCHEDULE_TZ", "America/Santiago")
    hour = _int_env("SYNC_SCHEDULE_HOUR", 2)
    minute = _int_env("SYNC_SCHEDULE_MINUTE", 15)
    every_days = max(1, _int_env("SYNC_SCHEDULE_EVERY_DAYS", 2))

    try:
        sched = AsyncIOScheduler(timezone=tz)
    except Exception:  # zoneinfo a veces falla en Windows sin tzdata
        logger.warning("[scheduler] timezone %s no disponible, usando UTC", tz)
        sched = AsyncIOScheduler(timezone="UTC")

    # Cron "cada N días a hora:minuto" — usamos day="*/N"
    day_expr = f"*/{every_days}" if every_days > 1 else "*"
    sched.add_job(
        _run_sync_ganadas,
        CronTrigger(day=day_expr, hour=hour, minute=minute),
        id="sync_ganadas_periodic",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )
    # Master refresh diario 5 minutos antes (barato, ayuda a detectar nuevos PG)
    sched.add_job(
        _run_master_refresh,
        CronTrigger(hour=hour, minute=max(0, minute - 5)),
        id="master_refresh_daily",
        replace_existing=True,
        misfire_grace_time=1800,
        max_instances=1,
        coalesce=True,
    )

    sched.start()
    _scheduler = sched
    logger.info(
        "[scheduler] iniciado tz=%s every_days=%s hour=%s minute=%s limit=%s",
        tz, every_days, hour, minute, _int_env("SYNC_SCHEDULE_LIMIT", 20),
    )
    return {
        "enabled": True,
        "timezone": tz,
        "every_days": every_days,
        "hour": hour,
        "minute": minute,
        "limit": _int_env("SYNC_SCHEDULE_LIMIT", 20),
        "jobs": [j.id for j in sched.get_jobs()],
    }


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and getattr(_scheduler, "running", False):
        _scheduler.shutdown(wait=False)
        logger.info("[scheduler] shutdown")
    _scheduler = None


def scheduler_status() -> dict:
    if _scheduler is None or not getattr(_scheduler, "running", False):
        return {"running": False, "last_run": _last_run}
    jobs = []
    for j in _scheduler.get_jobs():
        nxt = getattr(j, "next_run_time", None)
        jobs.append({
            "id": j.id,
            "next_run": nxt.isoformat() if nxt else None,
            "trigger": str(j.trigger),
        })
    return {
        "running": True,
        "timezone": str(_scheduler.timezone),
        "jobs": jobs,
        "last_run": _last_run,
    }


async def trigger_now(job: str = "sync_ganadas") -> dict:
    """Dispara un job inmediatamente (no espera al cron). Usado desde el endpoint admin."""
    if job == "sync_ganadas":
        # No await dentro del request — corre en background del loop actual
        asyncio.create_task(_run_sync_ganadas())
        return {"triggered": "sync_ganadas", "status": "running_in_background"}
    if job == "master_refresh":
        asyncio.create_task(_run_master_refresh())
        return {"triggered": "master_refresh", "status": "running_in_background"}
    return {"error": f"job '{job}' desconocido (usar 'sync_ganadas' o 'master_refresh')"}
