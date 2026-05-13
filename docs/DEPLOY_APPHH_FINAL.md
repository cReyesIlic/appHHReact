# Deploy SHIMIN sobre `apphh` — paso a paso ejecutable

> **Estado**: `apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net` ya existe. App Registration Entra ID `0104b363-efc0-488d-af2e-2cb652dd82e9` ya configurado en tenant `e6912f7f-971b-4479-8cc7-cf5cfe63913c`. Aprovechamos todo.

## Mapa de pasos

```
0. Git: inicializar repo + push a GitHub        ← prerequisito
1. Audit Azure (qué hay hoy)
2. Upgrade plan ASP-appshimin a B2
3. File Share + subir SQLite + storage/llm_wiki/
4. Build imagen backend + apuntar apphhshimin
5. Configurar App Service (mounts, env vars, always-on, health check)
6. FRONTEND → Static Web App + GitHub Actions (auto-deploy)
7. OAuth Entra ID en Static Web App (reusa App Registration)
8. Endurecer backend (rechazar acceso directo)
9. Secrets a Key Vault
10. Cron diario (GitHub Actions, gratis)
11. Verificación end-to-end
```

---

## ⚠️ Antes de empezar — seguridad

Tu `.env` tiene secrets sensibles en texto claro. **Rota estos** si compartes el repo:
- `SECRET_OPENAIKEY` (sk-proj-...)
- `AZURE_CONNECTION_STRING` (storage key de `apphhdrive`)
- `CLIENT_SECRET` SharePoint
- `cookie_secret`

Asegurar `.gitignore`:
```bash
cd "C:/Users/CristianReyes/OneDrive - SHIMIN/Documentos/GitHub/proyectohh_app/app_principal"
grep -qx ".env" .gitignore || echo ".env" >> .gitignore
grep -qx "deploy/env.sh" .gitignore || echo "deploy/env.sh" >> .gitignore
grep -qx "database/*.db" .gitignore || echo "database/*.db" >> .gitignore
grep -qx "database/*.db.backup-*" .gitignore || echo "database/*.db.backup-*" >> .gitignore
grep -qx "storage/" .gitignore || echo "storage/" >> .gitignore
grep -qx "exports/" .gitignore || echo "exports/" >> .gitignore
```

---

## Paso 0 — Inicializar repo Git + push a GitHub

**Por qué**: Static Web App se conecta a GitHub para auto-deploy del frontend en cada commit.

```bash
cd "C:/Users/CristianReyes/OneDrive - SHIMIN/Documentos/GitHub/proyectohh_app/app_principal"

# Init local
git init -b main
git add .
git status     # revisar que NO está commiteando .env, .venv, node_modules, database/*.db
git commit -m "feat: agente SHIMIN con tool calling, sesiones, wiki librería y deploy Azure"

# Crear repo remoto (privado, recomendado) y conectar
gh repo create proyectohh-app-shimin --private --source=. --remote=origin --push
# o manualmente: gh auth login → crear en https://github.com/new → luego:
# git remote add origin https://github.com/<usuario>/proyectohh-app-shimin.git
# git push -u origin main
```

Si no tenes `gh` CLI: https://cli.github.com/ o instala con `winget install GitHub.cli`.

---

## Paso 1 — Audit Azure (sin tocar nada)

Crear `deploy/env.sh` (no commitear):

```bash
export SUBSCRIPTION_ID=""           # az account show --query id -o tsv
export RG=""                        # az resource list --name apphhshimin --query "[0].resourceGroup" -o tsv
export REGION="chilecentral"
export ACR_NAME="apphshimin"
export STORAGE_ACCOUNT="apphhdrive"
export APP_SERVICE="apphhshimin"
export APP_PLAN="ASP-appshimin"
export AOAI_NAME="testapphhopenai"
export TENANT_ID="e6912f7f-971b-4479-8cc7-cf5cfe63913c"
export AAD_CLIENT_ID="0104b363-efc0-488d-af2e-2cb652dd82e9"
export STATIC_WEB_APP="shimin-frontend"
export STATIC_WEB_REGION="eastus2"
export IMAGE_TAG="v1"
export SHARE_NAME="shimin-data"
export GITHUB_REPO="https://github.com/<usuario>/proyectohh-app-shimin"
export PROJECT_ROOT="C:/Users/CristianReyes/OneDrive - SHIMIN/Documentos/GitHub/proyectohh_app/app_principal"
```

