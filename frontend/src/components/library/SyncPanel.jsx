import { useEffect, useState } from "react";
import { CloudDownload, BookPlus, RefreshCw, Sparkles, Trophy } from "lucide-react";
import { getSyncStatus, syncDiscoverNew, syncNew, syncBackfillWiki, discoverGanadasPendientes, syncGanadas } from "../../lib/api.js";
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

  const refresh = async () => {
    try {
      const s = await getSyncStatus();
      setStatus(s);
    } catch (exc) {
      setLog((prev) => [...prev, `❌ status: ${exc.message}`]);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const push = (line) => setLog((prev) => [line, ...prev].slice(0, 12));

  const handleDiscover = async () => {
    setBusy(true);
    try {
      const r = await syncDiscoverNew(200);
      setNewPreview(r);
      push(`🔎 SharePoint: ${r.sharepoint_total} totales · ${r.new_count} nuevos`);
    } catch (exc) {
      push(`❌ discover: ${exc.message}`);
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
      push(`❌ ganadas: ${exc.message}`);
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
      push(`✅ ganadas: ingested=${r.ingested} wiki_ok=${r.wiki_ok} no_pdf=${r.skipped} errors=${r.errors}`);
      setGanadasPreview(null);
      await refresh();
      onChanged?.();
    } catch (exc) {
      push(`❌ sync-ganadas: ${exc.message}`);
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
      push(`❌ sync-new: ${exc.message}`);
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
      push(`❌ backfill: ${exc.message}`);
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
