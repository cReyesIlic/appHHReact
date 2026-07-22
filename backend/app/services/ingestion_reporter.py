"""Reportes operativos de correo, legibles y compatibles con Outlook/Gmail."""

from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo


SHIMIN_INK = "#17313b"
SHIMIN_COPPER = "#c67f32"
SHIMIN_MIST = "#eef3f4"
SHIMIN_MUTED = "#607780"
SUCCESS = "#087a55"
WARNING = "#b85c16"
ERROR = "#b42318"


def _now_chile() -> datetime:
    return datetime.now(ZoneInfo("America/Santiago"))


def _safe(value: object) -> str:
    return escape(str(value or "—"), quote=True)


def _number(value: object) -> str:
    try:
        return f"{int(value or 0):,}".replace(",", ".")
    except (TypeError, ValueError):
        return _safe(value)


def _metric(label: str, value: object, color: str = SHIMIN_INK) -> str:
    return (
        '<td width="25%" style="padding:5px;vertical-align:top;">'
        f'<div style="background:{SHIMIN_MIST};border-radius:8px;padding:14px 8px;text-align:center;">'
        f'<div style="font-size:24px;line-height:1.1;font-weight:700;color:{color};">{_number(value)}</div>'
        f'<div style="margin-top:5px;font-size:10px;color:{SHIMIN_MUTED};text-transform:uppercase;'
        f'letter-spacing:.06em;">{_safe(label)}</div></div></td>'
    )


def _metrics(*cards: tuple[str, object, str]) -> str:
    return '<table width="100%" cellpadding="0" cellspacing="0"><tr>' + "".join(
        _metric(label, value, color) for label, value, color in cards
    ) + "</tr></table>"


def _info_row(label: str, value: object) -> str:
    return (
        '<tr>'
        f'<td style="padding:7px 10px;border-bottom:1px solid #e3eaec;color:{SHIMIN_MUTED};font-size:12px;">{_safe(label)}</td>'
        f'<td align="right" style="padding:7px 10px;border-bottom:1px solid #e3eaec;color:{SHIMIN_INK};'
        f'font-size:12px;font-weight:600;">{_safe(value)}</td>'
        '</tr>'
    )


def _status_banner(label: str, message: str, color: str) -> str:
    background = {
        SUCCESS: "#edf8f4",
        WARNING: "#fff6eb",
        ERROR: "#fff1f0",
    }.get(color, SHIMIN_MIST)
    return (
        f'<div style="border-left:4px solid {color};background:{background};border-radius:6px;'
        f'padding:12px 14px;margin:0 0 18px;">'
        f'<div style="font-size:12px;font-weight:700;color:{color};text-transform:uppercase;'
        f'letter-spacing:.06em;">{_safe(label)}</div>'
        f'<div style="font-size:13px;line-height:1.5;color:{SHIMIN_INK};margin-top:3px;">{_safe(message)}</div>'
        '</div>'
    )


def _wrap_html(title: str, report_label: str, body: str, preheader: str = "") -> str:
    generated = _now_chile().strftime("%d-%m-%Y · %H:%M")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{_safe(title)}</title></head>
<body style="margin:0;padding:0;background:#f4f7f8;font-family:Segoe UI,Arial,sans-serif;color:{SHIMIN_INK};">
  <div style="display:none;max-height:0;overflow:hidden;color:#f4f7f8;">{_safe(preheader)}</div>
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background:#f4f7f8;padding:24px 10px;">
    <tr><td align="center">
      <table width="680" cellpadding="0" cellspacing="0" role="presentation" style="max-width:680px;width:100%;background:#fff;border:1px solid #e1e8ea;border-radius:10px;overflow:hidden;">
        <tr><td style="background:{SHIMIN_INK};padding:18px 24px;">
          <table width="100%" cellpadding="0" cellspacing="0" role="presentation"><tr>
            <td style="color:#fff;font-size:17px;font-weight:700;">SHIMIN <span style="color:{SHIMIN_COPPER};">·</span> Proposal Intelligence</td>
            <td align="right" style="color:#cbd8dc;font-size:10px;text-transform:uppercase;letter-spacing:.09em;">{_safe(report_label)}</td>
          </tr></table>
        </td></tr>
        <tr><td style="padding:24px;">{body}</td></tr>
        <tr><td style="background:{SHIMIN_MIST};padding:13px 24px;text-align:center;color:{SHIMIN_MUTED};font-size:10px;line-height:1.5;">
          Generado automáticamente el {generated}, hora de Chile.<br>Este mensaje resume el estado operativo; no es necesario responder.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _sync_status(status: object) -> tuple[str, str]:
    value = str(status or "").lower()
    if value == "ok":
        return "Completada", SUCCESS
    if value in {"skipped", "no_files", "no_pdf"}:
        return "Sin archivos", WARNING
    if value == "invalid_source_removed":
        return "Fuente retirada", WARNING
    if value == "source_mismatch":
        return "Fuente rechazada", ERROR
    return "Error", ERROR


