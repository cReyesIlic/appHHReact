from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import Request


@dataclass
class CurrentUser:
    id: str
    email: str
    name: str
    role: str = "user"


current_user_var: ContextVar[CurrentUser] = ContextVar(
    "current_user",
    default=CurrentUser(
        id="local-dev",
        email="cristian.reyes@shimin.cl",
        name="Cristian Reyes",
        role="admin",
    ),
)


def get_current_user() -> CurrentUser:
    return current_user_var.get()


def user_from_request(request: Request) -> CurrentUser:
    email = (
        request.headers.get("x-ms-client-principal-name")
        or request.headers.get("x-user-email")
        or "cristian.reyes@shimin.cl"
    )
    name = request.headers.get("x-user-name") or email.split("@")[0].replace(".", " ").title()
    user_id = request.headers.get("x-ms-client-principal-id") or email.lower()
    role = request.headers.get("x-user-role") or ("admin" if "cristian" in email.lower() else "user")
    return CurrentUser(id=user_id, email=email.lower(), name=name, role=role)