Ejecutar audit:
```bash
source deploy/env.sh
az login
az account set --subscription "$SUBSCRIPTION_ID"

# Si no sabes el RG, descúbrelo:
az resource list --name apphhshimin --query "[0].resourceGroup" -o tsv

# Plan
az appservice plan show -n $APP_PLAN -g $RG --query "{sku:sku.name, status:status, workers:numberOfWorkers}"

# App Service actual
az webapp show -n $APP_SERVICE -g $RG --query "{state:state, host:defaultHostName, runtime:siteConfig.linuxFxVersion, alwaysOn:siteConfig.alwaysOn}"

# Container actual
az webapp config container show -n $APP_SERVICE -g $RG

# Storage
az storage share list --account-name $STORAGE_ACCOUNT -o table
az storage container list --account-name $STORAGE_ACCOUNT -o table

# Registry
az acr repository list -n $ACR_NAME -o table

# Otras webapps en el mismo plan
az webapp list --query "[?contains(serverFarmId, '$APP_PLAN')].{name:name, state:state}" -o table

# OpenAI deployments
az cognitiveservices account deployment list -n $AOAI_NAME -g $RG --query "[].{name:name, model:properties.model.name}" -o table
```

Anota la salida. Si el plan está en SKU `B1` o menos, paso 2 es necesario.

---

## Paso 2 — Upgrade plan a B2

```bash
az appservice plan update -n $APP_PLAN -g $RG --sku B2
# verificar
az appservice plan show -n $APP_PLAN -g $RG --query sku
```

Costo: +$13/mes vs B1. Sin downtime.

---

## Paso 3 — File Share + subir SQLite + storage/

```bash
# Crear File Share
az storage share-rm create -g $RG --storage-account $STORAGE_ACCOUNT \
  --name $SHARE_NAME --quota 50 --access-tier TransactionOptimized

# Subir data inicial con azcopy (instala: winget install Microsoft.AzCopy o descarga azcopy)
STORAGE_KEY=$(az storage account keys list -g $RG -n $STORAGE_ACCOUNT --query "[0].value" -o tsv)
SAS=$(az storage share generate-sas \
  --account-name $STORAGE_ACCOUNT --account-key "$STORAGE_KEY" \
  --name $SHARE_NAME --permissions rwdl --expiry 2027-01-01 -o tsv)
DEST="https://$STORAGE_ACCOUNT.file.core.windows.net/$SHARE_NAME?$SAS"

azcopy copy "$PROJECT_ROOT/database/proyectos 9.db" "$DEST/database/" --overwrite=ifSourceNewer
azcopy copy "$PROJECT_ROOT/storage/llm_wiki" "$DEST/storage/" --recursive --overwrite=ifSourceNewer
azcopy copy "$PROJECT_ROOT/storage/sync_manifest.csv" "$DEST/storage/" 2>/dev/null || true
```

---

## Paso 4 — Build imagen + apuntar el App Service

```bash
# Build remoto en ACR (no necesita Docker local)
az acr build -r $ACR_NAME -t shimin-backend:$IMAGE_TAG ./backend

# Verificar
az acr repository show-tags -n $ACR_NAME --repository shimin-backend -o table

# Apuntar App Service a la nueva imagen
az acr update -n $ACR_NAME --admin-enabled true
ACR_PASSWORD=$(az acr credential show -n $ACR_NAME --query "passwords[0].value" -o tsv)
ACR_LOGIN_SERVER=$(az acr show -n $ACR_NAME --query loginServer -o tsv)

az webapp config container set \
  -n $APP_SERVICE -g $RG \
  --docker-custom-image-name "$ACR_LOGIN_SERVER/shimin-backend:$IMAGE_TAG" \
  --docker-registry-server-url "https://$ACR_LOGIN_SERVER" \
  --docker-registry-server-user $ACR_NAME \
  --docker-registry-server-password "$ACR_PASSWORD"
```

---

## Paso 5 — Configurar App Service (mounts, settings, always-on)