def _detail_status(item: dict) -> tuple[str, str]:
    if str(item.get("status") or "").lower() == "ok" and (
        item.get("wiki_status") not in {"ok", "skipped"}
        or item.get("embedding_error")
        or item.get("excel_errors")
    ):
        return "Incompleta", WARNING
    return _sync_status(item.get("status"))


def _detail_problem(item: dict) -> str:
    problems = [item.get("error"), item.get("wiki_error"), item.get("embedding_error"), item.get("note")]
    problems.extend(item.get("excel_errors") or [])
    return " · ".join(str(value) for value in problems if value)


def ganadas_sync_report(result: dict, kind: str = "ganadas") -> tuple[str, str, str]:
    """Reporte diario de nuevas, modificadas y reprocesadas."""
    objetivo = int(result.get("objetivo_corrida") or 0)
    completed = int(result.get("ingested") or 0)
    skipped = int(result.get("skipped") or 0)
    errors = int(result.get("errors") or 0)
    wiki_errors = int(result.get("wiki_error") or 0)
    partial = int(result.get("partial") or 0)
    alerts = errors + (partial if "partial" in result else wiki_errors)
    details = result.get("details") or []
    total = int(result.get("total_ganadas_master") or 0)
    queue_before = result.get("queue_before")
    queue_remaining = result.get("queue_remaining")
    pending_new = result.get("pending_new_remaining")
    pending_reprocess = result.get("pending_reprocess_remaining")
    status_word = "ATENCIÓN" if alerts else "OK"
    subject = f"[SHIMIN] Sync diario {status_word} — {completed}/{objetivo} completadas"
    if alerts:
        subject += f" · {alerts} alerta{'s' if alerts != 1 else ''}"

    lines = [
        f"SINCRONIZACIÓN DIARIA — {status_word}",
        _now_chile().strftime("%d-%m-%Y %H:%M, hora de Chile"),
        "",
        "RESUMEN",
        f"- Propuestas objetivo: {objetivo}",
        f"- Completadas: {completed}",
        f"- Sin archivos / omitidas: {skipped}",
        f"- Errores de proceso: {errors}",
        f"- Incompletas para reintento: {partial}",
        f"- Wikis compiladas: {int(result.get('wiki_ok') or 0)}",
        f"- Errores Wiki: {wiki_errors}",
        "",
        "COLA AUTOMÁTICA",
        f"- Ganadas únicas en Master: {total}",
    ]
    if queue_before is not None:
        lines.append(f"- Pendientes al iniciar: {queue_before}")
    if queue_remaining is not None:
        lines.extend([
            f"- Pendientes al terminar: {queue_remaining}",
            f"  · Nuevas sin RAG: {pending_new or 0}",
            f"  · Reproceso de pipeline: {pending_reprocess or 0}",
        ])
    lines.extend(["", "DETALLE"])
    for item in details[:40]:
        label, _ = _detail_status(item)
        quality = item.get("quality") or {}
        lines.append(
            f"- {item.get('codigo', '—')} · {label} · motivo={item.get('sync_reason', '—')} · "
            f"archivos={item.get('files_processed', 0)} · chunks={item.get('chunks_child', 0)} · "
            f"wiki={item.get('wiki_status', '—')} · Q={quality.get('wiki_score', '—')}"
        )
        problem = _detail_problem(item)
        if problem:
            lines.append(f"  Acción requerida: {str(problem)[:300]}")
    if len(details) > 40:
        lines.append(f"- … y {len(details) - 40} resultados adicionales.")
    plain = "\n".join(lines)

    banner = _status_banner(
        "Requiere revisión" if alerts else "Proceso completado",
        f"{alerts} incidencias necesitan atención." if alerts else "La corrida terminó sin errores operativos.",
        ERROR if alerts else SUCCESS,
    )
    cards = _metrics(
        ("Completadas", completed, SUCCESS),
        ("Wikis", int(result.get("wiki_ok") or 0), SHIMIN_COPPER),
        ("Sin archivos", skipped, WARNING if skipped else SHIMIN_MUTED),
        ("Alertas", alerts, ERROR if alerts else SHIMIN_MUTED),
    )
    queue_rows = _info_row("Ganadas únicas en Master", total)
    if queue_before is not None:
        queue_rows += _info_row("Pendientes al iniciar", queue_before)
    if queue_remaining is not None:
        queue_rows += _info_row("Pendientes al terminar", queue_remaining)
        queue_rows += _info_row("Nuevas sin RAG", pending_new or 0)
        queue_rows += _info_row("Reprocesos pendientes", pending_reprocess or 0)

    rows = []
    for item in details[:40]:
        label, color = _detail_status(item)
        quality = item.get("quality") or {}
        problem = _detail_problem(item)
        result_cell = f'<b style="color:{color};">{_safe(label)}</b>'
        if problem:
            result_cell += f'<div style="color:{ERROR};font-size:10px;margin-top:3px;line-height:1.35;">{_safe(str(problem)[:240])}</div>'
        rows.append(
            '<tr>'
            f'<td style="padding:8px;border-bottom:1px solid #e3eaec;font:600 11px Consolas,monospace;">{_safe(item.get("codigo"))}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #e3eaec;font-size:11px;">{_safe(item.get("sync_reason"))}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #e3eaec;font-size:11px;">{result_cell}</td>'
            f'<td align="right" style="padding:8px;border-bottom:1px solid #e3eaec;font-size:11px;">{_number(item.get("files_processed"))}</td>'
            f'<td align="right" style="padding:8px;border-bottom:1px solid #e3eaec;font-size:11px;">{_number(item.get("chunks_child"))}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #e3eaec;font-size:11px;">{_safe(item.get("wiki_status"))}<br><span style="color:{SHIMIN_MUTED};">Q {_safe(quality.get("wiki_score"))}</span></td>'
            '</tr>'
        )
    detail_table = (
        '<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px;border:1px solid #e3eaec;border-radius:7px;overflow:hidden;">'
        f'<tr style="background:{SHIMIN_INK};color:#fff;">'
        '<th align="left" style="padding:8px;font-size:10px;">Código</th>'
        '<th align="left" style="padding:8px;font-size:10px;">Motivo</th>'
        '<th align="left" style="padding:8px;font-size:10px;">Resultado</th>'
        '<th align="right" style="padding:8px;font-size:10px;">Arch.</th>'
        '<th align="right" style="padding:8px;font-size:10px;">Chunks</th>'
        '<th align="left" style="padding:8px;font-size:10px;">Wiki</th></tr>'
        + "".join(rows) + "</table>"
    )
    extra = f'<p style="font-size:11px;color:{SHIMIN_MUTED};">Se omitieron {len(details)-40} filas del correo; permanecen disponibles en Operaciones.</p>' if len(details) > 40 else ""
    body = f"""
      <h1 style="font-size:20px;margin:0 0 14px;">Sincronización diaria de propuestas ganadas</h1>
      {banner}{cards}
      <h2 style="font-size:14px;margin:22px 0 8px;">Estado de la cola</h2>
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e3eaec;border-radius:7px;overflow:hidden;">{queue_rows}</table>
      <h2 style="font-size:14px;margin:22px 0 8px;">Resultado por propuesta</h2>
      {detail_table}{extra}
    """
    return subject, plain, _wrap_html(subject, "Operaciones · sincronización", body, f"{completed} completadas; {alerts} alertas")


