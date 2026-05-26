"""Repositorio de entregables — usa la tabla `proyectos` (la real).

Esquema (`pragma table_info(proyectos)`):
  - codigo (O-XXXX) · descripcion · clasificacion ("Actividad"|"Documento") · estado
  - factor (multiplicador 1-160)
  - **columnas de cargo con HH licitadas**: dc, pl, gl, jp, ji, jd, abim, cbim, ec,
    cn, esp, ia, ib, ic, pa, pb, cp, cd, ce, i, c, db, pc
  - FKs: tipo_id → tipo · id_area → area · id_actividad → actividad_main · categoria_reg_id → categoria_reg

Cruzamos con `oferta` por codigo para traer cliente, título, tipo_servicio, estado, monto.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core.config import settings


# Columnas de la tabla `proyectos` que representan HH por cargo profesional.
# DC/PL/GL están EXCLUIDOS — son flags de tipo de entregable (Documento/Plano/Actividad),
# no cargos. Sumarlos infla los totales y duplica info de `clasificacion`.
CARGOS = [
    "jp", "ji", "jd", "abim", "cbim", "ec", "cn", "esp",
    "ia", "ib", "ic", "pa", "pb", "cp", "cd", "ce", "i", "c", "db", "pc",
]

# Flags de tipo de entregable en la tabla `proyectos` (no son HH)
TIPO_FLAGS = {"dc": "Documento", "pl": "Plano", "gl": "Actividad"}

# Suma SQL de todos los cargos (HH totales de una fila)
SUM_CARGOS_SQL = " + ".join(f"coalesce({c},0)" for c in CARGOS)


class EntregablesRepository:
    def __init__(self) -> None:
        self.sqlite_path = settings.sqlite_path

    # ---- 1. Lista de proyectos con HH totales (para el selector) ----

    def listar_proyectos(self, query: str | None = None, limit: int = 500) -> dict:
        """Devuelve cada proyecto con total HH, n° de entregables, cliente y servicio.

        Para el dropdown / selector. Filtra por código o texto en descripción si se da.
        """
        params: list[Any] = []
        extra_where = ""
        if query:
            extra_where = "where p.codigo like ? or p.descripcion like ? or o.titulo like ? or o.cliente_directo like ?"
            v = f"%{query}%"
            params.extend([v, v, v, v])

        sql = f"""
            select p.codigo,
                   max(o.titulo) as titulo,
                   max(coalesce(nullif(o.cliente_directo,'No data'), nullif(o.cliente_final,'No data'))) as cliente,
                   max(nullif(o.tipo_servicio,'No data')) as tipo_servicio,
                   max(o.estado) as estado,
                   count(*) as entregables,
                   sum(case when p.clasificacion='Documento' then 1 else 0 end) as documentos,
                   sum(case when p.clasificacion='Actividad' then 1 else 0 end) as actividades,
                   sum({SUM_CARGOS_SQL}) as total_hh
            from proyectos p
            left join oferta o on o.codigo = p.codigo
            {extra_where}
            group by p.codigo
            order by total_hh desc
            limit ?
        """
        params.append(limit)
        with sqlite3.connect(self.sqlite_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        return {"rows": rows, "count": len(rows)}

    # ---- 2. Detalle de un proyecto: entregables + HH por cargo ----

    def detalle_proyecto(self, codigo: str, only: str | None = None) -> dict:
        """Devuelve los entregables/actividades de un proyecto con HH desglosadas por cargo.

        `only` ∈ {None, 'Actividad', 'Documento'} — filtra por clasificación.
        Incluye:
          - meta del proyecto (cliente, título, servicio) desde oferta
          - filas (cada entregable con sus HH por cargo)
          - resumen por cargo (suma + % a través del proyecto)
          - resumen por clasificación
          - resumen por tipo de documento (JOIN con `tipo`)
        """
        codigo = (codigo or "").strip().upper()
        if not codigo:
            return {"error": "Código vacío", "codigo": None}

        cargo_cols = ", ".join(f"p.{c}" for c in CARGOS)
        sql_rows = f"""
            select p.id, p.descripcion, p.clasificacion, p.factor, p.estado,
                   p.tipo_id, p.id_area, p.id_actividad, p.categoria_reg_id,
                   t.nombre as tipo_nombre,
                   a.area as area_nombre,
                   am.nombre_act as actividad_nombre,
                   {cargo_cols},
                   ({SUM_CARGOS_SQL}) as total_hh
            from proyectos p
            left join tipo t on t.id = p.tipo_id
            left join area a on a.id = p.id_area
            left join actividad_main am on am.id = p.id_actividad
            where p.codigo = ?
              {"and p.clasificacion = ?" if only else ""}
            order by total_hh desc, p.descripcion
        """
        params: list[Any] = [codigo]
        if only:
            params.append(only)

        with sqlite3.connect(self.sqlite_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            entregables = [dict(r) for r in conn.execute(sql_rows, params).fetchall()]
            meta_row = conn.execute(
                """
                select codigo, titulo, cliente_directo, cliente_final, tipo_servicio,
                       estado, monto, horas_lic, cod_proy, fecha_recep
                from oferta where codigo = ?
                """,
                (codigo,),
            ).fetchone()
            meta = dict(meta_row) if meta_row else None

        if not entregables:
            return {
                "codigo": codigo,
                "found": False,
                "message": f"No hay entregables registrados en `proyectos` para {codigo}",
                "meta": meta,
            }

        # Detecta cargos efectivamente usados en este proyecto (para no mostrar columnas vacías)
        cargos_usados = []
        cargos_totales: dict[str, float] = {}
        total_proyecto = 0.0
        for c in CARGOS:
            s = sum((row.get(c) or 0) for row in entregables)
            if s > 0:
                cargos_usados.append(c)
                cargos_totales[c] = s
                total_proyecto += s

        cargos_pct = {
            c: round(v * 100.0 / total_proyecto, 2) if total_proyecto else 0
            for c, v in cargos_totales.items()
        }

        # Resumen por clasificación
        por_clasificacion: dict[str, dict] = {}
        for row in entregables:
            cls = row.get("clasificacion") or "(sin)"
            d = por_clasificacion.setdefault(cls, {"filas": 0, "hh": 0.0})
            d["filas"] += 1
            d["hh"] += row.get("total_hh") or 0

        # Resumen por tipo de documento
        por_tipo: dict[str, dict] = {}
        for row in entregables:
            tipo = row.get("tipo_nombre") or "(sin tipo)"
            d = por_tipo.setdefault(tipo, {"filas": 0, "hh": 0.0})
            d["filas"] += 1
            d["hh"] += row.get("total_hh") or 0

        return {
            "codigo": codigo,
            "found": True,
            "meta": meta,
            "entregables": entregables,
            "cargos_usados": cargos_usados,
            "resumen_cargos": [
                {"cargo": c, "hh": cargos_totales[c], "pct": cargos_pct[c]}
                for c in sorted(cargos_usados, key=lambda c: cargos_totales[c], reverse=True)
            ],
            "resumen_clasificacion": [
                {"clasificacion": k, "filas": v["filas"], "hh": v["hh"],
                 "pct": round(v["hh"] * 100.0 / total_proyecto, 2) if total_proyecto else 0}
                for k, v in sorted(por_clasificacion.items(), key=lambda kv: -kv[1]["hh"])
            ],
            "resumen_tipo": [
                {"tipo": k, "filas": v["filas"], "hh": v["hh"],
                 "pct": round(v["hh"] * 100.0 / total_proyecto, 2) if total_proyecto else 0}
                for k, v in sorted(por_tipo.items(), key=lambda kv: -kv[1]["hh"])
            ],
            "total_entregables": len(entregables),
            "total_hh": total_proyecto,
        }

    # ---- 3. Stats globales (para el header de la vista) ----

    def stats(self) -> dict:
        with sqlite3.connect(self.sqlite_path, timeout=10) as conn:
            row = conn.execute(
                f"""
                select count(distinct codigo) proyectos,
                       count(*) entregables,
                       sum(case when clasificacion='Documento' then 1 else 0 end) documentos,
                       sum(case when clasificacion='Actividad' then 1 else 0 end) actividades,
                       sum({SUM_CARGOS_SQL}) total_hh
                from proyectos
                """
            ).fetchone()
        return {
            "proyectos": row[0],
            "entregables": row[1],
            "documentos": row[2],
            "actividades": row[3],
            "total_hh": row[4],
            "fuente": "tabla `proyectos`",
        }

    # ---- 4. Top proyectos por tamaño (para ayudar al usuario a elegir) ----

    def top_proyectos(self, limit: int = 20, cliente: str | None = None, tipo_servicio: str | None = None) -> dict:
        params: list[Any] = []
        where = []
        if cliente:
            where.append("(o.cliente_directo like ? or o.cliente_final like ?)")
            v = f"%{cliente}%"
            params.extend([v, v])
        if tipo_servicio:
            where.append("o.tipo_servicio = ?")
            params.append(tipo_servicio)
        where_clause = ("where " + " and ".join(where)) if where else ""
        sql = f"""
            select p.codigo,
                   max(o.titulo) titulo,
                   max(coalesce(nullif(o.cliente_directo,'No data'), nullif(o.cliente_final,'No data'))) cliente,
                   max(nullif(o.tipo_servicio,'No data')) tipo_servicio,
                   count(*) entregables,
                   sum({SUM_CARGOS_SQL}) total_hh
            from proyectos p
            left join oferta o on o.codigo = p.codigo
            {where_clause}
            group by p.codigo
            order by total_hh desc
            limit ?
        """
        params.append(limit)
        with sqlite3.connect(self.sqlite_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        return {"rows": rows, "count": len(rows)}
