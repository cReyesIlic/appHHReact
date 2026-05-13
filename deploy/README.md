# Deploy SHIMIN Proposal Intelligence usando recursos `apphh` existentes

## Recursos reutilizados (NO se crean nuevos)

| Recurso existente | Tipo | Región | Rol nuevo |
|---|---|---|---|
| **apphhshimin** | App Service | Chile Central | Backend FastAPI (Docker container) — reemplaza Streamlit viejo |
| **apphshimin** | Container Registry | Chile Central | Guarda imagen `shimin-backend` |
| **ASP-appshimin** | App Service Plan | Chile Central | Ya pagado — host del App Service |
| **apphhdrive** | Storage Account | Chile Central | File Share `shimin-data` montado en backend (SQLite + storage + exports) |
| **testapphhopenai** | Azure OpenAI | East US | Modelos gpt-4o-mini + text-embedding-3-small (ya en `.env`) |
| **docIntelhhSHIMIN** | Document Intelligence | East US | Reservado: futuro reemplazo de liteparse para extracción de PDFs |

## Recurso NUEVO opcional (free tier)

- **shimin-frontend** — Azure Static Web App (Free) para el frontend React. **$0/mes**. Da SSL, dominio custom y SSO Entra ID gratis.

## Costos esperados

| Componente | Mensual |
|---|---|
| App Service plan ASP-appshimin | **ya pagado** (sin incremento) |
| Container Registry apphshimin | **ya pagado** |
| Storage Account apphhdrive (File Share ~5 GB) | **~$1–3 USD** adicional según SKU |
| Static Web App nuevo | **$0** (Free) |
| Azure OpenAI consumo | variable (~$2–10/mes para uso interno) |
| **Delta vs hoy** | **≈ $0–10 USD/mes** |

## Pasos de deploy

### 1. Configurar variables de despliegue

Crear `deploy/env.sh` (NO commitear):
```bash
export RG="rg-apphh"          # ajustar al RG real de los recursos
export ACR_NAME="apphshimin"
export STORAGE_ACCOUNT="apphhdrive"
export SHARE_NAME="shimin-data"
export APP_SERVICE="apphhshimin"
export APP_PLAN="ASP-appshimin"
export REGION="chilecentral"
export AOAI_NAME="testapphhopenai"
```

```bash
source deploy/env.sh
# verificar acceso
az login
az account set --subscription "<SUBSCRIPTION_ID>"
az group show -n $RG
```

### 2. Preparar File Share en apphhdrive

```bash
# Crear el File Share si no existe (idempotente)
az storage share-rm create \
  --resource-group $RG \
  --storage-account $STORAGE_ACCOUNT \
  --name $SHARE_NAME \
  --quota 50    # 50 GB es suficiente para SQLite + storage actual (~1 GB)

# Subir data inicial desde tu máquina con AzCopy
STORAGE_KEY=$(az storage account keys list -g $RG -n $STORAGE_ACCOUNT --query "[0].value" -o tsv)
SAS=$(az storage share generate-sas \
  --account-name $STORAGE_ACCOUNT --account-key "$STORAGE_KEY" \
  --name $SHARE_NAME --permissions rwl --expiry 2026-12-31 -o tsv)

# Sincronizar (usa azcopy desde https://aka.ms/downloadazcopy)
azcopy copy "C:/Users/CristianReyes/OneDrive - SHIMIN/Documentos/GitHub/proyectohh_app/app_principal/database" \
  "https://$STORAGE_ACCOUNT.file.core.windows.net/$SHARE_NAME?$SAS" --recursive

azcopy copy "C:/Users/CristianReyes/OneDrive - SHIMIN/Documentos/GitHub/proyectohh_app/app_principal/storage/llm_wiki" \
  "https://$STORAGE_ACCOUNT.file.core.windows.net/$SHARE_NAME/storage?$SAS" --recursive

azcopy copy "C:/Users/CristianReyes/OneDrive - SHIMIN/Documentos/GitHub/proyectohh_app/app_principal/storage/hh_excel_ingestion_manifest.csv" \
  "https://$STORAGE_ACCOUNT.file.core.windows.net/$SHARE_NAME/storage/?$SAS"
```

### 3. Build + push imagen al registry existente

```bash
# Build remoto (no usa Docker local, lo hace ACR)
az acr build -r $ACR_NAME -t shimin-backend:v1 ./backend

# Verificar
az acr repository show-tags -n $ACR_NAME --repository shimin-backend
```

### 4. Configurar App Service apphhshimin como Docker

