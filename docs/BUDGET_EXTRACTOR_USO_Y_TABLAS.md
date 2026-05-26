# Manual de Uso y Extraccion de Tablas desde Excel

Este manual explica como usar la Azure Function `budget extractor` para subir un Excel de oferta y obtener las tablas detectadas, tanto en formato crudo como en formato normalizado para el backend.

## Objetivo

La Function recibe un Excel de oferta y extrae tres grupos de datos:

- Entregables con HH por cargo profesional.
- Tarifas por cargo.
- Gastos reembolsables.

Luego puede devolver:

- tablas raw, muy utiles para auditoria y debugging;
- tablas normalizadas, listas para persistir o revisar en el backend.

## Servicio desplegado

- Function App: `apphh-budget-extractor`
- URL base: `https://apphh-budget-extractor.azurewebsites.net`
- Health: `GET /api/health`
- Extraccion raw: `POST /api/extract`
- Extraccion normalizada: `POST /api/extract-normalized`

## Autenticacion

La Function usa API key custom por header.

Header requerido:

```text
x-api-key: <BUDGET_EXTRACTOR_API_KEY>
```

Si falta o no coincide, la respuesta es `401`.

## Formas validas de enviar el Excel

Hay dos formas soportadas:

### 1. Multipart form-data

Campo esperado:

```text
file
```

Este es el formato recomendado.

### 2. Raw body

Puedes enviar directamente los bytes del Excel en el body, con este header:

```text
x-filename: archivo.xlsx
```

## Endpoint 1: Health

Sirve para comprobar que la Function esta viva.

### Request

```bash
curl https://apphh-budget-extractor.azurewebsites.net/api/health
```

### Respuesta esperada

```json
{
  "status": "ok",
  "service": "budget-extractor-function",
  "version": "1.0.0",
  "auth_required": true
}
```

## Endpoint 2: Extraccion raw

Este endpoint detecta tablas y devuelve la estructura extraida sin normalizar. Es el mejor punto para revisar hojas, filas detectadas y confianza del extractor.

### URL

```text
POST https://apphh-budget-extractor.azurewebsites.net/api/extract
```

### Ejemplo con curl

```bash
curl -X POST \
  -H "x-api-key: TU_API_KEY" \
  -F "file=@storage/emitted_offer_assets/excel/O-0274/HH O274 Rev 1.xlsx" \
  "https://apphh-budget-extractor.azurewebsites.net/api/extract"
```

### Ejemplo con PowerShell

```powershell
$headers = @{ "x-api-key" = "TU_API_KEY" }
$form = @{ file = Get-Item "storage/emitted_offer_assets/excel/O-0274/HH O274 Rev 1.xlsx" }
Invoke-RestMethod -Method Post `
  -Uri "https://apphh-budget-extractor.azurewebsites.net/api/extract" `
  -Headers $headers `
  -Form $form
```

### Que devuelve

La respuesta incluye, entre otros, estos campos:

- `file_name`: nombre del archivo procesado.
- `processing_time`: tiempo de proceso.
- `summary`: resumen generado por el extractor.
- `entregables`: tablas detectadas como entregables.
- `tarifas`: tablas detectadas como tarifas.
- `gastos_reembolsables`: tablas detectadas como gastos.
- `presupuesto`: otras tablas detectadas como presupuesto.

Cada tabla viene con:

- `sheet`: hoja origen.
- `confidence`: confianza de deteccion.
- `num_rows`: cantidad de filas detectadas.
- `rows`: filas extraidas.
- `method`: metodo de deteccion.

### Cuando usar `/api/extract`

Usalo cuando necesites:

- inspeccionar que hojas fueron detectadas;
- revisar filas originales extraidas;
- diagnosticar por que una tabla no quedo bien normalizada;
- comparar revisiones del mismo Excel.

## Endpoint 3: Extraccion normalizada

Este endpoint transforma el resultado al formato usado por el backend. Es el endpoint recomendado para integracion.

### URL

```text
POST https://apphh-budget-extractor.azurewebsites.net/api/extract-normalized?codigo=O-0274
```

El `codigo` puede venir por:

- query string: `?codigo=O-0274`
- header: `x-codigo: O-0274`

### Ejemplo con curl

```bash
curl -X POST \
  -H "x-api-key: TU_API_KEY" \
  -F "file=@storage/emitted_offer_assets/excel/O-0274/HH O274 Rev 1.xlsx" \
  "https://apphh-budget-extractor.azurewebsites.net/api/extract-normalized?codigo=O-0274"