def master_refresh_report(
    rows_loaded: int,
    diff: dict | None = None,
    metadata: dict | None = None,
) -> tuple[str, str, str]:
    metadata = metadata or {}
    source = str(metadata.get("source") or "desconocida")
    source_label = {"sharepoint": "SharePoint", "blob": "Blob de respaldo", "local": "copia local"}.get(source, source)
    warnings = [str(item) for item in metadata.get("warnings") or [] if str(item).strip()]
    status_word = "ATENCIÓN" if warnings else "OK"
    subject = f"[SHIMIN] Master actualizado {status_word} — {_number(rows_loaded)} filas · {source_label}"
    lines = [
        f"ACTUALIZACIÓN DE PLANILLA MASTER — {status_word}",
        f"Filas cargadas: {_number(rows_loaded)}",
        f"Fuente efectiva: {source_label}",
        f"Archivo: {metadata.get('file_name') or '—'}",
        f"Última modificación origen: {metadata.get('source_last_modified') or '—'}",
        f"Respaldo Blob actualizado: {'Sí' if metadata.get('blob_updated') else 'No'}",
    ]
    if diff:
        lines.extend([f"Nuevas propuestas: {diff.get('new', 0)}", f"Cambios de estado: {diff.get('status_changed', 0)}"])
    if warnings:
        lines.extend(["", "ADVERTENCIAS", *[f"- {warning}" for warning in warnings]])
    plain = "\n".join(lines)
    banner = _status_banner(
        "Actualizado con advertencias" if warnings else "Actualización correcta",
        f"La Planilla Master quedó disponible con {_number(rows_loaded)} filas desde {source_label}.",
        WARNING if warnings else SUCCESS,
    )
    info = "".join([
        _info_row("Filas cargadas", _number(rows_loaded)),
        _info_row("Fuente efectiva", source_label),
        _info_row("Archivo", metadata.get("file_name") or "—"),
        _info_row("Modificado en origen", metadata.get("source_last_modified") or "—"),
        _info_row("Respaldo Blob actualizado", "Sí" if metadata.get("blob_updated") else "No"),
    ])
    if diff:
        info += _info_row("Nuevas propuestas", diff.get("new", 0)) + _info_row("Cambios de estado", diff.get("status_changed", 0))
    warning_html = ""
    if warnings:
        warning_html = '<h2 style="font-size:14px;margin:22px 0 8px;">Advertencias</h2>' + "".join(
            f'<div style="color:{ERROR};font-size:12px;padding:7px 0;border-bottom:1px solid #f1dedb;">{_safe(item)}</div>'
            for item in warnings
        )
    body = f"""
      <h1 style="font-size:20px;margin:0 0 14px;">Planilla Master actualizada</h1>
      {banner}
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e3eaec;border-radius:7px;overflow:hidden;">{info}</table>
      {warning_html}
    """
    return subject, plain, _wrap_html(subject, "Datos · Planilla Master", body, f"{rows_loaded} filas cargadas desde {source_label}")


