import { useState } from "react";
import { Search, X } from "lucide-react";
import { searchMaster } from "../../lib/api.js";
import { EMPTY_FILTERS, compactFilters } from "../../lib/filters.js";
import { Button } from "../shared/Button.jsx";
import { Card } from "../shared/Card.jsx";
import { DataTable } from "../shared/DataTable.jsx";
import { Input } from "../shared/Field.jsx";
import { FilterChips } from "../shared/FilterChips.jsx";
import { EstadoPill } from "../shared/Chip.jsx";

const COLUMNS = [
  { key: "codigo", label: "Código", width: 92 },
  {
    key: "estado",
    label: "Estado",
    render: (row) => <EstadoPill estado={row.estado} />,
    width: 110,
  },
  { key: "cliente_directo", label: "Cliente directo", width: 140 },
  { key: "cliente_final", label: "Cliente final", width: 140 },
  { key: "titulo", label: "Título" },
  { key: "tipo_servicio", label: "Servicio", width: 80 },
  { key: "fecha_recep", label: "Fecha", width: 110, date: true },
  { key: "monto", label: "Monto", width: 90, numeric: true },
  { key: "cod_proy", label: "Cod proy", width: 90 },
];

export function MasterView() {
  const [query, setQuery] = useState("");
  const [cliente, setCliente] = useState("");
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [count, setCount] = useState(null);

  const run = async () => {
    setLoading(true);
    try {
      const result = await searchMaster({
        query: query || null,
        cliente: cliente || null,
        limit: 200,
        filters: compactFilters(filters),
      });
      setRows(result.rows || []);
      setCount(result.count ?? result.rows?.length ?? 0);
    } catch (exc) {
      console.error(exc);
      setRows([]);
      setCount(0);
    } finally {
      setLoading(false);
    }
  };

  const clearAll = () => {
    setQuery("");
    setCliente("");
    setFilters(EMPTY_FILTERS);
    setRows([]);
    setCount(null);
  };

  return (
    <div className="view-body">
      <Card
        title="Búsqueda de propuestas"
        subtitle="Texto libre + cliente + filtros estructurados. Click en columnas para ordenar."
      >
        <div className="master-toolbar">
          <div className="flex-col" style={{ minWidth: 240, flex: 1 }}>
            <label className="label">Texto / código</label>
            <Input
              placeholder="dewatering, relaves, O-2200, SH-0428, 428…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && run()}
            />
          </div>
          <div className="flex-col" style={{ minWidth: 200, flex: 1 }}>
            <label className="label">Cliente (directo o final)</label>
            <Input
              placeholder="VALE, Codelco, CMP, Anglo…"
              value={cliente}
              onChange={(e) => setCliente(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && run()}
            />
          </div>
          <div className="flex-row" style={{ alignItems: "flex-end", gap: 8 }}>
            <Button variant="primary" icon={Search} onClick={run} disabled={loading}>
              {loading ? "Buscando…" : "Buscar"}
            </Button>
            <Button variant="ghost" icon={X} onClick={clearAll}>
              Limpiar
            </Button>
          </div>
        </div>
        <div style={{ marginTop: 12 }}>
          <FilterChips filters={filters} onChange={setFilters} />
        </div>
      </Card>
      <Card
        title={count != null ? `Resultados (${count})` : "Resultados"}
        subtitle={loading ? "Cargando…" : "Click en cabeceras para ordenar"}
      >
        <DataTable
          columns={COLUMNS}
          rows={rows}
          emptyMessage="Sin coincidencias. Prueba aflojar filtros o cambiar el texto."
          defaultSort={{ key: "fecha_recep", dir: "desc" }}
        />
      </Card>
    </div>
  );
}
