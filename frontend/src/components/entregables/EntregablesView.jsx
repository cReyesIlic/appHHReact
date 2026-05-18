import { useEffect, useMemo, useState } from "react";
import { Hash, Search, Sparkles, Users, Briefcase, BookOpen, Workflow, RefreshCw, Send } from "lucide-react";
import { getEntregablesStats, getEntregablesDisciplinas, getEntregablesAggregate, askEntregablesAgent } from "../../lib/api.js";
import { Button } from "../shared/Button.jsx";
import { Card } from "../shared/Card.jsx";
import { Input } from "../shared/Field.jsx";

const VIEWS = [
  { key: "proyecto", label: "Por proyecto", icon: Briefcase },
  { key: "disciplina", label: "Por disciplina", icon: Workflow },
  { key: "role", label: "Por rol/profesional", icon: Users },
  { key: "entregable", label: "Por entregable", icon: BookOpen },
];

function fmtH(v) {
  if (v == null) return "—";
  return Number(v).toLocaleString("es-CL", { maximumFractionDigits: 0 });
}

function PctBar({ pct }) {
  const v = Math.min(100, Math.max(0, Number(pct) || 0));
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ flex: 1, height: 6, background: "var(--bg-alt)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${v}%`, height: "100%", background: "var(--accent)" }} />
      </div>
      <span style={{ fontSize: 11, color: "var(--text-muted)", minWidth: 42, textAlign: "right" }}>{v.toFixed(1)}%</span>
    </div>
  );
}

