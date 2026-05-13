export function Button({ variant = "default", icon: Icon, children, ...rest }) {
  const cls =
    variant === "primary"
      ? "btn btn-primary"
      : variant === "accent"
      ? "btn btn-accent"
      : variant === "ghost"
      ? "btn btn-ghost"
      : "btn";
  return (
    <button type="button" className={cls} {...rest}>
      {Icon && <Icon size={14} />}
      {children}
    </button>
  );
}

export function IconButton({ icon: Icon, title, ...rest }) {
  return (
    <button type="button" className="btn-icon" title={title} aria-label={title} {...rest}>
      <Icon size={16} />
    </button>
  );
}
