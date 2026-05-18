"""Repositorio agregador para la vista "Entregables".

Combina dos fuentes:
  - **Licitadas (local)** — tabla `hh_estimate_rows` (185k filas extraídas de Excels de propuesta)
  - **Reales (staffing)** — API externa, vía `StaffingClient`

Soporta cuatro modos de pivote:
  - by_proyecto    — agrupa por código de propuesta
  - by_disciplina  — agrupa por disciplina
  - by_role        — agrupa por rol/profesional (solo licitadas — el local NO tiene persona)
  - by_entregable  — top entregables por horas
  - by_persona     — solo en modo reales (delegamos a staffing)

Path adaptable: lee `settings.hh_excel_source`. Hoy es path local; si en el futuro
los Excels viven en blob, el setter solo cambia el env var y el extractor baja a cache.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core.config import settings


class EntregablesRepository:
    def __init__(self) -> None:
        self.sqlite_path = settings.sqlite_path

    # ---- agregaciones licitadas (DB local) ----

    def aggregate_licitadas(
        self,
        view: str = "proyecto",
        codigo: str | None = None,
        cliente: str | None = None,
        disciplina: str | None = None,
        text: str | None = None,
        min_hours: float = 0.0,
        limit: int = 100,
    ) -> dict:
        """Pivota `hh_estimate_rows`. `view` ∈ {proyecto, disciplina, role, entregable}."""
        where, params = self._build_where(codigo=codigo, disciplina=disciplina, text=text, min_hours=min_hours)
        join = ""
        if cliente:
            # Master tiene cliente; lo cruzamos para filtrar
            join = "join master_offers m on m.codigo = h.codigo"
            where.append("(m.cliente_directo like ? or m.cliente_final like ?)")
            cli = f"%{cliente}%"
            params.extend([cli, cli])

        where_clause = (" where " + " and ".join(where)) if where else ""

        if view == "proyecto":
            sql = f"""
                select h.codigo as key,
                       count(*) as rows,
                       sum(coalesce(h.hours,0)) as total_hours,
                       sum(coalesce(h.amount,0)) as total_amount,
                       count(distinct h.discipline) as disciplinas,
                       count(distinct h.deliverable) as entregables,
                       group_concat(distinct h.discipline) as disciplina_list
                from hh_estimate_rows h
                {join}
                {where_clause}
                group by h.codigo
                order by total_hours desc
                limit ?
            """
        elif view == "disciplina":
            sql = f"""
                select coalesce(nullif(h.discipline,''), '(sin disciplina)') as key,
                       count(*) as rows,
                       sum(coalesce(h.hours,0)) as total_hours,
                       sum(coalesce(h.amount,0)) as total_amount,
                       count(distinct h.codigo) as proyectos,
                       count(distinct h.deliverable) as entregables
                from hh_estimate_rows h
                {join}
                {where_clause}
                group by coalesce(nullif(h.discipline,''), '(sin disciplina)')
                order by total_hours desc
                limit ?
            """
        elif view == "role":
            sql = f"""
                select coalesce(nullif(h.role,''), '(sin rol)') as key,
                       count(*) as rows,
                       sum(coalesce(h.hours,0)) as total_hours,
                       sum(coalesce(h.amount,0)) as total_amount,
                       count(distinct h.codigo) as proyectos
                from hh_estimate_rows h
                {join}
                {where_clause}
                group by coalesce(nullif(h.role,''), '(sin rol)')
                order by total_hours desc
                limit ?
            """
        elif view == "entregable":
            sql = f"""
                select coalesce(nullif(h.deliverable,''), nullif(h.activity,'')) as key,
                       h.codigo as proyecto,
                       h.discipline as disciplina,
                       count(*) as rows,
                       sum(coalesce(h.hours,0)) as total_hours,
                       sum(coalesce(h.amount,0)) as total_amount
                from hh_estimate_rows h
                {join}
                {where_clause}
                group by h.codigo, coalesce(nullif(h.deliverable,''), nullif(h.activity,''))
                having total_hours > 0
                order by total_hours desc
                limit ?
            """
        else:
            return {"error": f"view '{view}' no soportada (usar proyecto|disciplina|role|entregable)"}

        params.append(limit)

        with sqlite3.connect(self.sqlite_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        total_hours = sum(r.get("total_hours") or 0 for r in rows)
        total_amount = sum(r.get("total_amount") or 0 for r in rows)
        for r in rows:
            r["pct_hours"] = round((r.get("total_hours") or 0) * 100.0 / total_hours, 2) if total_hours else 0
            r["pct_amount"] = round((r.get("total_amount") or 0) * 100.0 / total_amount, 2) if total_amount else 0

        return {
            "fuente": "licitadas",
            "view": view,
            "rows": rows,
            "totals": {
                "rows": len(rows),
                "total_hours": total_hours,
                "total_amount": total_amount,
            },
            "filters_applied": {
                "codigo": codigo,
                "cliente": cliente,
                "disciplina": disciplina,
                "text": text,
                "min_hours": min_hours,
            },
            "source_path": settings.hh_excel_source,
            "note": "HH licitadas extraídas de Excels de oferta. NO incluyen persona individual (solo rol/cargo).",
        }

    # ---- agregaciones reales (Staffing API) ----

    async def aggregate_reales(
        self,
        view: str = "proyecto",
        codigo: str | None = None,
        disciplina: str | None = None,
        text: str | None = None,
        ano: int | None = None,
        top: int = 100,
    ) -> dict:
        """Delega a Staffing API. `view` ∈ {proyecto, disciplina, entregable, persona}."""
        from app.services.staffing_client import StaffingClient

        client = StaffingClient()
        if not client.available:
            return {
                "error": "STAFFING_API_KEY no configurada — no se pueden obtener HH reales",
                "fuente": "reales",
                "rows": [],
            }

        if view == "persona" and codigo:
            data = await client.personas_proyecto(codigo, ano=ano, con_detalle=True)
            personas = (data.get("personas") if isinstance(data, dict) else None) or []
            total_hours = sum((p.get("horas_totales") or 0) for p in personas)
            rows = []
            for p in personas:
                hours = p.get("horas_totales") or 0
                rows.append({
                    "key": p.get("nombre") or p.get("usuario_id"),
                    "usuario_id": p.get("usuario_id"),
                    "disciplina": p.get("disciplina"),
                    "rol": p.get("rol"),
                    "total_hours": hours,
                    "pct_hours": round(hours * 100.0 / total_hours, 2) if total_hours else 0,
                    "entregables": p.get("entregables_count"),
                })
            rows.sort(key=lambda r: r["total_hours"], reverse=True)
            return {
                "fuente": "reales",
                "view": "persona",
                "rows": rows[:top],
                "totals": {"rows": len(rows), "total_hours": total_hours},
                "proyecto": codigo,
            }

        if view == "entregable" or text or disciplina:
            data = await client.analisis_hh(
                q=text,
                disciplina=disciplina,
                proyecto_codigo=codigo,
                ano=ano,
                top=top,
                incluir_personas=False,
            )
            items = (data.get("items") or data.get("entregables") or []) if isinstance(data, dict) else []
            total_hours = sum((e.get("horas_totales") or e.get("horas") or 0) for e in items)
            rows = []
            for e in items:
                hours = e.get("horas_totales") or e.get("horas") or 0
                rows.append({
                    "key": e.get("nombre") or e.get("descripcion") or e.get("id"),
                    "proyecto": e.get("proyecto_codigo") or e.get("codigo"),
                    "disciplina": e.get("disciplina"),
                    "total_hours": hours,
                    "pct_hours": round(hours * 100.0 / total_hours, 2) if total_hours else 0,
                    "personas": e.get("personas_count"),
                })
            rows.sort(key=lambda r: r["total_hours"], reverse=True)
            return {
                "fuente": "reales",
                "view": "entregable",
                "rows": rows[:top],
                "totals": {"rows": len(rows), "total_hours": total_hours},
            }

        if view == "proyecto":
            data = await client.listar_proyectos(activo=None, limit=top)
            proyectos = (data.get("proyectos") or data.get("items") or []) if isinstance(data, dict) else []
            rows = [{
                "key": p.get("codigo"),
                "titulo": p.get("nombre") or p.get("titulo"),
                "cliente": p.get("cliente"),
                "total_hours": p.get("horas_cargadas") or p.get("hh_total"),
                "personas": p.get("personas_count"),
                "entregables": p.get("entregables_count"),
                "activo": p.get("activo"),
            } for p in proyectos]
            return {"fuente": "reales", "view": "proyecto", "rows": rows, "totals": {"rows": len(rows)}}

        return {"error": f"view '{view}' no soportada en modo reales", "rows": []}

    # ---- helpers ----

    def _build_where(self, codigo, disciplina, text, min_hours):
        where: list[str] = []
        params: list[Any] = []
        if codigo:
            where.append("upper(h.codigo) = ?")
            params.append(codigo.strip().upper())
        if disciplina:
            where.append("h.discipline like ?")
            params.append(f"%{disciplina}%")
        if text:
            where.append("(h.deliverable like ? or h.activity like ? or h.raw_text like ?)")
            v = f"%{text}%"
            params.extend([v, v, v])
        if min_hours and min_hours > 0:
            where.append("coalesce(h.hours,0) >= ?")
            params.append(float(min_hours))
        # Solo filas plausibles: confianza mínima + horas/monto en rangos creíbles.
        # Evita filas garbage extraídas del Excel (códigos con 100M horas, etc).
        where.append("h.confidence >= 0.65")
        where.append("(h.hours is null or (h.hours > 0 and h.hours <= 20000))")
        where.append("(h.amount is null or (h.amount >= 0 and h.amount <= 100000000))")
        return where, params

    def stats(self) -> dict:
        """Estadísticas globales — para el header de la vista."""
        with sqlite3.connect(self.sqlite_path, timeout=10) as conn:
            row = conn.execute(
                """
                select count(*) total_rows,
                       count(distinct codigo) total_proyectos,
                       count(distinct discipline) total_disciplinas,
                       count(distinct nullif(role,'')) total_roles,
                       sum(coalesce(hours,0)) total_hours,
                       sum(coalesce(amount,0)) total_amount
                from hh_estimate_rows
                where confidence >= 0.65
                  and (hours is null or (hours > 0 and hours <= 20000))
                """
            ).fetchone()
        return {
            "rows": row[0],
            "proyectos": row[1],
            "disciplinas": row[2],
            "roles": row[3],
            "total_hours": row[4],
            "total_amount": row[5],
            "source_path": settings.hh_excel_source,
        }

    def list_disciplines(self, limit: int = 50) -> list[str]:
        with sqlite3.connect(self.sqlite_path, timeout=10) as conn:
            rows = conn.execute(
                """
                select discipline, sum(coalesce(hours,0)) h
                from hh_estimate_rows
                where confidence >= 0.6 and discipline is not null and discipline != ''
                group by discipline
                order by h desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [r[0] for r in rows]
