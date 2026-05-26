# Manual de Deploy — Budget Extractor Function

Guía paso a paso para subir la Azure Function a producción.
Suscripción detectada: **Azure subscription 1** (tenant `e6912f7f-971b-4479-8cc7-cf5cfe63913c`, user `innovacion.developer@shimin.cl`).

Estado verificado al 2026-05-19:
- El backend principal vive en el resource group `appHH`.
- El App Service backend es `apphhshimin` en `chilecentral`.
- No existe todavía un Function App para este `budget extractor`.
- Los nombres `apphhbudgetst` y `apphh-budget-extractor` no están ocupados al momento de escribir este manual.

---

## 0. Path absoluto de la function

```
C:\Users\CristianReyes\OneDrive - SHIMIN\Documentos\GitHub\proyectohh_app\app_principal\budget-extractor-function\
```

Contenido:
```
budget-extractor-function/
  host.json                     # config runtime (timeout 9 min, extension bundle v4)
  function_app.py               # 3 HTTP triggers (health, extract, extract-normalized)
  requirements.txt              # azure-functions, pandas, openpyxl, pydantic, openai
  local.settings.json           # solo dev local — NO se sube a Azure
  portable_table_extractor/     # extractor (copiado de agentePresupuesto)
  README.md                     # uso del servicio
  DEPLOY_MANUAL.md              # este archivo
```

---

## 1. Pre-requisitos en tu máquina (ya verificado)

| Tool | Versión instalada |
|---|---|
| Azure CLI (`az`) | 2.80.0 ✅ |
| Azure Functions Core Tools (`func`) | 4.8.0 ✅ |
| Python 3.11+ | (cualquiera local sirve, Azure usa 3.11) |
| Sesión `az login` activa | ✅ |

Si necesitas re-login:
```bash
az login
az account set --subscription "Azure subscription 1"
```

---

## 2. Variables de decisión (las eliges TÚ antes de empezar)

| Variable | Valor sugerido | Notas |
|---|---|---|
| `RG` | `appHH` | resource group del backend principal; ya existe |
| `LOCATION` | `chilecentral` | misma región que el backend `apphhshimin` |
| `STORAGE` | `apphhbudgetst` | 3-24 chars, lowercase + números, único globalmente |
| `FUNCAPP` | `apphh-budget-extractor` | nombre del Function App (único globalmente) |
| `API_KEY` | **genera uno** con `openssl rand -hex 32` o `python -c "import secrets; print(secrets.token_hex(32))"` | el secret que protege la function |

Si tu resource group se llama distinto, primero lista los existentes:
```bash
az group list --query "[].{name:name, location:location}" -o table
```

---

## 3. Comandos paso a paso

Pega esto en una **bash** (Git Bash funciona). Cambia los 5 valores de arriba si quieres distintos.

```bash
# --- 0. Definir variables ---
RG=appHH
LOCATION=chilecentral
STORAGE=apphhbudgetst
FUNCAPP=apphh-budget-extractor
API_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
echo "API_KEY generada (GUÁRDALA): $API_KEY"

# --- 1. Crear storage account (requerido por Functions) ---
az storage account create \
  -n $STORAGE -g $RG -l $LOCATION \
  --sku Standard_LRS \
  --kind StorageV2

# --- 2. Crear Function App (Consumption plan, Python 3.11) ---
az functionapp create \
  -g $RG -n $FUNCAPP \
  --consumption-plan-location $LOCATION \
  --runtime python --runtime-version 3.11 \
  --functions-version 4 \
  --storage-account $STORAGE \
  --os-type Linux

# --- 3. App Settings (la API key + flag de Python v2) ---
az functionapp config appsettings set \
  -g $RG -n $FUNCAPP \
  --settings \
    BUDGET_EXTRACTOR_API_KEY="$API_KEY" \
    AzureWebJobsFeatureFlags="EnableWorkerIndexing"

# --- 4. Desplegar el código (desde la carpeta del proyecto) ---
cd "/c/Users/CristianReyes/OneDrive - SHIMIN/Documentos/GitHub/proyectohh_app/app_principal/budget-extractor-function"
func azure functionapp publish $FUNCAPP --python

# --- 5. Verificar URLs ---
echo "Endpoints:"
echo "  https://${FUNCAPP}.azurewebsites.net/api/health"
echo "  https://${FUNCAPP}.azurewebsites.net/api/extract"
echo "  https://${FUNCAPP}.azurewebsites.net/api/extract-normalized"
echo ""
echo "API key (para header x-api-key): $API_KEY"
```