def upload_report(filename: str, kind: str, chars_extracted: int, target: str) -> tuple[str, str, str]:
    target_label = {"rag": "RAG / inspección", "master": "Planilla Master", "inspect": "sólo inspección"}.get(target, target)
    has_text = int(chars_extracted or 0) > 0
    status_word = "OK" if has_text else "ATENCIÓN"
    subject = f"[SHIMIN] Archivo procesado {status_word} — {filename}"
    plain = "\n".join([
        f"ARCHIVO PROCESADO — {status_word}",
        f"Nombre: {filename}",
        f"Formato: {kind.upper()}",
        f"Texto extraído: {_number(chars_extracted)} caracteres",
        f"Destino solicitado: {target_label}",
        "Resultado: contenido legible detectado" if has_text else "Acción requerida: no se detectó texto extraíble; revisar el archivo.",
    ])
    banner = _status_banner(
        "Contenido recibido" if has_text else "Revisar archivo",
        "El archivo contiene texto utilizable por el pipeline." if has_text else "No se detectó texto extraíble; puede ser un escaneo o un formato no compatible.",
        SUCCESS if has_text else WARNING,
    )
    info = "".join([
        _info_row("Archivo", filename),
        _info_row("Formato", kind.upper()),
        _info_row("Texto extraído", f"{_number(chars_extracted)} caracteres"),
        _info_row("Destino solicitado", target_label),
    ])
    body = f"""
      <h1 style="font-size:20px;margin:0 0 14px;">Archivo recibido y analizado</h1>
      {banner}
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e3eaec;border-radius:7px;overflow:hidden;">{info}</table>
    """
    return subject, plain, _wrap_html(subject, "Operaciones · carga manual", body, f"{filename}: {chars_extracted} caracteres extraídos")