```bash
# Puerto
az webapp config appsettings set -n $APP_SERVICE -g $RG --settings WEBSITES_PORT=8010

# Always On (sin cold starts)
az webapp config set -n $APP_SERVICE -g $RG --always-on true

# Health check
az webapp config set -n $APP_SERVICE -g $RG \
  --generic-configurations '{"healthCheckPath": "/api/config/status"}'

# HTTPS only + HTTP/2
az webapp update -n $APP_SERVICE -g $RG --https-only true
az webapp config set -n $APP_SERVICE -g $RG --http20-enabled true

# Mount File Share (database + storage)
STORAGE_KEY=$(az storage account keys list -g $RG -n $STORAGE_ACCOUNT --query "[0].value" -o tsv)
az webapp config storage-account add -n $APP_SERVICE -g $RG \
  --custom-id shimin-data --storage-type AzureFiles \
  --account-name $STORAGE_ACCOUNT --share-name $SHARE_NAME --access-key "$STORAGE_KEY" \
  --mount-path "/srv/app_principal/database"
az webapp config storage-account add -n $APP_SERVICE -g $RG \
  --custom-id shimin-storage --storage-type AzureFiles \
  --account-name $STORAGE_ACCOUNT --share-name $SHARE_NAME --access-key "$STORAGE_KEY" \
  --mount-path "/srv/app_principal/storage"

# Subir todo el .env como App Settings (auto)
while IFS='=' read -r key value; do
  [[ -z "$key" || "$key" =~ ^# ]] && continue
  value="${value%\"}"; value="${value#\"}"
  value="${value%\'}"; value="${value#\'}"
  az webapp config appsettings set -n $APP_SERVICE -g $RG --settings "${key}=${value}" -o none
done < "$PROJECT_ROOT/.env"

# Restart
az webapp restart -n $APP_SERVICE -g $RG

# Verificar (esperar ~30 s)
sleep 30
curl -s https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net/api/config/status | head -c 400
curl -s https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net/api/sync/status
```

**Espera ver**: JSON con `{"rag_proposals": 1508, ...}`. Si ves 500, ver logs: `az webapp log tail -n $APP_SERVICE -g $RG`.

---

## Paso 6 — FRONTEND con Static Web App

### Opción A — Con GitHub Actions (auto-deploy en cada push) ⭐ RECOMENDADO

**Requiere**: repo en GitHub (paso 0 ya lo hizo).

```bash
# Crear SWA conectado al repo
az staticwebapp create -n $STATIC_WEB_APP -g $RG -l $STATIC_WEB_REGION \
  --source "$GITHUB_REPO" \
  --branch main \
  --app-location "frontend" \
  --output-location "dist" \
  --login-with-github
```

Esto hace **automáticamente**:
1. Crea el recurso Static Web App (SKU Free, $0/mes).
2. Pide auth en GitHub (browser se abre).
3. Crea un archivo `.github/workflows/azure-static-web-apps-<random>.yml` en TU repo con el workflow de build/deploy.
4. Hace `git pull` localmente (o hace falta `git pull` manual después).
5. Trigger del primer build: tarda ~3-5 min.

Ver el progreso del build: en GitHub → tu repo → tab "Actions".

```bash
# URL del frontend (espera 5 min después del primer push)
SWA_URL=$(az staticwebapp show -n $STATIC_WEB_APP -g $RG --query defaultHostname -o tsv)
echo "Frontend: https://$SWA_URL"
```

**Linkear con el backend** para que `/api/*` haga proxy:
```bash
BACKEND_ID=$(az webapp show -n $APP_SERVICE -g $RG --query id -o tsv)
az staticwebapp backends link -n $STATIC_WEB_APP -g $RG \
  --backend-resource-id "$BACKEND_ID" --backend-region $REGION
```

### Opción B — Sin GitHub, deploy manual con SWA CLI

```bash
# Build local
cd frontend
npm install
npm run build      # genera dist/

# Crear SWA sin source
az staticwebapp create -n $STATIC_WEB_APP -g $RG -l $STATIC_WEB_REGION --sku Free

# Obtener deployment token
SWA_TOKEN=$(az staticwebapp secrets list -n $STATIC_WEB_APP -g $RG --query "properties.apiKey" -o tsv)

# Deploy con swa cli (npm install -g @azure/static-web-apps-cli)
npx @azure/static-web-apps-cli deploy ./dist \
  --deployment-token "$SWA_TOKEN" \
  --env production

# Linkear backend
BACKEND_ID=$(az webapp show -n $APP_SERVICE -g $RG --query id -o tsv)
az staticwebapp backends link -n $STATIC_WEB_APP -g $RG \
  --backend-resource-id "$BACKEND_ID" --backend-region $REGION
```

Cada update del frontend: `npm run build && npx @azure/static-web-apps-cli deploy ./dist --deployment-token "$SWA_TOKEN"`.

---

## Paso 7 — OAuth con Entra ID

### 7.1 — `staticwebapp.config.json` (YA está en el repo)

Archivo `frontend/staticwebapp.config.json` ya creado con:
- Provider Microsoft Entra ID configurado con tu tenant `e6912f7f-...`
- Rutas `/api/*` y `/*` requieren autenticación
- Redirect a Microsoft login si no autenticado
- Logout en `/logout`
- `domain_hint=shimin.cl` para sugerir cuenta corporativa

