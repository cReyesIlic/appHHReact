/* Filtros estructurados — schema espejo de backend/app/services/search_filters.py */

export const EMPTY_FILTERS = {
  codigos: [],
  estados: [],
  estado_categoria: [],
  clientes: [],
  tipos_servicio: [],
  disciplinas: [],
  componentes: [],
  instalaciones: [],
  procesos_sistemas: [],
  fecha_desde: null,
  fecha_hasta: null,
  monto_min: null,
  monto_max: null,
};

export const ESTADO_CATEGORIA_OPTIONS = [
  { value: "ganada", label: "Ganadas" },
  { value: "perdida", label: "Perdidas" },
  { value: "en_preparacion", label: "En preparación" },
  { value: "pendiente", label: "Pendientes" },
  { value: "no_licitada", label: "No licitadas" },
  { value: "desierta", label: "Desiertas" },
];

export const TIPO_SERVICIO_OPTIONS = [
  { value: "IP", label: "IP — Ingeniería de Perfil" },
  { value: "IC", label: "IC — Ingeniería Conceptual" },
  { value: "IB", label: "IB — Ingeniería Básica" },
  { value: "ID", label: "ID — Ingeniería de Detalle" },
  { value: "CO", label: "CO — Contraparte" },
  { value: "EP", label: "EP — EPC/EPCM" },
  { value: "CC", label: "CC — Comisión / Estudio" },
  { value: "AO", label: "AO — Apoyo Operaciones" },
];

export const DISCIPLINA_OPTIONS = [
  "civil",
  "hidraulica",
  "mecanica",
  "piping",
  "electrica",
  "instrumentacion",
  "control",
  "geotecnia",
  "procesos",
  "estructural",
];

export function isFiltersEmpty(f) {
  if (!f) return true;
  return Object.entries(f).every(([k, v]) => {
    if (v === null || v === undefined || v === "") return true;
    if (Array.isArray(v)) return v.length === 0;
    return false;
  });
}

export function compactFilters(f) {
  if (!f) return null;
  const out = {};
  for (const [k, v] of Object.entries(f)) {
    if (v === null || v === undefined || v === "") continue;
    if (Array.isArray(v) && v.length === 0) continue;
    out[k] = v;
  }
  return Object.keys(out).length ? out : null;
}

export function toggleArrayValue(arr, value) {
  if (!arr) return [value];
  return arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value];
}

/** Detecta filtros en lenguaje natural y los pre-rellena. */
export function parseFiltersFromText(text) {
  const lower = (text || "").toLowerCase();
  const filters = { ...EMPTY_FILTERS };
  if (/\b(ganada|ganadas|adjudicada|adjudicadas)\b/.test(lower)) filters.estado_categoria.push("ganada");
  if (/\b(perdida|perdidas)\b/.test(lower)) filters.estado_categoria.push("perdida");
  if (/\b(en preparacion|en preparación|preparando)\b/.test(lower)) filters.estado_categoria.push("en_preparacion");
  for (const opt of TIPO_SERVICIO_OPTIONS) {
    const re = new RegExp(`\\btipo (de )?(servicio )?${opt.value.toLowerCase()}\\b`);
    if (re.test(lower)) filters.tipos_servicio.push(opt.value);
  }
  for (const d of DISCIPLINA_OPTIONS) {
    if (new RegExp(`\\b${d}\\b`).test(lower)) filters.disciplinas.push(d);
  }
  return compactFilters(filters);
}
