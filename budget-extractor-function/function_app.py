"""Azure Function — Budget Extractor.

Extrae tablas estructuradas (entregables · tarifas · reembolsables) de Excels de oferta
y devuelve JSON normalizado al formato canónico de la tabla `proyectos` del backend.

Endpoints:
  POST /api/extract          — recibe Excel multipart, devuelve tablas extraídas
  POST /api/extract-normalized — devuelve directo en formato `proyectos` (1 fila por entregable × cargo)
  GET  /api/health           — ping

Auth: header `x-api-key` debe coincidir con `BUDGET_EXTRACTOR_API_KEY` (App Setting).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

import azure.functions as func

from portable_table_extractor.excel_table_extractor import ExcelTableExtractor
from portable_table_extractor.schemas import TableType


app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


# Códigos canónicos de cargo profesional — los que llevan HH reales.
# IMPORTANTE: DC/PL/GL NO son cargos, son flags de tipo de entregable:
#   DC = Documento de Cálculo · PL = Plano · GL = Actividad General
# Por eso los excluimos: si vienen en la tabla del Excel, se mapean a `tipo_entregable`,
# no a HH-por-cargo. Si no, contaminamos la suma y duplicamos horas.
CARGOS_CANONICOS = {
    "JP", "JI", "JD", "ABIM", "CBIM", "EC", "CN", "ESP",
    "IA", "IB", "IC", "PA", "PB", "CP", "CD", "CE", "I", "C", "DB", "PC",
    "DA", "CA", "CB", "GP", "DI", "SI",
}

# Flags de clasificación / tipo de entregable (no son HH de profesionales)
TIPO_ENTREGABLE_FLAGS = {
    "DC": "Documento",
    "PL": "Plano",
    "GL": "Actividad",
}


def _check_auth(req: func.HttpRequest) -> tuple[bool, str]:
    expected = os.getenv("BUDGET_EXTRACTOR_API_KEY", "")
    if not expected:
        return True, ""  # sin key configurada — modo abierto (solo dev)
    received = req.headers.get("x-api-key") or req.params.get("api_key") or ""
    if received != expected:
        return False, "x-api-key inválida o ausente"
    return True, ""


def _json(payload: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False, default=str),
        status_code=status,
        mimetype="application/json",
    )


def _read_uploaded_file(req: func.HttpRequest) -> tuple[bytes | None, str, str | None]:
    """Lee el archivo Excel del request (multipart o raw body). Devuelve (content, filename, error)."""
    try:
        files = req.files
    except Exception:
        files = {}
    if files:
        for key in ("file", "excel", "upload"):
            f = files.get(key)
            if f is not None:
                return f.read(), getattr(f, "filename", "uploaded.xlsx"), None
    body = req.get_body()
    if body and len(body) > 100:
        filename = req.headers.get("x-filename", "uploaded.xlsx")
        return body, filename, None
    return None, "", "No se recibió archivo. Envía multipart con campo 'file' o raw body con x-filename header."


def _extract(file_bytes: bytes, filename: str) -> dict:
    """Corre el extractor sobre los bytes del Excel."""
    suffix = Path(filename).suffix.lower() or ".xlsx"
    if suffix not in {".xlsx", ".xls", ".xlsm"}:
        raise ValueError(f"Formato no soportado: {suffix}")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        extractor = ExcelTableExtractor(tmp_path, use_ai=False)
        result = extractor.process()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    entregables = [t for t in result.tables if t.table_type == TableType.ENTREGABLES]
    tarifas = [t for t in result.tables if t.table_type == TableType.TARIFAS]
    gastos = [t for t in result.tables if t.table_type == TableType.GASTOS]
    presupuesto = [t for t in result.tables if t.table_type == TableType.PRESUPUESTO]

    return {
        "file_name": filename,
        "processing_time": result.processing_time_seconds,
        "summary": result.get_summary(),
        "entregables": [_table_dict(t) for t in entregables],
        "tarifas": [_table_dict(t) for t in tarifas],
        "gastos_reembolsables": [_table_dict(t) for t in gastos],
        "presupuesto": [_table_dict(t) for t in presupuesto],
    }


def _table_dict(t) -> dict:
    return {
        "sheet": t.sheet_name,
        "confidence": t.confidence,
        "num_rows": t.num_rows,
        "rows": t.data,
        "method": t.detection_method,
    }


def _normalize_cargo(code: str | None) -> tuple[str, str]:
    """Devuelve (cargo_canonico_o_UNKNOWN, cargo_raw)."""
    raw = (code or "").strip().upper()
    if raw in CARGOS_CANONICOS:
        return raw, raw
    return "UNKNOWN", raw


def _pick_best_entregables_table(tables: list[dict]) -> list[dict]:
    """Si el Excel tiene múltiples hojas con entregables (Rev 0, Rev 1, copia...),
    selecciona UNA — la que tenga mayor confidence; con empate, la última en orden
    (asume orden natural del workbook). Evita doble-conteo por revisiones.
    """
    if not tables:
        return []
    if len(tables) == 1:
        return tables
    indexed = list(enumerate(tables))
    indexed.sort(key=lambda x: (-(x[1].get("confidence") or 0), -x[0]))
    return [indexed[0][1]]


def _es_agregador(row: dict, all_items: list[str]) -> bool:
    """Detecta si una fila es un agregador/título de sección (no un entregable real).

    Heurística:
      - Si su `item` es de nivel 1 (ej. "1", "2") Y existen hijos suyos en la lista
        (ej. "1.1", "1.2", ...), es agregador → su HH es la suma de los hijos.
      - Si su descripción es TODO MAYÚSCULAS y tiene HH muy altas (>200), probable
        cabecera de área.
    """
    item = (row.get("item") or "").strip()
    if item and "." not in item and not item.isalpha():
        # Es nivel 1 numérico. Busca hijos "item.X"
        prefix = item + "."
        children = [it for it in all_items if it and it.startswith(prefix)]
        if children:
            return True
    desc = (row.get("description") or "").strip()
    if desc and desc.upper() == desc and len(desc) >= 5:
        # Heurística suave: descripciones todo MAYÚSCULAS sin tilde de entregable normal
        man_hours = row.get("man_hours") or {}
        try:
            total_hh = sum(float(v or 0) for v in man_hours.values())
        except (TypeError, ValueError):
            total_hh = 0
        if total_hh > 200:
            return True
    return False


def _to_proyectos_format(extracted: dict, codigo: str | None) -> dict:
    """Normaliza la salida al formato canónico de la tabla `proyectos`:
      proyecto_filas: 1 fila por entregable × cargo con HH > 0
      tarifas_filas:  1 fila por cargo con tarifa
      gastos_filas:   1 fila por concepto reembolsable

    Reglas:
      - Si el Excel tiene varias hojas de entregables (Rev 0 + Rev 1 + copia), se elige UNA
        (la de mayor confidence). Evita doble-conteo.
      - `DC/PL/GL` en man_hours NO se cuentan como cargo: se usan para inferir `clasificacion`
        del entregable (Documento/Plano/Actividad). Si vienen con valor > 0, marcan el tipo.
    """
    entregables_tabs = _pick_best_entregables_table(extracted.get("entregables", []))

    proyecto_filas: list[dict] = []
    descartados: list[dict] = []  # auditoría: lo que se descartó por estar fuera de cargos canónicos
    agregadores: list[dict] = []  # auditoría: agregadores/títulos que se excluyeron para no doble-contar
    for tabla in entregables_tabs:
        sheet = tabla.get("sheet")
        conf = tabla.get("confidence")
        all_items = [(r.get("item") or "").strip() for r in tabla.get("rows", [])]
        for row in tabla.get("rows", []):
            if _es_agregador(row, all_items):
                agregadores.append({
                    "item": row.get("item"),
                    "descripcion": (row.get("description") or "")[:120],
                })
                continue
            descripcion = (row.get("description") or row.get("item") or "").strip()
            if not descripcion:
                continue
            man_hours = row.get("man_hours") or {}

            # Inferir clasificación: si vienen DC/PL/GL > 0, usar el flag más fuerte;
            # si no, leer del campo `clasificacion` o `type` del row.
            clasif_inferida = None
            for flag_code, flag_label in TIPO_ENTREGABLE_FLAGS.items():
                try:
                    flag_val = float(man_hours.get(flag_code) or man_hours.get(flag_code.lower()) or 0)
                except (TypeError, ValueError):
                    flag_val = 0
                if flag_val > 0:
                    clasif_inferida = flag_label
                    break
            clasif = clasif_inferida or row.get("clasificacion") or row.get("type") or None

            for cargo_raw, hh in man_hours.items():
                # Saltar flags de tipo de entregable
                if (cargo_raw or "").strip().upper() in TIPO_ENTREGABLE_FLAGS:
                    continue
                try:
                    hh_num = float(hh or 0)
                except (TypeError, ValueError):
                    continue
                if hh_num <= 0:
                    continue
                cargo, raw = _normalize_cargo(cargo_raw)
                if cargo == "UNKNOWN":
                    descartados.append({"descripcion": descripcion[:80], "cargo_raw": raw, "hh": hh_num})
                    continue
                proyecto_filas.append({
                    "codigo": codigo,
                    "descripcion": descripcion[:300],
                    "clasificacion": clasif,
                    "cargo": cargo,
                    "cargo_raw": raw,
                    "hh": hh_num,
                    "item": row.get("item"),
                    "source_sheet": sheet,
                    "confidence": conf,
                })

    tarifas_filas: list[dict] = []
    for tabla in extracted.get("tarifas", []):
        sheet = tabla.get("sheet")
        conf = tabla.get("confidence")
        for row in tabla.get("rows", []):
            cargo_raw = row.get("role_code") or row.get("code") or row.get("rol")
            if not cargo_raw:
                continue
            try:
                tarifa = float(row.get("rate") or row.get("tarifa") or 0)
            except (TypeError, ValueError):
                tarifa = None
            if not tarifa or tarifa <= 0:
                continue
            cargo, raw = _normalize_cargo(cargo_raw)
            tarifas_filas.append({
                "codigo": codigo,
                "cargo": cargo,
                "cargo_raw": raw,
                "nombre_profesional": row.get("original_description") or row.get("profesional"),
                "tarifa": tarifa,
                "moneda": (row.get("currency") or row.get("moneda") or "CLP").upper(),
                "source_sheet": sheet,
                "confidence": conf,
            })

    gastos_filas: list[dict] = []
    for tabla in extracted.get("gastos_reembolsables", []):
        sheet = tabla.get("sheet")
        conf = tabla.get("confidence")
        for row in tabla.get("rows", []):
            concepto = (row.get("concepto") or row.get("description") or row.get("item") or "").strip()
            if not concepto:
                continue
            try:
                cantidad = float(row.get("cantidad") or row.get("quantity") or 0) or None
            except (TypeError, ValueError):
                cantidad = None
            try:
                precio = float(row.get("precio_unit") or row.get("unit_price") or 0) or None
            except (TypeError, ValueError):
                precio = None
            try:
                total = float(row.get("total") or row.get("amount") or 0) or None
            except (TypeError, ValueError):
                total = None
            if not (total or precio):
                continue
            gastos_filas.append({
                "codigo": codigo,
                "concepto": concepto[:200],
                "cantidad": cantidad,
                "precio_unit": precio,
                "total": total or (cantidad * precio if cantidad and precio else None),
                "moneda": (row.get("currency") or row.get("moneda") or "CLP").upper(),
                "source_sheet": sheet,
                "confidence": conf,
            })

    return {
        "codigo": codigo,
        "file_name": extracted.get("file_name"),
        "processed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "totals": {
            "proyecto_filas": len(proyecto_filas),
            "tarifas_filas": len(tarifas_filas),
            "gastos_filas": len(gastos_filas),
            "descartados": len(descartados),
        },
        "proyecto_filas": proyecto_filas,
        "tarifas_filas": tarifas_filas,
        "gastos_filas": gastos_filas,
        "descartados": descartados,
        "agregadores_excluidos": agregadores,
        "entregables_sheet_seleccionado": entregables_tabs[0].get("sheet") if entregables_tabs else None,
        "entregables_sheets_disponibles": [t.get("sheet") for t in extracted.get("entregables", [])],
        "_summary": extracted.get("summary"),
        "_processing_time": extracted.get("processing_time"),
    }


# ---- Rutas ----

@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _json({
        "status": "ok",
        "service": "budget-extractor-function",
        "version": "1.0.0",
        "auth_required": bool(os.getenv("BUDGET_EXTRACTOR_API_KEY")),
    })


@app.route(route="extract", methods=["POST"])
def extract(req: func.HttpRequest) -> func.HttpResponse:
    """Recibe Excel, devuelve tablas extraídas raw (sin normalizar)."""
    ok, err = _check_auth(req)
    if not ok:
        return _json({"error": err}, 401)
    file_bytes, filename, err = _read_uploaded_file(req)
    if err:
        return _json({"error": err}, 400)
    try:
        return _json({"success": True, **_extract(file_bytes, filename)})
    except ValueError as exc:
        return _json({"error": str(exc)}, 400)
    except Exception as exc:
        logging.exception("Error extrayendo")
        return _json({"error": f"{type(exc).__name__}: {exc}"}, 500)


@app.route(route="extract-normalized", methods=["POST"])
def extract_normalized(req: func.HttpRequest) -> func.HttpResponse:
    """Recibe Excel + `codigo` (query o header `x-codigo`), devuelve tablas en formato proyectos."""
    ok, err = _check_auth(req)
    if not ok:
        return _json({"error": err}, 401)
    codigo = (req.params.get("codigo") or req.headers.get("x-codigo") or "").strip().upper() or None
    file_bytes, filename, err = _read_uploaded_file(req)
    if err:
        return _json({"error": err}, 400)
    try:
        extracted = _extract(file_bytes, filename)
        normalized = _to_proyectos_format(extracted, codigo)
        return _json({"success": True, **normalized})
    except ValueError as exc:
        return _json({"error": str(exc)}, 400)
    except Exception as exc:
        logging.exception("Error normalizando")
        return _json({"error": f"{type(exc).__name__}: {exc}"}, 500)
