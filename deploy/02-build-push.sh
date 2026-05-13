#!/usr/bin/env bash
# Paso 2: build remoto en apphshimin (ACR) — no necesita Docker local.

set -euo pipefail
source "$(dirname "$0")/env.sh"

echo "🔧 Asegurando ACR admin habilitado…"
az acr update -n "$ACR_NAME" --admin-enabled true --output none

echo "🏗  Build imagen shimin-backend:$IMAGE_TAG (build remoto en ACR)…"
az acr build -r "$ACR_NAME" -t "shimin-backend:$IMAGE_TAG" \
  --file "$PROJECT_ROOT/backend/Dockerfile" \
  "$PROJECT_ROOT/backend"

echo "✅ Imagen disponible:"
az acr repository show-tags -n "$ACR_NAME" --repository shimin-backend -o table