> El paso 4 toma 3–6 minutos. La primera vez instala `pandas`/`openpyxl` (pesados); las siguientes son más rápidas.

---

## 4. Probar end-to-end con `curl`

```bash
# A. Health (sin auth)
curl https://apphh-budget-extractor.azurewebsites.net/api/health

# Respuesta esperada:
# {"status":"ok","service":"budget-extractor-function","version":"1.0.0","auth_required":true}

# B. Extraer un Excel real (auth con API key)
API_KEY="<la-que-generaste-arriba>"
EXCEL="../storage/emitted_offer_assets/excel/O-0274/HH O274 Rev 1.xlsx"

curl -X POST \
  -H "x-api-key: $API_KEY" \
  -F "file=@${EXCEL}" \
  "https://apphh-budget-extractor.azurewebsites.net/api/extract-normalized?codigo=O-0274" \
  | python -m json.tool | head -60

# C. Sin API key → debe devolver 401
curl -X POST \
  -F "file=@${EXCEL}" \
  "https://apphh-budget-extractor.azurewebsites.net/api/extract-normalized?codigo=O-0274"
# Respuesta: {"error":"x-api-key inválida o ausente"}
```

Respuesta exitosa (recortada):
```json
{
  "success": true,
  "codigo": "O-0274",
  "file_name": "HH O274 Rev 1.xlsx",
  "totals": { "proyecto_filas": 45, "tarifas_filas": 0, "gastos_filas": 6, "descartados": 0 },
  "entregables_sheet_seleccionado": "HH",
  "agregadores_excluidos": [{"item": "1.0", "descripcion": "ESTACIÓN DE BOMBEO N°1"}],
  "proyecto_filas": [
    {"codigo":"O-0274", "descripcion":"Informe de Interferencias", "cargo":"JP", "hh":5, ...}
  ],
  "gastos_filas": [
    {"codigo":"O-0274", "concepto":"Pasajes", "cantidad":2, "precio_unit":250000, "total":500000, "moneda":"CLP"}
  ]
}
```

---

## 5. Conectar el backend `apphhshimin` a la function

Una vez deployada y probada, agregar al backend principal:

### App Settings del backend (Azure Portal → apphhshimin → Configuration)

```
BUDGET_EXTRACTOR_URL=https://apphh-budget-extractor.azurewebsites.net
BUDGET_EXTRACTOR_API_KEY=<el-mismo-secret-de-paso-3>
```

O por CLI:
```bash
az webapp config appsettings set -g appHH -n apphhshimin --settings \
  BUDGET_EXTRACTOR_URL="https://apphh-budget-extractor.azurewebsites.net" \
  BUDGET_EXTRACTOR_API_KEY="<paste>"
```

Luego reinicia el backend:
```bash
az webapp restart -g appHH -n apphhshimin
```

### Disparar extracción desde el backend ya conectado

```bash
# Extraer todos los Excels de un código O-XXXX desde SharePoint
curl -X POST https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net/api/entregables/extract-budget/O-0274 \
  -H "x-user-email: cri.reyes@shimin.cl"

# Ver lo extraído
curl https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net/api/entregables/extracted/O-0274 \
  -H "x-user-email: cri.reyes@shimin.cl"
```

---

## 6. Variables de entorno completas

### En la Function (Azure App Settings de `apphh-budget-extractor`)

