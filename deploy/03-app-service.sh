#!/usr/bin/env bash
# Paso 3: configurar apphhshimin para usar la nueva imagen + mounts + env vars.

set -euo pipefail
source "$(dirname "$0")/env.sh"

ACR_LOGIN_SERVER=$(az acr show -n "$ACR_NAME" --query loginServer -o tsv)
ACR_PASSWORD=$(az acr credential show -n "$ACR_NAME" --query "passwords[0].value" -o tsv)
STORAGE_KEY=$(az storage account keys list -g "$RG" -n "$STORAGE_ACCOUNT" --query "[0].value" -o tsv)

echo "🐳 Apuntando $APP_SERVICE a $ACR_LOGIN_SERVER/shimin-backend:$IMAGE_TAG …"
az webapp config container set \
  -n "$APP_SERVICE" -g "$RG" \
  --docker-custom-image-name "$ACR_LOGIN_SERVER/shimin-backend:$IMAGE_TAG" \
  --docker-registry-server-url "https://$ACR_LOGIN_SERVER" \
  --docker-registry-server-user "$ACR_NAME" \
  --docker-registry-server-password "$ACR_PASSWORD" \
  --output none

echo "⚙️  Configurando puerto y settings base…"
az webapp config appsettings set -n "$APP_SERVICE" -g "$RG" --settings \
  WEBSITES_PORT=8010 \
  WEBSITES_ENABLE_APP_SERVICE_STORAGE=false \
  DATABASE_DIR="database/proyectos 9.db" \
  --output none

echo "🔐 Inyectando .env como App Settings…"
if [ ! -f "$PROJECT_ROOT/.env" ]; then
  echo "  ⚠️  no se encontró $PROJECT_ROOT/.env — salta este paso"
else
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" =~ ^# ]] && continue
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    az webapp config appsettings set -n "$APP_SERVICE" -g "$RG" \
      --settings "${key}=${value}" --output none
  done < "$PROJECT_ROOT/.env"
fi

echo "💾 Montando File Share como volumes…"
az webapp config storage-account add -n "$APP_SERVICE" -g "$RG" \
  --custom-id shimin-data \
  --storage-type AzureFiles \
  --account-name "$STORAGE_ACCOUNT" \
  --share-name "$SHARE_NAME" \
  --access-key "$STORAGE_KEY" \
  --mount-path "/srv/app_principal/database" \
  --output none 2>/dev/null || echo "  (mount shimin-data ya existe)"

az webapp config storage-account add -n "$APP_SERVICE" -g "$RG" \
  --custom-id shimin-storage \
  --storage-type AzureFiles \
  --account-name "$STORAGE_ACCOUNT" \
  --share-name "$SHARE_NAME" \
  --access-key "$STORAGE_KEY" \
  --mount-path "/srv/app_principal/storage" \
  --output none 2>/dev/null || echo "  (mount shimin-storage ya existe)"

echo "♻️  Restart…"
az webapp restart -n "$APP_SERVICE" -g "$RG" --output none

APP_URL=$(az webapp show -n "$APP_SERVICE" -g "$RG" --query defaultHostName -o tsv)
echo
echo "✅ Backend desplegado en: https://$APP_URL"
echo "    Logs en vivo: az webapp log tail -n $APP_SERVICE -g $RG"
echo "    Health: curl https://$APP_URL/api/config/status"
