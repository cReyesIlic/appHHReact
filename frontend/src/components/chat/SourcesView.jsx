export function SourcesView({ sources }) {
  if (!sources || sources.length === 0) return null;
  const grouped = sources.reduce((acc, s) => {
    const key = s.kind || "otro";
    (acc[key] = acc[key] || []).push(s);
    return acc;
  }, {});
  return (
    <div className="flex-col">
      {Object.entries(grouped).map(([kind, items]) => (
        <div key={kind} className="flex-col">
          <small className="dim" style={{ textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 }}>
            {kind} · {items.length}
          </small>
          <div className="source-list">
            {items.map((s, i) => (
              <a
                key={`${s.codigo || s.title}-${i}`}
                className="source-item"
                href={s.url || "#"}
                target={s.url ? "_blank" : undefined}
                rel="noreferrer"
              >
                <span className="source-item-title">{s.title || s.codigo}</span>
                <span className="source-item-meta">
                  {s.codigo && <span>{s.codigo}</span>}
                  {s.score != null && <span>score {Number(s.score).toFixed(2)}</span>}
                </span>
              </a>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
