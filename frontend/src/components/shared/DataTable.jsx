import { useMemo, useState } from "react";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";

export function DataTable({ columns, rows, emptyMessage = "Sin datos.", defaultSort = null }) {
  const [sortKey, setSortKey] = useState(defaultSort?.key || null);
  const [sortDir, setSortDir] = useState(defaultSort?.dir || "desc");

  const sortedRows = useMemo(() => {
    if (!rows || rows.length === 0) return [];
    if (!sortKey) return rows;
    const col = columns.find((c) => c.key === sortKey);
    const numeric = col?.numeric;
    const dateCol = col?.date;
    return [...rows].sort((a, b) => {
      const va = a[sortKey];
      const vb = b[sortKey];
      // Empty values al final
      const ea = va === null || va === undefined || va === "" || va === "No data";
      const eb = vb === null || vb === undefined || vb === "" || vb === "No data";
      if (ea && !eb) return 1;
      if (!ea && eb) return -1;
      if (ea && eb) return 0;
      let cmp;
      if (numeric) {
        cmp = parseFloat(va) - parseFloat(vb);
      } else if (dateCol) {
        cmp = new Date(va).getTime() - new Date(vb).getTime();
      } else {
        cmp = String(va).localeCompare(String(vb), "es", { numeric: true });
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [rows, sortKey, sortDir, columns]);

  const handleSort = (col) => {
    if (col.sortable === false) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(col.key);
      setSortDir(col.numeric || col.date ? "desc" : "asc");
    }
  };

  if (!rows || rows.length === 0) {
    return <div className="empty-state"><h3>{emptyMessage}</h3></div>;
  }

  return (
    <div style={{ overflow: "auto" }}>
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((col) => {
              const sortable = col.sortable !== false;
              const isActive = sortKey === col.key;
              return (
                <th
                  key={col.key}
                  style={col.width ? { width: col.width, cursor: sortable ? "pointer" : "default" } : { cursor: sortable ? "pointer" : "default" }}
                  onClick={sortable ? () => handleSort(col) : undefined}
                >
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                    {col.label}
                    {sortable && (
                      isActive ? (
                        sortDir === "asc" ? <ChevronUp size={11} /> : <ChevronDown size={11} />
                      ) : (
                        <ChevronsUpDown size={10} style={{ opacity: 0.4 }} />
                      )
                    )}
                  </span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row, idx) => (
            <tr key={row.id ?? row.codigo ?? idx}>
              {columns.map((col) => (
                <td key={col.key}>{col.render ? col.render(row) : row[col.key] ?? "—"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
