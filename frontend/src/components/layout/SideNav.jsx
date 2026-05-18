import { MessageSquare, Table, BookOpen, FilePlus, Clock, Settings as Cog } from "lucide-react";
import { Brand } from "./Brand.jsx";

const ITEMS = [
  { key: "chat", label: "Chat", icon: MessageSquare },
  { key: "master", label: "Master", icon: Table },
  { key: "entregables", label: "Entregables / HH", icon: Clock },
  { key: "library", label: "Wiki / Librería", icon: BookOpen },
  { key: "drafts", label: "Propuestas en armado", icon: FilePlus },
];

export function SideNav({ active, onChange, onOpenSettings }) {
  return (
    <aside className="side-nav">
      <Brand />
      <div className="nav-section-title">Vistas</div>
      <nav className="nav-list">
        {ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.key}
              type="button"
              className={`nav-item${active === item.key ? " active" : ""}`}
              onClick={() => onChange(item.key)}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="nav-footer">
        <button
          type="button"
          className={`nav-item${active === "ops" ? " active" : ""}`}
          onClick={onOpenSettings}
        >
          <Cog size={18} />
          <span>Ajustes</span>
        </button>
      </div>
    </aside>
  );
}
