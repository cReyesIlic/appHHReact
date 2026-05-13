# SHIMIN Proposal Intelligence

Plataforma agéntica para consultar todas las propuestas técnicas y comerciales SHIMIN. Combina **Master Excel** + **RAG sobre PDFs** + **Wiki librería curada** + **Azure OpenAI** con un agente que decide qué herramientas usar según la pregunta.

> Reemplaza la versión Streamlit anterior. Mismo backend Azure (`apphhshimin`, `apphshimin`, `apphhdrive`, `testapphhopenai`) + nuevo frontend React con SSO Entra ID.

---

## Qué puede hacer el agente

- 💬 **Chat libre** con tool-calling (12 herramientas, 7 skills/playbooks)
- 🔎 **Búsqueda inteligente** con sinónimos del dominio minero (*"depósito relaves"* ↔ *"tranque"*)
- 📊 **Estadísticas** sobre propuestas (cuántas ganadas, distribución, montos, HH, tarifas)
- 🧠 **Recomendaciones** con explicación del por qué de cada propuesta
- 📝 **Armar propuestas nuevas** con referencias clasificadas (directas/comparables/metodológicas)
- 📥 **Exportar** respuestas a PDF / Word / Excel (con marca SHIMIN)
- 💾 **Sesiones por usuario** persistidas en SQLite (estilo ChatGPT)
- 🔄 **Sync automático** diario desde SharePoint (nuevas propuestas → RAG → Wiki)
- 🔐 **SSO Entra ID** con cuenta corporativa `@shimin.cl`

---

## Estructura

```
app_principal/
├── backend/              FastAPI + agente + tools + skills + RAG/Wiki
│   ├── app/
│   │   ├── agents/       AgentLoop + tools (registry, handlers)
│   │   ├── skills/       Playbooks markdown por tipo de pregunta (7)
│   │   ├── api/          Endpoints REST
│   │   ├── rag/          Hybrid store (vector + lexical) + parent/child
│   │   └── services/     Master, Wiki, Sync, LLM, etc.
│   └── scripts/          CLI (sync, backfill, test full system)
├── frontend/             React + Vite, identidad SHIMIN
│   ├── src/
│   │   ├── components/   chat / master / library / ops / layout / shared
│   │   ├── theme/        Paleta SHIMIN (cobre/dorado/azul-noche)
│   │   └── lib/          api.js + filters.js
│   └── staticwebapp.config.json  ← config Auth Entra ID
├── deploy/               Scripts az para Azure (numerados 00–04)
├── docs/                 Arquitectura, deploy y migration docs
└── .github/workflows/    Cron diario sync
```

---

## Primera ejecución local (con Docker)

Requiere: Docker Desktop + .env (pedirlo al admin).

```bash
docker compose up -d
```

URLs:
- Frontend: http://localhost:5180
- Backend: http://localhost:8010
- Test agent: http://localhost:8010/api/sync/status

---

## Primera ejecución local (sin Docker)

### Backend
```powershell
cd backend
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8010
```

### Frontend
```powershell
cd frontend
npm install
npm run dev   # http://localhost:5173
```

---

## Pushear a GitHub (primera vez)

### Si tienes `gh` CLI (recomendado)

```bash
cd "C:/Users/CristianReyes/OneDrive - SHIMIN/Documentos/GitHub/proyectohh_app/app_principal"
./deploy/00-git-init.sh
```

Eso:
1. Crea `.gitignore` robusto (excluye `.env`, `*.db`, `node_modules`, `.venv`, secrets, etc.)
2. Hace `git init` + commit inicial
3. Crea repo **privado** en GitHub con nombre `shimin-proposal-intelligence`
4. Pushea a `origin/main`

Cambiar nombre del repo: `REPO_NAME=otro-nombre ./deploy/00-git-init.sh`

### Sin `gh` CLI

```bash
cd "C:/Users/CristianReyes/OneDrive - SHIMIN/Documentos/GitHub/proyectohh_app/app_principal"

# .gitignore (crítico para no subir secrets)
cat >> .gitignore <<'EOF'
.env
deploy/env.sh
database/*.db
database/*.db-shm
database/*.db-wal
database/*.db.backup-*
**/__pycache__
**/.venv
node_modules
frontend/dist
exports/
storage/sync_manifest.csv
EOF

git init -b main
git add .
git status   # ← VERIFICAR que NO está commiteando .env, *.db, .venv, node_modules
git commit -m "feat: SHIMIN Proposal Intelligence inicial"
```