export function EntregablesView() {
  const [stats, setStats] = useState(null);
  const [disciplinas, setDisciplinas] = useState([]);
  const [fuente, setFuente] = useState("licitadas");
  const [view, setView] = useState("proyecto");
  const [codigo, setCodigo] = useState("");
  const [cliente, setCliente] = useState("");
  const [discipline, setDiscipline] = useState("");
  const [text, setText] = useState("");
  const [minHours, setMinHours] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  // Sub-agente
  const [question, setQuestion] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentResp, setAgentResp] = useState(null);

  useEffect(() => {
    getEntregablesStats().then(setStats).catch(() => {});
    getEntregablesDisciplinas(40).then((r) => setDisciplinas(r.disciplinas || [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (fuente === "reales" && view === "role") {
      setView("entregable");
    }
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fuente, view]);

  const run = async () => {
    setLoading(true);
    setErr(null);
    try {
      const r = await getEntregablesAggregate({
        fuente,
        view: fuente === "reales" && view === "role" ? "entregable" : view,
        codigo: codigo || undefined,
        cliente: cliente || undefined,
        disciplina: discipline || undefined,
        text: text || undefined,
        min_hours: minHours ? Number(minHours) : undefined,
        limit: 100,
      });
      if (r.error) setErr(r.error);
      setData(r);
    } catch (exc) {
      setErr(exc.detail || exc.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const handleAsk = async () => {
    const q = question.trim();
    if (!q) return;
    setAgentBusy(true);
    setAgentResp(null);
    try {
      const r = await askEntregablesAgent({ question: q, codigo: codigo || undefined });
      setAgentResp(r);
    } catch (exc) {
      setAgentResp({ answer: `❌ ${exc.detail || exc.message}` });
    } finally {
      setAgentBusy(false);
    }
  };

  const columns = useMemo(() => buildColumns(view, fuente), [view, fuente]);
  const availableViews = fuente === "reales" ? VIEWS.filter((v) => v.key !== "role").concat([{ key: "persona", label: "Por persona", icon: Users }]) : VIEWS;

  return (
    <div className="flex-col" style={{ gap: 12 }}>
      {/* Header con stats */}
      <Card
        title="Entregables y HH"
        subtitle={
          stats
            ? `Local: ${fmtH(stats.rows)} filas plausibles · ${stats.proyectos} proyectos · ${stats.disciplinas} disciplinas · ${stats.roles} roles · ${fmtH(stats.total_hours)} HH totales licitadas`
            : "Cargando…"
        }
        actions={
          <Button variant="ghost" icon={RefreshCw} onClick={run} disabled={loading}>
            Actualizar
          </Button>
        }
      >
        {stats?.source_path && (
          <small className="dim" style={{ display: "block" }}>
            Fuente HH licitadas: <code>{stats.source_path}</code> (adaptable via env <code>HH_EXCEL_SOURCE</code>)
          </small>
        )}
      </Card>

      {/* Toggle fuente */}
      <Card>
        <div className="flex-row" style={{ flexWrap: "wrap", gap: 16, alignItems: "center", marginBottom: 12 }}>
          <div className="flex-row" style={{ gap: 6 }}>
            <Button variant={fuente === "licitadas" ? "primary" : "ghost"} onClick={() => setFuente("licitadas")}>
              HH licitadas (local)
            </Button>
            <Button variant={fuente === "reales" ? "primary" : "ghost"} onClick={() => setFuente("reales")}>
              HH reales (staffing)
            </Button>
          </div>
          <small className="dim">
            {fuente === "licitadas"
              ? "Datos extraídos de Excels de propuesta — sin nombres de persona."
              : "Datos de carga semanal en staffing — con nombres y entregables ejecutados."}
          </small>
        </div>

        {/* Toggle de vista */}
        <div className="flex-row" style={{ flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
          {availableViews.map((v) => {
            const Icon = v.icon;
            return (
              <Button key={v.key} variant={view === v.key ? "accent" : "ghost"} icon={Icon} onClick={() => setView(v.key)}>
                {v.label}
              </Button>
            );
          })}
        </div>

        {/* Filtros */}
        <div className="flex-row" style={{ flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
          <Input placeholder="Código (O-XXXX)" value={codigo} onChange={(e) => setCodigo(e.target.value.toUpperCase())} style={{ width: 140 }} />
          {fuente === "licitadas" && (
            <Input placeholder="Cliente" value={cliente} onChange={(e) => setCliente(e.target.value)} style={{ width: 160 }} />
          )}
          <select
            value={discipline}
            onChange={(e) => setDiscipline(e.target.value)}
            style={{ padding: "6px 10px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg-surface)", minWidth: 180 }}
          >
            <option value="">— Disciplina —</option>
            {disciplinas.map((d) => (
              <option key={d} value={d}>{d.length > 50 ? d.slice(0, 50) + "…" : d}</option>
            ))}
          </select>
          <Input placeholder="Texto libre" value={text} onChange={(e) => setText(e.target.value)} style={{ width: 180 }} />
          {fuente === "licitadas" && (
            <Input placeholder="Min HH" value={minHours} onChange={(e) => setMinHours(e.target.value)} style={{ width: 90 }} type="number" />
          )}
          <Button variant="primary" icon={Search} onClick={run} disabled={loading}>
            {loading ? "Buscando…" : "Buscar"}
          </Button>
        </div>

        {err && (
          <div style={{ padding: 8, borderRadius: 6, background: "rgba(181,71,8,0.08)", border: "1px solid rgba(181,71,8,0.3)", fontSize: 12, marginBottom: 8 }}>
            ⚠️ {err}
          </div>
        )}

        {/* Tabla */}
        {data?.rows?.length > 0 ? (
          <div style={{ overflowX: "auto", maxHeight: 600 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ position: "sticky", top: 0, background: "var(--accent)", color: "white", zIndex: 1 }}>
                  {columns.map((c) => (
                    <th key={c.key} style={{ padding: "8px 10px", textAlign: c.align || "left", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                    {columns.map((c) => (
                      <td key={c.key} style={{ padding: "6px 10px", textAlign: c.align || "left" }}>
                        {c.render ? c.render(row) : (row[c.key] != null ? String(row[c.key]).slice(0, 200) : "—")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              {data.totals && (
                <tfoot>
                  <tr style={{ background: "var(--bg-alt)", fontWeight: 600 }}>
                    <td colSpan={columns.length} style={{ padding: "8px 10px", fontSize: 11 }}>
                      Total: {data.totals.rows} filas · {fmtH(data.totals.total_hours)} HH
                      {data.totals.total_amount != null && data.totals.total_amount > 0 && ` · $${fmtH(data.totals.total_amount)}`}
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        ) : (
          !loading && !err && <small className="dim">Sin resultados con esos filtros.</small>
        )}
        {data?.note && <small className="dim" style={{ display: "block", marginTop: 8 }}>{data.note}</small>}
      </Card>

      {/* Sub-agente conversacional */}
      <Card title="Preguntar al agente de entregables" subtitle="El agente adapta su respuesta al tipo de servicio (IP/IC/IB/ID)">
        <div className="flex-row" style={{ gap: 8, marginBottom: 8 }}>
          <Input
            placeholder="Ej: ¿Quién carga más HH en hidráulica? · % por profesional en O-2658 · desviación lic vs real"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !agentBusy && handleAsk()}
            disabled={agentBusy}
            style={{ flex: 1 }}
          />
          <Button variant="primary" icon={agentBusy ? Sparkles : Send} onClick={handleAsk} disabled={agentBusy || !question.trim()}>
            {agentBusy ? "Pensando…" : "Preguntar"}
          </Button>
        </div>
        {agentResp && (
          <div style={{ padding: 12, borderRadius: 6, background: "var(--bg-alt)", border: "1px solid var(--border)" }}>
            {agentResp.codigo && (
              <small className="dim" style={{ display: "block", marginBottom: 8 }}>
                <Hash size={11} style={{ verticalAlign: "middle" }} /> {agentResp.codigo}
                {agentResp.tipo_servicio && ` · servicio ${agentResp.tipo_servicio}`}
                {agentResp.adaptacion && ` · ${agentResp.adaptacion}`}
              </small>
            )}
            <div style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.5 }}>{agentResp.answer}</div>
          </div>
        )}
      </Card>
    </div>
  );
}

function buildColumns(view, fuente) {
  if (fuente === "reales" && view === "persona") {
    return [
      { key: "key", label: "Persona" },
      { key: "rol", label: "Rol", width: 120 },
      { key: "disciplina", label: "Disciplina", width: 140 },
      { key: "total_hours", label: "HH", align: "right", render: (r) => fmtH(r.total_hours) },
      { key: "pct_hours", label: "% del proyecto", render: (r) => <PctBar pct={r.pct_hours} /> },
      { key: "entregables", label: "Entreg", align: "right" },
    ];
  }
  if (view === "proyecto") {
    return [
      { key: "key", label: "Código", width: 90 },
      { key: "titulo", label: "Título" },
      { key: "cliente", label: "Cliente", width: 140 },
      { key: "total_hours", label: "HH", align: "right", render: (r) => fmtH(r.total_hours) },
      ...(fuente === "licitadas" ? [
        { key: "total_amount", label: "Monto", align: "right", render: (r) => r.total_amount ? `$${fmtH(r.total_amount)}` : "—" },
        { key: "disciplinas", label: "Disc", align: "right" },
        { key: "entregables", label: "Entreg", align: "right" },
      ] : [
        { key: "personas", label: "Personas", align: "right" },
        { key: "entregables", label: "Entreg", align: "right" },
      ]),
      { key: "pct_hours", label: "% del total", render: (r) => <PctBar pct={r.pct_hours} /> },
    ];
  }
  if (view === "disciplina") {
    return [
      { key: "key", label: "Disciplina" },
      { key: "total_hours", label: "HH", align: "right", render: (r) => fmtH(r.total_hours) },
      { key: "proyectos", label: "Proyectos", align: "right" },
      { key: "entregables", label: "Entreg", align: "right" },
      { key: "pct_hours", label: "% del total", render: (r) => <PctBar pct={r.pct_hours} /> },
    ];
  }
  if (view === "role") {
    return [
      { key: "key", label: "Rol / Profesional" },
      { key: "total_hours", label: "HH", align: "right", render: (r) => fmtH(r.total_hours) },
      { key: "proyectos", label: "Proyectos", align: "right" },
      { key: "pct_hours", label: "% del total", render: (r) => <PctBar pct={r.pct_hours} /> },
    ];
  }
  if (view === "entregable") {
    return [
      { key: "key", label: "Entregable" },
      { key: "proyecto", label: "Proyecto", width: 100 },
      { key: "disciplina", label: "Disciplina", width: 160 },
      { key: "total_hours", label: "HH", align: "right", render: (r) => fmtH(r.total_hours) },
      { key: "pct_hours", label: "% del top", render: (r) => <PctBar pct={r.pct_hours} /> },
    ];
  }
  return [];
}
