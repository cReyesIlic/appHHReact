# Budget Extractor Deploy Report

Fecha: 2026-05-26

## Estado general

El microservicio `budget extractor` fue desplegado exitosamente en Azure y responde por HTTP con extracción real de Excel.

Estado por componente:

| Componente | Estado | Nota |
|---|---|---|
| Azure Storage Account | OK | `apphhbudgetst` creado en `appHH` |
| Azure Function App | OK | `apphh-budget-extractor` creado en `appHH` |
| Publicación código Function | OK | 3 funciones registradas en Azure |
| Health endpoint | OK | `GET /api/health` responde 200 |
| Extract endpoint real | OK | `POST /api/extract-normalized?codigo=O-0274` responde 200 |
| Integración App Settings backend | OK | `BUDGET_EXTRACTOR_URL` y `BUDGET_EXTRACTOR_API_KEY` cargadas en `apphhshimin` |
| Endpoint backend `/api/entregables/extract-budget/{codigo}` | PENDIENTE | hoy responde 404, el backend desplegado no incluye aún esa ruta |

## Recursos Azure creados

- Resource group: `appHH`
- Región: `chilecentral`
- Storage account: `apphhbudgetst`
- Function App: `apphh-budget-extractor`
- Host público: `https://apphh-budget-extractor.azurewebsites.net`
- App Insights: `apphh-budget-extractor`
- Hosting: plan dedicado Linux existente `ASP-appshimin`

## App Settings configuradas en la Function

- `BUDGET_EXTRACTOR_API_KEY`
- `AzureWebJobsFeatureFlags=EnableWorkerIndexing`
- `SCM_DO_BUILD_DURING_DEPLOYMENT=true`
- `ENABLE_ORYX_BUILD=true`
- `FUNCTIONS_WORKER_RUNTIME=python`
- `FUNCTIONS_EXTENSION_VERSION=~4`

## Endpoints publicados

- `GET https://apphh-budget-extractor.azurewebsites.net/api/health`
- `POST https://apphh-budget-extractor.azurewebsites.net/api/extract`
- `POST https://apphh-budget-extractor.azurewebsites.net/api/extract-normalized?codigo=O-XXXX`

## Validación ejecutada

### 1. Health

Respuesta:

```json
{"status": "ok", "service": "budget-extractor-function", "version": "1.0.0", "auth_required": true}
```

### 2. Extracción real

Archivo probado:

- `storage/emitted_offer_assets/excel/O-0274/HH O274 Rev 1.xlsx`

Request probado:

- `POST /api/extract-normalized?codigo=O-0274`
- header `x-api-key` válido
- multipart con campo `file`

Resultado resumido:

- `success=true`
- `codigo=O-0274`
- `proyecto_filas=45`
- `tarifas_filas=0`
- `gastos_filas=6`
- `descartados=0`
- `agregadores_excluidos=[{"item":"1.0","descripcion":"ESTACIÓN DE BOMBEO N°1"}]`
- hoja seleccionada: `HH`

## Backend principal

Se cargaron estas App Settings en `apphhshimin`:

- `BUDGET_EXTRACTOR_URL=https://apphh-budget-extractor.azurewebsites.net`
- `BUDGET_EXTRACTOR_API_KEY=<configurada>`

También se agregó al `.env` local:

- `BUDGET_EXTRACTOR_URL=https://apphh-budget-extractor.azurewebsites.net`
- `BUDGET_EXTRACTOR_API_KEY=<configurada>`

## Pendiente detectado

El backend hoy responde `404` para:

- `POST /api/entregables/extract-budget/O-0274`
- `GET /api/entregables/extracted/O-0274`

Interpretación:

- La Function sí está desplegada y funcional.
- El App Service backend `apphhshimin` todavía no está ejecutando una imagen/código que incluya esas rutas nuevas.
- Para cerrar el flujo end-to-end desde la UI/backend, falta desplegar el backend con la slice que contiene:
  - `backend/app/services/budget_extractor_client.py`
  - rutas nuevas en `backend/app/api/routes.py`
  - config nueva en `backend/app/core/config.py`

## Comandos relevantes usados

```powershell
az storage account create -n apphhbudgetst -g appHH -l chilecentral --sku Standard_LRS --kind StorageV2
az functionapp create -g appHH -p ASP-appshimin -n apphh-budget-extractor --runtime python --runtime-version 3.11 --functions-version 4 --storage-account apphhbudgetst
az functionapp config appsettings set -g appHH -n apphh-budget-extractor --settings BUDGET_EXTRACTOR_API_KEY=*** AzureWebJobsFeatureFlags=EnableWorkerIndexing SCM_DO_BUILD_DURING_DEPLOYMENT=true ENABLE_ORYX_BUILD=true
func azure functionapp publish apphh-budget-extractor --python
az webapp config appsettings set -g appHH -n apphhshimin --settings BUDGET_EXTRACTOR_URL=https://apphh-budget-extractor.azurewebsites.net BUDGET_EXTRACTOR_API_KEY=***
az webapp restart -g appHH -n apphhshimin
```

## Conclusión

Sí quedó deployado y funcionando en Azure como servicio independiente.

Lo que está listo:

- Function desplegada
- endpoint público operativo
- extracción real validada
- backend configurado para consumirla

Lo que falta para usarla desde la app principal:

- desplegar el backend que contiene las rutas y el cliente del `budget extractor`
