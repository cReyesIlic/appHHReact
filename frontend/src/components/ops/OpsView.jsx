import { useEffect, useState } from "react";
import { RefreshCw, Activity } from "lucide-react";
import { getOpsDashboard, getConfigStatus } from "../../lib/api.js";
import { Card } from "../shared/Card.jsx";
import { Button } from "../shared/Button.jsx";
import { EmptyState } from "../shared/EmptyState.jsx";
import { CoverageTable } from "./CoverageTable.jsx";

function Metric({ label, value }) {
  return (
    <div className="metric-card">
      <div className="metric-value">{value ?? "—"}</div>
      <div className="metric-label">{label}</div>
    </div>
  );
}

export function OpsView() {
  const [dashboard, setDashboard] = useState(null);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [d, c] = await Promise.all([
        getOpsDashboard(60).catch(() => null),
        getConfigStatus().catch(() => null),
      ]);
      setDashboard(d);
      setConfig(c);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (loading) {
    return (
      <div className="view-body">
        <EmptyState icon={Activity} title="Cargando operación…" />
      </div>
    );
  }

  const summary = dashboard?.summary || {};
  const ragHybrid = dashboard?.rag?.hybrid || config?.rag_hybrid || {};
  const wiki = config?.llm_wiki || {};
  const sqliteCounts = (dashboard?.sqlite || []).reduce((acc, r) => {
    acc[r.table] = r.rows;
    return acc;
  }, {});

  const masterCount = summary.master_rows ?? sqliteCounts.oferta ?? "—";
  const ragChunks = ragHybrid.chunks ?? ragHybrid.embedded_chunks ?? sqliteCounts.rag_child_embeddings ?? "—";
  const ragProposals = ragHybrid.proposal_count ?? "—";
  const wikiEntries = wiki.entries ?? sqliteCounts.wiki_entries ?? "—";
  const wikiPages = wiki.proposal_pages ?? "—";
  const embedModel = ragHybrid.embedding_model ?? "—";

  return (
    <div className="view-body">
      <Card
        title="Estado del sistema"
        subtitle="Cobertura e índices"
        actions={
          <Button icon={RefreshCw} variant="ghost" onClick={load}>
            Recargar
          </Button>
        }
      >
        <div className="metrics-grid">
          <Metric label="Propuestas en Master" value={masterCount} />
          <Metric label="Propuestas con RAG" value={ragProposals} />
          <Metric label="Chunks embebidos" value={ragChunks} />
          <Metric label="Páginas Wiki por propuesta" value={wikiPages} />
          <Metric label="Entradas Wiki (BD)" value={wikiEntries} />
          <Metric label="Modelo embedding" value={embedModel} />
        </div>
      </Card>

      {summary && Object.keys(summary).length > 0 && (
        <Card title="Resumen de cobertura comercial" subtitle="datos del último mes / histórico">
          <div className="metrics-grid">
            <Metric label="Propuestas ganadas (total)" value={summary.won_total} />
            <Metric label="Ganadas últimos 180 días" value={summary.won_last_180_days} />
            <Metric label="Manifest de assets" value={summary.manifest_rows} />
            <Metric label="Sin PDF" value={summary.missing_pdf} />
            <Metric label="Sin Excel" value={summary.missing_excel} />
            <Metric label="Sin assets" value={summary.no_assets} />
          </div>
        </Card>
      )}

      {dashboard?.asset_status && (
        <Card title="Estado de assets de propuestas">
          <div className="metrics-grid">
            {Object.entries(dashboard.asset_status).map(([key, value]) => (
              <Metric key={key} label={key} value={value} />
            ))}
          </div>
        </Card>
      )}

      {dashboard?.sqlite && dashboard.sqlite.length > 0 && (
        <Card title="Tablas SQLite" subtitle="conteo de filas por tabla">
          <div className="metrics-grid">
            {dashboard.sqlite.map((row) => (
              <Metric key={row.table} label={row.table} value={row.rows} />
            ))}
          </div>
        </Card>
      )}

      <CoverageTable />
    </div>
  );
}
