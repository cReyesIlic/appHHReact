# Plan de deploy a Azure — SHIMIN Proposal Intelligence

## Objetivos

- Subir backend + frontend a Azure con **costo mensual mínimo** (~$15–40 USD/mes para uso interno SHIMIN).
- Persistir: SQLite (`database/`), wiki/proposals (`storage/llm_wiki/`), exports (`exports/`), commercial_offers (`storage/commercial_offers_latest/`).
- **Sincronización automática** diaria: detectar nuevas propuestas en SharePoint → indexar RAG + compilar Wiki + refrescar Master.
- Mantener Azure OpenAI ya configurado (sin cambios).

---

## Arquitectura recomendada (lowest-cost serverless)

```
┌─────────────────────────────────────────────────────────────┐
│                    SHIMIN Tenant Azure                       │
│                                                              │
│  ┌──────────────────┐         ┌─────────────────────────┐   │
│  │ Azure Static     │ ───────►│ Azure Container Apps    │   │
│  │ Web App (free)   │  /api/* │ "shimin-backend"        │   │
│  │ Frontend Vite    │         │  scale 0→3              │   │
│  │ build estático   │         │  Python 3.12            │   │
│  └──────────────────┘         └────────┬────────────────┘   │
│         ▲                              │                     │
│         │                              │ mount               │
│         │ entra.id auth                ▼                     │
│  ┌──────┴───────┐         ┌─────────────────────────────┐   │
│  │ Microsoft    │         │ Azure Files (premium SMB)   │   │
│  │ Entra ID     │         │ /data/database/             │   │
│  │ (SSO SHIMIN) │         │ /data/storage/              │   │
│  └──────────────┘         │ /data/exports/              │   │
│                            └─────────────────────────────┘   │
│                                       ▲                      │
│                                       │ lectura/escritura    │
│                            ┌──────────┴─────────────────┐   │
│                            │ Container Apps Job (cron)  │   │
│                            │ daily 02:00 — sync_new     │   │
│                            └────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────┐                                    │
│  │ Azure OpenAI (ya OK) │  ← consume desde backend          │
│  └──────────────────────┘                                    │
│                                                              │
│  ┌──────────────────────┐                                    │
│  │ SharePoint Online    │  ← Graph API (ya OK)              │
│  │ (Ofertas / Proyectos)│                                    │
│  └──────────────────────┘                                    │
│                                                              │
│  ┌──────────────────────┐                                    │
│  │ Container Registry   │  ← imágenes shimin-backend        │
│  │ (basic tier)         │                                    │
│  └──────────────────────┘                                    │
└─────────────────────────────────────────────────────────────┘
```

## Recursos y costos mensuales (estimado uso interno bajo)

| Recurso | SKU | Costo (USD/mes) | Por qué |
|---|---|---|---|
| **Azure Static Web App** | Free | **$0** | Hosting frontend Vite. 100 GB ancho banda, dominio custom y SSL incluidos. |
| **Azure Container Apps** | Consumption, scale 0→3 | **$0–10** | Backend FastAPI. Escala a 0 réplicas cuando nadie consulta. Solo paga vCPU-s + GB-s realmente usados. |
| **Azure Container Apps Job** | Consumption | **$0–1** | Cron diario `sync_sharepoint.py sync-new`. Corre ~5 min/día. |
| **Azure Files** | Premium SMB 100 GB | **$15** | Mount para SQLite + storage + exports. Premium para baja latencia con SQLite (estándar funciona pero más lento). |
| **Azure Container Registry** | Basic | **$5** | Imágenes Docker. 10 GB almacenamiento. Privado. |
| **Azure OpenAI** | Pay-as-you-go (ya existe) | _ya facturado_ | Sin cambios. gpt-4o-mini ~$0.15 input / $0.60 output por 1M tokens. Costo dependiente de uso. |
| **Microsoft Entra ID** | Built-in | **$0** | SSO con cuenta corporativa SHIMIN. |
| **Application Insights** (opcional) | 5 GB/mes free tier | **$0** | Logs y métricas. |
| **Total infraestructura** | | **~$20–30 USD/mes** | + costo Azure OpenAI variable. |

