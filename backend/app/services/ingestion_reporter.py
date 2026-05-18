"""Arma reportes HTML + texto plano para enviar por email tras una corrida de ingesta.

Casos de uso:
  - Cron cada 2 días sincroniza ganadas: envía resumen al finalizar
  - Master refresh manual: envía diff de filas nuevas/cambiadas
  - Upload individual via /api/ingest/upload: confirma al usuario

Estilo HTML inline (no CSS externo) para compatibilidad con Outlook/Gmail.
"""

from __future__ import annotations

from datetime import datetime


SHIMIN_INK = "#182b36"
SHIMIN_COPPER = "#c8863b"
SHIMIN_MIST = "#eef3f4"
SHIMIN_MUTED = "#5f747d"


def _wrap_html(title: str, body: str) -> str:
    """Layout HTML básico con header SHIMIN."""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title></head>
<body style="margin:0;padding:0;background:#f5f7f8;font-family:-apple-system,Segoe UI,Arial,sans-serif;color:{SHIMIN_INK};">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f8;padding:24px 0;">
    <tr><td align="center">
      <table width="640" cellpadding="0" cellspacing="0" border="0" style="background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(24,43,54,0.08);">
        <tr><td style="background:linear-gradient(90deg,{SHIMIN_INK},#223f4d);padding:16px 24px;">
          <table width="100%" border="0"><tr>
            <td style="color:white;font-size:16px;font-weight:600;letter-spacing:0.04em;">SHIMIN · Proposal Intelligence</td>
            <td align="right" style="color:{SHIMIN_COPPER};font-size:11px;text-transform:uppercase;letter-spacing:0.08em;">Reporte de ingesta</td>
          </tr></table>
        </td></tr>
        <tr><td style="padding:24px;">
          {body}
        </td></tr>
        <tr><td style="background:{SHIMIN_MIST};padding:12px 24px;font-size:11px;color:{SHIMIN_MUTED};text-align:center;">
          Generado automáticamente · {datetime.now().strftime('%d-%m-%Y %H:%M')}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def ganadas_sync_report(result: dict, kind: str = "ganadas") -> tuple[str, str, str]:
    """Devuelve (subject, plain_text, html) para un reporte de sync_ganadas."""
    objetivo = result.get("objetivo_corrida", 0)
    ingested = result.get("ingested", 0)
    skipped = result.get("skipped", 0)
    errors = result.get("errors", 0)
    wiki_ok = result.get("wiki_ok", 0)
    total = result.get("total_ganadas_master", 0)
    ya = result.get("ya_indexadas", 0)
    pendientes_post = max(total - ya - ingested, 0)
    details = result.get("details") or []

    subject = f"SHIMIN sync ganadas · {ingested} ingestadas / {errors} errores"

    # --- Texto plano ---
    lines = [
        f"Reporte de ingesta — {kind} — {datetime.now().strftime('%d-%m-%Y %H:%M')}",
        "",
        f"Total ganadas en master:     {total}",
        f"Ya indexadas antes:          {ya}",
        f"Objetivo de esta corrida:    {objetivo}",
        f"Ingestadas (nuevas en RAG):  {ingested}",
        f"Wiki compilada:              {wiki_ok}",
        f"Sin archivos / skipped:      {skipped}",
        f"Con error:                   {errors}",
        f"Quedan pendientes:           {pendientes_post}",
        "",
        "Detalle por código:",
    ]
    for d in details[:50]:
        cod = d.get("codigo", "")
        st = d.get("status", "")
        cli = d.get("cliente", "") or ""
        tit = (d.get("titulo") or "")[:55]
        files = d.get("files_processed", 0)
        chunks = d.get("chunks_child", 0)
        ws = d.get("wiki_status", "")
        err = d.get("error", "")
        lines.append(f"  {cod:8} · {st:9} · {cli[:18]:18} · {tit:55} · files={files} chunks={chunks} wiki={ws}")
        if err:
            lines.append(f"           error: {err[:160]}")
    text = "\n".join(lines)

    # --- HTML ---
    metric_card = lambda label, value, color=SHIMIN_INK: (
        f'<td style="background:{SHIMIN_MIST};padding:14px;border-radius:6px;text-align:center;width:25%;">'
        f'<div style="font-size:22px;font-weight:700;color:{color};">{value}</div>'
        f'<div style="font-size:10px;color:{SHIMIN_MUTED};text-transform:uppercase;letter-spacing:0.05em;">{label}</div>'
        f'</td>'
    )
    cards = (
        '<table width="100%" cellpadding="0" cellspacing="6" border="0" style="margin-bottom:18px;">'
        '<tr>'
        + metric_card("Ingestadas", ingested, "#047857")
        + metric_card("Wiki compiladas", wiki_ok, SHIMIN_COPPER)
        + metric_card("Skipped", skipped, SHIMIN_MUTED)
        + metric_card("Errores", errors, "#b54708" if errors else SHIMIN_MUTED)
        + "</tr></table>"
    )

    summary = (
        f'<p style="font-size:13px;line-height:1.6;margin:0 0 14px;color:{SHIMIN_INK};">'
        f"Total ganadas en master: <b>{total}</b>. Indexadas antes: <b>{ya}</b>. "
        f"Quedan pendientes: <b>{pendientes_post}</b> propuestas."
        f"</p>"
    )

    rows_html = []
    for d in details[:50]:
        cod = d.get("codigo", "")
        st = d.get("status", "")
        st_color = "#047857" if st == "ok" else ("#b54708" if st == "error" else SHIMIN_MUTED)
        cli = d.get("cliente", "") or "—"
        tit = (d.get("titulo") or "")[:80]
        files = d.get("files_processed", 0)
        chunks = d.get("chunks_child", 0)
        ws = d.get("wiki_status", "")
        err = d.get("error", "")
        rows_html.append(
            f'<tr>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6ebed;font-family:monospace;font-size:11px;color:{SHIMIN_INK};">{cod}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6ebed;color:{st_color};font-weight:600;font-size:11px;">{st}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6ebed;font-size:11px;">{cli}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6ebed;font-size:11px;color:{SHIMIN_MUTED};">{tit}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6ebed;text-align:right;font-size:11px;">{files}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6ebed;text-align:right;font-size:11px;">{chunks}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6ebed;font-size:11px;color:{st_color};">{ws}</td>'
            f'</tr>'
        )
        if err:
            rows_html.append(
                f'<tr><td colspan="7" style="padding:0 10px 6px;font-size:10px;color:#b54708;border-bottom:1px solid #e6ebed;">↳ {err[:280]}</td></tr>'
            )

    table_html = (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="font-size:11px;margin-top:14px;">'
        '<thead><tr>'
        f'<th align="left" style="background:{SHIMIN_COPPER};color:white;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.05em;">Código</th>'
        f'<th align="left" style="background:{SHIMIN_COPPER};color:white;padding:8px 10px;font-size:10px;">Estado</th>'
        f'<th align="left" style="background:{SHIMIN_COPPER};color:white;padding:8px 10px;font-size:10px;">Cliente</th>'
        f'<th align="left" style="background:{SHIMIN_COPPER};color:white;padding:8px 10px;font-size:10px;">Título</th>'
        f'<th align="right" style="background:{SHIMIN_COPPER};color:white;padding:8px 10px;font-size:10px;">Files</th>'
        f'<th align="right" style="background:{SHIMIN_COPPER};color:white;padding:8px 10px;font-size:10px;">Chunks</th>'
        f'<th align="left" style="background:{SHIMIN_COPPER};color:white;padding:8px 10px;font-size:10px;">Wiki</th>'
        '</tr></thead><tbody>' + "".join(rows_html) + "</tbody></table>"
    )

    if len(details) > 50:
        table_html += f'<p style="font-size:11px;color:{SHIMIN_MUTED};margin-top:8px;">… +{len(details)-50} entradas más en el manifest CSV.</p>'

    body = f"""
        <h2 style="margin:0 0 14px;color:{SHIMIN_INK};font-size:18px;">Sincronización de propuestas ganadas</h2>
        {summary}
        {cards}
        <h3 style="margin:14px 0 6px;color:{SHIMIN_INK};font-size:13px;">Detalle</h3>
        {table_html}
    """
    return subject, text, _wrap_html(subject, body)


