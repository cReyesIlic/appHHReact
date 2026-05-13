import { SideNav } from "./SideNav.jsx";

export function Shell({ active, onChange, onOpenSettings, children }) {
  return (
    <div className="app-shell">
      <SideNav active={active} onChange={onChange} onOpenSettings={onOpenSettings} />
      <div className="workspace">{children}</div>
    </div>
  );
}