```bash
# Habilitar admin del ACR
az acr update -n $ACR_NAME --admin-enabled true
ACR_PASSWORD=$(az acr credential show -n $ACR_NAME --query "passwords[0].value" -o tsv)
ACR_LOGIN_SERVER=$(az acr show -n $ACR_NAME --query loginServer -o tsv)

# Apuntar el App Service a la imagen nueva (REEMPLAZA al Streamlit viejo)
az webapp config container set \
  -n $APP_SERVICE -g $RG \
  --docker-custom-image-name $ACR_LOGIN_SERVER/shimin-backend:v1 \
  --docker-registry-server-url https://$ACR_LOGIN_SERVER \
  --docker-registry-server-user $ACR_NAME \
  --docker-registry-server-password "$ACR_PASSWORD"

# Configurar puerto
az webapp config appsettings set -n $APP_SERVICE -g $RG \
  --settings WEBSITES_PORT=8010 \
             DATABASE_DIR="database/proyectos 9.db" \
             DOCKER_REGISTRY_SERVER_URL="https://$ACR_LOGIN_SERVER" \
             DOCKER_REGISTRY_SERVER_USERNAME="$ACR_NAME" \
             DOCKER_REGISTRY_SERVER_PASSWORD="$ACR_PASSWORD"
```

### 5. Inyectar secrets (.env)

```bash
# Lee tu .env local y sube cada valor como App Setting
while IFS='=' read -r key value; do
  [[ -z "$key" || "$key" =~ ^# ]] && continue
  # Quitar comillas
  value="${value%\"}"; value="${value#\"}"
  az webapp config appsettings set -n $APP_SERVICE -g $RG --settings "$key=$value" -o none
done < "C:/Users/CristianReyes/OneDrive - SHIMIN/Documentos/GitHub/proyectohh_app/app_principal/.env"
```

> Si prefieres usar **Key Vault** (más seguro), crea uno y referencia con `@Microsoft.KeyVault(SecretUri=...)`. Para empezar, App Settings está OK.

### 6. Montar File Share como volume

```bash
# Crear storage mount en App Service
STORAGE_KEY=$(az storage account keys list -g $RG -n $STORAGE_ACCOUNT --query "[0].value" -o tsv)

az webapp config storage-account add \
  -n $APP_SERVICE -g $RG \
  --custom-id shimin-data \
  --storage-type AzureFiles \
  --account-name $STORAGE_ACCOUNT \
  --share-name $SHARE_NAME \
  --access-key "$STORAGE_KEY" \
  --mount-path "/srv/app_principal/database"

# Mount adicional para storage/
az webapp config storage-account add \
  -n $APP_SERVICE -g $RG \
  --custom-id shimin-storage \
  --storage-type AzureFiles \
  --account-name $STORAGE_ACCOUNT \
  --share-name $SHARE_NAME \
  --access-key "$STORAGE_KEY" \
  --mount-path "/srv/app_principal/storage"
```

> Nota: si el File Share tiene `database/` y `storage/` como subcarpetas, ambos mounts apuntan al mismo share pero a paths distintos dentro del container. Si prefieres simplicidad, crea **dos shares** (`shimin-db`, `shimin-storage`).

### 7. Restart y verificar

```bash
az webapp restart -n $APP_SERVICE -g $RG
az webapp log tail -n $APP_SERVICE -g $RG    # logs en vivo

# Probar health
APP_URL=$(az webapp show -n $APP_SERVICE -g $RG --query defaultHostName -o tsv)
curl -s https://$APP_URL/api/config/status | head -c 300
curl -s https://$APP_URL/api/sync/status
```

### 8. Frontend → Static Web App nuevo

```bash
az staticwebapp create \
  -n shimin-frontend \
  -g $RG \
  --location eastus2 \
  --source https://github.com/<usuario>/proyectohh_app \
  --branch main \
  --app-location frontend \
  --output-location dist \
  --login-with-github

# Configurar proxy /api/* hacia el App Service
# (Static Web App permite linked backends para que /api/* re-escriba sin CORS)
az staticwebapp backends link \
  -n shimin-frontend -g $RG \
  --backend-resource-id $(az webapp show -n $APP_SERVICE -g $RG --query id -o tsv) \
  --backend-region $REGION
```

Después de `link backends`, el frontend llama `/api/...` y Azure rewrites al App Service automáticamente.

### 9. Auth Entra ID en Static Web App

Editar `frontend/staticwebapp.config.json`:
```json
{
  "navigationFallback": { "rewrite": "/index.html" },
  "auth": {
    "identityProviders": {
      "azureActiveDirectory": {
        "userDetailsClaim": "preferred_username",
        "registration": {
          "openIdIssuer": "https://login.microsoftonline.com/<TENANT-ID-SHIMIN>/v2.0",
          "clientIdSettingName": "AAD_CLIENT_ID"
        }
      }
    }
  },
  "routes": [
    { "route": "/api/*", "allowedRoles": ["authenticated"] },
    { "route": "/*", "allowedRoles": ["authenticated"] }
  ],
  "globalHeaders": { "X-Frame-Options": "DENY" }
}
```

App Settings de Static Web App:
```bash
az staticwebapp appsettings set -n shimin-frontend -g $RG \
  --setting-names "AAD_CLIENT_ID=<APP_REGISTRATION_CLIENT_ID>"
```