> Comparación: AKS empezaría en $70+/mes (control plane + node pool); App Service B1 $13/mes pero no escala a cero. Container Apps es la opción más barata para uso intermitente interno.

## Pre-requisitos

- Suscripción Azure activa con permiso de crear Resource Group.
- Azure CLI instalado (`az --version` ≥ 2.50).
- Docker Desktop local (ya lo tienes).
- Repositorio Git en GitHub o Azure Repos.
- Tenant Entra ID con cuentas SHIMIN.

## Paso 1 — Crear infraestructura (script `infra/setup.sh`)

```bash
RG="shimin-rg"
LOC="eastus2"
ACR_NAME="shiminregistry"
ENV_NAME="shimin-env"
STORAGE="shiminstorage"
SHARE_NAME="shimin-data"

az group create -n $RG -l $LOC

# Container Registry
az acr create -n $ACR_NAME -g $RG --sku Basic --admin-enabled true

# Storage Account + File Share (Azure Files)
az storage account create -n $STORAGE -g $RG -l $LOC --sku Premium_LRS --kind FileStorage
az storage share-rm create --resource-group $RG --storage-account $STORAGE --name $SHARE_NAME --quota 100

# Container Apps Environment
az containerapp env create -n $ENV_NAME -g $RG -l $LOC

# Mount Azure Files al environment
STORAGE_KEY=$(az storage account keys list -g $RG -n $STORAGE --query "[0].value" -o tsv)
az containerapp env storage set -n $ENV_NAME -g $RG \
  --storage-name shimin-data \
  --azure-file-account-name $STORAGE \
  --azure-file-account-key "$STORAGE_KEY" \
  --azure-file-share-name $SHARE_NAME \
  --access-mode ReadWrite
```

## Paso 2 — Migrar storage local a Azure Files (one-shot)

```bash
# Desde tu máquina local, copia la data inicial usando AzCopy:
# - database/proyectos 9.db
# - storage/llm_wiki/  (1500+ páginas wiki + entries)
# - storage/commercial_offers_latest/  (PDFs descargados)
# - storage/hybrid_rag_embeddings/  (embeddings cache si aplica)

azcopy login
azcopy copy "C:/.../app_principal/database" \
  "https://$STORAGE.file.core.windows.net/$SHARE_NAME/database?<SAS>" \
  --recursive
azcopy copy "C:/.../app_principal/storage/llm_wiki" \
  "https://$STORAGE.file.core.windows.net/$SHARE_NAME/storage/llm_wiki?<SAS>" \
  --recursive
# … etc para storage/commercial_offers_latest, storage/hh_excel_ingestion, etc
```

## Paso 3 — Build + push imagen backend

```bash
az acr build -r $ACR_NAME -t shimin-backend:v1 ./backend
```

(El frontend se publica en Static Web App vía GitHub Actions, ver paso 5.)

## Paso 4 — Deploy backend Container App

```bash
ACR_LOGIN_SERVER=$(az acr show -n $ACR_NAME --query loginServer -o tsv)
ACR_PASSWORD=$(az acr credential show -n $ACR_NAME --query "passwords[0].value" -o tsv)

az containerapp create \
  -n shimin-backend \
  -g $RG \
  --environment $ENV_NAME \
  --image $ACR_LOGIN_SERVER/shimin-backend:v1 \
  --registry-server $ACR_LOGIN_SERVER \
  --registry-username $ACR_NAME \
  --registry-password "$ACR_PASSWORD" \
  --target-port 8010 \
  --ingress external \
  --cpu 1.0 --memory 2.0Gi \
  --min-replicas 0 \
  --max-replicas 3 \
  --env-vars \
    AZURE_OPENAI_ENDPOINT=secretref:azure-openai-endpoint \
    AZURE_OPENAI_KEY=secretref:azure-openai-key \
    AZURE_OPENAI_DEPLOYMENT=gpt-5.4 \
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small \
    AZURE_OPENAI_API_VERSION=2024-12-01-preview \
    SHAREPOINT_TENANT_ID=secretref:sp-tenant \
    SHAREPOINT_CLIENT_ID=secretref:sp-client \
    SHAREPOINT_CLIENT_SECRET=secretref:sp-secret \
    DATABASE_DIR="database/proyectos 9.db" \
  --secrets \
    azure-openai-endpoint=$AZURE_OPENAI_ENDPOINT \
    azure-openai-key=$AZURE_OPENAI_KEY \
    sp-tenant=$SP_TENANT \
    sp-client=$SP_CLIENT \
    sp-secret=$SP_SECRET

# Mount el volume al container
az containerapp update \
  -n shimin-backend -g $RG \
  --set-env-vars EXPORT_DIR=/app/exports \
  --yaml mount-azfiles.yaml
```

