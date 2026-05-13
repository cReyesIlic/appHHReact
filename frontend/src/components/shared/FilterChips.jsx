import { useState } from "react";
import { Filter, X, Plus } from "lucide-react";
import { ESTADO_CATEGORIA_OPTIONS, TIPO_SERVICIO_OPTIONS, DISCIPLINA_OPTIONS, toggleArrayValue } from "../../lib/filters.js";
import { Chip } from "./Chip.jsx";
import { Input } from "./Field.jsx";

function Dropdown({ label, count, items, selected, onToggle }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="filter-dropdown">
      <button
        type="button"
        className={`chip${selected.length ? " chip-active" : ""}`}
        onClick={() => setOpen((v) => !v)}
      >
        <Filter size={11} />
        {label}{count ? ` · ${count}` : ""}
      </button>
      {open && (
        <div className="filter-dropdown-menu" onMouseLeave={() => setOpen(false)}>
          {items.map((it) => {
            const val = it.value ?? it;
            const text = it.label ?? it;
            const checked = selected.includes(val);
            return (
              <label key={val} className="filter-option">
                <input type="checkbox" checked={checked} onChange={() => onToggle(val)} />
                {text}
              </label>
            );
          })}
        </div>
      )}
    </span>
  );
}

export function FilterChips({ filters, onChange }) {
  const set = (key, value) => onChange({ ...filters, [key]: value });
  const toggle = (key, value) => set(key, toggleArrayValue(filters[key] || [], value));
  const removeFromArray = (key, value) =>
    set(key, (filters[key] || []).filter((v) => v !== value));
  const [clienteInput, setClienteInput] = useState("");
  const addCliente = () => {
    const v = clienteInput.trim();
    if (!v) return;
    set("clientes", [...(filters.clientes || []), v]);
    setClienteInput("");
  };

  return (
    <div className="filter-bar">
      <span className="filter-bar-label">Filtros:</span>
      <Dropdown
        label="Estado"
        count={(filters.estado_categoria || []).length}
        items={ESTADO_CATEGORIA_OPTIONS}
        selected={filters.estado_categoria || []}
        onToggle={(v) => toggle("estado_categoria", v)}
      />
      <Dropdown
        label="Tipo de servicio"
        count={(filters.tipos_servicio || []).length}
        items={TIPO_SERVICIO_OPTIONS}
        selected={filters.tipos_servicio || []}
        onToggle={(v) => toggle("tipos_servicio", v)}
      />
      <Dropdown
        label="Disciplina"
        count={(filters.disciplinas || []).length}
        items={DISCIPLINA_OPTIONS}
        selected={filters.disciplinas || []}
        onToggle={(v) => toggle("disciplinas", v)}
      />
      <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
        <Input
          placeholder="cliente…"
          value={clienteInput}
          onChange={(e) => setClienteInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addCliente()}
          style={{ width: 140 }}
        />
        <button type="button" className="btn-icon" title="Añadir cliente" onClick={addCliente}>
          <Plus size={14} />
        </button>
      </span>
      {(filters.clientes || []).map((c) => (
        <Chip key={c} variant="accent" onRemove={() => removeFromArray("clientes", c)}>
          {c}
        </Chip>
      ))}
      {(filters.codigos || []).map((c) => (
        <Chip key={c} onRemove={() => removeFromArray("codigos", c)}>
          {c}
        </Chip>
      ))}
    </div>
  );
}

export function FilterSummary({ filters }) {
  const chips = [];
  for (const c of filters?.estado_categoria || []) chips.push({ key: `est-${c}`, label: c });
  for (const t of filters?.tipos_servicio || []) chips.push({ key: `tipo-${t}`, label: `Tipo ${t}` });
  for (const c of filters?.clientes || []) chips.push({ key: `cli-${c}`, label: c });
  for (const d of filters?.disciplinas || []) chips.push({ key: `disc-${d}`, label: d });
  if (!chips.length) return null;
  return (
    <div className="chip-row">
      {chips.map((c) => (
        <Chip key={c.key} variant="accent">
          {c.label}
        </Chip>
      ))}
    </div>
  );
}