### 7.2 — Setear el client ID en SWA

```bash
az staticwebapp appsettings set -n $STATIC_WEB_APP -g $RG \
  --setting-names "AAD_CLIENT_ID=$AAD_CLIENT_ID"
```

### 7.3 — Agregar redirect URI en el App Registration

En **Azure Portal → Microsoft Entra ID → App registrations → buscar `0104b363-efc0-488d-af2e-2cb652dd82e9`**:

1. **Authentication** → Platform configurations → Web → Add URI:
   ```
   https://<SWA_URL>/.auth/login/aad/callback
   ```
   (reemplazar `<SWA_URL>` por el `defaultHostname` del paso 6)
2. Mantener el redirect existente (`...azurewebsites.net/oauth2callback`) — lo usa SharePoint.
3. **API permissions** → Add:
   - Microsoft Graph → Delegated → `openid`, `profile`, `email`, `User.Read`
4. **Token configuration** → Add optional claim → ID token → marcar `email` y `preferred_username`.
5. Grant admin consent (si tienes permisos).

### 7.4 — Restringir a tenant SHIMIN

Por defecto, cualquier cuenta Microsoft puede entrar. Para restringir a `@shimin.cl`:
- En App Registration → Authentication → Supported account types → **Accounts in this organizational directory only** (`SHIMIN Ingeniería only`).

### 7.5 — Test del flujo

```bash
SWA_URL=$(az staticwebapp show -n $STATIC_WEB_APP -g $RG --query defaultHostname -o tsv)
echo "Abrir en browser: https://$SWA_URL"
```

Deberías ver:
1. Redirect a Microsoft Login → ingresar `tu.email@shimin.cl`.
2. Tras login, sale el frontend SHIMIN.
3. En el chat, cada respuesta debería persistir en tu sesión.
4. Click logout: `https://<SWA_URL>/logout`.

---

## Paso 8 — Endurecer backend

**Problema**: `apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net` es público sin auth. Para que solo SWA pueda llamarlo:

```bash
# IPs salientes de SWA (allowlist)
SWA_IPS=$(az staticwebapp show -n $STATIC_WEB_APP -g $RG --query "outboundIpAddresses" -o tsv)
echo "IPs SWA: $SWA_IPS"

# Permitir solo SWA + tu IP de dev (opcional)
MY_IP=$(curl -s ifconfig.me)
az webapp config access-restriction add -n $APP_SERVICE -g $RG \
  --rule-name "swa-allow" --action Allow --ip-address "$SWA_IPS" --priority 100
az webapp config access-restriction add -n $APP_SERVICE -g $RG \
  --rule-name "dev-allow" --action Allow --ip-address "$MY_IP/32" --priority 200
# Implicit deny-all queda al final (regla default)
```

**Defensa en profundidad**: middleware FastAPI ya recibe `x-ms-client-principal-name`. Para bloquear requests que no lo traen, ver `docs/MIGRATION_RATIONALE.md` paso 7.B.

---

## Paso 9 — Secrets a Key Vault

```bash
KV="shimin-kv"
az keyvault create -n $KV -g $RG -l $REGION

# Subir los más sensibles
az keyvault secret set --vault-name $KV --name OpenAIKey --value "$AZURE_OPENAI_API_KEY"
az keyvault secret set --vault-name $KV --name SharePointSecret --value "$CLIENT_SECRET"
az keyvault secret set --vault-name $KV --name StorageKey --value "$STORAGE_KEY"

# Managed identity al App Service
az webapp identity assign -n $APP_SERVICE -g $RG
PRINCIPAL_ID=$(az webapp identity show -n $APP_SERVICE -g $RG --query principalId -o tsv)
az keyvault set-policy -n $KV --object-id $PRINCIPAL_ID --secret-permissions get list

# Reemplazar app settings con referencias
KV_URI=$(az keyvault show -n $KV -g $RG --query "properties.vaultUri" -o tsv)
az webapp config appsettings set -n $APP_SERVICE -g $RG --settings \
  "AZURE_OPENAI_API_KEY=@Microsoft.KeyVault(SecretUri=${KV_URI}secrets/OpenAIKey/)" \
  "CLIENT_SECRET=@Microsoft.KeyVault(SecretUri=${KV_URI}secrets/SharePointSecret/)" \
  "STORAGE_KEY=@Microsoft.KeyVault(SecretUri=${KV_URI}secrets/StorageKey/)"

az webapp restart -n $APP_SERVICE -g $RG
```

---

## Paso 10 — Cron diario (GitHub Actions, gratis)

