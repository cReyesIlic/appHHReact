---
name: estadisticas_propuestas
description: Úsala para preguntas estadísticas, conteos, distribuciones o tendencias sobre propuestas. Triggers típicos: "cuántas", "cuántos", "porcentaje", "por estado", "por cliente", "por año", "distribución", "ratio ganadas/perdidas", "tendencia", "evolución".
allowed-tools: compute_master_stats, search_master, search_wiki_entries
---

# Estadísticas de propuestas

Tu objetivo es entregar **números concretos** con contexto y al menos una tabla o desglose.

## Flujo

1. **`compute_master_stats(query=<filtro opcional>)`** — primera llamada. Devuelve summary + tablas (por estado, cliente, año, tipo de servicio) + charts.
2. Si el usuario pide un corte específico no cubierto, complementa con **`search_master(filters={...}, limit=200)`** y resume tú.
3. Si hay un patrón histórico relevante, **`search_wiki_entries(category='analisis_comercial')`** puede tener contexto curado.

## Estructura de la respuesta

### Resumen ejecutivo (1-2 líneas)
Número clave + comparación o tendencia. Ej: *"VALE tiene 47 propuestas, 28% ganadas, monto promedio ganadas $187."*

### Tabla principal
Una tabla compacta con la dimensión preguntada (estado / cliente / año / tipo). Máx 12 filas.

### Notas
- Si los datos están sesgados (montos en "No data"), avísalo.
- Si la pregunta requiere período específico, filtra por `fecha_desde`/`fecha_hasta`.

## Reglas

- **Siempre la totalidad y el subset**: si dices "47 propuestas ganadas de VALE", también di "(de 89 propuestas totales con VALE)".
- **Ratios sobre nombres**: ratios ganadas/total son más útiles que conteos absolutos.
- **No fabriques agregados**: si master_stats no trae la dimensión, dilo y propone cómo obtenerla.
