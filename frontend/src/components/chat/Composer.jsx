import { useState } from "react";
import { Send } from "lucide-react";
import { FilterChips } from "../shared/FilterChips.jsx";
import { Button } from "../shared/Button.jsx";

export function Composer({ filters, onFiltersChange, onSend, busy }) {
  const [text, setText] = useState("");
  const submit = () => {
    const value = text.trim();
    if (!value || busy) return;
    onSend(value);
    setText("");
  };
  return (
    <div className="composer">
      <FilterChips filters={filters} onChange={onFiltersChange} />
      <div className="composer-row">
        <textarea
          className="composer-textarea"
          placeholder="Pregunta cualquier cosa sobre proyectos, propuestas, estadísticas…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={Math.min(6, Math.max(1, text.split("\n").length))}
        />
        <Button variant="accent" icon={Send} onClick={submit} disabled={busy}>
          {busy ? "Procesando…" : "Enviar"}
        </Button>
      </div>
    </div>
  );
}
