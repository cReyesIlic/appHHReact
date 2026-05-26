import { useEffect, useMemo, useState } from "react";
import { Hash, Search, Sparkles, Users, Briefcase, BookOpen, Workflow, RefreshCw, Send } from "lucide-react";
import { getEntregablesStats, getEntregablesDisciplinas, getEntregablesAggregate, getEntregablesTiposServicio, askEntregablesAgent } from "../../lib/api.js";
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
  const [tiposServicio, setTiposServicio] = useState([]);
  const [fuente, setFuente] = useState("licitadas");
  const [view, setView] = useState("proyecto");
  const [codigo, setCodigo] = useState("");
  const [cliente, setCliente] = useState("");
  const [tipoServicio, setTipoServicio] = useState("");
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
    // Solo carga estadísticas livianas + lista de disciplinas. NO dispara aggregate.
    // El user debe hacer clic en "Buscar" — evita colgar la UI al abrir la pestaña.
    getEntregablesStats().then(setStats).catch((exc) => setErr(exc.detail || exc.message));
    getEntregablesDisciplinas(40).then((r) => setDisciplinas(r.disciplinas || [])).catch(() => {});
    getEntregablesTiposServicio().then((r) => setTiposServicio(r.catalogo || [])).catch(() => {});
  }, []);

  useEffect(() => {
    // Si cambia el toggle Licitadas/Reales y la vista activa no aplica, ajusta.
    if (fuente === "reales" && view === "role") {
      setView("entregable");
    }
    // No re-ejecutar búsqueda automáticamente al cambiar fuente/view —
    // el user controla cuándo lanzar la query.
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
        tipo_servicio: tipoServicio || undefined,
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
            ? (stats.empty
                ? "⚠️ Tabla hh_estimate_rows vacía"
                : `Local: ${fmtH(stats.rows)} filas plausibles · ${stats.proyectos} proyectos · ${fmtH(stats.total_hours)} HH totales licitadas`)
            : "Cargando estadísticas…"
        }
      >
        {stats?.empty && (
          <div style={{ padding: 10, borderRadius: 6, background: "rgba(181,71,8,0.08)", border: "1px solid rgba(181,71,8,0.3)", fontSize: 12 }}>
            ⚠️ No hay entregables cargados. {stats.hint}
          </div>
        )}
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
            value={tipoServicio}
            onChange={(e) => setTipoServicio(e.target.value)}
            style={{ padding: "6px 10px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg-surface)", minWidth: 140 }}
            title="Tipo de servicio (IP/IC/IB/ID/etc) del master"
          >
            <option value="">— Servicio —</option>
            {tiposServicio.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
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
        {!data && !loading && !err && (
          <div style={{ padding: 16, textAlign: "center", color: "var(--text-muted)", fontSize: 13, background: "var(--bg-alt)", borderRadius: 6 }}>
            Elige fuente, vista y filtros — luego pulsa <b>Buscar</b>.
          </div>
        )}
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
      { key: "key", label: "Código", width: 80 },
      { key: "titulo", label: "Título", render: (r) => r.titulo ? String(r.titulo).slice(0, 60) : "—" },
      { key: "cliente", label: "Cliente", width: 130 },
      ...(fuente === "licitadas" ? [
        {
          key: "tipo_servicio",
          label: "Servicio",
          width: 90,
          render: (r) => {
            const ts = r.tipo_servicio;
            if (!ts || ts === "No data") return "—";
            const color = ts.startsWith("IP") ? "#0369a1"
              : ts.startsWith("IC") ? "#7c3aed"
              : ts.startsWith("IB") ? "#b54708"
              : ts.startsWith("ID") ? "#047857"
              : "#5f747d";
            return <span style={{ background: color, color: "white", padding: "2px 6px", borderRadius: 4, fontSize: 10, fontWeight: 600 }}>{ts}</span>;
          },
        },
        {
          key: "tamano",
          label: "Tamaño",
          width: 90,
          render: (r) => {
            const map = { muy_grande: ["🔥 muy grande", "#b91c1c"], grande: ["🟠 grande", "#b54708"], mediano: ["🟡 mediano", "#a16207"], chico: ["🟢 chico", "#15803d"] };
            const [label, color] = map[r.tamano] || ["—", "#5f747d"];
            return <span style={{ color, fontSize: 11, fontWeight: 600 }}>{label}</span>;
          },
        },
        { key: "total_hours", label: "HH (Excel)", align: "right", render: (r) => fmtH(r.total_hours) },
        { key: "horas_lic_master", label: "HH (master)", align: "right", render: (r) => r.horas_lic_master ? fmtH(r.horas_lic_master) : "—" },
        {
          key: "match_master_pct",
          label: "Excel/Master",
          align: "right",
          render: (r) => {
            if (r.match_master_pct == null) return "—";
            const color = Math.abs(r.match_master_pct - 100) <= 20 ? "#047857" : Math.abs(r.match_master_pct - 100) <= 60 ? "#a16207" : "#b91c1c";
            const flag = r.sospechoso ? " ⚠️" : "";
            return <span style={{ color, fontWeight: 600, fontSize: 11 }} title={r.sospechoso ? "Excel difiere mucho del master — revisar extracción" : ""}>{r.match_master_pct}%{flag}</span>;
          },
        },
        { key: "monto_master", label: "Monto", align: "right", render: (r) => r.monto_master ? `$${fmtH(r.monto_master)}` : "—" },
        { key: "disciplinas", label: "Disc", align: "right" },
      ] : [
        { key: "total_hours", label: "HH reales", align: "right", render: (r) => fmtH(r.total_hours) },
        { key: "personas", label: "Personas", align: "right" },
        { key: "entregables", label: "Entreg", align: "right" },
      ]),
      { key: "pct_hours", label: "% top", render: (r) => <PctBar pct={r.pct_hours} /> },
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
