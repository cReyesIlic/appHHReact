import { Pin } from "lucide-react";
import { Chip } from "../shared/Chip.jsx";
import { ValidationBadge } from "./ValidationBadge.jsx";

export function EntryList({ entries, activeId, onSelect }) {
  if (!entries || entries.length === 0) {
    return <small className="dim">Aún no hay entradas. Crea la primera.</small>;
  }
  return (
    <div className="library-list">
      {entries.map((entry) => (
        <button
          key={entry.id}
          type="button"
          className={`library-entry${entry.id === activeId ? " active" : ""}`}
          onClick={() => onSelect(entry.id)}
        >
          <div className="library-entry-title">
            {entry.pinned && <Pin size={11} style={{ marginRight: 4, color: "var(--accent)" }} />}
            {entry.title}
          </div>
          <div className="library-entry-meta">
            <Chip>{entry.category || "general"}</Chip>
            <ValidationBadge status={entry.validation_status || "unchecked"} />
            {(entry.tags || []).slice(0, 3).map((t) => (
              <Chip key={t}>{t}</Chip>
            ))}
            {entry.times_used > 0 && <small className="dim">usada {entry.times_used}×</small>}
          </div>
        </button>
      ))}
    </div>
  );
}
