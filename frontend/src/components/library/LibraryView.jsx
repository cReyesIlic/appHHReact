import { useEffect, useMemo, useState } from "react";
import { Plus, RefreshCw, Search } from "lucide-react";
import {
  getWikiEntries,
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
  const [activeId, setActiveId] = useState(null);
  const [filter, setFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const result = await getWikiEntries();
      setEntries(result.entries || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    if (!filter.trim()) return entries;
    const q = filter.toLowerCase();
    return entries.filter((e) =>
      [e.title, e.category, ...(e.tags || []), ...(e.propuestas_referenciadas || [])]
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }, [entries, filter]);

  const active = creating
    ? null
    : entries.find((e) => e.id === activeId) || null;

  const handleSave = async (draft) => {
    setBusy(true);
    try {
      const saved = await saveWikiEntry(draft, active?.id);
      await load();
      setActiveId(saved.id || active?.id);
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
    } finally {
      setBusy(false);
    }
  };

  const handleValidate = async (id) => {
    setBusy(true);
    try {
      await validateLibraryEntry(id);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const handleReindex = async () => {
    setBusy(true);
    try {
      await reindexWiki();
      await load();
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
            <small className="dim">{entries.length} entradas</small>
          </div>
          <div style={{ flex: 1, overflow: "auto", marginTop: 8 }}>
            <EntryList
              entries={filtered}
              activeId={creating ? null : activeId}
              onSelect={(id) => {
                setCreating(false);
                setActiveId(id);
              }}
            />
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
