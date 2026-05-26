# Budget Extractor Function

Azure Function (Python v2, HTTP trigger) dedicada a extraer de Excels de oferta:
- **Entregables × cargos × HH** (tabla baseline)
- **Tarifas por cargo** (UF / USD / CLP)
- **Gastos reembolsables**

Devuelve JSON normalizado al esquema canónico de la tabla `proyectos` del backend SHIMIN.

Espejo de `agentePresupuesto/portable_table_extractor` pero aislada como microservicio para producción.

## Endpoints

| Verbo | Ruta | Propósito |
|---|---|---|
| GET  | `/api/health` | Ping + estado de auth |
| POST | `/api/extract` | Sube Excel → JSON crudo (todas las tablas detectadas) |
| POST | `/api/extract-normalized` | Sube Excel + `codigo=O-XXXX` → JSON listo para insertar en SQLite |

Auth: header `x-api-key` debe coincidir con el App Setting `BUDGET_EXTRACTOR_API_KEY`. Si no está configurada, modo abierto (solo dev).

### Subida del Excel

Dos formas válidas:
- **Multipart**: campo `file` con el .xlsx
- **Raw body**: bytes del Excel + header `x-filename: archivo.xlsx`

### Respuesta `/api/extract-normalized`

```json
{
  "success": true,
  "codigo": "O-2658",
  "file_name": "SH0466-ODS-001.xlsx",
  "processed_at": "2026-05-14T20:31:00Z",
  "totals": { "proyecto_filas": 142, "tarifas_filas": 11, "gastos_filas": 4 },
  "proyecto_filas": [
    {
      "codigo": "O-2658",
      "descripcion": "Memorias de cálculo sistema hidráulico",
      "clasificacion": "Documento",
      "cargo": "JD",
      "cargo_raw": "JD",
      "hh": 5,
      "item": "1.2",
      "source_sheet": "Estimación HH",
      "confidence": 0.92
    }
  ],
  "tarifas_filas": [
    { "codigo": "O-2658", "cargo": "JP", "nombre_profesional": "Jefe de Proyecto", "tarifa": 85000, "moneda": "CLP", "source_sheet": "Tarifas", "confidence": 0.95 }
  ],
  "gastos_filas": [
    { "codigo": "O-2658", "concepto": "Pasajes Santiago–Antofagasta", "cantidad": 4, "precio_unit": 220000, "total": 880000, "moneda": "CLP" }
  ]
}
```

## Deploy a Azure

Estado verificado:
- Resource group backend: `appHH`
- Región backend: `chilecentral`
- Nombres sugeridos disponibles al momento de documentar: `apphhbudgetst`, `apphh-budget-extractor`

### Recursos necesarios

```bash
RG=appHH
NAME=apphh-budget-extractor
LOCATION=chilecentral

# 1. Storage account (requerido por Functions)
az storage account create -n apphhbudgetst -g $RG -l $LOCATION --sku Standard_LRS

# 2. Function App (Consumption plan, Python 3.11)
az functionapp create \
  -g $RG -n $NAME \
  --consumption-plan-location $LOCATION \
  --runtime python --runtime-version 3.11 \
  --functions-version 4 \
  --storage-account apphhbudgetst \
  --os-type Linux

# 3. App Settings
az functionapp config appsettings set -g $RG -n $NAME --settings \
  BUDGET_EXTRACTOR_API_KEY="<genera-un-secret-fuerte>" \
  AzureWebJobsFeatureFlags="EnableWorkerIndexing"

# 4. Deploy
func azure functionapp publish $NAME --python
```

### URL pública resultante

```
https://apphh-budget-extractor.azurewebsites.net/api/extract-normalized
```

### Consumir desde el backend `proyectohh_app`

Añadir al `.env` / App Settings del backend principal:

```
BUDGET_EXTRACTOR_URL=https://apphh-budget-extractor.azurewebsites.net
BUDGET_EXTRACTOR_API_KEY=<misma-key-que-arriba>
```

## Local

```bash
cd budget-extractor-function
pip install -r requirements.txt
func start
# Endpoint local: http://localhost:7071/api/extract-normalized?codigo=O-2658
```

## Actualización rápida

Si la Function ya existe en Azure y solo quieres republicar cambios:

```powershell
Set-Location "C:\Users\CristianReyes\OneDrive - SHIMIN\Documentos\GitHub\proyectohh_app\app_principal\budget-extractor-function"
.\update-azure-function.ps1
```

Opciones útiles:

```powershell
# Publicar y además sincronizar URL/key en el backend
.\update-azure-function.ps1 -UpdateBackendSettings -ApiKey "<tu-api-key>"

# Probar el script sin tocar Azure
.\update-azure-function.ps1 -WhatIf
```

## Schema canónico (formato `proyectos`)

El output `proyecto_filas` se mapea 1:1 a la tabla SQLite `proyectos_extracted` que el backend principal crea al consumir esta function:

```sql
create table proyectos_extracted (
  id integer primary key,
  codigo text not null,
  descripcion text,
  clasificacion text,        -- "Actividad" | "Documento"
  cargo text,                -- canónico: JP, JI, JD, IA, IB, ...
  cargo_raw text,            -- lo que extrajo el Excel literal
  hh real,
  item text,
  source_file text,
  source_sheet text,
  confidence real,
  extracted_at text
);
```

## Notas

- Timeout 9 min (configurable en `host.json`).
- `use_ai=False` por defecto (la heurística del extractor es más precisa que la IA para roles).
- Si necesitas activar IA fallback, setea `OPENAI_API_KEY` y modifica `function_app.py:_extract`.
- Función *anónima* a nivel de Azure (`AuthLevel.ANONYMOUS`); seguridad la maneja la API key custom.