Archivo `.github/workflows/sync-daily.yml` ya en el repo. Después del push a GitHub corre automáticamente.

**Si endureciste el backend (paso 8)**, agregar las IPs de GitHub Actions a la allowlist o usar OIDC token. Alternativa más simple: dejar el path `/api/sync/*` abierto a internet pero requerir un header secreto:

```bash
SYNC_TOKEN=$(openssl rand -base64 32)
az webapp config appsettings set -n $APP_SERVICE -g $RG --settings "SYNC_TOKEN=$SYNC_TOKEN"
gh secret set SYNC_TOKEN -b "$SYNC_TOKEN"  # en el repo
```

Editar `.github/workflows/sync-daily.yml` para mandar `-H "x-sync-token: ${{ secrets.SYNC_TOKEN }}"` y validar en backend.

---

## Paso 11 — Verificación end-to-end

```bash
SWA_URL=$(az staticwebapp show -n $STATIC_WEB_APP -g $RG --query defaultHostname -o tsv)
APP_URL=$(az webapp show -n $APP_SERVICE -g $RG --query defaultHostName -o tsv)

# Backend status (debería responder, requiere bypass de access restriction si lo activaste)
curl -s "https://$APP_URL/api/config/status" | head -c 300
curl -s "https://$APP_URL/api/sync/status"

# Frontend (abrir en browser)
echo "Abre: https://$SWA_URL"
```

**Test E2E** (en browser):
1. Ir a `https://$SWA_URL` → debería redirigir a Microsoft login
2. Ingresar credencial `@shimin.cl` → entrar al frontend
3. Crear una nueva conversación → escribir *"Cuántas propuestas ganadas tiene VALE?"*
4. Verificar que aparece la respuesta del agente con tabla
5. Click en botones de export → descargar PDF / Word / Excel
6. Crear otra conversación → verificar que las dos quedan en el sidebar
7. Logout → `/logout` → vuelve a Microsoft login

---

## Costos finales

| Componente | Mensual |
|---|---|
| App Service Plan B2 | **$26** |
| Container Registry Basic (ya pagado) | $0 incremental |
| Storage Account (File Share 5 GB) | **$2** |
| Static Web App | **$0** (Free tier) |
| Key Vault | **$0** (10K ops/mes free) |
| Application Insights | **$0** (5 GB/mes free) |
| Azure OpenAI (uso) | ~$2–10 variable |
| **Total** | **~$30–38 USD/mes** |

---

## Comandos de operación diaria

```bash
# Ver logs en vivo
az webapp log tail -n $APP_SERVICE -g $RG

# Reiniciar backend
az webapp restart -n $APP_SERVICE -g $RG

# Publicar nueva versión backend
git push  # si usas GitHub Actions
# o manual:
az acr build -r $ACR_NAME -t shimin-backend:v2 ./backend
az webapp config container set -n $APP_SERVICE -g $RG \
  --docker-custom-image-name "$ACR_LOGIN_SERVER/shimin-backend:v2"

# Publicar nueva versión frontend
git push  # SWA auto-rebuilds
# o manual (opción B):
cd frontend && npm run build && npx swa deploy ./dist --deployment-token "$SWA_TOKEN"

# Forzar sync manual
curl -X POST "https://$APP_URL/api/sync/new?limit=20" -H "x-user-email: cri.reyes@shimin.cl"

# Ver costos del mes
az consumption usage list --start-date "2026-05-01" --end-date "2026-05-31" --query "[?contains(instanceName, 'apphh')]" -o table
```

---

## Checklist final

- [ ] **Paso 0**: Repo en GitHub (privado), `.gitignore` cubre secrets
- [ ] **Paso 1**: Audit ejecutado, plan está en B1 (target B2)
- [ ] **Paso 2**: Plan upgraded a B2
- [ ] **Paso 3**: File Share creado, SQLite + storage subidos
- [ ] **Paso 4**: Imagen `shimin-backend:v1` en ACR, App Service apunta a ella
- [ ] **Paso 5**: Mounts, settings, always-on, health check activos. `GET /api/config/status` → 200
- [ ] **Paso 6**: Static Web App creado, build pasó, linkeado con backend
- [ ] **Paso 7**: Redirect URI agregado en App Registration, login Microsoft funciona
- [ ] **Paso 8**: Backend solo acepta requests de SWA (access restriction)
- [ ] **Paso 9**: Secrets en Key Vault
- [ ] **Paso 10**: GitHub Actions cron diario configurado y testeado manualmente
- [ ] **Paso 11**: E2E test pasa (login, chat, sesión, export)
- [ ] Budget alert configurado en Azure Cost Management
