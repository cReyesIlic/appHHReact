#!/usr/bin/env bash
# Paso 0: inicializar git, conectar a GitHub y hacer primer push.
# Idempotente — si ya hay repo, solo verifica estado.

set -euo pipefail

REPO_NAME="${REPO_NAME:-shimin-proposal-intelligence}"
PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
cd "$PROJECT_ROOT"

echo "📂 Trabajando en: $PROJECT_ROOT"

# 1. .gitignore robusto
echo "🔒 Asegurando .gitignore con secrets…"
touch .gitignore
for pat in ".env" "deploy/env.sh" "database/*.db" "database/*.db-shm" "database/*.db-wal" \
           "database/*.db.backup-*" "database/*.db.corrupted-*" \
           "**/__pycache__" "**/*.pyc" "**/.venv" \
           "node_modules" "frontend/dist" "frontend/.vite" \
           "exports/" "storage/sync_manifest.csv" \
           "C:/Users/" ".DS_Store" "*.log"; do
  grep -qxF "$pat" .gitignore 2>/dev/null || echo "$pat" >> .gitignore
done
echo "  .gitignore tiene $(wc -l < .gitignore) líneas."

# 2. Git init si no existe
if [ ! -d ".git" ]; then
  echo "🌱 git init…"
  git init -b main
fi

# 3. Verificar que .env NO está siendo trackeado
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "⚠️  .env está commiteado. Sacándolo del index (queda en disco)…"
  git rm --cached .env
fi

# 4. Add + commit inicial
git add .
STATUS=$(git status --porcelain | wc -l)
if [ "$STATUS" -gt 0 ]; then
  echo "📦 Commiteando $STATUS cambios…"
  git commit -m "feat: SHIMIN Proposal Intelligence — agente con tool calling, sesiones, wiki librería curada, deploy Azure"
else
  echo "  (sin cambios para commitear)"
fi

# 5. Crear repo en GitHub si no hay remote
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "🌐 No hay remote 'origin' configurado."
  if command -v gh &>/dev/null; then
    echo "   Creando repo PRIVADO en GitHub: $REPO_NAME"
    gh repo create "$REPO_NAME" --private --source=. --remote=origin --push --description "SHIMIN Proposal Intelligence — agente conversacional sobre propuestas"
  else
    echo "   ⚠️  gh CLI no instalado. Sigue estos pasos manuales:"
    echo "      1) Instala: winget install GitHub.cli  (Windows) o https://cli.github.com/"
    echo "      2) Auth:    gh auth login"
    echo "      3) Re-ejecuta: ./deploy/00-git-init.sh"
    echo "   O crea el repo manualmente en https://github.com/new (privado, sin README inicial) y luego:"
    echo "      git remote add origin https://github.com/<tu-usuario>/$REPO_NAME.git"
    echo "      git push -u origin main"
    exit 1
  fi
else
  REMOTE_URL=$(git remote get-url origin)
  echo "🔗 Remote ya configurado: $REMOTE_URL"
  echo "   Pusheando cambios pendientes…"
  git push -u origin main || echo "   (push falló — quizá no hay cambios o branch divergente)"
fi

echo
echo "✅ Repo listo. URL:"
git remote get-url origin
echo
echo "Siguiente: ./deploy/01-storage.sh"
