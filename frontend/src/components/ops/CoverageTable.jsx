import { useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, Download, Check, X, Sparkles, Loader2, FileUp, FileSpreadsheet, BookOpen } from "lucide-react";

import { getOpsCoverage, syncNew, syncCode, uploadCoverageAsset, getCoverageWiki } from "../../lib/api.js";
import { Card } from "../shared/Card.jsx";
import { Button } from "../shared/Button.jsx";
import { EmptyState } from "../shared/EmptyState.jsx";
import { Modal } from "../shared/Modal.jsx";

const RECENT_HIGHLIGHT = 20;

function Flag({ on, label }) {
  return (
    <span
      title={label}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 22,
        height: 22,
        borderRadius: 6,
        background: on ? "rgba(40, 160, 90, 0.18)" : "rgba(200, 60, 60, 0.12)",
        color: on ? "#1f8a4c" : "#b34141",
      }}
    >
      {on ? <Check size={14} /> : <X size={14} />}
    </span>
  );
}

export function CoverageTable() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const [onlyIncomplete, setOnlyIncomplete] = useState(false);
  const [search, setSearch] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [rowSyncing, setRowSyncing] = useState(null);
  const [rowUploading, setRowUploading] = useState(null);
  const [message, setMessage] = useState(null);
  const pdfInputRef = useRef(null);
  const excelInputRef = useRef(null);
  const pendingUpload = useRef({ codigo: null, kind: null });
  const [wikiOpen, setWikiOpen] = useState(null);
  const [wikiLoading, setWikiLoading] = useState(false);
  const [wikiContent, setWikiContent] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await getOpsCoverage({ estado: showAll ? "" : "PG", limit: 5000 });
      setData(res);
    } catch (exc) {
      setMessage({ type: "error", text: exc.message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showAll]);

  const handleSyncAll = async () => {
    setSyncing(true);
    setMessage({ type: "info", text: "Sincronizando nuevas propuestas desde SharePoint…" });
    try {
      const res = await syncNew(20, false);
      setMessage({
        type: "success",
        text: `Sync completado: ${res.processed ?? res.count ?? 0} propuestas procesadas`,
      });
      await load();
    } catch (exc) {
      setMessage({ type: "error", text: exc.message });
    } finally {
      setSyncing(false);
    }
  };

  const openWiki = async (codigo) => {
    setWikiOpen(codigo);
    setWikiLoading(true);
    setWikiContent(null);
    try {
      const res = await getCoverageWiki(codigo);
      setWikiContent(res);
    } catch (exc) {
      setWikiContent({ error: exc.message });
    } finally {
      setWikiLoading(false);
    }
  };

  const triggerUpload = (codigo, kind) => {
    pendingUpload.current = { codigo, kind };
    const input = kind === "pdf" ? pdfInputRef.current : excelInputRef.current;
    if (input) {
      input.value = "";
      input.click();
    }
  };

  const handleFileSelected = async (event) => {
    const file = event.target.files?.[0];
    const { codigo, kind } = pendingUpload.current;
    pendingUpload.current = { codigo: null, kind: null };
    if (!file || !codigo) return;
    setRowUploading(codigo);
    setMessage({ type: "info", text: `Subiendo ${file.name} para ${codigo}…` });
    try {
      const res = await uploadCoverageAsset(codigo, file);
      if (res.status === "ok") {
        const extras = [];
        if (res.chunks_child) extras.push(`${res.chunks_child} chunks`);
        if (res.hh_rows) extras.push(`${res.hh_rows} HH local`);
        const be = res.budget_extractor?.totals;
        if (be) {
          const parts = [];
          if (be.proyecto_filas) parts.push(`${be.proyecto_filas} filas`);
          if (be.tarifas_filas) parts.push(`${be.tarifas_filas} tarifas`);
          if (be.gastos_filas) parts.push(`${be.gastos_filas} gastos`);
          if (parts.length) extras.push(`Function: ${parts.join("+")}`);
        }
        setMessage({
          type: "success",
          text: `${codigo}: ${res.filename} indexado${extras.length ? ` (${extras.join(", ")})` : ""}`,
        });
      } else {
        setMessage({ type: "error", text: `${codigo}: ${res.error || res.status}` });
      }
      await load();
    } catch (exc) {
      setMessage({ type: "error", text: `Upload falló: ${exc.message}` });
    } finally {
      setRowUploading(null);
    }
  };

  const handleSyncRow = async (codigo) => {
    setRowSyncing(codigo);
    setMessage({ type: "info", text: `Re-sincronizando ${codigo}…` });
    try {
      await syncCode(codigo, false);
      setMessage({ type: "success", text: `${codigo} re-sincronizada` });
      await load();
    } catch (exc) {
      setMessage({ type: "error", text: exc.message });
    } finally {
      setRowSyncing(null);
    }
  };

  const filtered = useMemo(() => {
    const rows = data?.rows || [];
    const term = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (onlyIncomplete && r.pdf && r.excel && r.in_db) return false;
      if (!term) return true;
      return (
        (r.codigo || "").toLowerCase().includes(term) ||
        (r.cod_proy || "").toLowerCase().includes(term) ||
        (r.titulo || "").toLowerCase().includes(term) ||
        (r.cliente_final || "").toLowerCase().includes(term)
      );
    });
  }, [data, onlyIncomplete, search]);

  const totals = data?.totals || {};

  return (
    <>
      <input
        ref={pdfInputRef}
        type="file"
        accept="application/pdf,.pdf"
        style={{ display: "none" }}
        onChange={handleFileSelected}
      />
      <input
        ref={excelInputRef}
        type="file"
        accept=".xlsx,.xls,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        style={{ display: "none" }}
        onChange={handleFileSelected}
      />
    <Card
      title="Inventario de propuestas"
      subtitle={
        showAll
          ? "todas las propuestas del Master"
          : "ganadas (PG) — código O, código SH, PDF, Excel y estado en BD"
      }
      actions={
        <>
          <Button
            icon={syncing ? Loader2 : Download}
            variant="primary"
            onClick={handleSyncAll}
            disabled={syncing}
          >
            {syncing ? "Actualizando…" : "Actualizar sistema"}
          </Button>
          <Button icon={RefreshCw} variant="ghost" onClick={load} disabled={loading}>
            Recargar
          </Button>
        </>
      }
    >
      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          flexWrap: "wrap",
          marginBottom: 12,
        }}
      >
        <input
          type="text"
          placeholder="Buscar por código, SH, cliente o título…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            flex: "1 1 280px",
            padding: "6px 10px",
            border: "1px solid var(--border, #d0d0d0)",
            borderRadius: 6,
            fontSize: 13,
          }}
        />
        <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
          <input
            type="checkbox"
            checked={onlyIncomplete}
            onChange={(e) => setOnlyIncomplete(e.target.checked)}
          />
          Solo incompletas
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
          <input
            type="checkbox"
            checked={showAll}
            onChange={(e) => setShowAll(e.target.checked)}
          />
          Ver todas (no solo PG)
        </label>
      </div>

      {message && (
        <div
          style={{
            padding: "8px 12px",
            marginBottom: 10,
            borderRadius: 6,
            fontSize: 13,
            background:
              message.type === "error"
                ? "rgba(200, 60, 60, 0.12)"
                : message.type === "success"
                ? "rgba(40, 160, 90, 0.14)"
                : "rgba(70, 120, 200, 0.12)",
            color:
              message.type === "error"
                ? "#b34141"
                : message.type === "success"
                ? "#1f8a4c"
                : "#3457a3",
          }}
        >
          {message.text}
        </div>
      )}

      <div style={{ display: "flex", gap: 16, fontSize: 12, marginBottom: 10, color: "var(--muted, #666)" }}>
        <span>Total: <b>{totals.total ?? 0}</b></span>
        <span>Con PDF: <b>{totals.with_pdf ?? 0}</b></span>
        <span>Con Excel: <b>{totals.with_excel ?? 0}</b></span>
        <span>Excel procesado: <b>{totals.excel_parsed ?? 0}</b></span>
        <span>En BD (RAG): <b>{totals.in_db ?? 0}</b></span>
        <span>Con Wiki: <b>{totals.with_wiki ?? 0}</b></span>
        <span>Incompletas: <b>{totals.incomplete ?? 0}</b></span>
      </div>

      {loading ? (
        <EmptyState title="Cargando inventario…" />
      ) : filtered.length === 0 ? (
        <EmptyState title="Sin resultados" />
      ) : (
        <div style={{ overflow: "auto", maxHeight: 520 }}>
          <table className="data-table" style={{ fontSize: 13 }}>
            <thead>
              <tr>
                <th style={{ width: 30 }}></th>
                <th>Código O</th>
                <th>Código SH</th>
                <th>Cliente</th>
                <th>Título</th>
                <th>Fecha</th>
                <th style={{ textAlign: "center" }}>PDF</th>
                <th style={{ textAlign: "center" }}>Excel</th>
                <th style={{ textAlign: "center" }} title="Excel parseado a hh_estimate_rows / proyectos_extracted (Azure Function)">
                  Excel proc.
                </th>
                <th style={{ textAlign: "center" }}>En BD</th>
                <th style={{ textAlign: "center" }} title="Página Wiki auto-compilada">Wiki</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, idx) => {
                const isNew = idx < RECENT_HIGHLIGHT && row.is_recent;
                return (
                  <tr
                    key={row.codigo}
                    style={
                      isNew
                        ? { background: "rgba(220, 170, 60, 0.10)" }
                        : undefined
                    }
                  >
                    <td>
                      {isNew && (
                        <span title="Agregada recientemente">
                          <Sparkles size={14} color="#c08a1c" />
                        </span>
                      )}
                    </td>
                    <td><b>{row.codigo}</b></td>
                    <td>{row.cod_proy || "—"}</td>
                    <td>{row.cliente_final || "—"}</td>
                    <td style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {row.titulo || "—"}
                    </td>
                    <td>{(row.fecha_recep || "").slice(0, 10) || "—"}</td>
                    <td style={{ textAlign: "center" }}><Flag on={row.pdf} label="PDF cargado" /></td>
                    <td style={{ textAlign: "center" }}><Flag on={row.excel} label="Excel descargado" /></td>
                    <td style={{ textAlign: "center" }}>
                      <Flag on={row.excel_parsed} label="Excel parseado (HH / Azure Function)" />
                    </td>
                    <td style={{ textAlign: "center" }}><Flag on={row.in_db} label="Indexada en BD (RAG chunks)" /></td>
                    <td style={{ textAlign: "center" }}>
                      {row.has_wiki ? (
                        <button
                          className="btn btn-ghost"
                          style={{ padding: "2px 8px", fontSize: 12 }}
                          onClick={() => openWiki(row.codigo)}
                          title="Ver página Wiki auto-compilada"
                        >
                          <BookOpen size={13} /> Ver
                        </button>
                      ) : (
                        <Flag on={false} label="Sin página Wiki" />
                      )}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        <Button
                          variant="ghost"
                          icon={FileUp}
                          onClick={() => triggerUpload(row.codigo, "pdf")}
                          disabled={rowUploading === row.codigo}
                          title="Subir PDF manualmente e indexar a RAG"
                        >
                          PDF
                        </Button>
                        <Button
                          variant="ghost"
                          icon={FileSpreadsheet}
                          onClick={() => triggerUpload(row.codigo, "excel")}
                          disabled={rowUploading === row.codigo}
                          title="Subir Excel manualmente (indexa + HH extractor)"
                        >
                          Excel
                        </Button>
                        <Button
                          variant="ghost"
                          icon={rowSyncing === row.codigo || rowUploading === row.codigo ? Loader2 : RefreshCw}
                          onClick={() => handleSyncRow(row.codigo)}
                          disabled={rowSyncing === row.codigo || rowUploading === row.codigo || syncing}
                          title="Re-sincronizar desde SharePoint"
                        >
                          Sync
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
    <Modal
      open={wikiOpen !== null}
      title={wikiOpen ? `Wiki · ${wikiOpen}` : "Wiki"}
      onClose={() => { setWikiOpen(null); setWikiContent(null); }}
    >
      {wikiLoading && <EmptyState title="Cargando página Wiki…" />}
      {!wikiLoading && wikiContent?.error && (
        <div style={{ padding: 12, color: "#b34141" }}>{wikiContent.error}</div>
      )}
      {!wikiLoading && wikiContent?.markdown && (
        <div style={{ maxHeight: "70vh", overflow: "auto" }}>
          <div style={{ fontSize: 11, color: "var(--muted, #888)", marginBottom: 8, fontFamily: "Consolas, monospace" }}>
            {wikiContent.path}  ·  {Math.round((wikiContent.size_bytes || 0) / 1024)} KB
          </div>
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "Consolas, 'SF Mono', monospace", fontSize: 12, lineHeight: 1.5, padding: 14, background: "rgba(0,0,0,0.03)", borderRadius: 6 }}>
            {wikiContent.markdown}
          </pre>
        </div>
      )}
    </Modal>
    </>
  );
}
