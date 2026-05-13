import { useEffect, useState } from "react";
import { Plus, Trash2, Edit2, MessageSquare } from "lucide-react";
import { listSessions, createSession, renameSession, deleteSession } from "../../lib/api.js";

export function SessionsSidebar({ activeId, onSelect, refreshKey }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [renamingId, setRenamingId] = useState(null);
  const [renameText, setRenameText] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await listSessions(60);
      setSessions(r.sessions || []);
    } catch (exc) {
      console.error(exc);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [refreshKey]);

  const handleNew = async () => {
    const s = await createSession();
    await load();
    onSelect(s.id);
  };

  const handleDelete = async (id) => {
    if (!confirm("¿Eliminar esta conversación?")) return;
    await deleteSession(id);
    if (activeId === id) onSelect(null);
    await load();
  };

  const startRename = (s) => {
    setRenamingId(s.id);
    setRenameText(s.title);
  };
  const commitRename = async () => {
    if (renameText.trim()) {
      await renameSession(renamingId, renameText.trim());
    }
    setRenamingId(null);
    setRenameText("");
    await load();
  };

  return (
    <aside className="sessions-sidebar">
      <div className="sessions-header">
        <button className="btn btn-accent" onClick={handleNew} style={{ width: "100%" }}>
          <Plus size={14} /> Nueva conversación
        </button>
      </div>
      <div className="sessions-list">
        {loading && <small className="dim" style={{ padding: 8 }}>Cargando…</small>}
        {!loading && sessions.length === 0 && (
          <small className="dim" style={{ padding: 8 }}>Aún sin conversaciones.</small>
        )}
        {sessions.map((s) => (
          <div
            key={s.id}
            className={`session-item${activeId === s.id ? " active" : ""}`}
            onClick={() => renamingId !== s.id && onSelect(s.id)}
          >
            <MessageSquare size={13} className="session-icon" />
            {renamingId === s.id ? (
              <input
                autoFocus
                value={renameText}
                onChange={(e) => setRenameText(e.target.value)}
                onBlur={commitRename}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename();
                  if (e.key === "Escape") { setRenamingId(null); setRenameText(""); }
                }}
                onClick={(e) => e.stopPropagation()}
                className="session-rename"
              />
            ) : (
              <>
                <div className="session-text">
                  <div className="session-title">{s.title}</div>
                  <div className="session-meta">{formatRelative(s.last_message_at || s.updated_at)} · {s.message_count} msg</div>
                </div>
                <div className="session-actions" onClick={(e) => e.stopPropagation()}>
                  <button className="btn-icon" title="Renombrar" onClick={() => startRename(s)}>
                    <Edit2 size={12} />
                  </button>
                  <button className="btn-icon" title="Eliminar" onClick={() => handleDelete(s.id)}>
                    <Trash2 size={12} />
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </aside>
  );
}

function formatRelative(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "ahora";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const days = Math.floor(h / 24);
  if (days < 7) return `${days}d`;
  return d.toLocaleDateString();
}