`mount-azfiles.yaml`:
```yaml
properties:
  template:
    volumes:
      - name: data
        storageType: AzureFile
        storageName: shimin-data
    containers:
      - name: shimin-backend
        volumeMounts:
          - volumeName: data
            mountPath: /srv/app_principal
```

## Paso 5 — Frontend en Static Web App

Crear `staticwebapp.config.json` en frontend/:
```json
{
  "navigationFallback": { "rewrite": "/index.html" },
  "routes": [
    { "route": "/api/*", "rewrite": "https://shimin-backend.<env-fqdn>.azurecontainerapps.io/api/*" }
  ],
  "auth": {
    "identityProviders": {
      "azureActiveDirectory": {
        "registration": { "openIdIssuer": "https://login.microsoftonline.com/<TENANT>/v2.0", "clientIdSettingName": "AAD_CLIENT_ID" }
      }
    }
  }
}
```

GitHub Action (`.github/workflows/azure-static-web-apps.yml`) que Azure crea automáticamente al hacer:
```bash
az staticwebapp create -n shimin-front -g $RG -l $LOC \
  --source https://github.com/<usuario>/proyectohh_app \
  --branch main \
  --app-location frontend \
  --output-location dist \
  --login-with-github
```

## Paso 6 — Cron diario de sincronización (Container Apps Job)

```bash
az containerapp job create \
  -n shimin-sync \
  -g $RG \
  --environment $ENV_NAME \
  --trigger-type Schedule \
  --cron-expression "0 5 * * *" \
  --image $ACR_LOGIN_SERVER/shimin-backend:v1 \
  --cpu 0.5 --memory 1.0Gi \
  --replica-timeout 1800 \
  --command "python" \
  --args "scripts/sync_sharepoint.py" "sync-new" "--limit" "50" \
  --env-vars (mismas secret refs que backend)
```

Cron `0 5 * * *` = 05:00 UTC = 02:00 hora Chile. Procesa cualquier nueva propuesta detectada en SharePoint, la indexa en RAG, embebe y compila la página wiki.

Para refrescar Master Excel también:
```bash
az containerapp job create -n shimin-master-refresh -g $RG \
  --environment $ENV_NAME --trigger-type Schedule \
  --cron-expression "0 4 * * *" \
  --image $ACR_LOGIN_SERVER/shimin-backend:v1 \
  --command "python" --args "-c" "from app.services.master_repository import MasterRepository; print(MasterRepository().refresh_from_excel())"
```

## Paso 7 — Autenticación SSO con Entra ID

Static Web App ya provee Microsoft Entra integration vía `staticwebapp.config.json`. Solo usuarios `@shimin.cl` autorizados pueden acceder.

Backend recibe el header `x-ms-client-principal-name` que `user_from_request()` ya consume (ver `backend/app/services/user_context.py:30`). Las sesiones de chat quedan automáticamente por usuario.

Restringir tenant en config:
```json
"auth": {
  "identityProviders": {
    "azureActiveDirectory": {
      "userDetailsClaim": "preferred_username",
      "registration": {
        "openIdIssuer": "https://login.microsoftonline.com/<TENANT-ID-SHIMIN>/v2.0",
        "clientIdSettingName": "AAD_CLIENT_ID"
      }
    }
  },
  "routes": [
    { "route": "/api/*", "allowedRoles": ["authenticated"] },
    { "route": "/*", "allowedRoles": ["authenticated"] }
  ]
}
```

