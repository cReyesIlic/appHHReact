"""Adopcion idempotente de datos asociados a IDs historicos de Entra."""

from __future__ import annotations

import logging
from threading import Lock

from app.services.chat_sessions import ChatSessionService
from app.services.proposal_drafts import ProposalDraftService
from app.services.user_context import CurrentUser

logger = logging.getLogger("shimin.identity")
_lock = Lock()
_processed: set[str] = set()
_reprocessing: set[str] = set()
_reprocessed: set[str] = set()


def restore_verified_identity(user: CurrentUser) -> dict:
    """Restaura datos solo a partir de aliases incluidos en el principal verificado."""
    if user.role == "system" or not user.id:
        return {"skipped": True}
    with _lock:
        if user.id in _processed:
            return {"skipped": True}

        aliases = tuple(alias for alias in user.aliases if alias and alias != user.id)
        chat = ChatSessionService().adopt_aliases(user.id, aliases)
        drafts_service = ProposalDraftService()
        drafts = drafts_service.adopt_aliases(user.id, aliases)
        result = {"user": user.id, "chat": chat, "drafts": drafts}
        _processed.add(user.id)
        if aliases:
            logger.info("identity data restored: %s", result)
        return result


def reprocess_verified_files(user_id: str) -> dict:
    """Repara archivos sin texto en segundo plano, una vez por proceso/usuario."""
    with _lock:
        if user_id in _reprocessed or user_id in _reprocessing:
            return {"skipped": True}
        _reprocessing.add(user_id)
    try:
        result = ProposalDraftService().reprocess_pending(user_id, limit=20)
        if result.get("checked"):
            logger.info("pending proposal files reprocessed for %s: %s", user_id, result)
        with _lock:
            _reprocessed.add(user_id)
        return result
    finally:
        with _lock:
            _reprocessing.discard(user_id)
