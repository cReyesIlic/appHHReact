"""Cliente HTTP para la API externa de Staffing.

Endpoints SHIMIN Staffing (lectura, X-API-Key auth):
  GET /external/proyectos
  GET /external/proyectos/{codigo}/entregables
  GET /external/proyectos/{codigo}/personas
  GET /external/proyectos/{codigo}/completo
  GET /external/entregables/analisis-hh        ← clave: HH reales por concepto + cliente + servicio
  GET /external/entregables/horas-detalle      ← audit: quién cargó qué semana
  GET /external/personas/{usuario_id}

Config via env vars (poner en .env o App Settings Azure):
  STAFFING_API_URL  = https://staffing-shimin-dgedc6cachagg8fx.eastus2-01.azurewebsites.net
  STAFFING_API_KEY  = <key>
"""

from __future__ import annotations

import os
from typing import Any

import httpx


DEFAULT_URL = "https://staffing-shimin-dgedc6cachagg8fx.eastus2-01.azurewebsites.net"


class StaffingClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = (base_url or os.getenv("STAFFING_API_URL") or DEFAULT_URL).rstrip("/")
        self.api_key = api_key or os.getenv("STAFFING_API_KEY") or os.getenv("EXTERNAL_API_KEY") or ""
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        if not self.api_key:
            return {"error": "STAFFING_API_KEY no configurada en .env / App Settings"}
        params = {k: v for k, v in (params or {}).items() if v not in (None, "", [])}
        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}{path}", params=params, headers=headers)
                if resp.status_code == 401:
                    return {"error": "401: API key inválida o no enviada"}
                if resp.status_code == 503:
                    return {"error": "503: el backend de staffing no tiene EXTERNAL_API_KEY configurada"}
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"}
        except httpx.RequestError as exc:
            return {"error": f"Conexión: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}

    # ---- API pública ----

    async def listar_proyectos(self, activo: bool | None = True, limit: int = 50, offset: int = 0, jp_id: str | None = None) -> dict:
        return await self._get(
            "/external/proyectos",
            {"activo": _bool(activo), "limit": limit, "offset": offset, "jp_id": jp_id},
        )

    async def proyecto_completo(self, codigo: str, ano: int | None = None) -> dict:
        return await self._get(f"/external/proyectos/{codigo}/completo", {"ano": ano})

    async def entregables_proyecto(self, codigo: str, ano: int | None = None) -> dict:
        return await self._get(f"/external/proyectos/{codigo}/entregables", {"ano": ano})

    async def personas_proyecto(self, codigo: str, ano: int | None = None, con_detalle: bool = False) -> dict:
        return await self._get(
            f"/external/proyectos/{codigo}/personas",
            {"ano": ano, "con_detalle": _bool(con_detalle)},
        )

    async def analisis_hh(
        self,
        q: str | None = None,
        disciplina: str | None = None,
        contexto: str | None = None,
        proyecto_codigo: str | None = None,
        ano: int | None = None,
        top: int = 100,
        incluir_personas: bool = False,
        personas_por_entregable: int | None = None,
    ) -> dict:
        """`/external/entregables/analisis-hh` — endpoint clave.

        Útil para preguntas tipo: "memoria de cálculo hidráulica en Caserones",
        "planos de piping para Vale", "informes de hidráulica con Codelco", etc.
        """
        return await self._get(
            "/external/entregables/analisis-hh",
            {
                "q": q,
                "disciplina": disciplina,
                "contexto": contexto,
                "proyecto_codigo": proyecto_codigo,
                "ano": ano,
                "top": top,
                "incluir_personas": _bool(incluir_personas),
                "personas_por_entregable": personas_por_entregable,
            },
        )

    async def horas_detalle(
        self,
        q: str | None = None,
        proyecto_codigo: str | None = None,
        entregable_id: str | None = None,
        persona_id: str | None = None,
        disciplina: str | None = None,
        contexto: str | None = None,
        ano: int | None = None,
        semana_desde: int | None = None,
        semana_hasta: int | None = None,
        limit: int = 500,
    ) -> dict:
        return await self._get(
            "/external/entregables/horas-detalle",
            {
                "q": q,
                "proyecto_codigo": proyecto_codigo,
                "entregable_id": entregable_id,
                "persona_id": persona_id,
                "disciplina": disciplina,
                "contexto": contexto,
                "ano": ano,
                "semana_desde": semana_desde,
                "semana_hasta": semana_hasta,
                "limit": limit,
            },
        )

    async def historial_persona(self, usuario_id: str, ano: int | None = None) -> dict:
        return await self._get(f"/external/personas/{usuario_id}", {"ano": ano})


def _bool(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
