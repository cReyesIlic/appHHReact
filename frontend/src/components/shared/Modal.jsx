import { X } from "lucide-react";
import { IconButton } from "./Button.jsx";

export function Modal({ open, title, onClose, children, footer }) {
  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header className="modal-header">
          <h2>{title}</h2>
          <IconButton icon={X} title="Cerrar" onClick={onClose} />
        </header>
        <div>{children}</div>
        {footer && <footer className="flex-row" style={{ justifyContent: "flex-end" }}>{footer}</footer>}
      </div>
    </div>
  );
}