### 10. Cron diario de sincronización

App Service no tiene cron jobs nativos baratos. Tres opciones:

**Opción A (recomendada): WebJob continuo dentro del mismo App Service**
```bash
# Subir un .zip con un script que ejecute cada N horas
zip -r sync-job.zip backend/scripts/sync_sharepoint.py
az webapp webjob continuous start -n $APP_SERVICE -g $RG --webjob-name daily-sync
```

**Opción B: Logic App con trigger Recurrence**
- Trigger: 02:00 hora Chile diaria
- Acción: HTTP POST a `https://apphhshimin.azurewebsites.net/api/sync/new?limit=50`
- Costo: <$1/mes

**Opción C: GitHub Actions con schedule**
- `.github/workflows/sync.yml` con cron `0 5 * * *`
- Solo curl al endpoint
- Gratis

Recomiendo **C** (cero costo, fácil de versionar):

`.github/workflows/sync.yml`:
```yaml
name: SHIMIN Daily Sync
on:
  schedule:
    - cron: '0 5 * * *'   # 05:00 UTC = 02:00 hora Chile
  workflow_dispatch:
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger sync-new
        run: |
          curl -X POST "https://apphhshimin.azurewebsites.net/api/sync/new?limit=50" \
            -H "x-user-email: cron@shimin.cl" \
            --max-time 1200
      - name: Refresh master
        run: |
          curl -X POST "https://apphhshimin.azurewebsites.net/api/master/refresh" \
            -H "x-user-email: cron@shimin.cl"
```

### 11. Eliminar Streamlit viejo

Cuando confirmes que el nuevo backend funciona en `apphhshimin`:
- El container del Streamlit antiguo desaparece automáticamente al cambiar la imagen (paso 4)
- Si la app vieja tenía archivos en `apphhdrive` que no necesitamos, borrar:
  ```bash
  az storage file delete-batch -s old-streamlit-share --account-name $STORAGE_ACCOUNT
  ```

---

## Tareas opcionales / futuras

### Reemplazar liteparse con Document Intelligence (`docIntelhhSHIMIN`)

El parsing actual de PDFs (`liteparse-service/`) podría reemplazarse por **Azure Document Intelligence** que ya tienes:
- Más preciso para PDFs con tablas, formularios, layout complejo
- Saca texto + estructura (headings, tablas como dataframes) en un solo call
- ~$1.50 por 1000 páginas (modelo "read")

Cambio mínimo en `backend/app/services/liteparse_client.py`:
```python
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential

client = DocumentIntelligenceClient(
    endpoint=settings.docintel_endpoint,
    credential=AzureKeyCredential(settings.docintel_key),
)
poller = client.begin_analyze_document("prebuilt-layout", body=pdf_bytes)
result = poller.result()
# result.content, result.tables, result.paragraphs
```

Esto es opcional — no es necesario para hacer deploy.

### Backup automático SQLite

WebJob diario que hace `cp database/proyectos\ 9.db backup-$(date).db` y lo sube a un blob en apphhdrive.

### Logs centralizados

Habilitar Application Insights gratis (5 GB/mes) en App Service para ver request latency, errors, etc.

---

## Comandos útiles post-deploy

```bash
# Ver logs en vivo
az webapp log tail -n $APP_SERVICE -g $RG

# SSH al container (debug)
az webapp ssh -n $APP_SERVICE -g $RG

# Restart sin re-deploy
az webapp restart -n $APP_SERVICE -g $RG

# Publicar nueva versión
az acr build -r $ACR_NAME -t shimin-backend:v2 ./backend
az webapp config container set -n $APP_SERVICE -g $RG \
  --docker-custom-image-name $ACR_LOGIN_SERVER/shimin-backend:v2

# Disparar sync manualmente
curl -X POST "https://apphhshimin.azurewebsites.net/api/sync/new?limit=20"
```

---

## Checklist final

- [ ] `deploy/env.sh` con variables reales
- [ ] `az login` y subscription correcta
- [ ] File Share `shimin-data` creado en `apphhdrive`
- [ ] Data inicial subida con `azcopy` (database/, storage/llm_wiki/, manifests)
- [ ] Imagen `shimin-backend:v1` en `apphshimin` registry
- [ ] App Service `apphhshimin` apuntando a la nueva imagen (Streamlit dejó de funcionar)
- [ ] App Settings con todas las variables del `.env`
- [ ] Mounts de Azure Files configurados
- [ ] `GET /api/config/status` desde la URL pública responde 200
- [ ] Static Web App `shimin-frontend` creado y linkeado al App Service
- [ ] SSO Entra ID restringe a `@shimin.cl`
- [ ] GitHub Actions cron configurado
- [ ] Test end-to-end: login → chat → respuesta → descargar PDF
- [ ] Streamlit viejo confirmado deprecado (opcional: blob/files limpiados)