```

### Ejemplo con PowerShell

```powershell
$headers = @{ "x-api-key" = "TU_API_KEY" }
$form = @{ file = Get-Item "storage/emitted_offer_assets/excel/O-0274/HH O274 Rev 1.xlsx" }
Invoke-RestMethod -Method Post `
  -Uri "https://apphh-budget-extractor.azurewebsites.net/api/extract-normalized?codigo=O-0274" `
  -Headers $headers `
  -Form $form
```

### Estructura de respuesta

```json
{
  "success": true,
  "codigo": "O-0274",
  "file_name": "HH O274 Rev 1.xlsx",
  "processed_at": "2026-05-26T12:00:00Z",
  "totals": {
    "proyecto_filas": 45,
    "tarifas_filas": 0,
    "gastos_filas": 6,
    "descartados": 0
  },
  "proyecto_filas": [],
  "tarifas_filas": [],
  "gastos_filas": [],
  "descartados": [],
  "agregadores_excluidos": [],
  "entregables_sheet_seleccionado": "HH",
  "entregables_sheets_disponibles": ["HH", "Hoja1"]
}
```

## Como leer las tablas devueltas

### 1. `proyecto_filas`

Es la tabla principal. Contiene una fila por combinacion:

```text
entregable x cargo x HH
```

Campos relevantes:

- `codigo`: codigo de oferta, por ejemplo `O-0274`.
- `descripcion`: nombre del entregable o actividad.
- `clasificacion`: tipologia inferida, por ejemplo `Documento`, `Plano` o `Actividad`.
- `cargo`: codigo canonico del profesional, por ejemplo `JP`, `JD`, `IA`, `IB`.
- `cargo_raw`: codigo tal como venia en el Excel.
- `hh`: horas hombre para ese cargo.
- `item`: item del entregable en la estructura del Excel.
- `source_sheet`: hoja origen.
- `confidence`: confianza de la tabla origen.

Ejemplo:

```json
{
  "codigo": "O-0274",
  "descripcion": "Informe de Interferencias",
  "clasificacion": "Documento",
  "cargo": "JP",
  "cargo_raw": "JP",
  "hh": 5,
  "item": "1.2",
  "source_sheet": "HH",
  "confidence": 0.92
}
```

### 2. `tarifas_filas`

Contiene una fila por tarifa detectada.

Campos relevantes:

- `codigo`
- `cargo`
- `cargo_raw`
- `nombre_profesional`
- `tarifa`
- `moneda`
- `source_sheet`
- `confidence`

Ejemplo:

```json
{
  "codigo": "O-0274",
  "cargo": "JP",
  "cargo_raw": "JP",
  "nombre_profesional": "Jefe de Proyecto",
  "tarifa": 85000,
  "moneda": "CLP",
  "source_sheet": "Tarifas",
  "confidence": 0.95
}
```

### 3. `gastos_filas`

Contiene gastos reembolsables detectados.

Campos relevantes:

- `codigo`
- `concepto`
- `cantidad`
- `precio_unit`
- `total`
- `moneda`
- `source_sheet`
- `confidence`

Ejemplo:

```json
{
  "codigo": "O-0274",
  "concepto": "Pasajes",
  "cantidad": 2,
  "precio_unit": 250000,
  "total": 500000,
  "moneda": "CLP",
  "source_sheet": "HH",
  "confidence": 0.88
}
```

### 4. `descartados`

Registra filas con HH que fueron omitidas porque el cargo no calzaba con el catalogo canonico de cargos profesionales.

Sirve para detectar:

- codigos de cargo raros;
- errores tipograficos del Excel;
- columnas que no corresponden a HH profesionales.

### 5. `agregadores_excluidos`

Registra filas que eran titulos o agregadores de seccion y se excluyeron para evitar doble conteo.

