---
name: comparar_propuestas
description: Úsala para comparar dos o más propuestas entre sí (alcances, montos, estados, clientes, entregables, criterios técnicos). Triggers típicos: "compara", "diferencia entre", "qué propuesta es más parecida a", "ventajas y desventajas", "vs", "evolución entre".
allowed-tools: get_proposal_detail, search_master, search_rag, search_wiki_entries, compute_economics
---

# Comparar propuestas

Tu objetivo es **una tabla comparativa concreta** + un párrafo de interpretación.

## Flujo

1. **`get_proposal_detail(codigo)`** para cada propuesta mencionada. Devuelve master + chunks RAG top + wiki entries que la referencian.
2. Si el usuario pidió un eje específico (HH, monto, alcance, metodología): pivota por ese eje.
3. Si una propuesta tiene wiki page, **léela primero** — ya tiene el resumen sintético que necesitas.
4. Para diferencias económicas: `compute_economics(codigos=[a, b, c])`.

## Estructura

### Tabla comparativa
Filas = propuestas, columnas = atributos. Atributos típicos:
- Código + Título corto
- Cliente / Cliente final
- Estado
- Tipo de servicio
- Monto (en kUF o miles)
- HH estimadas
- Fecha
- Sección clave de alcance (1-2 líneas, de RAG o wiki)
- Disciplinas involucradas

### Interpretación
2-4 frases que respondan **explícitamente la pregunta del usuario**:
- *"O-1376 es más completa porque incluye X, pero O-1377 es más barata."*
- *"Las dos son del mismo cliente VALE, pero O-1377 es de detalle (ID) mientras O-1376 es básica (EB)."*

## Reglas

- **Cita siempre el origen** del dato comparado (master / rag / wiki).
- **Si falta un dato** ("No data" en master), márcalo: `—` o `N/D`.
- **No infieras sin decirlo**: si comparas alcances sin tener evidencia textual de ambos, dilo.
