---
name: datos_economicos
description: Úsala cuando la pregunta es sobre monto, HH (horas hombre), tarifa, costo, presupuesto, valor, o cualquier indicador económico de una propuesta o conjunto. Triggers típicos: "cuánto cuesta", "monto", "valor", "horas", "tarifa", "presupuesto", "HH", "kUF", "costo".
allowed-tools: compute_economics, search_master, compute_master_stats, get_proposal_detail
---

# Datos económicos

Tu objetivo es entregar **cifras claras con su contexto temporal** (UF histórica vs actual, conversiones).

## Flujo

1. Si el usuario menciona códigos específicos: **`compute_economics(codigos=[...])`** directamente. Devuelve monto histórico, monto convertido a UF actual, HH, tarifa, entregables.
2. Si el usuario pide un agregado (promedio, mediana, ranking por monto): **`compute_master_stats`** o **`search_master(filters={...}, limit=N)`** ordenado por monto.
3. Si necesitas confirmar entregables o alcance asociado al monto: **`get_proposal_detail(codigo)`** para una propuesta clave.

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
