import { useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen, Briefcase, FileSpreadsheet, Hash, Loader2, RefreshCw,
  Search, Send, Sparkles, Upload, Users, Workflow,
} from "lucide-react";
import {
  askEntregablesAgent,
  extractEntregablesFromSharePoint,
  getEntregablesAggregate,
  getEntregablesDisciplinas,
  getEntregablesStats,
  getEntregablesTiposServicio,
  uploadCoverageAsset,
} from "../../lib/api.js";
import { Button } from "../shared/Button.jsx";
import { Card } from "../shared/Card.jsx";
import { Input } from "../shared/Field.jsx";
import { MarkdownView } from "../shared/MarkdownView.jsx";

const VIEWS = [
  { key: "proyecto", label: "Por proyecto", icon: Briefcase },
  { key: "disciplina", label: "Por disciplina", icon: Workflow },
  { key: "role", label: "Por rol", icon: Users },
  { key: "entregable", label: "Por entregable", icon: BookOpen },
];

const DISCIPLINE_COLORS = {
  hidraulica: "#0369a1", mecanica: "#7c3aed", piping: "#0f766e",
  electricidad: "#b7791f", "instrumentacion y control": "#be185d",
  "civil estructural": "#b54708", "geologia y geotecnia": "#6b7280",
  general: "#475569", multidisciplinario: "#334155", "control documental": "#a16207",
};

const SERVICE_COLORS = {
  IP: "#0891b2", IC: "#7c3aed", IB: "#b54708", IBA: "#c2410c",
  ID: "#047857", EP: "#0369a1", EPC: "#1d4ed8", EPCM: "#4338ca",
};

