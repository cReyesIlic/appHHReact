import { CheckCircle2, AlertTriangle, XCircle, HelpCircle } from "lucide-react";

export function ValidationBadge({ status }) {
  const map = {
    ok: { cls: "validation-ok", label: "Validada", icon: CheckCircle2 },
    partial: { cls: "validation-partial", label: "Parcial", icon: AlertTriangle },
    broken: { cls: "validation-broken", label: "Rotas", icon: XCircle },
    unchecked: { cls: "validation-unchecked", label: "Sin validar", icon: HelpCircle },
  };
  const entry = map[status] || map.unchecked;
  const Icon = entry.icon;
  return (
    <span className={`validation-badge ${entry.cls}`}>
      <Icon size={11} /> {entry.label}
    </span>
  );
}
