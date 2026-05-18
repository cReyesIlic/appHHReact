import { useEffect, useRef, useState } from "react";
import { CloudDownload, BookPlus, RefreshCw, Sparkles, Trophy, Upload, Mail, Clock, Play, Hash } from "lucide-react";
import { getSyncStatus, syncDiscoverNew, syncNew, syncBackfillWiki, discoverGanadasPendientes, syncGanadas, syncCode, ingestUpload, refreshMaster, adminEmailTest, getSchedulerStatus, triggerScheduler } from "../../lib/api.js";
import { Button } from "../shared/Button.jsx";
import { Card } from "../shared/Card.jsx";
import { Input } from "../shared/Field.jsx";

export function SyncPanel({ onChanged }) {
  const [status, setStatus] = useState(null);
  const [newPreview, setNewPreview] = useState(null);
  const [ganadasPreview, setGanadasPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState([]);
  const [backfillLimit, setBackfillLimit] = useState("");
  const [ganadasLimit, setGanadasLimit] = useState("");
  const [uploadTarget, setUploadTarget] = useState("rag");
  const [scheduler, setScheduler] = useState(null);
  const [singleCode, setSingleCode] = useState("");
  const [singleForceWiki, setSingleForceWiki] = useState(false);
  const [singleResult, setSingleResult] = useState(null);
  const fileInputRef = useRef(null);

  const refreshScheduler = async () => {
    try {
      const s = await getSchedulerStatus();
      setScheduler(s);
    } catch (exc) {
      setScheduler({ running: false, error: exc.message });
    }
  };

  const refresh = async () => {
    try {
      const s = await getSyncStatus();
      setStatus(s);
    } catch (exc) {
      setLog((prev) => [...prev, `❌ status: ${exc.detail || exc.message}`]);
    }
  };

  useEffect(() => {
    refresh();
    refreshScheduler();
  }, []);

  const push = (line) => setLog((prev) => [line, ...prev].slice(0, 12));

  const handleDiscover = async () => {
    setBusy(true);
    try {
      const r = await syncDiscoverNew(200);
      setNewPreview(r);
      push(`🔎 SharePoint: ${r.sharepoint_total} totales · ${r.new_count} nuevos`);
    } catch (exc) {
      push(`❌ discover: ${exc.detail || exc.message}`);
    } finally {
      setBusy(false);
    }
  };

  const handleDiscoverGanadas = async () => {
    setBusy(true);
    try {
      const r = await discoverGanadasPendientes();
      setGanadasPreview(r);
      push(`🏆 Ganadas master: ${r.total_ganadas_master} totales · ${r.pendientes_rag_count} sin RAG · ${r.pendientes_wiki_count} sin Wiki`);
    } catch (exc) {
      push(`❌ ganadas: ${exc.detail || exc.message}`);
    } finally {
      setBusy(false);
    }
  };

  const handleSyncGanadas = async () => {
    if (!ganadasPreview || ganadasPreview.pendientes_rag_count === 0) return;
    const total = ganadasPreview.pendientes_rag_count;
    const limit = parseInt(ganadasLimit || "10", 10) || 10;
    const target = Math.min(limit, total);
    const cost = (target * 0.0015).toFixed(2);
    if (!confirm(
      `Sincronizar ${target} propuestas GANADAS pendientes?\n\n` +
      `→ Descargará PDFs desde SharePoint (carpeta 03 Oferta/02 Emitido)\n` +
      `→ Indexará en RAG\n` +
      `→ Compilará página Wiki con LLM\n\n` +
      `Costo estimado: ~$${cost} USD. Tiempo: ~${Math.ceil(target * 25 / 60)} min.`
    )) return;
    setBusy(true);
    push(`🏆 sincronizando ${target} ganadas pendientes…`);
    try {
      const r = await syncGanadas(target);
      push(`✅ ganadas: ingested=${r.ingested} wiki_ok=${r.wiki_ok} skipped=${r.skipped} errors=${r.errors}`);
      setGanadasPreview(null);
      await refresh();
      onChanged?.();
    } catch (exc) {
      push(`❌ sync-ganadas: ${exc.detail || exc.message}`);
    } finally {
      setBusy(false);
    }
  };

  const handleSyncNew = async (limit) => {
    if (!confirm(`Sincronizar ${limit} propuestas nuevas? Descargará PDFs y compilará wiki (costo: ~$${(limit * 0.0013).toFixed(2)} USD).`)) return;
    setBusy(true);
    push(`⏳ sincronizando ${limit} nuevas…`);
    try {
      const r = await syncNew(limit);
      push(`✅ sync-new: ingested=${r.ingested} wiki_ok=${r.wiki_ok} errors=${r.errors}`);
      await refresh();
      onChanged?.();
    } catch (exc) {
      push(`❌ sync-new: ${exc.detail || exc.message}`);
    } finally {
      setBusy(false);
    }
  };

  const handleManualUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    push(`⏳ subiendo ${file.name}…`);
    try {
      const r = await ingestUpload(file, { target: uploadTarget });
      const emailMsg = r.email?.sent ? " · email enviado" : (r.email?.reason ? ` · email: ${r.email.reason}` : "");
      push(`✅ ${r.filename}: ${r.chars_extracted.toLocaleString()} chars (${r.kind} → ${r.target})${emailMsg}`);
      onChanged?.();
    } catch (exc) {
      push(`❌ upload: ${exc.detail || exc.message}`);
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleManualMasterRefresh = async () => {
    if (!confirm("Recargar el master Excel? Se leerá el archivo configurado en MASTER_PATH y se enviará reporte por email.")) return;
    setBusy(true);
    push("⏳ refrescando master…");
    try {
      const r = await refreshMaster();
      const emailMsg = r.email?.sent ? " · email enviado" : (r.email?.reason ? ` · email: ${r.email.reason}` : "");
      push(`✅ master: ${r.rows_loaded} filas${emailMsg}`);
      onChanged?.();
    } catch (exc) {
      push(`❌ master: ${exc.detail || exc.message}`);
    } finally {
      setBusy(false);
    }
  };

  const explainSyncStatus = (r) => {
    if (!r) return "";
    if (r.status === "ok") {
      const wikiTxt = r.wiki_status === "ok" ? "✅ wiki ok" : r.wiki_status === "skipped" ? "⏭ wiki ya existía" : r.wiki_status === "no_rag" ? "⚠️ wiki sin RAG" : r.wiki_status === "error" ? `❌ wiki: ${r.wiki_error || "error"}` : `wiki=${r.wiki_status || "—"}`;
      return `Indexado: parents=${r.chunks_parent} children=${r.chunks_child} · ${r.files_processed || 1} archivo(s) · ${wikiTxt}`;
    }
    if (r.status === "no_files") return "⚠️ La carpeta '03 Oferta/02 Emitido' está vacía en SharePoint (sin PDF/DOCX/XLSX). Revisa que el código exista y tenga archivos.";
    if (r.status === "no_pdf") return "⚠️ No se encontró ningún PDF emitido en SharePoint.";
    if (r.status === "skipped") return "⏭ Ya estaba indexado, no se re-procesó.";
    if (r.status === "error") return `❌ Error: ${r.error || "desconocido"}`;
    return `Status: ${r.status}`;
  };

  const handleSyncSingleCode = async () => {
    const codigo = (singleCode || "").trim().toUpperCase();
    if (!codigo) {
      push("⚠️ Ingresa un código (ej: O-2658)");
      return;
    }
    if (!/^O-?\d+/i.test(codigo)) {
      push(`⚠️ Código inválido: "${codigo}" — debe empezar con O-`);
      return;
    }
    setBusy(true);
    setSingleResult(null);
    push(`⏳ ${codigo}: descargando de SharePoint…`);
    try {
      const r = await syncCode(codigo, singleForceWiki);
      setSingleResult(r);
      push(`${r.status === "ok" ? "✅" : "⚠️"} ${codigo}: ${explainSyncStatus(r)}`);
      if (r.status === "ok") onChanged?.();
    } catch (exc) {
      const detail = exc.detail || exc.message;
      setSingleResult({ status: "error", error: detail });
      if (exc.status === 502 || (exc.detail || "").toLowerCase().includes("sharepoint")) {
        push(`❌ ${codigo}: SharePoint rechazó la petición — ${detail}`);
      } else if (exc.status === 504) {
        push(`❌ ${codigo}: timeout — el archivo es muy grande o SharePoint está lento`);
      } else if (exc.status === 0) {
        push(`❌ ${codigo}: no se pudo contactar al backend`);
      } else {
        push(`❌ ${codigo}: ${detail}`);
      }
    } finally {
      setBusy(false);
    }
  };

  const handleTriggerScheduler = async (job = "sync_ganadas") => {
    if (!confirm(`Disparar '${job}' ahora? Corre en background. El email llegará al terminar.`)) return;
    setBusy(true);
    push(`⏰ disparando ${job}…`);
    try {
      const r = await triggerScheduler(job);
      push(`✅ ${r.triggered || job}: ${r.status || "ok"}`);
      setTimeout(refreshScheduler, 1500);
    } catch (exc) {
      push(`❌ trigger: ${exc.detail || exc.message}`);
    } finally {
      setBusy(false);
    }
  };

  const handleEmailTest = async () => {
    setBusy(true);
    push("📧 probando ACS…");
    try {
      const r = await adminEmailTest({});
      if (!r.configured) {
        push(`⚠️ ACS no configurado: ${r.reason}`);
      } else if (r.sent) {
        push(`✅ email enviado (${r.status}) → ${(r.recipients || []).join(", ")}`);
      } else {
        push(`❌ ACS: ${r.reason || r.status}`);
      }
    } catch (exc) {
      push(`❌ email-test: ${exc.detail || exc.message}`);
    } finally {
      setBusy(false);
    }
  };

  const handleBackfill = async () => {
    const total = status?.wiki_missing || 0;
    const limit = parseInt(backfillLimit || "0", 10) || total;
    const target = Math.min(limit, total);
    const cost = (target * 0.00125).toFixed(2);
    if (!confirm(`Compilar Wiki para ${target} propuestas existentes? Costo estimado: ~$${cost} USD. Concurrencia 8. Tiempo: ~${Math.ceil((target * 25) / 60 / 8)} min.`)) return;
    setBusy(true);
    push(`⏳ backfill wiki (${target} propuestas)…`);
    try {
      const r = await syncBackfillWiki({ limit: target });
      push(`✅ backfill: ok=${r.wiki_ok} skipped=${r.wiki_skipped} sin_rag=${r.wiki_no_rag} err=${r.wiki_error}`);
      await refresh();
      onChanged?.();
    } catch (exc) {
      push(`❌ backfill: ${exc.detail || exc.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      title="Sincronización SharePoint ↔ RAG ↔ Wiki"
      subtitle={
        status
          ? `RAG: ${status.rag_proposals} propuestas · Wiki: ${status.wiki_pages_existing} páginas · faltan ${status.wiki_missing}`
          : "Cargando…"
      }
      actions={
        <Button variant="ghost" icon={RefreshCw} onClick={refresh} disabled={busy}>
          Actualizar
        </Button>
      }
    >
      <div className="flex-col" style={{ gap: 12 }}>
        {/* Bloque scheduler: estado del cron embebido */}
        <div
          style={{
            padding: 12,
            background: "var(--bg-alt)",
            borderRadius: 8,
            border: "1px solid var(--border)",
            borderLeft: `3px solid ${scheduler?.running ? "var(--accent)" : "var(--text-muted)"}`,
          }}
        >
          <div className="card-title" style={{ fontSize: 13, marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
            <Clock size={14} style={{ color: scheduler?.running ? "var(--accent)" : "var(--text-muted)" }} />
            Scheduler interno {scheduler?.running ? "· activo" : "· detenido"}
          </div>
          <small className="dim" style={{ display: "block", marginBottom: 8 }}>
            La app corre el sync sola — sin GitHub Actions. Por defecto cada 2 días a las 02:15 hora Chile.
          </small>
          {scheduler?.jobs?.length > 0 && (
            <div className="flex-col" style={{ gap: 4, marginBottom: 8 }}>
              {scheduler.jobs.map((j) => (
                <small key={j.id} className="dim text-mono">
                  · {j.id} → próximo: {j.next_run ? new Date(j.next_run).toLocaleString() : "—"}
                </small>
              ))}
            </div>
          )}
          {scheduler?.last_run && (
            <small className="dim" style={{ display: "block", marginBottom: 8 }}>
              Última corrida: {scheduler.last_run.finished_at} ·{" "}
              {scheduler.last_run.ok
                ? `ingested=${scheduler.last_run.ingested ?? "—"} errors=${scheduler.last_run.errors ?? "—"}`
                : `❌ ${scheduler.last_run.error}`}
            </small>
          )}
          <div className="flex-row" style={{ flexWrap: "wrap", gap: 8 }}>
            <Button variant="ghost" icon={RefreshCw} onClick={refreshScheduler} disabled={busy}>
              Actualizar estado
            </Button>
            <Button variant="primary" icon={Play} onClick={() => handleTriggerScheduler("sync_ganadas")} disabled={busy}>
              Disparar sync ahora
            </Button>
          </div>
        </div>

        {/* Bloque principal: ganadas nuevas en master */}
        <div
          style={{
            padding: 12,
            background: "var(--bg-alt)",
            borderRadius: 8,
            border: "1px solid var(--accent-soft)",
            borderLeft: "3px solid var(--accent)",
          }}
        >
          <div className="card-title" style={{ fontSize: 13, marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
            <Trophy size={14} style={{ color: "var(--accent)" }} />
            Propuestas ganadas nuevas (recomendado)
          </div>
          <small className="dim" style={{ display: "block", marginBottom: 10 }}>
            Detecta propuestas en estado <b>PG</b> en master que aún no están indexadas, descarga sus PDFs de SharePoint y las alimenta al sistema (RAG + Wiki). Sin cron automático — bajo demanda.
          </small>
          <div className="flex-row" style={{ flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <Button variant="primary" icon={Trophy} onClick={handleDiscoverGanadas} disabled={busy}>
              Detectar ganadas pendientes
            </Button>
            {ganadasPreview && ganadasPreview.pendientes_rag_count > 0 && (
              <>
                <Input
                  placeholder={`Límite (default 10, total ${ganadasPreview.pendientes_rag_count})`}
                  value={ganadasLimit}
                  onChange={(e) => setGanadasLimit(e.target.value)}
                  style={{ width: 240 }}
                />
                <Button variant="accent" icon={Sparkles} onClick={handleSyncGanadas} disabled={busy}>
                  Sincronizar {Math.min(parseInt(ganadasLimit || "10", 10) || 10, ganadasPreview.pendientes_rag_count)} ganadas
                </Button>
              </>
            )}
          </div>
          {ganadasPreview && (
            <small className="dim" style={{ display: "block", marginTop: 8 }}>
              {ganadasPreview.total_ganadas_master} ganadas en master · {ganadasPreview.ya_indexadas_rag} con RAG · {ganadasPreview.ya_compiladas_wiki} con Wiki ·{" "}
              <b>{ganadasPreview.pendientes_rag_count} pendientes</b>
            </small>
          )}
        </div>

        {/* Bloque manual: subida puntual + master refresh + email test */}
        <div
          style={{
            padding: 12,
            background: "var(--bg-alt)",
            borderRadius: 8,
            border: "1px solid var(--border)",
          }}
        >
          <div className="card-title" style={{ fontSize: 13, marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
            <Upload size={14} style={{ color: "var(--accent)" }} />
            Ingesta manual
          </div>
          <small className="dim" style={{ display: "block", marginBottom: 10 }}>
            Subir un archivo individual (PDF/DOCX/XLSX) o forzar la recarga del master Excel. Cada acción envía un reporte por email si ACS está configurado.
          </small>
          <div className="flex-row" style={{ flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <select
              value={uploadTarget}
              onChange={(e) => setUploadTarget(e.target.value)}
              disabled={busy}
              style={{ padding: "6px 10px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg-surface)" }}
            >
              <option value="rag">→ Indexar a RAG</option>
              <option value="master">→ Master Excel</option>
              <option value="inspect">→ Solo inspeccionar</option>
            </select>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.xlsx,.xls"
              onChange={handleManualUpload}
              disabled={busy}
              style={{ display: "none" }}
            />
            <Button variant="primary" icon={Upload} onClick={() => fileInputRef.current?.click()} disabled={busy}>
              Subir archivo
            </Button>
            <Button variant="ghost" icon={RefreshCw} onClick={handleManualMasterRefresh} disabled={busy}>
              Recargar master Excel
            </Button>
            <Button variant="ghost" icon={Mail} onClick={handleEmailTest} disabled={busy}>
              Probar email (ACS)
            </Button>
          </div>

          {/* Sincronizar código puntual */}
          <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px dashed var(--border)" }}>
            <div className="card-title" style={{ fontSize: 12, marginBottom: 6, display: "flex", alignItems: "center", gap: 6 }}>
              <Hash size={12} style={{ color: "var(--accent)" }} />
              Sincronizar una propuesta por código
            </div>
            <small className="dim" style={{ display: "block", marginBottom: 8 }}>
              Si conoces el código exacto (ej. O-2658). Descarga desde SharePoint, indexa en RAG y compila Wiki.
            </small>
            <div className="flex-row" style={{ flexWrap: "wrap", gap: 8, alignItems: "center" }}>
              <Input
                placeholder="O-XXXX"
                value={singleCode}
                onChange={(e) => setSingleCode(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !busy && handleSyncSingleCode()}
                disabled={busy}
                style={{ width: 140, fontFamily: "monospace", textTransform: "uppercase" }}
              />
              <label className="flex-row" style={{ gap: 4, alignItems: "center", fontSize: 12 }}>
                <input
                  type="checkbox"
                  checked={singleForceWiki}
                  onChange={(e) => setSingleForceWiki(e.target.checked)}
                  disabled={busy}
                />
                Forzar recompilar wiki
              </label>
              <Button variant="primary" icon={Sparkles} onClick={handleSyncSingleCode} disabled={busy || !singleCode.trim()}>
                Sincronizar este código
              </Button>
            </div>
            {singleResult && (
              <div
                style={{
                  marginTop: 8,
                  padding: 8,
                  borderRadius: 6,
                  fontSize: 12,
                  background:
                    singleResult.status === "ok" ? "rgba(4, 120, 87, 0.08)"
                    : singleResult.status === "error" ? "rgba(181, 71, 8, 0.08)"
                    : "rgba(95, 116, 125, 0.08)",
                  border: `1px solid ${
                    singleResult.status === "ok" ? "rgba(4, 120, 87, 0.3)"
                    : singleResult.status === "error" ? "rgba(181, 71, 8, 0.3)"
                    : "rgba(95, 116, 125, 0.25)"
                  }`,
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: 4 }}>
                  {singleResult.codigo || singleCode.toUpperCase()} · {singleResult.status}
                </div>
                <div className="dim">{explainSyncStatus(singleResult)}</div>
                {singleResult.pdf_name && (
                  <div className="dim text-mono" style={{ marginTop: 4, fontSize: 11 }}>
                    Archivo primario: {singleResult.pdf_name}
                  </div>
                )}
                {singleResult.kinds_processed?.length > 0 && (
                  <div className="dim" style={{ fontSize: 11 }}>
                    Tipos: {singleResult.kinds_processed.join(", ")}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Bloque legacy: barrido amplio de SharePoint */}
        <div className="flex-row" style={{ flexWrap: "wrap", gap: 8 }}>
          <Button variant="ghost" icon={CloudDownload} onClick={handleDiscover} disabled={busy}>
            Detectar todas las carpetas SharePoint (legacy)
          </Button>
          {newPreview && newPreview.new_count > 0 && (
            <>
              <Button variant="accent" icon={Sparkles} onClick={() => handleSyncNew(Math.min(10, newPreview.new_count))} disabled={busy}>
                Ingestar {Math.min(10, newPreview.new_count)} primeras
              </Button>
              {newPreview.new_count > 10 && (
                <Button variant="accent" icon={Sparkles} onClick={() => handleSyncNew(newPreview.new_count)} disabled={busy}>
                  Ingestar todas ({newPreview.new_count})
                </Button>
              )}
            </>
          )}
        </div>

        {status && status.wiki_missing > 0 && (
          <div className="flex-row" style={{ alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            <Input
              placeholder={`Límite (vacío = todas ${status.wiki_missing})`}
              value={backfillLimit}
              onChange={(e) => setBackfillLimit(e.target.value)}
              style={{ width: 280 }}
            />
            <Button variant="accent" icon={BookPlus} onClick={handleBackfill} disabled={busy}>
              Compilar Wiki para propuestas con RAG
            </Button>
            <small className="dim">Solo procesa las que aún no tienen página.</small>
          </div>
        )}

        {newPreview && (
          <small className="dim">
            SharePoint: {newPreview.sharepoint_total} carpetas totales · {newPreview.already_indexed} ya indexadas · {newPreview.new_count} nuevas
          </small>
        )}

        {log.length > 0 && (
          <div className="flex-col" style={{ gap: 4, marginTop: 4 }}>
            {log.map((line, i) => (
              <small key={i} className="dim text-mono">
                {line}
              </small>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
