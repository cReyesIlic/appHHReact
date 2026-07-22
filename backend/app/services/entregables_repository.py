"""Consulta unificada de entregables y HH licitadas/reales.

Fuentes y precedencia:
1. ``proyectos``: detalle estructurado histórico vinculado al Master.
2. ``proyectos_extracted``: lector propio (Azure Budget Extractor) para códigos que
   todavía no existen en ``proyectos``. Se elige un solo workbook canónico por O
   para no sumar revisiones alternativas del mismo presupuesto.
3. Staffing: fuente externa y exclusiva de HH reales.

``hh_estimate_rows`` se conserva como diagnóstico exploratorio, pero no participa
en totales: su heurística puede confundir números de ítem con horas.
"""

from __future__ import annotations

import math
import re
import sqlite3
import unicodedata
from collections import defaultdict
from contextlib import closing
from typing import Any

from app.core.config import settings
from app.services.staffing_client import StaffingClient


CARGOS = [
    "jp", "ji", "jd", "abim", "cbim", "ec", "cn", "esp",
    "ia", "ib", "ic", "pa", "pb", "cp", "cd", "ce", "i", "c", "db", "pc",
]

CARGO_LABELS = {
    "jp": "Jefe de proyecto", "ji": "Jefe de ingeniería", "jd": "Jefe de disciplina",
    "abim": "Administrador BIM", "cbim": "Coordinador BIM", "ec": "Especialista control",
    "cn": "Control documental", "esp": "Especialista", "ia": "Ingeniero A",
    "ib": "Ingeniero B", "ic": "Ingeniero C", "pa": "Proyectista A",
    "pb": "Proyectista B", "cp": "Control de proyectos", "cd": "Control documental",
    "ce": "Control estimaciones", "i": "Ingeniero", "c": "Consultor",
    "db": "Dibujante", "pc": "Programación y control",
}

DISCIPLINE_KEYWORDS = (
    ("Hidráulica", ("hidraul", "relave", "agua", "bombeo", "piping", "tuber")),
    ("Mecánica", ("mecanic", "equipo", "bomba", "valvula")),
    ("Piping", ("piping", "cañer", "caner", "isometr")),
    ("Electricidad", ("electric", "electrica", "potencia", "cable")),
    ("Instrumentación y control", ("instrument", "control", "tag", "pid", "p&id")),
    ("Civil estructural", ("civil", "estructur", "fundacion", "hormigon")),
    ("Geología y geotecnia", ("geotec", "geolog", "talud", "suelo")),
    ("Control documental", ("document", "recodific", "transmittal")),
)


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join("".join(ch for ch in text if not unicodedata.combining(ch)).split())


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        result = float(value)
        return result if math.isfinite(result) else None
    text = str(value or "").strip().replace(" ", "")
    if not text or _norm(text) in {"no data", "n/d", "nd", "-"}:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") == 1 and len(text.rsplit(".", 1)[1]) == 3:
        text = text.replace(".", "")
    else:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    try:
        result = float(text)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _infer_discipline(text: object) -> str:
    normalized = _norm(text)
    for label, tokens in DISCIPLINE_KEYWORDS:
        if any(token in normalized for token in tokens):
            return label
    return "Sin disciplina"


def _canonical_discipline(value: object) -> str:
    normalized = _norm(value)
    aliases = {
        "hidraulica": "Hidráulica", "mecanica": "Mecánica",
        "instrumentacion y control": "Instrumentación y control",
        "civil estructural": "Civil estructural", "tecnicos": "Técnicos",
        "multidisciplinario": "Multidisciplinario", "general": "General",
        "piping": "Piping", "electricidad": "Electricidad",
    }
    return aliases.get(normalized, str(value or "").strip() or "Sin disciplina")


def _clean_service(value: object) -> str | None:
    text = str(value or "").strip()
    return None if not text or _norm(text) == "no data" else text


def _resolve_service(value: object, title: object) -> tuple[str | None, str]:
    explicit = _clean_service(value)
    if explicit:
        return explicit, "master"
    match = re.match(r"^\s*(IP|IC|IBA|IB|ID|EPCM|EPC|EP)\b", str(title or ""), re.IGNORECASE)
    return (match.group(1).upper(), "titulo") if match else (None, "sin_dato")


