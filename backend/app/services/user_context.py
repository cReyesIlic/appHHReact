from __future__ import annotations

import base64
import binascii
import json
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.core.config import settings


@dataclass
class CurrentUser:
    id: str
    email: str
    name: str
    role: str = "user"
    aliases: tuple[str, ...] = ()


current_user_var: ContextVar[CurrentUser] = ContextVar(
    "current_user",
    default=CurrentUser(id="system", email="", name="System", role="system"),
)


def get_current_user() -> CurrentUser:
    return current_user_var.get()


def user_from_request(request: Request) -> CurrentUser:
    """Obtiene una identidad ya verificada por SWA/Easy Auth.

    No confia en headers de usuario sueltos ni suplanta a un administrador cuando
    falta autenticacion. El unico fallback es local, opt-in y limitado a loopback.
    """
    cached = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached

    encoded = request.headers.get("x-ms-client-principal")
    if encoded:
        user = _user_from_principal(_decode_principal(encoded))
    elif settings.auth_allow_local_dev and _is_loopback(request):
        email = (request.headers.get("x-dev-user-email") or "local-dev@shimin.cl").strip().lower()
        user = CurrentUser(
            id=email,
            email=email,
            name=email.split("@", 1)[0].replace(".", " ").title(),
            role="admin" if email in _csv(settings.auth_admin_emails) else "user",
        )
    elif not settings.auth_required:
        user = CurrentUser(id="local-dev", email="local-dev@shimin.cl", name="Local Dev")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticacion requerida")

    request.state.current_user = user
    return user


def _decode_principal(encoded: str) -> dict:
    try:
        padding = "=" * (-len(encoded) % 4)
        raw = base64.b64decode(encoded + padding, validate=True).decode("utf-8")
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identidad invalida") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identidad invalida")
    return payload


def _user_from_principal(principal: dict) -> CurrentUser:
    claims_rows = [row for row in principal.get("claims") or [] if isinstance(row, dict)]
    claims = {
        str(row.get("typ") or "").casefold(): str(row.get("val") or "").strip()
        for row in claims_rows
        if row.get("typ") and row.get("val")
    }
    roles = {
        str(role).strip().casefold()
        for role in principal.get("userRoles") or []
        if str(role).strip()
    }
    role_type = str(principal.get("role_typ") or "").casefold()
    if role_type:
        roles.update(
            str(row.get("val") or "").strip().casefold()
            for row in claims_rows
            if str(row.get("typ") or "").casefold() == role_type and row.get("val")
        )

    # SWA entrega userDetails; Easy Auth entrega las mismas senales como claims.
    email = str(principal.get("userDetails") or "").strip().lower()
    if "@" not in email:
        email = _claim(
            claims,
            "preferred_username",
            "email",
            "emails",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
        ).lower()
    if "@" not in email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La identidad no contiene email")

    allowed_domains = _csv(settings.auth_allowed_email_domains)
    domain = email.rsplit("@", 1)[-1]
    if allowed_domains and domain not in allowed_domains:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dominio no autorizado")

    # SWA siempre agrega authenticated. En formato Easy Auth, auth_typ confirma
    # que la plataforma autentico al llamador antes de inyectar sus claims.
    if "authenticated" not in roles and not principal.get("auth_typ"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesion no autenticada")

    name = _claim(
        claims,
        "name",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
    ) or email.split("@", 1)[0].replace(".", " ").title()
    admins = _csv(settings.auth_admin_emails)
    role = "admin" if email in admins or "admin" in roles else "user"

    # El email verificado es la identidad canonica. SWA historicamente expuso
    # `userId` (GUID de Entra) y versiones anteriores de la app lo usaron como
    # owner_id; se conserva exclusivamente como alias verificado para adoptar
    # esos datos, nunca como identidad aportada por el cliente.
    alias_candidates = [
        principal.get("userId"),
        _claim(
            claims,
            "oid",
            "http://schemas.microsoft.com/identity/claims/objectidentifier",
        ),
    ]
    aliases = tuple(
        dict.fromkeys(
            str(value).strip()
            for value in alias_candidates
            if str(value or "").strip() and str(value).strip().casefold() != email.casefold()
        )
    )
    return CurrentUser(id=email, email=email, name=name, role=role, aliases=aliases)


def _claim(claims: dict[str, str], *names: str) -> str:
    for name in names:
        value = claims.get(name.casefold())
        if value:
            return value
    return ""


def _csv(value: str) -> set[str]:
    return {item.strip().casefold() for item in str(value or "").split(",") if item.strip()}


def _is_loopback(request: Request) -> bool:
    host = str(getattr(request.client, "host", "") or "").casefold()
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}
