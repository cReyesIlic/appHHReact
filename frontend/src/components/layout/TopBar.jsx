export function TopBar({ title, subtitle, children }) {
  return (
    <header className="top-bar">
      <div className="top-bar-title">
        {title}
        {subtitle && <small>{subtitle}</small>}
      </div>
      <div className="top-bar-actions">{children}</div>
    </header>
  );
}
