export function Field({ label, hint, children }) {
  return (
    <label className="flex-col" style={{ gap: 4 }}>
      {label && <span className="label">{label}</span>}
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function Input(props) {
  return <input className="input" {...props} />;
}

export function Textarea(props) {
  return <textarea className="textarea" {...props} />;
}

export function Select({ options = [], children, ...rest }) {
  return (
    <select className="select" {...rest}>
      {children
        ? children
        : options.map((opt) => (
            <option key={opt.value ?? opt} value={opt.value ?? opt}>
              {opt.label ?? opt}
            </option>
          ))}
    </select>
  );
}
