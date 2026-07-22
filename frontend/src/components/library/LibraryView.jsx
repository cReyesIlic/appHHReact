import { useEffect, useState } from "react";
import { Plus, RefreshCw, Search } from "lucide-react";
import {
  getWikiEntries,
  getWikiEntry,
  saveWikiEntry,
  deleteWikiEntry,
  validateLibraryEntry,
  reindexWiki,
} from "../../lib/api.js";
import { Button } from "../shared/Button.jsx";
import { Card } from "../shared/Card.jsx";
import { EmptyState } from "../shared/EmptyState.jsx";
import { Input } from "../shared/Field.jsx";
import { EntryList } from "./EntryList.jsx";
import { EntryEditor } from "./EntryEditor.jsx";

export function LibraryView() {
  const [entries, setEntries] = useState([]);
  const [active, setActive] = useState(null);
  const [activeId, setActiveId] = useState(null);
  const [filter, setFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const load = async ({ query = filter, offset = 0, append = false } = {}) => {
    setLoading(true);
    try {
      const result = await getWikiEntries({ query, limit: 50, offset });
      setEntries((current) => append ? [...current, ...(result.entries || [])] : (result.entries || []));
      setTotal(result.total || 0);
      setHasMore(Boolean(result.has_more));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => load({ query: filter, offset: 0 }), 250);
    return () => clearTimeout(timer);
  }, [filter]);

  const selectEntry = async (id) => {
    setCreating(false);
    setActiveId(id);
    setActive(null);
    try {
      setActive(await getWikiEntry(id));
    } catch {
      setActiveId(null);
    }
  };

  const handleSave = async (draft) => {
    setBusy(true);
    try {
      const saved = await saveWikiEntry(draft, active?.id);
      await load({ query: filter, offset: 0 });
      setActiveId(saved.id || active?.id);
      setActive(saved);
      setCreating(false);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (id) => {
    if (!confirm("¿Eliminar entrada?")) return;
    setBusy(true);
    try {
      await deleteWikiEntry(id);
      await load();
      setActiveId(null);
      setActive(null);
    } finally {
      setBusy(false);
    }
  };

  const handleValidate = async (id) => {
    setBusy(true);
    try {
      await validateLibraryEntry(id);
      await load({ query: filter, offset: 0 });
      setActive(await getWikiEntry(id));
    } finally {
      setBusy(false);
    }
  };

  const handleReindex = async () => {
    setBusy(true);
    try {
      await reindexWiki();
      await load({ query: filter, offset: 0 });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view-body" style={{ height: "100%" }}>
      <div className="library-grid" style={{ flex: 1, minHeight: 0 }}>
        <div className="flex-col" style={{ overflow: "hidden" }}>
          <div className="flex-row" style={{ gap: 6 }}>
            <Input
              placeholder="Buscar entradas…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <Button
              variant="accent"
              icon={Plus}
              onClick={() => {
                setActiveId(null);
                setActive(null);
                setCreating(true);
              }}
            >
              Nueva
            </Button>
          </div>
          <div className="flex-row" style={{ marginTop: 4, gap: 6 }}>
            <Button variant="ghost" icon={RefreshCw} onClick={handleReindex} disabled={busy}>
              Reindexar
            </Button>
            <small className="dim">{entries.length} de {total} entradas</small>
          </div>
          <div style={{ flex: 1, overflow: "auto", marginTop: 8 }}>
            <EntryList
              entries={entries}
              activeId={creating ? null : activeId}
              onSelect={selectEntry}
            />
            {hasMore && (
              <Button
                variant="ghost"
                onClick={() => load({ query: filter, offset: entries.length, append: true })}
                disabled={loading}
              >
                {loading ? "Cargando…" : "Cargar 50 más"}
              </Button>
            )}
          </div>
        </div>

        <div className="library-detail">
          {creating || active ? (
            <EntryEditor
              key={active?.id || "new"}
              entry={active}
              onSave={handleSave}
              onDelete={handleDelete}
              onValidate={handleValidate}
              busy={busy}
            />
          ) : activeId ? (
            <EmptyState icon={RefreshCw} title="Cargando entrada" description="Obteniendo su contenido Markdown…" />
          ) : (
            <EmptyState
              icon={Search}
              title="Selecciona una entrada"
              description="O crea una nueva. La librería curada es la capa entre Master (datos) y RAG (PDFs): aquí guardas lecciones, criterios y referencias validadas que el agente reutiliza."
              action={
                <Button variant="accent" icon={Plus} onClick={() => setCreating(true)}>
                  Crear primera entrada
                </Button>
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}
