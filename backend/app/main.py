import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings
from app.services.database_runtime import prepare_runtime_database
from app.services.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="ProyectoHH Agents Chat", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.on_event("startup")
def _on_startup() -> None:
    database = prepare_runtime_database()
    logging.getLogger("shimin").info("database bootstrap: %s", database)
    info = start_scheduler()
    logging.getLogger("shimin").info("scheduler bootstrap: %s", info)


@app.on_event("shutdown")
def _on_shutdown() -> None:
    shutdown_scheduler()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
