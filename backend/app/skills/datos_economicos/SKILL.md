---
name: datos_economicos
description: Úsala cuando la pregunta es sobre monto, HH (horas hombre), tarifa, costo, presupuesto, valor, o cualquier indicador económico de una propuesta o conjunto. Triggers típicos: "cuánto cuesta", "monto", "valor", "horas", "tarifa", "presupuesto", "HH", "kUF", "costo".
allowed-tools: compute_economics, search_master, compute_master_stats, get_proposal_detail, search_entregables_hh, get_horas_detalle, get_proyecto_staffing
---

# Datos económicos

Tu objetivo es entregar **cifras claras con su contexto temporal** (UF histórica vs actual, conversiones).

## Dos tipos de "HH" — DISTÍNGUELOS

- **HH licitadas / cotizadas** (Master Excel): lo que SHIMIN ofertó. Lado comercial. Usa `compute_economics`.
- **HH reales cargadas** (Staffing system): lo que efectivamente consumió el equipo en `hh_control`. Lado ejecución. Usa `search_entregables_hh` o `get_proyecto_staffing`.

Si la pregunta no es clara, **muestra ambas en paralelo** y dile al usuario qué significa cada una. Si hay gap relevante (>20%), señálalo.

## Flujo

1. **Si menciona códigos O-XXXX** (oferta/propuesta): `compute_economics(codigos=[...])` para HH licitadas + monto + tarifa.
2. **Si menciona códigos SH-XXXX** (proyecto adjudicado): `get_proyecto_staffing(codigo=SH-XXXX)` para HH reales + personas asignadas.
3. **Si pregunta por HH típicas de un tipo de entregable** ("¿cuántas HH una memoria de cálculo en hidráulica?"): `search_entregables_hh(q=..., disciplina=..., contexto=..., incluir_personas=true)` — devuelve HH reales históricas.
4. **Para agregados** (promedio, mediana, ranking por monto): `compute_master_stats` o `search_master(filters={...}, limit=N)` ordenado por monto.
5. **Para detalles de alcance**: `get_proposal_detail(codigo)`.
6. **Para auditoría persona/semana**: `get_horas_detalle(...)`.

## Estructura

### Tabla económica
| Código | Monto histórico | Monto en UF actual | HH | Tarifa | Estado |
|---|---|---|---|---|---|
| O-1376 | 291 kUF (2021) | ~310 kUF (hoy) | 11.329 | 26 UF/HH | PP |

### Notas
- **Distingue** monto histórico (en `master.monto`) de monto convertido (en UF actual, factor `current_uf/historical_uf`).
- Si `compute_economics` devuelve `tarifa_calc` (monto/HH), úsalo como sanity check de la tarifa registrada.
- Si hay HH del Excel de HH (no del master), preferir el Excel — es más granular.

## Reglas

- **UF siempre como referencia temporal**: monto absoluto sin fecha es ambiguo.
- **No promedies "No data"**: filtra explícitamente filas con monto válido.
- **Avisa si los rangos parecen anómalos**: tarifas de 100 UF/HH son raras; saltar alerta.
