from __future__ import annotations

import unicodedata
from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.services.proposal_taxonomy import SERVICE_TYPES, STATUS_TYPES


STATUS_CATEGORIES = {
    "indefinida",
    "en_preparacion",
    "no_licitada",
    "pendiente",
    "ganada",
    "perdida",
    "desierta",
}


class SearchFilters(BaseModel):
    codigos: list[str] | None = Field(default=None, description="Lista de códigos de propuesta (ej O-1376)")
    estados: list[str] | None = Field(default=None, description="Códigos de estado: PG, PP, EP, NL, DP, PD, PDS")
    estado_categoria: list[str] | None = Field(default=None, description="Categorías: ganada, perdida, en_preparacion, ...")
    clientes: list[str] | None = Field(default=None, description="Match parcial sobre cliente o cliente_final")
    tipos_servicio: list[str] | None = Field(default=None, description="Códigos de servicio: IP, IC, IB, ID, ...")
    disciplinas: list[str] | None = Field(default=None, description="Disciplinas dentro de section_entities.disciplinas")
    componentes: list[str] | None = Field(default=None)
    instalaciones: list[str] | None = Field(default=None)
    procesos_sistemas: list[str] | None = Field(default=None)
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    monto_min: float | None = None
    monto_max: float | None = None
    query: str | None = Field(default=None, description="Texto libre para búsqueda lexical+vector")
    limit: int = Field(default=8, ge=1, le=100)

    @field_validator("codigos", mode="before")
    @classmethod
    def _norm_codigos(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = [value]
        return [str(code).strip().upper() for code in value if str(code).strip()] or None

    @field_validator("estados", mode="before")
    @classmethod
    def _norm_estados(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = [value]
        return [str(item).strip().upper() for item in value if str(item).strip()] or None

    @field_validator("estado_categoria", mode="before")
    @classmethod
    def _norm_categoria(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = [value]
        return [str(item).strip().lower() for item in value if str(item).strip()] or None

    @field_validator("tipos_servicio", mode="before")
    @classmethod
    def _norm_tipos(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = [value]
        return [str(item).strip().upper() for item in value if str(item).strip()] or None

    @field_validator("clientes", "disciplinas", "componentes", "instalaciones", "procesos_sistemas", mode="before")
    @classmethod
    def _norm_strings(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = [value]
        return [str(item).strip() for item in value if str(item).strip()] or None

    def is_empty(self) -> bool:
        return not any(
            [
                self.codigos,
                self.estados,
                self.estado_categoria,
                self.clientes,
                self.tipos_servicio,
                self.disciplinas,
                self.componentes,
                self.instalaciones,
                self.procesos_sistemas,
                self.fecha_desde,
                self.fecha_hasta,
                self.monto_min is not None,
                self.monto_max is not None,
                (self.query or "").strip(),
            ]
        )

    def has_metadata_filters(self) -> bool:
        return any(
            [
                self.codigos,
                self.estados,
                self.estado_categoria,
                self.clientes,
                self.tipos_servicio,
                self.disciplinas,
                self.componentes,
                self.instalaciones,
                self.procesos_sistemas,
            ]
        )

    def sql_clauses(self, table_alias: str = "c", metadata_column: str = "metadata") -> tuple[list[str], list]:
        """Construye cláusulas SQL para una tabla con columna `metadata` JSON.

        Devuelve (clauses, params) listas para hacer `where {AND clauses}` o concatenar.
        """
        clauses: list[str] = []
        params: list = []
        meta = f"{table_alias}.{metadata_column}"

        if self.codigos:
            placeholders = ",".join("?" for _ in self.codigos)
            clauses.append(f"{table_alias}.codigo in ({placeholders})")
            params.extend(self.codigos)

        if self.estados:
            placeholders = ",".join("?" for _ in self.estados)
            clauses.append(f"json_extract({meta}, '$.estado') in ({placeholders})")
            params.extend(self.estados)

        if self.estado_categoria:
            placeholders = ",".join("?" for _ in self.estado_categoria)
            clauses.append(f"json_extract({meta}, '$.estado_categoria') in ({placeholders})")
            params.extend(self.estado_categoria)

        if self.clientes:
            sub = []
            for cliente in self.clientes:
                pattern = f"%{_norm(cliente)}%"
                sub.append(
                    f"(lower(coalesce(json_extract({meta}, '$.cliente'), '')) like ? "
                    f"or lower(coalesce(json_extract({meta}, '$.cliente_final'), '')) like ?)"
                )
                params.extend([pattern, pattern])
            clauses.append("(" + " or ".join(sub) + ")")

        if self.tipos_servicio:
            sub = []
            for tipo in self.tipos_servicio:
                sub.append(f"lower(coalesce(json_extract({meta}, '$.tipo_servicio'), '')) like ?")
                params.append(f"%{tipo.lower()}%")
            clauses.append("(" + " or ".join(sub) + ")")

        for field_name, json_key in [
            ("disciplinas", "$.section_entities.disciplinas"),
            ("componentes", "$.section_entities.componentes"),
            ("instalaciones", "$.section_entities.instalaciones_mineras"),
            ("procesos_sistemas", "$.section_entities.procesos_sistemas"),
        ]:
            values = getattr(self, field_name)
            if not values:
                continue
            sub = []
            for value in values:
                sub.append(f"lower(coalesce(json_extract({meta}, '{json_key}'), '')) like ?")
                params.append(f"%{value.lower()}%")
            clauses.append("(" + " or ".join(sub) + ")")

        return clauses, params

    def matches_row_metadata(self, metadata: dict, codigo: str | None = None) -> bool:
        """Evalúa los filtros estructurados sobre un dict ya decodificado.

        Útil para stores que no consultan SQL directo (master DataFrame, wiki entries).
        """
        if self.codigos and codigo and codigo.upper() not in self.codigos:
            return False
        if self.estados:
            estado = str(metadata.get("estado") or "").strip().upper()
            if estado not in self.estados:
                return False
        if self.estado_categoria:
            cat = str(metadata.get("estado_categoria") or "").strip().lower()
            if cat not in self.estado_categoria:
                return False
        if self.clientes:
            haystack = _norm(" ".join(str(metadata.get(k) or "") for k in ("cliente", "cliente_final")))
            if not any(_norm(c) in haystack for c in self.clientes):
                return False
        if self.tipos_servicio:
            tipo = str(metadata.get("tipo_servicio") or "").upper()
            if not any(t in tipo for t in self.tipos_servicio):
                return False
        entities = metadata.get("section_entities") or {}
        for field_name, key in [
            ("disciplinas", "disciplinas"),
            ("componentes", "componentes"),
            ("instalaciones", "instalaciones_mineras"),
            ("procesos_sistemas", "procesos_sistemas"),
        ]:
            values = getattr(self, field_name)
            if not values:
                continue
            bucket = entities.get(key) or []
            bucket_text = " ".join(str(x).lower() for x in bucket)
            if not any(v.lower() in bucket_text for v in values):
                return False
        return True

    @classmethod
    def from_dict(cls, data: dict | None) -> "SearchFilters":
        return cls(**(data or {}))

    @classmethod
    def from_codes(cls, codes: list[str] | None) -> "SearchFilters":
        return cls(codigos=codes)


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def valid_estados() -> list[str]:
    return list(STATUS_TYPES.keys())


def valid_tipos_servicio() -> list[str]:
    return list(SERVICE_TYPES.keys())


def valid_categorias() -> list[str]:
    return sorted(STATUS_CATEGORIES)