Ejemplo real detectado:

```json
[
  {
    "item": "1.0",
    "descripcion": "ESTACION DE BOMBEO N°1"
  }
]
```

### 6. `entregables_sheet_seleccionado`

Si el Excel tiene varias hojas con entregables, el extractor elige solo una para evitar doble conteo. Este campo indica cual fue la seleccionada.

### 7. `entregables_sheets_disponibles`

Lista todas las hojas donde el extractor detecto tablas de entregables. Sirve para auditoria.

## Reglas importantes de normalizacion

### Cargos canónicos

Solo se aceptan cargos profesionales canonicos como:

```text
JP, JI, JD, IA, IB, IC, PA, PB, CP, CD, CE, SI, GP, DI, CA, CB, DA, DB, PC, I, C, ABIM, CBIM, EC, CN, ESP
```

Si el cargo no cae en esa lista, se manda a `descartados`.

### Flags que no cuentan como cargo

Los codigos `DC`, `PL` y `GL` no se tratan como cargos con HH. Se usan para inferir el tipo de entregable:

- `DC` -> `Documento`
- `PL` -> `Plano`
- `GL` -> `Actividad`

### Seleccion de hoja de entregables

Si el archivo trae varias revisiones o copias, no se suman todas. Se toma una sola tabla de entregables:

- primero por mayor `confidence`;
- en empate, la ultima en orden.

Esto evita doble conteo entre `Rev 0`, `Rev 1` o copias de hoja.

## Errores comunes

### 401 Unauthorized

Causa:

- falta `x-api-key`;
- la key no coincide.

### 400 Bad Request

Causa probable:

- no se envio archivo;
- el campo no se llamo `file` en multipart;
- extension no soportada.

Extensiones soportadas:

```text
.xlsx, .xls, .xlsm
```

### 500 Internal Server Error

Causa probable:

- error interno del extractor;
- Excel corrupto;
- estructura fuera del patron esperado.

En ese caso conviene probar primero `/api/extract` para ver el estado raw de deteccion.

## Flujo recomendado de uso

### Opcion 1. Validacion manual

1. Ejecutar `GET /api/health`.
2. Ejecutar `POST /api/extract` con el Excel.
3. Revisar hojas, confianza y filas detectadas.
4. Ejecutar `POST /api/extract-normalized` con `codigo`.
5. Validar `totals`, `descartados` y `agregadores_excluidos`.

### Opcion 2. Integracion backend

1. El backend envia el Excel a `/api/extract-normalized`.
2. Recibe `proyecto_filas`, `tarifas_filas` y `gastos_filas`.
3. Persiste el resultado en SQLite.
4. Usa `descartados` y `agregadores_excluidos` como auditoria.

## Ejemplo real validado

Archivo probado:

```text
storage/emitted_offer_assets/excel/O-0274/HH O274 Rev 1.xlsx
```

Resultado resumido validado en Azure:

- `success=true`
- `codigo=O-0274`
- `proyecto_filas=45`
- `tarifas_filas=0`
- `gastos_filas=6`
- `descartados=0`
- `entregables_sheet_seleccionado=HH`
- agregador excluido: `1.0 ESTACION DE BOMBEO N°1`

## Relacion con el backend principal

Para que el backend principal consuma esta Function, necesita estas variables:

```text
BUDGET_EXTRACTOR_URL=https://apphh-budget-extractor.azurewebsites.net
BUDGET_EXTRACTOR_API_KEY=<misma-api-key-de-la-function>
```

## Archivo recomendado para pruebas locales

Si quieres probar rapido desde este repo, usa uno de estos Excels reales:

```text
storage/emitted_offer_assets/excel/O-0274/HH O274 Rev 1.xlsx
```

## Resumen

Usa `/api/extract` cuando quieras inspeccionar la deteccion cruda.

Usa `/api/extract-normalized` cuando quieras obtener directamente las tablas listas para persistencia o analisis:

- `proyecto_filas`
- `tarifas_filas`
- `gastos_filas`
- `descartados`
- `agregadores_excluidos`

Ese segundo endpoint es el adecuado para asociar las tablas al Excel subido y dejarlas listas para el backend.