def master_refresh_report(rows_loaded: int, diff: dict | None = None) -> tuple[str, str, str]:
    subject = f"SHIMIN master refresh · {rows_loaded} filas"
    text = f"Master Excel recargado: {rows_loaded} filas.\n"
    if diff:
        text += f"\nDiff: nuevas={diff.get('new', 0)} · cambios estado={diff.get('status_changed', 0)}"
    body = f"""
        <h2 style="margin:0 0 14px;color:{SHIMIN_INK};font-size:18px;">Master Excel refrescado</h2>
        <p style="font-size:13px;">Total filas cargadas: <b>{rows_loaded}</b></p>
    """
    if diff:
        body += (
            f'<p style="font-size:13px;">Nuevas propuestas: <b>{diff.get("new", 0)}</b><br>'
            f'Cambios de estado: <b>{diff.get("status_changed", 0)}</b></p>'
        )
    return subject, text, _wrap_html(subject, body)


def upload_report(filename: str, kind: str, chars_extracted: int, target: str) -> tuple[str, str, str]:
    subject = f"SHIMIN ingesta · {filename}"
    text = f"Archivo ingestado: {filename}\nTipo: {kind}\nTexto extraído: {chars_extracted} caracteres\nDestino: {target}"
    body = f"""
        <h2 style="margin:0 0 14px;color:{SHIMIN_INK};font-size:18px;">Archivo procesado</h2>
        <p style="font-size:13px;line-height:1.6;">
          <b>{filename}</b><br>
          Tipo: <code>{kind}</code><br>
          Texto extraído: <b>{chars_extracted:,}</b> caracteres<br>
          Destino: {target}
        </p>
    """
    return subject, text, _wrap_html(subject, body)