class EntregablesRepository:
    def __init__(self) -> None:
        self.sqlite_path = settings.sqlite_path
        self.staffing = StaffingClient()

    def stats(self) -> dict:
        with closing(self._connect()) as conn:
            structured = conn.execute(
                f"""
                select count(*) rows, count(distinct codigo) projects,
                       sum({self._sum_cargos_sql()}) total_hours
                from proyectos
                """
            ).fetchone()
            extracted = conn.execute(
                "select count(*) rows, count(distinct codigo) projects, sum(coalesce(hh,0)) total_hours "
                "from proyectos_extracted"
            ).fetchone()
            exploratory = conn.execute(
                "select count(*) rows, count(distinct codigo) projects from hh_estimate_rows"
            ).fetchone()

        rows = self._licitada_rows()
        codes = {row["codigo"] for row in rows}
        return {
            "empty": not rows,
            "rows": len(rows),
            "proyectos": len(codes),
            "total_hours": round(sum(row["total_hours"] for row in rows), 2),
            "source_path": "Master · tabla proyectos + lector propio Azure Budget Extractor",
            "staffing_available": self.staffing.available,
            "reader_available": self._budget_reader_available(),
            "sources": {
                "master_structured": {
                    "rows": int(structured["rows"] or 0),
                    "projects": int(structured["projects"] or 0),
                    "total_hours": round(float(structured["total_hours"] or 0), 2),
                },
                "own_reader": {
                    "rows": int(extracted["rows"] or 0),
                    "projects": int(extracted["projects"] or 0),
                    "total_hours_raw": round(float(extracted["total_hours"] or 0), 2),
                },
                "exploratory_excluded": {
                    "rows": int(exploratory["rows"] or 0),
                    "projects": int(exploratory["projects"] or 0),
                    "reason": "No se usa en totales porque puede confundir ítems con HH.",
                },
            },
        }

    def list_disciplines(self, limit: int = 80) -> list[str]:
        rows = self._licitada_rows()
        values = sorted({row["disciplina"] for row in rows if row.get("disciplina")}, key=_norm)
        return values[: max(1, min(int(limit), 500))]

    def aggregate_licitadas(
        self,
        view: str = "proyecto",
        codigo: str | None = None,
        cliente: str | None = None,
        tipo_servicio: str | None = None,
        disciplina: str | None = None,
        text: str | None = None,
        min_hours: float = 0.0,
        limit: int = 100,
    ) -> dict:
        rows = self._filter_rows(
            self._licitada_rows(), codigo=codigo, cliente=cliente,
            tipo_servicio=tipo_servicio, disciplina=disciplina, text=text,
        )
        if view == "proyecto":
            grouped = self._by_project(rows)
        elif view == "disciplina":
            grouped = self._by_dimension(rows, "disciplina")
        elif view == "role":
            grouped = self._by_role(rows)
        elif view == "entregable":
            grouped = self._by_deliverable(rows)
        else:
            return {"error": f"Vista licitada desconocida: {view}", "rows": []}

        threshold = max(0.0, float(min_hours or 0))
        grouped = [row for row in grouped if float(row.get("total_hours") or 0) >= threshold]
        grouped.sort(key=lambda row: (-float(row.get("total_hours") or 0), _norm(row.get("key"))))
        total_hours = sum(float(row.get("total_hours") or 0) for row in grouped)
        for row in grouped:
            row["pct_hours"] = round(float(row.get("total_hours") or 0) * 100 / total_hours, 2) if total_hours else 0

        max_rows = max(1, min(int(limit or 100), 2000))
        return {
            "source": "licitadas",
            "view": view,
            "rows": grouped[:max_rows],
            "available_rows": len(grouped),
            "totals": {"rows": len(grouped), "total_hours": round(total_hours, 2)},
            "note": (
                "HH licitadas: tabla estructurada vinculada al Master; para códigos nuevos se usa "
                "el lector propio Azure Budget Extractor. Staffing no participa en estos totales."
            ),
        }

    async def aggregate_reales(
        self,
        view: str = "proyecto",
        codigo: str | None = None,
        disciplina: str | None = None,
        text: str | None = None,
        ano: int | None = None,
        top: int = 100,
    ) -> dict:
        if not self.staffing.available:
            return {"error": "STAFFING_API_KEY no configurada", "rows": []}
        resolved = self._resolve_staffing_code(codigo) if codigo else None
        max_rows = max(20, min(int(top or 100), 500))

        if view == "proyecto":
            payload = await self.staffing.listar_proyectos(activo=None, limit=max_rows)
            if payload.get("error"):
                return {"error": payload["error"], "rows": []}
            rows = []
            query = _norm(text or resolved or codigo)
            for item in payload.get("proyectos") or []:
                if query and query not in _norm(f"{item.get('codigo')} {item.get('nombre')}"):
                    continue
                master = self._master_for_staffing_code(item.get("codigo"))
                total = float(item.get("horas_totales") or 0)
                row = {
                    "key": item.get("codigo"), "titulo": item.get("nombre"),
                    "cliente": (master or {}).get("cliente"),
                    "tipo_servicio": (master or {}).get("tipo_servicio"),
                    "total_hours": total, "personas": item.get("personas_count") or 0,
                    "entregables": item.get("entregables_count") or 0,
                    "horas_lic_master": (master or {}).get("horas_lic"),
                    "codigo_oferta": (master or {}).get("codigo"), "source_type": "staffing",
                }
                self._add_comparison(row)
                rows.append(row)
            return self._real_result(view, rows, payload.get("total"))

        if not resolved and not (text or disciplina):
            return {
                "error": "Selecciona primero un proyecto SH-XXXX para navegar sus entregables o personas reales.",
                "rows": [],
            }

        if view == "persona":
            if not resolved:
                return {"error": "La vista por persona requiere un proyecto.", "rows": []}
            payload = await self.staffing.personas_proyecto(resolved, ano=ano, con_detalle=False)
            if payload.get("error"):
                return {"error": payload["error"], "rows": []}
            rows = [
                {
                    "key": item.get("nombre") or item.get("usuario_id"),
                    "rol": item.get("cargo"), "disciplina": item.get("disciplina_nombre"),
                    "total_hours": float(item.get("horas_totales") or 0),
                    "entregables": item.get("entregables_count") or 0,
                    "semanas": item.get("semanas_count") or 0,
                    "proyecto": resolved, "source_type": "staffing",
                }
                for item in payload.get("personas") or []
            ]
            return self._real_result(view, rows, payload.get("total_personas"))

        if resolved:
            payload = await self.staffing.entregables_proyecto(resolved, ano=ano)
            if payload.get("error"):
                return {"error": payload["error"], "rows": []}
            detail = payload.get("entregables") or []
        else:
            payload = await self.staffing.analisis_hh(
                q=text or disciplina or "entregable", disciplina=disciplina,
                ano=ano, top=max_rows, incluir_personas=False,
            )
            if payload.get("error"):
                return {"error": payload["error"], "rows": []}
            detail = payload.get("detalle") or []

        normalized = []
        for item in detail:
            name = item.get("nombre") or item.get("entregable_nombre")
            disc = item.get("disciplina_nombre") or "Sin disciplina"
            if disciplina and _norm(disciplina) not in _norm(disc):
                continue
            normalized.append(
                {
                    "key": name, "proyecto": item.get("proyecto_codigo") or resolved,
                    "codigo_entregable": item.get("entregable_codigo") or item.get("entregable_id"),
                    "disciplina": disc, "total_hours": float(item.get("horas_totales") or 0),
                    "personas": item.get("personas_count") or 0,
                    "tipo_servicio": item.get("servicio"), "cliente": item.get("cliente_resuelto"),
                    "source_type": "staffing",
                }
            )
        if view == "disciplina":
            groups: dict[str, dict] = {}
            for item in normalized:
                key = item["disciplina"]
                group = groups.setdefault(key, {"key": key, "total_hours": 0.0, "entregables": 0, "proyectos_set": set()})
                group["total_hours"] += item["total_hours"]
                group["entregables"] += 1
                group["proyectos_set"].add(item["proyecto"])
            rows = []
            for group in groups.values():
                group["proyectos"] = len(group.pop("proyectos_set"))
                rows.append(group)
        else:
            rows = normalized
        return self._real_result(view, rows, len(rows))

    # ---- Unified licitated rows -------------------------------------------------

    def _licitada_rows(self) -> list[dict]:
        with closing(self._connect()) as conn:
            structured_codes = {row[0] for row in conn.execute("select distinct codigo from proyectos")}
            structured = self._structured_rows(conn)
            extracted = self._extracted_rows(conn, structured_codes)
        return [*structured, *extracted]

    def _structured_rows(self, conn: sqlite3.Connection) -> list[dict]:
        cargo_sql = ", ".join(f"p.{cargo}" for cargo in CARGOS)
        rows = conn.execute(
            f"""
            select p.id, p.codigo, p.descripcion, p.clasificacion, p.factor,
                   cr.nombre disciplina, t.nombre tipo_entregable, a.area,
                   o.titulo, o.cliente_directo, o.cliente_final, o.tipo_servicio,
                   o.estado, o.cod_proy, o.horas_lic, o.monto, {cargo_sql}
            from proyectos p
            left join categoria_reg cr on cr.id=p.categoria_reg_id
            left join tipo t on t.id=p.tipo_id
            left join area a on a.id_area=cast(p.id_area as text) or a.id=p.id_area
            left join oferta o on o.codigo=p.codigo
            """
        ).fetchall()
        result = []
        for row in rows:
            roles = {cargo: float(row[cargo] or 0) for cargo in CARGOS if float(row[cargo] or 0) > 0}
            total = sum(roles.values())
            if total <= 0:
                continue
            service, service_source = _resolve_service(row["tipo_servicio"], row["titulo"])
            result.append(
                {
                    "row_id": f"master:{row['id']}", "codigo": row["codigo"],
                    "deliverable": row["descripcion"] or "Sin descripción",
                    "classification": row["clasificacion"] or "Sin clasificación",
                    "disciplina": _canonical_discipline(row["disciplina"] or _infer_discipline(row["descripcion"])),
                    "area": row["area"], "tipo_entregable": row["tipo_entregable"],
                    "roles": roles, "total_hours": total,
                    "titulo": row["titulo"],
                    "cliente": self._client(row["cliente_directo"], row["cliente_final"]),
                    "tipo_servicio": service, "tipo_servicio_source": service_source, "estado": row["estado"],
                    "cod_proy": row["cod_proy"], "horas_lic_master": _number(row["horas_lic"]),
                    "monto_master": _number(row["monto"]),
                    "source_type": "master_proyectos", "source_file": "Master · tabla proyectos",
                }
            )
        return result

    def _extracted_rows(self, conn: sqlite3.Connection, excluded_codes: set[str]) -> list[dict]:
        source_rows = conn.execute(
            """
            select codigo, source_file, max(extracted_at) extracted_at, count(*) row_count,
                   sum(coalesce(hh,0)) total_hh
            from proyectos_extracted
            group by codigo, source_file
            """
        ).fetchall()
        offers = self._offer_rows(conn)
        sources: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in source_rows:
            if row["codigo"] not in excluded_codes:
                sources[row["codigo"]].append(row)

        selected: dict[str, str] = {}
        for code, candidates in sources.items():
            master_hh = (offers.get(code) or {}).get("horas_lic_master")

            def rank(item: sqlite3.Row) -> tuple:
                total = float(item["total_hh"] or 0)
                distance = abs(total - master_hh) / master_hh if master_hh else 0
                return (-distance if master_hh else 0, str(item["extracted_at"] or ""), int(item["row_count"] or 0))

            selected[code] = max(candidates, key=rank)["source_file"]
        if not selected:
            return []

        raw = conn.execute(
            "select * from proyectos_extracted where coalesce(hh,0)>0 order by codigo, source_file, item, descripcion"
        ).fetchall()
        grouped: dict[tuple, dict] = {}
        for row in raw:
            if selected.get(row["codigo"]) != row["source_file"]:
                continue
            key = (row["codigo"], row["source_file"], row["source_sheet"], row["item"], row["descripcion"])
            item = grouped.setdefault(
                key,
                {
                    "codigo": row["codigo"], "source_file": row["source_file"],
                    "source_sheet": row["source_sheet"], "item": row["item"],
                    "deliverable": row["descripcion"] or "Sin descripción", "roles": defaultdict(float),
                    "classification": row["clasificacion"] or "Extraído",
                },
            )
            role = str(row["cargo"] or row["cargo_raw"] or "sin_rol").strip().lower()
            item["roles"][role] += float(row["hh"] or 0)

        result = []
        for index, item in enumerate(grouped.values()):
            offer = offers.get(item["codigo"]) or {}
            roles = dict(item.pop("roles"))
            result.append(
                {
                    **item, "row_id": f"reader:{item['codigo']}:{index}",
                    "disciplina": _infer_discipline(item["deliverable"]), "area": None,
                    "tipo_entregable": item["classification"], "roles": roles,
                    "total_hours": sum(roles.values()), **offer,
                    "source_type": "own_reader",
                }
            )
        return result

    # ---- Aggregations ----------------------------------------------------------

    def _by_project(self, rows: list[dict]) -> list[dict]:
        groups: dict[str, dict] = {}
        for row in rows:
            group = groups.setdefault(
                row["codigo"],
                {
                    "key": row["codigo"], "titulo": row.get("titulo"), "cliente": row.get("cliente"),
                    "tipo_servicio": row.get("tipo_servicio"),
                    "tipo_servicio_source": row.get("tipo_servicio_source"), "estado": row.get("estado"),
                    "cod_proy": row.get("cod_proy"), "horas_lic_master": row.get("horas_lic_master"),
                    "monto_master": row.get("monto_master"), "total_hours": 0.0,
                    "entregables": 0, "disciplinas_set": set(), "sources_set": set(), "files_set": set(),
                },
            )
            group["total_hours"] += row["total_hours"]
            group["entregables"] += 1
            group["disciplinas_set"].add(row["disciplina"])
            group["sources_set"].add(row["source_type"])
            group["files_set"].add(row["source_file"])
        result = []
        for group in groups.values():
            group["disciplinas_nombres"] = sorted(group.pop("disciplinas_set"), key=_norm)
            group["disciplinas"] = len(group["disciplinas_nombres"])
            group["source_types"] = sorted(group.pop("sources_set"))
            group["source_files"] = sorted(group.pop("files_set"))
            self._add_comparison(group)
            result.append(group)
        return result

    def _by_dimension(self, rows: list[dict], field: str) -> list[dict]:
        groups: dict[str, dict] = {}
        for row in rows:
            key = row.get(field) or f"Sin {field}"
            group = groups.setdefault(key, {"key": key, "total_hours": 0.0, "entregables": 0, "projects_set": set()})
            group["total_hours"] += row["total_hours"]
            group["entregables"] += 1
            group["projects_set"].add(row["codigo"])
        result = []
        for group in groups.values():
            group["proyectos"] = len(group.pop("projects_set"))
            result.append(group)
        return result

    def _by_role(self, rows: list[dict]) -> list[dict]:
        groups: dict[str, dict] = {}
        for row in rows:
            for role, hours in row["roles"].items():
                label = CARGO_LABELS.get(role, role.upper())
                group = groups.setdefault(label, {"key": label, "total_hours": 0.0, "projects_set": set()})
                group["total_hours"] += float(hours or 0)
                group["projects_set"].add(row["codigo"])
        result = []
        for group in groups.values():
            group["proyectos"] = len(group.pop("projects_set"))
            result.append(group)
        return result

    def _by_deliverable(self, rows: list[dict]) -> list[dict]:
        return [
            {
                "key": row["deliverable"], "proyecto": row["codigo"],
                "codigo_proyecto": row["codigo"], "disciplina": row["disciplina"],
                "tipo_servicio": row.get("tipo_servicio"),
                "tipo_servicio_source": row.get("tipo_servicio_source"),
                "clasificacion": row.get("classification"),
                "tipo_entregable": row.get("tipo_entregable"), "area": row.get("area"),
                "total_hours": row["total_hours"], "roles": row["roles"],
                "source_type": row["source_type"], "source_file": row["source_file"],
            }
            for row in rows
        ]

    def _filter_rows(self, rows: list[dict], **filters: Any) -> list[dict]:
        code = _norm(filters.get("codigo"))
        client = _norm(filters.get("cliente"))
        service = _norm(filters.get("tipo_servicio"))
        discipline = _norm(filters.get("disciplina"))
        text = _norm(filters.get("text"))
        result = []
        for row in rows:
            if code and code not in _norm(f"{row.get('codigo')} {row.get('cod_proy')}"):
                continue
            if client and client not in _norm(row.get("cliente")):
                continue
            if service and service != _norm(row.get("tipo_servicio")):
                continue
            if discipline and discipline not in _norm(row.get("disciplina")):
                continue
            haystack = " ".join(str(row.get(key) or "") for key in (
                "codigo", "deliverable", "disciplina", "classification", "tipo_entregable", "area", "titulo", "cliente"
            ))
            if text and text not in _norm(haystack):
                continue
            result.append(row)
        return result

    def _real_result(self, view: str, rows: list[dict], available: int | None) -> dict:
        rows.sort(key=lambda row: -float(row.get("total_hours") or 0))
        total = sum(float(row.get("total_hours") or 0) for row in rows)
        for row in rows:
            row["pct_hours"] = round(float(row.get("total_hours") or 0) * 100 / total, 2) if total else 0
        return {
            "source": "staffing", "view": view, "rows": rows,
            "available_rows": int(available if available is not None else len(rows)),
            "totals": {"rows": len(rows), "total_hours": round(total, 2)},
            "note": "HH reales consultadas en Staffing; no provienen del lector de Excel.",
        }

    # ---- Master links / helpers ------------------------------------------------

    def _offer_rows(self, conn: sqlite3.Connection) -> dict[str, dict]:
        result = {}
        for row in conn.execute(
            "select codigo,titulo,cliente_directo,cliente_final,tipo_servicio,estado,cod_proy,horas_lic,monto from oferta"
        ):
            service, service_source = _resolve_service(row["tipo_servicio"], row["titulo"])
            result[row["codigo"]] = {
                "titulo": row["titulo"], "cliente": self._client(row["cliente_directo"], row["cliente_final"]),
                "tipo_servicio": service, "tipo_servicio_source": service_source, "estado": row["estado"],
                "cod_proy": row["cod_proy"], "horas_lic_master": _number(row["horas_lic"]),
                "monto_master": _number(row["monto"]),
            }
        return result

    def _resolve_staffing_code(self, codigo: str | None) -> str | None:
        value = str(codigo or "").strip().upper()
        if not value:
            return None
        if value.startswith("SH-"):
            return value
        if value.startswith("O-"):
            with closing(self._connect()) as conn:
                row = conn.execute("select cod_proy from oferta where codigo=?", (value,)).fetchone()
            if row and row[0] and _norm(row[0]) != "no data":
                number = re.search(r"\d+", str(row[0]))
                if number:
                    return f"SH-{int(number.group()):04d}"
        return value

    def _master_for_staffing_code(self, code: object) -> dict | None:
        digits = re.search(r"\d+", str(code or ""))
        if not digits:
            return None
        number = str(int(digits.group()))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "select codigo,titulo,cliente_directo,cliente_final,tipo_servicio,horas_lic,cod_proy "
                "from oferta where cast(replace(replace(cod_proy,'.0',''),'SH-','') as integer)=? "
                "order by case when estado='PG' then 0 else 1 end limit 1",
                (int(number),),
            ).fetchone()
        if not rows:
            return None
        return {
            "codigo": rows["codigo"], "titulo": rows["titulo"],
            "cliente": self._client(rows["cliente_directo"], rows["cliente_final"]),
            "tipo_servicio": _clean_service(rows["tipo_servicio"]),
            "horas_lic": _number(rows["horas_lic"]), "cod_proy": rows["cod_proy"],
        }

    def _add_comparison(self, row: dict) -> None:
        extracted = _number(row.get("total_hours"))
        master = _number(row.get("horas_lic_master"))
        row["delta_hours"] = round(extracted - master, 2) if extracted is not None and master else None
        row["match_master_pct"] = round(extracted * 100 / master, 1) if extracted is not None and master else None
        if row["match_master_pct"] is None:
            row["comparison_status"] = "sin_master"
        else:
            deviation = abs(row["match_master_pct"] - 100)
            row["comparison_status"] = "match" if deviation <= 10 else "review" if deviation <= 25 else "mismatch"
        row["sospechoso"] = row["comparison_status"] == "mismatch"

    def _budget_reader_available(self) -> bool:
        try:
            from app.services.budget_extractor_client import BudgetExtractorClient
            return BudgetExtractorClient().available
        except Exception:
            return False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _client(direct: object, final: object) -> str | None:
        for value in (final, direct):
            text = str(value or "").strip()
            if text and _norm(text) != "no data":
                return text
        return None

    @staticmethod
    def _sum_cargos_sql() -> str:
        return " + ".join(f"coalesce({cargo},0)" for cargo in CARGOS)