| Variable | Valor | Obligatoria | Notas |
|---|---|---|---|
| `BUDGET_EXTRACTOR_API_KEY` | (secret 64 chars hex) | **Sí** | Si está vacío, function entra en modo abierto (solo dev) |
| `AzureWebJobsFeatureFlags` | `EnableWorkerIndexing` | **Sí** | Habilita Python programming model v2 |
| `OPENAI_API_KEY` | (key OpenAI) | No | Solo si activas `use_ai=True` (no por defecto, heurística es mejor) |
| `FUNCTIONS_WORKER_RUNTIME` | `python` | (auto) | La setea `func` al crear |
| `AzureWebJobsStorage` | (connection string) | (auto) | La setea Azure al asociar el storage account |
| `WEBSITE_RUN_FROM_PACKAGE` | `1` | (auto) | La setea `func` al deployar |

### En el backend `apphhshimin` (App Settings)

| Variable | Valor | Obligatoria |
|---|---|---|
| `BUDGET_EXTRACTOR_URL` | `https://apphh-budget-extractor.azurewebsites.net` | **Sí** para usar la function |
| `BUDGET_EXTRACTOR_API_KEY` | (mismo secret que paso 3) | **Sí** si la function tiene auth activa |

### En `.env` local (`backend/.env`) para dev

```
BUDGET_EXTRACTOR_URL=https://apphh-budget-extractor.azurewebsites.net
BUDGET_EXTRACTOR_API_KEY=el-mismo-secret
```

O para apuntar a la function corriendo local con `func start`:
```
BUDGET_EXTRACTOR_URL=http://localhost:7071
BUDGET_EXTRACTOR_API_KEY=  # vacío en local
```

---

## 7. Costo estimado

- **Consumption plan**: pagas por ejecución + GB·s memoria. Para extraer Excels de 50KB tarda ~0.2s con ~256MB → **~$0** mensual con uso normal SHIMIN.
- **Storage account**: ~$1 USD/mes (solo metadatos de Functions).
- **Egress**: ignorable (las respuestas JSON son pequeñas).

Free tier: 1M ejecuciones + 400.000 GB·s gratis al mes.

---

## 8. Troubleshooting

| Problema | Causa probable | Solución |
|---|---|---|
| `404` al llamar `/api/extract` | `EnableWorkerIndexing` no setupado | Agregar App Setting `AzureWebJobsFeatureFlags=EnableWorkerIndexing` y reiniciar function |
| `401 x-api-key inválida` | Header faltante o key distinta | Verificar header `x-api-key` en request vs App Setting `BUDGET_EXTRACTOR_API_KEY` |
| `500 internal error` | `pandas`/`openpyxl` no instalados | Re-deployar con `func azure functionapp publish ... --python --build remote` |
| `504 timeout` | Excel muy grande (>5MB con muchas hojas) | Subir `functionTimeout` en `host.json` (max 10 min en consumption) |
| Backend `proyectohh_app` da `503: BUDGET_EXTRACTOR_URL no configurada` | Falta env var en `apphhshimin` | Agregar App Setting y reiniciar |

### Logs

```bash
az functionapp log tail -g $RG -n $FUNCAPP
# o en Portal: apphh-budget-extractor → Log stream
```

---

## 9. Re-deploy (después de cambios al código)

Cualquier cambio en `function_app.py` o `portable_table_extractor/` requiere re-deploy:

```bash
cd "/c/Users/CristianReyes/OneDrive - SHIMIN/Documentos/GitHub/proyectohh_app/app_principal/budget-extractor-function"
func azure functionapp publish $FUNCAPP --python
```

Toma 1–3 min. Cero downtime (Azure hace blue-green automático).

---

## 10. Rollback / destruir todo

Si quieres eliminar la function:
```bash
az functionapp delete -g $RG -n apphh-budget-extractor
az storage account delete -g $RG -n apphhbudgetst --yes
```
