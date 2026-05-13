import { useEffect, useState } from "react";
import { Sparkles, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import { sendChat, getSession } from "../../lib/api.js";
import { EMPTY_FILTERS, compactFilters, parseFiltersFromText } from "../../lib/filters.js";
import { Card } from "../shared/Card.jsx";
import { EmptyState } from "../shared/EmptyState.jsx";
import { Composer } from "./Composer.jsx";
import { MessageList } from "./MessageList.jsx";
import { TraceView } from "./TraceView.jsx";
import { SourcesView } from "./SourcesView.jsx";
import { ThinkingIndicator } from "./ThinkingIndicator.jsx";
import { SessionsSidebar } from "./SessionsSidebar.jsx";
import { DataTable } from "../shared/DataTable.jsx";

export function ChatView() {
  const [messages, setMessages] = useState([]);
  const [trace, setTrace] = useState([]);
  const [sources, setSources] = useState([]);
  const [tables, setTables] = useState([]);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [busy, setBusy] = useState(false);
  const [workingContext, setWorkingContext] = useState({});
  const [sessionId, setSessionId] = useState(() => localStorage.getItem("shimin_session_id") || null);
  const [sessionsRefreshKey, setSessionsRefreshKey] = useState(0);
  // Toggle paneles (persistido en localStorage)
  const [showSessions, setShowSessions] = useState(() => localStorage.getItem("shimin_show_sessions") !== "0");
  const [showProcess, setShowProcess] = useState(() => localStorage.getItem("shimin_show_process") !== "0");

  // Cargar mensajes de sesión activa al cambiar
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setTrace([]);
      setSources([]);
      setTables([]);
      setWorkingContext({});
      return;
    }
    localStorage.setItem("shimin_session_id", sessionId);
    getSession(sessionId)
      .then((s) => {
        setMessages((s.messages || []).map((m) => ({ role: m.role, content: m.content })));
        setWorkingContext(s.working_context || {});
        const last = (s.messages || []).filter((m) => m.role === "assistant").slice(-1)[0];
        setTrace(last?.trace || []);
        setSources(last?.sources || []);
        setTables(last?.tables || []);
      })
      .catch(() => {
        localStorage.removeItem("shimin_session_id");
        setSessionId(null);
      });
  }, [sessionId]);

  const handleSelectSession = (id) => {
    setSessionId(id);
    if (!id) localStorage.removeItem("shimin_session_id");
  };

  const toggleSessions = () => {
    setShowSessions((v) => {
      localStorage.setItem("shimin_show_sessions", v ? "0" : "1");
      return !v;
    });
  };

  const toggleProcess = () => {
    setShowProcess((v) => {
      localStorage.setItem("shimin_show_process", v ? "0" : "1");
      return !v;
    });
  };

  const handleSend = async (text) => {
    setBusy(true);
    const userMsg = { role: "user", content: text };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);

    const detected = parseFiltersFromText(text);
    const merged = mergeFilters(filters, detected);
    const compactedFilters = compactFilters(merged);

    try {
      const response = await sendChat({
        message: text,
        history: newMessages.slice(-12),
        selected_codes: workingContext.suggested_codes || [],
        deep_pdf_read: false,
        working_context: workingContext,
        filters: compactedFilters,
        session_id: sessionId,
        create_session_if_missing: true,
      });
      setMessages((prev) => [...prev, { role: "assistant", content: response.answer || "(sin respuesta)" }]);
      setTrace(response.trace || []);
      setSources(response.sources || []);
      setTables(response.tables || []);
      setWorkingContext(response.working_context || {});
      // Si vino session_id distinto (creación inicial), guardarlo y refrescar lista
      if (response.session_id && response.session_id !== sessionId) {
        setSessionId(response.session_id);
      }
      setSessionsRefreshKey((k) => k + 1);
    } catch (exc) {
      setMessages((prev) => [...prev, { role: "assistant", content: `❌ Error: ${exc.message}` }]);
    } finally {
      setBusy(false);
    }
  };

  const gridTemplate = `${showSessions ? "260px" : "0px"} 1fr`;
  const chatGrid = `1fr ${showProcess ? "320px" : "0px"}`;

  return (
    <div className="view-body" style={{ height: "100%", paddingBottom: 0 }}>
      <div className="chat-view-with-sessions" style={{ gridTemplateColumns: gridTemplate }}>
        {showSessions && (
          <SessionsSidebar activeId={sessionId} onSelect={handleSelectSession} refreshKey={sessionsRefreshKey} />
        )}
        <div className="chat-view" style={{ gridTemplateColumns: chatGrid }}>
          <div className="chat-main">
            <div className="chat-toolbar">
              <button
                type="button"
                className="btn-icon"
                title={showSessions ? "Ocultar conversaciones" : "Mostrar conversaciones"}
                onClick={toggleSessions}
              >
                {showSessions ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}
              </button>
              <div className="chat-toolbar-spacer" />
              <button
                type="button"
                className="btn-icon"
                title={showProcess ? "Ocultar proceso del agente" : "Mostrar proceso del agente"}
                onClick={toggleProcess}
              >
                {showProcess ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
              </button>
            </div>
            {messages.length === 0 ? (
              <EmptyState
                icon={Sparkles}
                title="¿Sobre qué quieres preguntar?"
                description="El agente combina Master + RAG + Wiki para responder cualquier consulta. Usa los filtros o el chat. Crea nuevas conversaciones desde la barra izquierda."
              />
            ) : (
              <MessageList messages={messages} busy={busy} latestTables={tables} latestSources={sources} />
            )}
            {messages.length === 0 && busy && (
              <div style={{ marginTop: 12 }}>
                <ThinkingIndicator />
              </div>
            )}
            {tables.length > 0 && (
              <div className="flex-col">
                {tables.map((tbl, idx) => (
                  <Card key={idx} title={tbl.name || `Tabla ${idx + 1}`}>
                    <DataTable
                      columns={inferColumns(tbl.rows)}
                      rows={tbl.rows || []}
                    />
                  </Card>
                ))}
              </div>
            )}
            <Composer filters={filters} onFiltersChange={setFilters} onSend={handleSend} busy={busy} />
          </div>
          {showProcess && (
            <aside className="chat-side">
              <Card title="Proceso del agente" subtitle="trace de tool calls">
                {trace.length === 0 ? <small className="dim">Sin actividad aún.</small> : <TraceView trace={trace} />}
              </Card>
              <Card title="Fuentes" subtitle={`${sources.length} referencias`}>
                {sources.length === 0 ? <small className="dim">Las fuentes aparecerán aquí.</small> : <SourcesView sources={sources} />}
              </Card>
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}

function mergeFilters(base, detected) {
  if (!detected) return base;
  const out = { ...base };
  for (const [k, v] of Object.entries(detected)) {
    if (Array.isArray(v) && v.length) {
      const existing = new Set(base[k] || []);
      v.forEach((x) => existing.add(x));
      out[k] = Array.from(existing);
    }
  }
  return out;
}

function inferColumns(rows) {
  if (!rows || rows.length === 0) return [];
  const keys = Object.keys(rows[0]);
  return keys.slice(0, 8).map((key) => ({ key, label: key }));
}
