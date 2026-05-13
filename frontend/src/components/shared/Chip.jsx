import { X } from "lucide-react";

export function Chip({ children, variant = "default", onRemove }) {
  const cls =
    variant === "accent"
      ? "chip chip-accent"
      : variant === "active"
      ? "chip chip-active"
      : "chip";
  return (
    <span className={cls}>
      {children}
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label="quitar">
          <X size={11} />
        </button>
      )}
    </span>
  );
}

export function StatusPill({ category }) {
  const map = {
    ganada: { cls: "status-ganada", label: "Ganada" },
    perdida: { cls: "status-perdida", label: "Perdida" },
    en_preparacion: { cls: "status-proceso", label: "En preparación" },
    pendiente: { cls: "status-proceso", label: "Pendiente" },
    no_licitada: { cls: "status-otro", label: "No licitada" },
    desierta: { cls: "status-otro", label: "Desierta" },
    indefinida: { cls: "status-otro", label: "Indefinida" },
  };
  const entry = map[category] || { cls: "status-otro", label: category || "—" };
  return <span className={`status-pill ${entry.cls}`}>{entry.label}</span>;
}

export function EstadoPill({ estado }) {
  const cat = mapEstadoCategoria(estado);
  return <StatusPill category={cat} />;
}

export function mapEstadoCategoria(estado) {
  const upper = String(estado || "").toUpperCase();
  switch (upper) {
    case "PG":
      return "ganada";
    case "PP":
      return "perdida";
    case "EP":
      return "en_preparacion";
    case "DP":
      return "pendiente";
    case "NL":
      return "no_licitada";
    case "PD":
      return "desierta";
    case "PDS":
      return "indefinida";
    default:
      return "indefinida";
  }
}
