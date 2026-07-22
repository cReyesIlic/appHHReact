"""Scheduler embebido en el backend (APScheduler) — sin dependencias externas.

Reemplaza al workflow `sync-daily.yml` de GitHub Actions. La app es autónoma:
arranca con uvicorn, levanta un BackgroundScheduler en el mismo proceso, y dispara
`sync_ganadas` una vez al día (02:15 Chile).

Config via env:
  SYNC_SCHEDULE_ENABLED   = "true" / "false"  (default true)
  SYNC_SCHEDULE_HOURS     = horas locales separadas por coma (default 2)
  SYNC_SCHEDULE_MINUTE    = minuto local (default 15)
  SYNC_SCHEDULE_LIMIT     = máximo de propuestas por corrida (default 20)
  SYNC_SOURCE_RECHECK_LIMIT = fuentes ya indexadas a revisar por corrida (default 200)
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
_last_master_run: dict | None = None


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


def _schedule_hours() -> list[int]:
    raw = os.getenv("SYNC_SCHEDULE_HOURS", "2")
    hours: list[int] = []
    for value in raw.split(","):
        try:
            hour = int(value.strip())
        except (TypeError, ValueError):
            continue
        if 0 <= hour <= 23 and hour not in hours:
            hours.append(hour)
    return sorted(hours) or [2]


async def _run_sync_ganadas() -> None:
    """Ciclo automatico: refresca Master y luego sincroniza ganadas pendientes."""
    from app.services.proposal_sync_service import ProposalSyncService

    global _last_run
    limit = _int_env("SYNC_SCHEDULE_LIMIT", 20)
    started_at = datetime.now()
    logger.info("[scheduler] sync_ganadas start (limit=%s)", limit)
    try:
        master_result = await _run_master_refresh(send_email=False)
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
            "master_refresh": master_result,
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


async def _run_storage_monitor() -> None:
    """Job: chequea uso del File Share `shimin-data` y manda email si pasa el umbral.

    Reusa la lógica del CLI `scripts/monitor_share_usage.py`. Soft-fails si Azure SDK
    no está disponible o las env vars no están seteadas (modo dev local).
    """
    logger.info("[scheduler] storage_monitor start")
    try:
        from scripts.monitor_share_usage import get_share_stats, render_report
        from app.services.email_client import EmailClient

        account = os.getenv("AZURE_STORAGE_ACCOUNT", "apphhdrive")
        share = os.getenv("AZURE_FILE_SHARE_NAME", "shimin-data")
        key = os.getenv("AZURE_STORAGE_KEY")
        conn_str = os.getenv("AZURE_CONNECTION_STRING")
        threshold = float(os.getenv("SHARE_USAGE_THRESHOLD", "0.70"))

        if not (key or conn_str):
            logger.info("[scheduler] storage_monitor skip: sin AZURE_STORAGE_KEY/CONNECTION_STRING")
            return

        stats = get_share_stats(account, share, key, conn_str)
        subject, plain, html = render_report(stats, [], threshold)
        logger.info("[scheduler] storage_monitor: %.1f%% used", stats["utilization"] * 100)

        if stats["utilization"] >= threshold:
            email = EmailClient()
            if email.configured:
                email.send(subject, plain, html)
                logger.warning("[scheduler] storage_monitor alert email sent (%.1f%%)", stats["utilization"] * 100)
    except Exception:  # noqa: BLE001
        logger.exception("[scheduler] storage_monitor failed")


async def _run_master_refresh(send_email: bool = True) -> dict:
    """Job secundario: refresca el master Excel (también envía email)."""
    from app.services.email_client import EmailClient
    from app.services.ingestion_reporter import master_refresh_report
    from app.services.master_repository import MasterRepository

    global _last_master_run
    started_at = datetime.now()
    logger.info("[scheduler] master_refresh start")
    try:
        result = await MasterRepository().refresh_from_source()
        rows = int(result.get("rows_loaded") or 0)
        email = EmailClient()
        if send_email and email.configured:
            subject, text, html = master_refresh_report(rows)
            result["email"] = email.send(subject, text, html)
        _last_master_run = {
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "ok": True,
            **result,
        }
        logger.info("[scheduler] master_refresh done: %s rows source=%s", rows, result.get("source"))
        return _last_master_run
    except Exception as exc:  # noqa: BLE001
        _last_master_run = {
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        logger.exception("[scheduler] master_refresh failed")
        return _last_master_run


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
    hours = _schedule_hours()
    minute = _int_env("SYNC_SCHEDULE_MINUTE", 15)

    try:
        sched = AsyncIOScheduler(timezone=tz)
    except Exception:  # zoneinfo a veces falla en Windows sin tzdata
        logger.warning("[scheduler] timezone %s no disponible, usando UTC", tz)
        sched = AsyncIOScheduler(timezone="UTC")

    # Cada CronTrigger recibe explicitamente el timezone. Sin esto APScheduler
    # puede resolverlo en UTC aunque el scheduler declare America/Santiago.
    sched.add_job(
        _run_sync_ganadas,
        CronTrigger(hour=",".join(str(hour) for hour in hours), minute=minute, timezone=sched.timezone),
        id="sync_ganadas_periodic",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )
    # El Master se refresca dentro del ciclo anterior, garantizando el orden.
    # Storage monitor diario: 1 hora antes del ciclo.
    storage_hour = (hours[0] - 1) % 24
    sched.add_job(
        _run_storage_monitor,
        CronTrigger(hour=storage_hour, minute=minute, timezone=sched.timezone),
        id="storage_monitor_daily",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )

    sched.start()
    _scheduler = sched
    logger.info(
        "[scheduler] iniciado tz=%s hours=%s minute=%s limit=%s",
        tz, hours, minute, _int_env("SYNC_SCHEDULE_LIMIT", 20),
    )
    return {
        "enabled": True,
        "timezone": tz,
        "hours": hours,
        "runs_per_day": len(hours),
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
        return {"running": False, "last_run": _last_run, "last_master_run": _last_master_run}
    jobs = []
    for j in _scheduler.get_jobs():
        nxt = getattr(j, "next_run_time", None)
        jobs.append({
            "id": j.id,
            "next_run": nxt.isoformat() if nxt else None,
            "trigger": str(j.trigger),
            "timezone": str(getattr(j.trigger, "timezone", "")),
        })
    return {
        "running": True,
        "timezone": str(_scheduler.timezone),
        "jobs": jobs,
        "last_run": _last_run,
        "last_master_run": _last_master_run,
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
    if job == "storage_monitor":
        asyncio.create_task(_run_storage_monitor())
        return {"triggered": "storage_monitor", "status": "running_in_background"}
    return {"error": f"job '{job}' desconocido (usar 'sync_ganadas', 'master_refresh' o 'storage_monitor')"}
