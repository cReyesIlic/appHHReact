export function SourcesView({ sources, onOpenWiki }) {
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
            {items.map((s, i) => {
              const key = `${s.codigo || s.entry_id || s.title}-${i}`;
              const body = <>
                <span className="source-item-title">{s.title || s.codigo}</span>
                <span className="source-item-meta">
                  {s.codigo && <span>{s.codigo}</span>}
                  {s.score != null && <span>score {Number(s.score).toFixed(2)}</span>}
                  {s.entry_id && <span>Abrir Wiki</span>}
                  {s.url && <span>Abrir SharePoint ↗</span>}
                </span>
              </>;
              if (s.entry_id && onOpenWiki) {
                return <button type="button" key={key} className="source-item source-item-button" onClick={() => onOpenWiki(s)}>{body}</button>;
              }
              if (s.url) {
                return <a key={key} className="source-item" href={s.url} target="_blank" rel="noreferrer">{body}</a>;
              }
              return <div key={key} className="source-item">{body}</div>;
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
