# LLM Wiki como context builder SHIMIN

## Principio

El LLM Wiki no reemplaza el RAG. Cumple otra funcion:

- RAG parent-child: recupera evidencia granular desde PDFs completos, con pagina, seccion, chunk y metadata.
- LLM Wiki: compila conocimiento durable en Markdown estructurado, con resumen, entidades, relaciones, contradicciones y gaps.
- Master: entrega datos comerciales estructurados y confiables.
- Excel HH: entrega estimaciones, entregables, horas y tarifas.

La respuesta final debe mezclar esas capas, indicando cuando algo viene de evidencia directa y cuando es inferencia.

## Patron usado

El patron LLM Wiki se atribuye a Andrej Karpathy. La forma practica es:

1. Mantener fuentes crudas intactas.
2. Compilar paginas Markdown estructuradas.
3. Usar links y metadata para que el agente navegue el conocimiento.
4. Ejecutar lint/health checks para detectar gaps, contradicciones y paginas pobres.
5. Al responder, partir desde la wiki y profundizar con RAG o lectura directa cuando haga falta evidencia.

## Estructura propuesta

```text
storage/llm_wiki/
  index.md
  proposals/
    O-1509.md
    O-1548.md
  concepts/
    dewatering.md
    relaves.md
    bombeo.md
    factibilidad.md
  clients/
    caserones.md
    codelco-dand.md
  capabilities/
    hidraulica-minera.md
    relaves-y-aguas.md
    estimacion-hh.md
  gaps/
    cobertura-rag-baja.md
    propuestas-sin-pdf-emitido.md
```

## Pagina por propuesta

Cada `proposals/O-XXXX.md` debe tener:

- YAML frontmatter con `codigo`, `estado_categoria`, `tipo_servicio`, `cliente`, `fuente`, `metadata_version`.
- Resumen ejecutivo.
- Objetivo.
- Alcance.
- Entregables.
- Disciplinas.
- Equipos/sistemas.
- Criterios de busqueda.
- Util para.
- Limitaciones.
- Links a conceptos: `[[dewatering]]`, `[[relaves]]`, `[[bombeo]]`.
- Referencias RAG disponibles: codigos de parent/child relevantes.

## Pagina por concepto

Cada `concepts/*.md` debe actuar como memoria compilada:

- Definicion operacional para SHIMIN.
- Sinonimos y terminos relacionados.
- Propuestas ganadas asociadas.
- Propuestas perdidas/presentadas asociadas.
- Casos no iguales pero utiles, explicando por que sirven.
- Entregables tipicos.
- Disciplinas tipicas.
- Riesgos/gaps de cobertura.

Ejemplo: una pagina `relaves.md` no debe listar solo propuestas que dicen "relaves"; tambien debe separar:

- experiencia directa en relaves;
- experiencia cercana en tranques/aguas/drenaje;
- experiencia metodologica comparable en evaluacion de alternativas hidraulicas;
- gaps cuando falta evidencia directa.

## Context builder para respuesta

Para una pregunta del usuario:

1. Planificador extrae conceptos, sinonimos, etapa, activo minero, cliente, estado deseado y tipo de evidencia.
2. Busca en Master para candidatos rapidos.
3. Busca en Wiki por conceptos y paginas canonicas.
4. Busca en RAG parent-child solo si la cobertura es suficiente o si hay candidatos concretos.
5. Lee PDF directo si necesita justificar por que una propuesta sirve.
6. Integra Excel HH si la pregunta toca entregables, horas, tarifas o dimensionamiento.
7. Responde con:
   - evidencia directa;
   - alternativas comparables;
   - propuestas ganadas/perdidas;
   - razon de similitud;
   - gaps y nivel de confianza.

## Regla de calidad

Si el RAG o Wiki cubren menos de 10% de la master, el agente debe levantar alarma y tratar esas herramientas como complementarias, no como fuente exhaustiva.

Si una propuesta aparece en Master pero no tiene PDF/Excel emitido, debe quedar como candidato estructurado, no como evidencia documental.
