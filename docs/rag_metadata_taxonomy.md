# Taxonomia de metadata para RAG de propuestas

Esta taxonomia se usa para enriquecer cada propuesta, seccion parent y chunk child del RAG.

## Codigos estructurados

### Tipo de negociacion

| Codigo | Etiqueta |
|---|---|
| ND | Negociacion Directa |
| LM | Licitacion Multiple |
| AC | Apoyo Contratos |
| LC | Licitacion Contrato Abierto |
| N/A | No Aplica |

### Tipo de servicio

| Codigo | Etiqueta | Categoria |
|---|---|---|
| IP | Ingenieria de Perfil | Proyecto T: Perfil / Conceptual / Prefactibilidad |
| IC | Ingenieria Conceptual | Proyecto T: Perfil / Conceptual / Prefactibilidad |
| IB | Ingenieria Basica | Proyecto P: Basica / Detalle / Contraparte |
| ID | Ingenieria de Detalle | Proyecto P: Basica / Detalle / Contraparte |
| CO | Ingenieria de Contraparte | Proyecto P: Basica / Detalle / Contraparte |
| CC | Comision de Confianza / Auditoria / Estudio / Diagnostico / Benchmarking / Bases | Proyecto D |
| EP | Ingenieria, Adquisicion y Construccion | Proyecto P: EPC/EPCM |
| CM | Administracion de Construccion | Proyecto P: EPC/EPCM |
| C | Construccion | Proyecto P: EPC/EPCM |
| AD | Adquisiciones | Proyecto P |
| CA | Contratos Abiertos / Contrato Marco / Asesoria | Proyecto F |
| IT | Ingenieria de Terreno | Proyecto S |
| AO | Apoyo a Operaciones / Manuales / PEM | Proyecto S |
| AC | Administracion de Construccion | Proyecto S |
| TP | Transferencia de Profesionales | Proyecto G |
| CT | Capacitacion a Terceros | Proyecto C |
| VD | Venta de Dragas y Elementos Relacionados | Proyecto Q |
| PR | Precalificacion / Inscripcion / Registro |  |
| OS | Otros Servicios |  |
| N/A | No Aplica |  |

### Ambito

| Codigo | Etiqueta |
|---|---|
| NAC | Nacional |
| INT | Internacional |

### Estado

| Codigo | Etiqueta | Categoria RAG |
|---|---|---|
| PDS | Por Definir Situacion | indefinida |
| EP | En Preparacion | en_preparacion |
| NL | Propuesta No Licitada | no_licitada |
| DP | Decision del Cliente Pendiente | pendiente |
| PG | Propuesta Ganada | ganada |
| PP | Propuesta Perdida | perdida |
| PD | Propuesta Declarada Desierta | desierta |

## Entidades utiles

Estas entidades se guardan en `entidades_taxonomia` a nivel propuesta y en `section_entities` a nivel seccion.

| Grupo | Ejemplos |
|---|---|
| etapa_ingenieria | perfil, conceptual, prefactibilidad, factibilidad, basica, detalle, contraparte, epcm, construccion |
| instalaciones_mineras | rajo abierto, open pit, fondo mina, planta concentradora, tranque, deposito, embalse, botadero |
| procesos_sistemas | dewatering, desague, drenaje, bombeo, impulsion, relaves, transporte de relaves, disposicion de relaves, aguas recuperadas |
| disciplinas | civil, hidraulica, mecanica, piping, electrica, instrumentacion, control, geotecnia, procesos, estructural |
| componentes | bombas, pozos, piscinas, estanques, tuberias, canales, valvulas, salas electricas, relaveducto, acueducto |
| artefactos_propuesta | alcance, objetivo, metodologia, entregables, exclusiones, supuestos, cronograma, plazo, horas hombre, hh, tarifa, estimacion |

## Metadata minima por chunk

Cada chunk child debe conservar:

| Campo | Uso |
|---|---|
| codigo | Union con master y SharePoint |
| tipo_documento | oferta_tecnica, estimacion_hh, anexo_tecnico, etc. |
| archivo_nombre | Trazabilidad al archivo |
| source_path | Ruta local o SharePoint |
| cliente / cliente_final | Filtros comerciales |
| titulo | Titulo de master o documento |
| estado_info / estado_categoria | Separar ganadas, perdidas, pendientes, desiertas |
| tipo_servicio_info | Filtro por tipo de ingenieria o servicio |
| tipo_negociacion_info | Filtro comercial |
| ambito_info | Nacional / internacional |
| section_index / section_count | Ubicacion parent |
| child_index | Ubicacion child dentro del parent |
| section_title / child_section_title | Navegacion por titulos |
| page_start / page_end | Citas por pagina cuando LiteParse las entregue |
| section_entities | Busqueda por conceptos tecnicos detectados en la seccion |
