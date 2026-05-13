#!/usr/bin/env bash
# Paso 4: crear Static Web App para el frontend (Free tier) y linkear al backend.
# Requiere repo Git en GitHub.

set -euo pipefail
source "$(dirname "$0")/env.sh"

GITHUB_REPO="${GITHUB_REPO:-}"
if [ -z "$GITHUB_REPO" ]; then
  echo "❌ Define GITHUB_REPO=https://github.com/<usuario>/proyectohh_app en env.sh"
  exit 1
fi

echo "🌐 Creando Static Web App '$STATIC_WEB_APP'…"
az staticwebapp create \
  -n "$STATIC_WEB_APP" \
  -g "$RG" \
  --location "$STATIC_WEB_REGION" \
  --source "$GITHUB_REPO" \
  --branch main \
  --app-location "frontend" \
  --output-location "dist" \
  --login-with-github

echo "🔗 Linkeando con apphhshimin (App Service backend)…"
BACKEND_ID=$(az webapp show -n "$APP_SERVICE" -g "$RG" --query id -o tsv)
az staticwebapp backends link \
  -n "$STATIC_WEB_APP" -g "$RG" \
  --backend-resource-id "$BACKEND_ID" \
  --backend-region "$REGION" \
  --output none

if [ -n "${AAD_CLIENT_ID:-}" ]; then
  echo "🔐 Configurando AAD_CLIENT_ID…"
  az staticwebapp appsettings set -n "$STATIC_WEB_APP" -g "$RG" \
    --setting-names "AAD_CLIENT_ID=$AAD_CLIENT_ID" --output none
fi

SWA_URL=$(az staticwebapp show -n "$STATIC_WEB_APP" -g "$RG" --query defaultHostname -o tsv)
echo
echo "✅ Frontend desplegado en: https://$SWA_URL"
echo "    El primer build puede tardar 3-5 min. Mira progress en GitHub Actions."