## Paso 8 — Observabilidad (opcional)

```bash
az monitor app-insights component create -a shimin-insights -g $RG -l $LOC
# Inyectar la connection string en backend env vars
az containerapp update -n shimin-backend -g $RG --set-env-vars \
  APPLICATIONINSIGHTS_CONNECTION_STRING=secretref:appinsights-cs
```

Logs estructurados, métricas de latencia, errors. 5 GB/mes incluidos en free tier.

## Costos en pico (escenarios)

| Escenario | Container Apps | OpenAI | Total/mes |
|---|---|---|---|
| **Idle weekend** (sin uso) | $0 (scale-to-zero) | $0 | $20 (infra base) |
| **Equipo SHIMIN, 100 queries/día** | ~$3 | ~$1 | ~$24 |
| **Backfill semestral 1000 nuevas propuestas** | ~$5 (jobs) | ~$1.50 (one-shot) | ~$27 ese mes |
| **Pico equipo: 1000 queries/día** | ~$10–20 | ~$10 | ~$50 |

## Roadmap incremental

1. **MVP** (semana 1): Container Apps + Azure Files + frontend en Static Web App, mismo SQLite que tienes.
2. **Auth Entra** (semana 2): SSO, restricción `@shimin.cl`, sesiones por usuario ya implementadas.
3. **Cron sync** (semana 3): Container Apps Job diario. Notifica por email/Teams cuando hay nuevas.
4. **App Insights** (semana 4): Métricas + alertas si Azure OpenAI tira 429 o si el sync falla.
5. **Migrar a PostgreSQL** (opcional, mes 2): si SQLite empieza a sufrir contention con varios usuarios concurrentes. Azure Database for PostgreSQL Flexible Server B1ms (~$13/mes) reemplaza SQLite sin tocar el ORM (es solo cambiar `sqlite3.connect` por `psycopg`).

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| SQLite en Azure Files lento con concurrencia | WAL ya activado. Si >5 usuarios concurrentes, migrar a PostgreSQL. |
| Tokens Azure OpenAI explotan | Configurar quota mensual en Azure OpenAI Studio. App ya cuenta créditos por usuario (`CreditService`). |
| Storage 100 GB se queda corto | Azure Files escala a 5 TB sin downtime. Monitorear via `az storage share stats`. |
| SharePoint cambia formato carpetas | El sync job tira error visible en App Insights — alerta por email. |
| Costos suben sin avisar | Budget alert en Azure Cost Management: $30/mes con notificación. |

## Pre-deploy checklist

- [ ] `.env` con secrets reales subidos a Azure Container App secrets (NUNCA al repositorio)
- [ ] SQLite local copiado a Azure Files via `azcopy`
- [ ] `storage/llm_wiki/` copiado (1508 archivos, ~50 MB)
- [ ] `storage/commercial_offers_latest/` copiado solo lo que se necesita (no todo, es grande)
- [ ] Static Web App linked al repo GitHub
- [ ] Backend health check pasa: `GET /api/config/status` 200
- [ ] Frontend abre y login Entra funciona
- [ ] Test de chat E2E desde URL Azure
- [ ] Cron job tested manualmente con `az containerapp job start -n shimin-sync`
- [ ] Budget alert configurado

## Comandos útiles post-deploy

```bash
# Ver logs en vivo
az containerapp logs show -n shimin-backend -g $RG --follow

# Forzar ejecución del sync job manualmente
az containerapp job start -n shimin-sync -g $RG

# Escalar manualmente (debug)
az containerapp update -n shimin-backend -g $RG --min-replicas 1

# Actualizar imagen tras nuevo build
az acr build -r $ACR_NAME -t shimin-backend:v2 ./backend
az containerapp update -n shimin-backend -g $RG --image $ACR_LOGIN_SERVER/shimin-backend:v2
```
