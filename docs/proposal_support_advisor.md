# Proposal Support Advisor

Herramienta backend para ayudar a equipos que estan armando propuestas.

Endpoint:

```http
POST /api/proposal-support/advice
```

Request:

```json
{
  "query": "Estoy armando una propuesta de factibilidad para disposicion alternativa de relaves",
  "selected_codes": ["O-2370", "O-2609"],
  "limit": 16
}
```

Respuesta principal:

```json
{
  "referencias_directas": [],
  "referencias_comparables": [],
  "referencias_metodologicas": [],
  "referencias_entregables_hh": [],
  "no_recomendadas": [],
  "texto_sugerido_pdf": [],
  "gaps_a_validar": [],
  "deepening_plan": [],
  "tables": []
}
```

## Uso esperado en frontend

La vista deberia mostrar:

- Candidatos directos: experiencia que se puede mencionar como antecedente principal.
- Comparables: propuestas no identicas, pero utiles por sistema, disciplina, instalacion o cliente.
- Metodologicas: propuestas que demuestran forma de estudiar alternativas, factibilidad, trade-off, diagnostico o benchmark.
- Entregables/HH: propuestas utiles para estructura de alcance, actividades, roles, HH y tarifas.
- Gaps: documentos o Excel faltantes antes de citar.
- Plan de profundizacion: que debe leer el agente antes de redactar o recomendar.

## Regla de uso

Una propuesta directa sin RAG/PDF debe mostrarse como oportunidad o antecedente Master, no como evidencia documental.

Una propuesta comparable debe explicar exactamente que componente sirve:

- sistema de bombeo;
- transporte de relaves;
- recuperacion de aguas;
- etapa de factibilidad;
- evaluacion de alternativas;
- multidisciplinariedad;
- entregables/HH.

Una propuesta metodologica puede servir aunque no sea del mismo tema, pero se debe mencionar como respaldo de metodo, no como experiencia directa.
