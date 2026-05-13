export function TraceView({ trace }) {
  if (!trace || trace.length === 0) return null;
  return (
    <div className="trace-list">
      {trace.map((t, idx) => (
        <div key={idx} className="trace-item">
          <span className={`trace-status-${t.status}`}>●</span>
          <span className="trace-tool">{t.tool}</span>
          <span className="trace-detail">{t.detail}</span>
        </div>
      ))}
    </div>
  );
}
