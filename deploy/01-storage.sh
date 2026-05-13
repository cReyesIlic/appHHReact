#!/usr/bin/env bash
# Paso 1: crear/asegurar File Share en apphhdrive y subir data inicial.
# Idempotente — re-ejecutable.

set -euo pipefail
source "$(dirname "$0")/env.sh"

echo "🗂  Asegurando File Share '$SHARE_NAME' en $STORAGE_ACCOUNT…"
az storage share-rm create \
  --resource-group "$RG" \
  --storage-account "$STORAGE_ACCOUNT" \
  --name "$SHARE_NAME" \
  --quota 50 \
  --enabled-protocols SMB \
  --output none 2>/dev/null || echo "  (ya existía)"

STORAGE_KEY=$(az storage account keys list -g "$RG" -n "$STORAGE_ACCOUNT" --query "[0].value" -o tsv)
SAS=$(az storage share generate-sas \
  --account-name "$STORAGE_ACCOUNT" --account-key "$STORAGE_KEY" \
  --name "$SHARE_NAME" --permissions rwdl --expiry 2027-01-01 -o tsv)

DEST="https://$STORAGE_ACCOUNT.file.core.windows.net/$SHARE_NAME?$SAS"

echo "📤 Subiendo database/proyectos*.db (puede tardar ~5 min para 800 MB)…"
azcopy copy "$PROJECT_ROOT/database/proyectos 9.db" "$DEST/database/" --overwrite=ifSourceNewer

echo "📤 Subiendo storage/llm_wiki/ (1500+ páginas curadas)…"
azcopy copy "$PROJECT_ROOT/storage/llm_wiki" "$DEST/storage/" --recursive --overwrite=ifSourceNewer

echo "📤 Subiendo manifests..."
for f in storage/wiki_ingestion_manifest.csv storage/rag_parent_child_manifest.csv \
         storage/hh_excel_ingestion_manifest.csv storage/sync_manifest.csv; do
  if [ -f "$PROJECT_ROOT/$f" ]; then
    azcopy copy "$PROJECT_ROOT/$f" "$DEST/storage/" --overwrite=ifSourceNewer
  fi
done

echo "✅ Storage listo. Verifica en portal: $STORAGE_ACCOUNT/$SHARE_NAME"