Crear el repo en https://github.com/new:
- Nombre sugerido: **`shimin-proposal-intelligence`**
- Visibilidad: **Private**
- NO marcar "Initialize with README" (ya tienes uno)

Conectar y pushear:
```bash
git remote add origin https://github.com/<tu-usuario>/shimin-proposal-intelligence.git
git push -u origin main
```

---

## Nombre del repo recomendado

| Nombre | Cuándo elegirlo |
|---|---|
| `shimin-proposal-intelligence` ⭐ | Más descriptivo, claro para alguien externo |
| `proyectohh-app` | Si quieres mantener consistencia con la carpeta `proyectohh_app` |
| `apphh-shimin` | Si quieres alineación con los recursos Azure (`apphh*`) |

Mi recomendación: **`shimin-proposal-intelligence`** — describe qué hace, no de dónde viene.

---

## Deploy a Azure

Una vez pusheado a GitHub:

1. Leer **[`docs/MIGRATION_RATIONALE.md`](docs/MIGRATION_RATIONALE.md)** — qué cambia y por qué (para entender o presentar).
2. Seguir **[`docs/DEPLOY_APPHH_FINAL.md`](docs/DEPLOY_APPHH_FINAL.md)** — pasos 0–11 ejecutables.

Scripts ya hechos en `deploy/`:
- `00-git-init.sh` — Git + push a GitHub
- `01-storage.sh` — File Share en `apphhdrive` + subir SQLite + wiki
- `02-build-push.sh` — Build imagen backend en `apphshimin`
- `03-app-service.sh` — Apuntar `apphhshimin` a la nueva imagen + mounts + env
- `04-static-web-app.sh` — Crear Static Web App y linkear con backend

Cada uno es idempotente (re-ejecutable sin romper).

---

## Costos esperados Azure

| | Mensual |
|---|---|
| App Service Plan B2 (`ASP-appshimin`) | $26 |
| Storage Azure Files 5 GB | $2 |
| Container Registry Basic (`apphshimin`, ya pagado) | $0 incremental |
| Static Web App (frontend) | $0 (Free) |
| Key Vault | $0 |
| Azure OpenAI | $2–10 (variable) |
| **Total** | **~$30–38 USD/mes** |

---

## Seguridad — antes de pushear

✅ Verificar `.env` NO está en git: `git ls-files .env` (debe estar vacío)
✅ `.gitignore` cubre `.env`, `*.db`, `node_modules`, `.venv`
✅ Si ya commiteaste `.env` por error, rotar los secrets:
  - OpenAI: https://platform.openai.com/api-keys
  - Storage: `az storage account keys renew -n apphhdrive -g <RG> --key key1`
  - SharePoint client_secret: portal Entra ID → App registration → Certificates & secrets

---

## Documentos relacionados

- [`docs/DEPLOY_APPHH_FINAL.md`](docs/DEPLOY_APPHH_FINAL.md) — Plan deploy paso a paso (11 secciones)
- [`docs/MIGRATION_RATIONALE.md`](docs/MIGRATION_RATIONALE.md) — Qué cambia y por qué (para equipo)
- [`docs/hybrid_rag_embeddings.md`](docs/hybrid_rag_embeddings.md) — Cómo funciona el RAG híbrido
- [`docs/rag_metadata_taxonomy.md`](docs/rag_metadata_taxonomy.md) — Schema de filtros estructurados
- [`backend/app/skills/*/SKILL.md`](backend/app/skills/) — Las 7 skills del agente (markdown)

---

## Operación diaria

```bash
# Logs en vivo del backend en Azure
az webapp log tail -n apphhshimin -g <RG>

# Forzar sync manual (detecta nuevas propuestas en SharePoint)
curl -X POST "https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net/api/sync/new?limit=20"

# Test del agente
curl -X POST "https://apphhshimin-.../api/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"Qué propuestas hay de dewatering en Codelco?"}'

# Publicar nueva versión backend (tras git push):
az acr build -r apphshimin -t shimin-backend:v2 ./backend
az webapp config container set -n apphhshimin -g <RG> \
  --docker-custom-image-name "apphshimin.azurecr.io/shimin-backend:v2"
```

Frontend se actualiza automáticamente con cada `git push` a `main` (vía GitHub Actions de Static Web App).

---

## Soporte

- Issues: GitHub Issues del repo
- Admin Azure: revisar con el equipo SHIMIN quién tiene permisos de App Registration