def email_test_report(message: str) -> tuple[str, str, str]:
    subject = "[SHIMIN] Notificaciones operativas configuradas correctamente"
    plain = f"PRUEBA DE NOTIFICACIÓN — OK\n\n{message}\n\nAzure Communication Services está enviando correctamente."
    banner = _status_banner("Canal operativo disponible", "Azure Communication Services respondió correctamente.", SUCCESS)
    body = f"""
      <h1 style="font-size:20px;margin:0 0 14px;">Prueba de notificación</h1>
      {banner}
      <div style="font-size:13px;line-height:1.6;background:{SHIMIN_MIST};border-radius:7px;padding:14px;">{_safe(message)}</div>
    """
    return subject, plain, _wrap_html(subject, "Sistema · prueba de correo", body, "Canal de notificaciones operativo")


def _human_bytes(value: float) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def storage_usage_report(stats: dict, top_dirs: list[dict], threshold: float) -> tuple[str, str, str]:
    pct = float(stats.get("utilization") or 0) * 100
    over = pct >= threshold * 100
    status_word = "ALERTA" if over else "OK"
    subject = f"[SHIMIN] Almacenamiento {status_word} — {pct:.1f}% utilizado"
    used = _human_bytes(stats.get("used_bytes") or 0)
    quota = f"{stats.get('quota_gb', 0)} GB"
    plain_lines = [
        f"ALMACENAMIENTO AZURE — {status_word}",
        f"Cuenta / recurso: {stats.get('account', '—')} / {stats.get('share', '—')}",
        f"Uso: {used} de {quota} ({pct:.1f}%)",
        f"Umbral de alerta: {threshold * 100:.0f}%",
    ]
    if over:
        plain_lines.append("Acción recomendada: revisar crecimiento y ampliar cuota o depurar respaldos antes de alcanzar el límite.")
    if top_dirs:
        plain_lines.extend(["", "CARPETAS CON MAYOR USO"])
        plain_lines.extend(f"- {item.get('name', '—')}: {_human_bytes(item.get('bytes') or 0)}" for item in top_dirs)
    plain = "\n".join(plain_lines)
    banner = _status_banner(
        "Capacidad sobre el umbral" if over else "Capacidad dentro de rango",
        "Revisar capacidad y crecimiento del File Share." if over else "No se requiere acción inmediata.",
        ERROR if over else SUCCESS,
    )
    bar_color = ERROR if over else SUCCESS
    width = max(0, min(100, pct))
    directory_html = ""
    if top_dirs:
        directory_html = '<h2 style="font-size:14px;margin:22px 0 8px;">Carpetas con mayor uso</h2>' + "".join(
            _info_row(str(item.get("name") or "—"), _human_bytes(item.get("bytes") or 0)) for item in top_dirs
        )
        directory_html = directory_html.replace('<tr>', '<table width="100%" cellpadding="0" cellspacing="0"><tr>', 1) + '</table>'
    body = f"""
      <h1 style="font-size:20px;margin:0 0 14px;">Capacidad de almacenamiento</h1>
      {banner}
      {_metrics(("Uso", f"{pct:.1f}%", bar_color), ("Utilizado", used, SHIMIN_INK), ("Cuota", quota, SHIMIN_INK), ("Umbral", f"{threshold*100:.0f}%", WARNING))}
      <div style="height:10px;background:#e3eaec;border-radius:5px;margin:16px 5px 4px;overflow:hidden;"><div style="width:{width:.1f}%;height:10px;background:{bar_color};"></div></div>
      <div style="text-align:right;color:{SHIMIN_MUTED};font-size:10px;margin:0 5px;">{pct:.1f}% utilizado</div>
      {directory_html}
    """
    return subject, plain, _wrap_html(subject, "Infraestructura · almacenamiento", body, f"File Share al {pct:.1f}%")
