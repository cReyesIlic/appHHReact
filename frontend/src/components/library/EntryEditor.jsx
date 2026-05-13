import { useEffect, useState } from "react";
import { Save, Trash2, ShieldCheck, Plus } from "lucide-react";
import { Button } from "../shared/Button.jsx";
import { Field, Input, Textarea } from "../shared/Field.jsx";
import { Chip } from "../shared/Chip.jsx";
import { ValidationBadge } from "./ValidationBadge.jsx";

const EMPTY = {
  title: "",
  category: "lecciones_aprendidas",
  tags: [],
  propuestas_referenciadas: [],
  content: "",
  pinned: false,
};

export function EntryEditor({ entry, onSave, onDelete, onValidate, busy }) {
  const [draft, setDraft] = useState(entry || EMPTY);
  const [tagInput, setTagInput] = useState("");
  const [codeInput, setCodeInput] = useState("");

  useEffect(() => {
    setDraft(entry || EMPTY);
    setTagInput("");
    setCodeInput("");
  }, [entry?.id]);

  const update = (key, value) => setDraft((prev) => ({ ...prev, [key]: value }));
  const addTag = () => {
    const v = tagInput.trim();
    if (!v) return;
    update("tags", [...(draft.tags || []), v]);
    setTagInput("");
  };
  const addCode = () => {
    const v = codeInput.trim().toUpperCase();
    if (!v) return;
    update("propuestas_referenciadas", [...(draft.propuestas_referenciadas || []), v]);
    setCodeInput("");
  };

  const save = () => onSave(draft);

  return (
    <div className="flex-col" style={{ gap: 16 }}>
      <div className="flex-row" style={{ justifyContent: "space-between" }}>
        <div className="flex-col" style={{ gap: 4 }}>
          <h2>{entry ? "Editar entrada" : "Nueva entrada"}</h2>
          {entry && (
            <div className="flex-row" style={{ gap: 8 }}>
              <ValidationBadge status={entry.validation_status || "unchecked"} />
              {entry.validated_at && <small className="dim">validada {new Date(entry.validated_at).toLocaleString()}</small>}
              {entry.times_used > 0 && <small className="dim">· usada {entry.times_used}×</small>}
            </div>
          )}
        </div>
        <div className="flex-row" style={{ gap: 6 }}>
          {entry && (
            <Button variant="ghost" icon={ShieldCheck} onClick={() => onValidate(entry.id)} disabled={busy}>
              Validar
            </Button>
          )}
          {entry && (
            <Button variant="ghost" icon={Trash2} onClick={() => onDelete(entry.id)} disabled={busy}>
              Borrar
            </Button>
          )}
          <Button variant="accent" icon={Save} onClick={save} disabled={busy}>
            {entry ? "Guardar" : "Crear"}
          </Button>
        </div>
      </div>

      <Field label="Título">
        <Input value={draft.title} onChange={(e) => update("title", e.target.value)} placeholder="ej: Uso de propuestas comparables para relaves" />
      </Field>

      <div className="flex-row" style={{ gap: 12 }}>
        <Field label="Categoría">
          <Input value={draft.category} onChange={(e) => update("category", e.target.value)} placeholder="lecciones_aprendidas" />
        </Field>
        <label className="flex-row" style={{ alignItems: "center", gap: 6, marginTop: 22 }}>
          <input type="checkbox" checked={!!draft.pinned} onChange={(e) => update("pinned", e.target.checked)} />
          <small>Pinear</small>
        </label>
      </div>

      <Field label="Tags">
        <div className="flex-row" style={{ flexWrap: "wrap", gap: 6 }}>
          {(draft.tags || []).map((t, idx) => (
            <Chip key={`${t}-${idx}`} onRemove={() => update("tags", draft.tags.filter((_, i) => i !== idx))}>
              {t}
            </Chip>
          ))}
          <Input
            placeholder="añadir tag…"
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addTag())}
            style={{ width: 160 }}
          />
          <button type="button" className="btn-icon" onClick={addTag} title="Añadir tag"><Plus size={14} /></button>
        </div>
      </Field>

      <Field label="Propuestas referenciadas (códigos master)">
        <div className="flex-row" style={{ flexWrap: "wrap", gap: 6 }}>
          {(draft.propuestas_referenciadas || []).map((c, idx) => (
            <Chip
              key={`${c}-${idx}`}
              variant="accent"
              onRemove={() => update("propuestas_referenciadas", draft.propuestas_referenciadas.filter((_, i) => i !== idx))}
            >
              {c}
            </Chip>
          ))}
          <Input
            placeholder="O-1376"
            value={codeInput}
            onChange={(e) => setCodeInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addCode())}
            style={{ width: 110 }}
          />
          <button type="button" className="btn-icon" onClick={addCode} title="Añadir código"><Plus size={14} /></button>
        </div>
      </Field>

      <Field label="Contenido (markdown)">
        <Textarea
          rows={14}
          value={draft.content}
          onChange={(e) => update("content", e.target.value)}
          placeholder="Resumen, criterios, gaps a validar, etc."
        />
      </Field>
    </div>
  );
}