function normalize(value) {
  return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function fmtH(value, decimals = 0) {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString("es-CL", { maximumFractionDigits: decimals });
}

function ServiceBadge({ value, inferred = false }) {
  if (!value) return <span className="dim">—</span>;
  const key = String(value).toUpperCase();
  const color = Object.entries(SERVICE_COLORS).find(([prefix]) => key.startsWith(prefix))?.[1] || "#5f747d";
  return (
    <span className="hh-badge" style={{ background: color }} title={inferred ? "Tipo inferido desde el título porque Master no trae dato" : "Tipo de servicio del Master"}>
      {value}{inferred ? "*" : ""}
    </span>
  );
}

function DisciplineBadge({ value }) {
  const color = DISCIPLINE_COLORS[normalize(value)] || "#5f747d";
  return <span className="hh-badge hh-badge-soft" style={{ "--badge-color": color }}>{value || "Sin disciplina"}</span>;
}

function SourceBadge({ row }) {
  const own = row.source_type === "own_reader" || row.source_types?.includes("own_reader");
  const staffing = row.source_type === "staffing";
  const label = staffing ? "Staffing" : own ? "Lector propio" : "Master";
  return <span className={`hh-source hh-source-${staffing ? "staffing" : own ? "reader" : "master"}`}>{label}</span>;
}

function Comparison({ row }) {
  if (row.match_master_pct == null) return <span className="dim">Sin HH Master</span>;
  const status = row.comparison_status || "review";
  return (
    <div className={`hh-comparison hh-comparison-${status}`} title="Suma de HH mostradas / HH licitadas del Master">
      <b>{row.match_master_pct}%</b>
      <small>{row.delta_hours > 0 ? "+" : ""}{fmtH(row.delta_hours)} HH</small>
    </div>
  );
}

function PctBar({ pct }) {
  const value = Math.min(100, Math.max(0, Number(pct) || 0));
  return (
    <div className="hh-pct">
      <div><span style={{ width: `${value}%` }} /></div>
      <small>{value.toFixed(1)}%</small>
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
  const [searchText, setSearchText] = useState("");
  const [minHours, setMinHours] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState({ key: "total_hours", direction: "desc" });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const [uploadCode, setUploadCode] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const fileRef = useRef(null);

  const [question, setQuestion] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentResp, setAgentResp] = useState(null);

  const loadMeta = async () => {
    const results = await Promise.allSettled([
      getEntregablesStats(), getEntregablesDisciplinas(100), getEntregablesTiposServicio(),
    ]);
    if (results[0].status === "fulfilled") setStats(results[0].value);
    else setError(results[0].reason?.detail || results[0].reason?.message);
    if (results[1].status === "fulfilled") setDisciplinas(results[1].value.disciplinas || []);
    if (results[2].status === "fulfilled") setTiposServicio(results[2].value.catalogo || []);
  };

  const run = async (overrides = {}) => {
    const next = {
      fuente, view, codigo, cliente, tipoServicio, discipline, searchText, minHours,
      ...overrides,
    };
    setLoading(true);
    setError(null);
    setPage(1);
    try {
      const result = await getEntregablesAggregate({
        fuente: next.fuente,
        view: next.fuente === "reales" && next.view === "role" ? "proyecto" : next.view,
        codigo: next.codigo || undefined,
        cliente: next.fuente === "licitadas" ? next.cliente || undefined : undefined,
        tipo_servicio: next.fuente === "licitadas" ? next.tipoServicio || undefined : undefined,
        disciplina: next.discipline || undefined,
        text: next.searchText || undefined,
        min_hours: next.fuente === "licitadas" && next.minHours ? Number(next.minHours) : undefined,
        limit: next.fuente === "licitadas" ? 2000 : 500,
      });
      setData(result);
      if (result.error) setError(result.error);
    } catch (exc) {
      setError(exc.detail || exc.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMeta();
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changeSource = (nextSource) => {
    setFuente(nextSource);
    setView("proyecto");
    setCodigo("");
    setCliente("");
    setTipoServicio("");
    setDiscipline("");
    setSearchText("");
    run({ fuente: nextSource, view: "proyecto", codigo: "", cliente: "", tipoServicio: "", discipline: "", searchText: "" });
  };

  const changeView = (nextView) => {
    setView(nextView);
    run({ view: nextView });
  };

  const openProject = (projectCode) => {
    setCodigo(projectCode);
    setView("entregable");
    run({ codigo: projectCode, view: "entregable" });
  };

  const handleUpload = async (mode) => {
    const code = uploadCode.trim().toUpperCase();
    if (!/^O-?\d{2,6}$/.test(code)) {
      setUploadResult({ error: "Ingresa un código O-XXXX válido." });
      return;
    }
    if (mode === "file" && !uploadFile) {
      setUploadResult({ error: "Selecciona un Excel." });
      return;
    }
    setUploading(true);
    setUploadResult(null);
    try {
      const result = mode === "sharepoint"
        ? await extractEntregablesFromSharePoint(code)
        : await uploadCoverageAsset(code, uploadFile);
      setUploadResult(result);
      setCodigo(code);
      await loadMeta();
      await run({ fuente: "licitadas", view: "entregable", codigo: code });
      setFuente("licitadas");
      setView("entregable");
    } catch (exc) {
      setUploadResult({ error: exc.detail || exc.message });
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
      setUploadFile(null);
    }
  };

  const handleAsk = async () => {
    const value = question.trim();
    if (!value) return;
    setAgentBusy(true);
    setAgentResp(null);
    try {
      setAgentResp(await askEntregablesAgent({ question: value, codigo: codigo || undefined }));
    } catch (exc) {
      setAgentResp({ answer: `No se pudo consultar: ${exc.detail || exc.message}` });
    } finally {
      setAgentBusy(false);
    }
  };

  const availableViews = fuente === "reales"
    ? VIEWS.filter((item) => item.key !== "role").concat([{ key: "persona", label: "Por persona", icon: Users }])
    : VIEWS;
  const columns = buildColumns(view, fuente, openProject);
  const sortedRows = useMemo(() => {
    const rows = [...(data?.rows || [])];
    rows.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      const numeric = typeof av === "number" || typeof bv === "number";
      const cmp = numeric ? (Number(av) || 0) - (Number(bv) || 0) : String(av || "").localeCompare(String(bv || ""), "es");
      return sort.direction === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [data, sort]);
  const pages = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const visibleRows = sortedRows.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div className="flex-col entregables-view">
      <Card
        title="Entregables y horas hombre"
        subtitle={stats ? `${fmtH(stats.rows)} entregables · ${fmtH(stats.proyectos)} proyectos · ${fmtH(stats.total_hours)} HH licitadas conciliables` : "Cargando fuentes…"}
        actions={<Button variant="ghost" icon={RefreshCw} onClick={() => { loadMeta(); run(); }} disabled={loading}>Actualizar</Button>}
      >
        {stats && (
          <div className="hh-source-summary">
            <div><b>{fmtH(stats.sources?.master_structured?.projects)}</b><small>proyectos estructurados Master</small></div>
            <div><b>{fmtH(stats.sources?.own_reader?.projects)}</b><small>proyectos procesados por lector propio</small></div>
            <div><b>{stats.reader_available ? "Activo" : "No configurado"}</b><small>Azure Budget Extractor</small></div>
            <div><b>{stats.staffing_available ? "Activo" : "No configurado"}</b><small>Staffing · sólo HH reales</small></div>
          </div>
        )}
        <small className="dim">El extractor exploratorio se excluye de los totales para evitar que números de ítem sean contados como horas.</small>
      </Card>

      <Card title="Cargar o reprocesar un presupuesto" subtitle="Zona propia de Entregables/HH; no usa el lector de Staffing">
        <div className="hh-upload-room">
          <Input placeholder="O-XXXX" value={uploadCode} onChange={(event) => setUploadCode(event.target.value.toUpperCase())} disabled={uploading} />
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xlsm,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(event) => setUploadFile(event.target.files?.[0] || null)}
            disabled={uploading}
          />
          <Button variant="primary" icon={uploading ? Loader2 : Upload} onClick={() => handleUpload("file")} disabled={uploading || !uploadFile}>
            Procesar Excel
          </Button>
          <Button variant="ghost" icon={FileSpreadsheet} onClick={() => handleUpload("sharepoint")} disabled={uploading || !uploadCode.trim()}>
            Leer desde SharePoint
          </Button>
        </div>
        {uploadFile && <small className="dim">Seleccionado: {uploadFile.name}</small>}
        {uploadResult && <UploadResult result={uploadResult} />}
      </Card>

      <Card>
        <div className="hh-toolbar">
          <div className="flex-row" style={{ flexWrap: "wrap" }}>
            <Button variant={fuente === "licitadas" ? "primary" : "ghost"} onClick={() => changeSource("licitadas")}>HH licitadas · Excel</Button>
            <Button variant={fuente === "reales" ? "primary" : "ghost"} onClick={() => changeSource("reales")}>HH reales · Staffing</Button>
          </div>
          <small className="dim">{fuente === "licitadas" ? "Presupuesto original y lector propio" : "Carga semanal ejecutada por personas"}</small>
        </div>

        <div className="flex-row hh-view-tabs">
          {availableViews.map((item) => {
            const Icon = item.icon;
            return <Button key={item.key} variant={view === item.key ? "accent" : "ghost"} icon={Icon} onClick={() => changeView(item.key)}>{item.label}</Button>;
          })}
        </div>

        <div className="hh-filters">
          <Input placeholder={fuente === "reales" ? "O-XXXX o SH-XXXX" : "O-XXXX"} value={codigo} onChange={(event) => setCodigo(event.target.value.toUpperCase())} />
          {fuente === "licitadas" && <Input placeholder="Cliente" value={cliente} onChange={(event) => setCliente(event.target.value)} />}
          {fuente === "licitadas" && (
            <select value={tipoServicio} onChange={(event) => setTipoServicio(event.target.value)}>
              <option value="">Todos los servicios</option>
              {tiposServicio.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          )}
          <select value={discipline} onChange={(event) => setDiscipline(event.target.value)}>
            <option value="">Todas las disciplinas</option>
            {disciplinas.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <Input placeholder="Buscar entregable o proyecto" value={searchText} onChange={(event) => setSearchText(event.target.value)} onKeyDown={(event) => event.key === "Enter" && run()} />
          {fuente === "licitadas" && <Input placeholder="HH mínimas" type="number" value={minHours} onChange={(event) => setMinHours(event.target.value)} />}
          <Button variant="primary" icon={loading ? Loader2 : Search} onClick={() => run()} disabled={loading}>{loading ? "Consultando…" : "Aplicar"}</Button>
        </div>

        {error && <div className="hh-alert">{error}</div>}
        {!loading && data?.rows?.length > 0 && (
          <>
            <div className="hh-table-wrap">
              <table className="hh-table">
                <thead><tr>{columns.map((column) => (
                  <th key={column.key} onClick={() => {
                    setSort((current) => ({ key: column.key, direction: current.key === column.key && current.direction === "asc" ? "desc" : "asc" }));
                    setPage(1);
                  }}>
                    {column.label}{sort.key === column.key ? (sort.direction === "asc" ? " ↑" : " ↓") : ""}
                  </th>
                ))}</tr></thead>
                <tbody>{visibleRows.map((row, index) => (
                  <tr key={`${row.key}-${row.proyecto || ""}-${index}`}>
                    {columns.map((column) => <td key={column.key}>{column.render ? column.render(row) : row[column.key] ?? "—"}</td>)}
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <div className="hh-pagination">
              <small className="dim">
                Mostrando {Math.min((page - 1) * pageSize + 1, sortedRows.length)}–{Math.min(page * pageSize, sortedRows.length)} de {fmtH(data.available_rows ?? sortedRows.length)} · {fmtH(data.totals?.total_hours)} HH
              </small>
              <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }}>
                {[25, 50, 100].map((value) => <option key={value} value={value}>{value} filas</option>)}
              </select>
              <Button variant="ghost" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1}>Anterior</Button>
              <small>{page} / {pages}</small>
              <Button variant="ghost" onClick={() => setPage((value) => Math.min(pages, value + 1))} disabled={page >= pages}>Siguiente</Button>
            </div>
          </>
        )}
        {!loading && !error && data?.rows?.length === 0 && <div className="hh-empty">Sin resultados. Ajusta filtros o selecciona un proyecto.</div>}
        {data?.note && <small className="dim">{data.note}</small>}
      </Card>

      <Card title="Analista de entregables" subtitle="Compara HH licitadas, reales y Master indicando siempre la fuente">
        <div className="flex-row">
          <Input
            placeholder="Ej.: compara las HH licitadas y reales de O-2239 por disciplina"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && !agentBusy && handleAsk()}
            disabled={agentBusy}
            style={{ flex: 1 }}
          />
          <Button variant="primary" icon={agentBusy ? Sparkles : Send} onClick={handleAsk} disabled={agentBusy || !question.trim()}>{agentBusy ? "Analizando…" : "Preguntar"}</Button>
        </div>
        {agentResp && (
          <div className="hh-agent-answer">
            {agentResp.codigo && <small className="dim"><Hash size={11} /> {agentResp.codigo}{agentResp.tipo_servicio ? ` · ${agentResp.tipo_servicio}` : ""}</small>}
            <MarkdownView content={agentResp.answer || ""} />
          </div>
        )}
      </Card>
    </div>
  );
}

function UploadResult({ result }) {
  if (result.error) return <div className="hh-alert">{result.error}</div>;
  const persisted = result.budget_extractor?.persisted;
  const sharepointPersisted = (result.results || []).reduce((total, item) => {
    total.rows += Number(item.persisted?.proyecto_filas || 0);
    total.rates += Number(item.persisted?.tarifas_filas || 0);
    total.expenses += Number(item.persisted?.gastos_filas || 0);
    return total;
  }, { rows: 0, rates: 0, expenses: 0 });
  const rows = persisted?.proyecto_filas ?? sharepointPersisted.rows;
  return (
    <div className="hh-upload-result">
      <b>Lector propio completado</b>
      <span>{fmtH(rows)} filas de entregables/roles</span>
      <span>{fmtH(persisted?.tarifas_filas ?? sharepointPersisted.rates)} tarifas</span>
      <span>{fmtH(persisted?.gastos_filas ?? sharepointPersisted.expenses)} gastos</span>
      {result.hh_rows != null && <span>{fmtH(result.hh_rows)} filas exploratorias separadas</span>}
    </div>
  );
}

function buildColumns(view, source, openProject) {
  const projectButton = (value) => <button type="button" className="hh-project-link" onClick={() => openProject(value)}>{value}</button>;
  if (view === "proyecto") {
    const shared = [
      { key: "key", label: source === "reales" ? "Proyecto SH" : "Oferta", render: (row) => projectButton(row.key) },
      ...(source === "reales" ? [{ key: "codigo_oferta", label: "Oferta O" }] : []),
      { key: "titulo", label: "Proyecto", render: (row) => <span title={row.titulo}>{row.titulo || "—"}</span> },
      { key: "cliente", label: "Cliente" },
      { key: "tipo_servicio", label: "Servicio", render: (row) => <ServiceBadge value={row.tipo_servicio} inferred={row.tipo_servicio_source === "titulo"} /> },
      { key: "total_hours", label: source === "reales" ? "HH reales" : "Σ HH entregables", render: (row) => <b>{fmtH(row.total_hours, 1)}</b> },
      { key: "horas_lic_master", label: "HH Master", render: (row) => fmtH(row.horas_lic_master, 1) },
      { key: "match_master_pct", label: "Conciliación", render: (row) => <Comparison row={row} /> },
    ];
    if (source === "reales") return [
      ...shared,
      { key: "personas", label: "Personas" }, { key: "entregables", label: "Entregables" },
      { key: "source_type", label: "Fuente", render: (row) => <SourceBadge row={row} /> },
    ];
    return [
      ...shared,
      { key: "entregables", label: "Entregables" },
      { key: "disciplinas", label: "Disciplinas", render: (row) => <div className="hh-badge-list">{(row.disciplinas_nombres || []).map((item) => <DisciplineBadge key={item} value={item} />)}</div> },
      { key: "source_type", label: "Fuente", render: (row) => <SourceBadge row={row} /> },
    ];
  }
  if (view === "disciplina") return [
    { key: "key", label: "Disciplina", render: (row) => <DisciplineBadge value={row.key} /> },
    { key: "total_hours", label: "HH", render: (row) => <b>{fmtH(row.total_hours, 1)}</b> },
    { key: "proyectos", label: "Proyectos" }, { key: "entregables", label: "Entregables" },
    { key: "pct_hours", label: "% total", render: (row) => <PctBar pct={row.pct_hours} /> },
  ];
  if (view === "role") return [
    { key: "key", label: "Rol" }, { key: "total_hours", label: "HH", render: (row) => <b>{fmtH(row.total_hours, 1)}</b> },
    { key: "proyectos", label: "Proyectos" }, { key: "pct_hours", label: "% total", render: (row) => <PctBar pct={row.pct_hours} /> },
  ];
  if (view === "persona") return [
    { key: "key", label: "Persona" }, { key: "rol", label: "Rol" },
    { key: "disciplina", label: "Disciplina", render: (row) => <DisciplineBadge value={row.disciplina} /> },
    { key: "total_hours", label: "HH reales", render: (row) => <b>{fmtH(row.total_hours, 1)}</b> },
    { key: "entregables", label: "Entregables" }, { key: "semanas", label: "Semanas" },
    { key: "pct_hours", label: "% proyecto", render: (row) => <PctBar pct={row.pct_hours} /> },
  ];
  return [
    { key: "key", label: "Entregable", render: (row) => <span title={row.key}>{row.key}</span> },
    { key: "proyecto", label: "Proyecto", render: (row) => projectButton(row.proyecto) },
    { key: "disciplina", label: "Disciplina", render: (row) => <DisciplineBadge value={row.disciplina} /> },
    { key: "tipo_servicio", label: "Servicio", render: (row) => <ServiceBadge value={row.tipo_servicio} inferred={row.tipo_servicio_source === "titulo"} /> },
    { key: "tipo_entregable", label: "Tipo" },
    { key: "total_hours", label: "HH", render: (row) => <b>{fmtH(row.total_hours, 1)}</b> },
    { key: "source_type", label: "Fuente", render: (row) => <SourceBadge row={row} /> },
    { key: "pct_hours", label: "%", render: (row) => <PctBar pct={row.pct_hours} /> },
  ];
}
