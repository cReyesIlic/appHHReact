# Cambios pendientes que afectan el deploy Azure

> Este documento se actualiza CADA VEZ que se agrega una funcionalidad nueva que requiere ajustes en el deploy a Azure (mounts, env vars, endpoints, sync, permisos, dependencias). Usar como checklist al hacer release.

Última actualización: 2026-05-14

---

## 1. Variables de entorno nuevas (App Settings en Azure)

| Variable | Valor | Dónde usar | Estado |
|---|---|---|---|
| `STAFFING_API_URL` | `https://staffing-shimin-dgedc6cachagg8fx.eastus2-01.azurewebsites.net` | `app/services/staffing_client.py` | **PENDIENTE en Azure** (ya en `.env` local) |
| `STAFFING_API_KEY` / `EXTERNAL_API_KEY` | (key del staffing app) | tools de staffing | **PENDIENTE en Azure** (ya en `.env` local) |
| `ACS_CONNECTION_STRING` | `endpoint=https://<acs>.communication.azure.com/;accesskey=...` | `services/email_client.py` (reportes ingesta) | **PENDIENTE** — crear recurso Azure Communication Services |
| `ACS_SENDER_ADDRESS` | `DoNotReply@<dominio-acs>.azurecomm.net` (o dominio custom verificado) | `services/email_client.py` | **PENDIENTE** |
| `EMAIL_REPORT_RECIPIENTS` | CSV: `cri.reyes@shimin.cl,otro@shimin.cl` | destinatarios por defecto de reportes | **PENDIENTE** |
| `HH_EXCEL_SOURCE` | `storage/emitted_offer_assets/excel` (default) o `blob://<container>/<prefix>` | path adaptable de Excels HH licitadas | opcional |
| `HH_EXCEL_CACHE_DIR` | `storage/hh_excel_ingestion` (default) | cache si HH_EXCEL_SOURCE es blob | opcional |

Comando para aplicar a App Service:
```bash
az webapp config appsettings set -n apphhshimin -g <RG> --settings \
  STAFFING_API_URL="https://staffing-shimin-dgedc6cachagg8fx.eastus2-01.azurewebsites.net" \
  EXTERNAL_API_KEY="<paste>" \
  ACS_CONNECTION_STRING="endpoint=https://<acs>.communication.azure.com/;accesskey=<paste>" \
  ACS_SENDER_ADDRESS="DoNotReply@<dominio-acs>.azurecomm.net" \
  EMAIL_REPORT_RECIPIENTS="cri.reyes@shimin.cl"
```

Crear recurso Azure Communication Services + dominio email:
```bash
az communication create -n shimin-acs -g <RG> -l global --data-location southamerica
az communication email create -n shimin-email -g <RG> -l global --data-location southamerica
az communication email domain create --domain-name AzureManagedDomain --email-service-name shimin-email -g <RG> --location global --domain-management AzureManaged
az communication email domain sender-username create --domain-name AzureManagedDomain --email-service-name shimin-email -g <RG> --sender-username DoNotReply
# Linkear el dominio al ACS:
az communication linked-domain create --communication-service-name shimin-acs -g <RG> --linked-domain <resource-id-domain>
# Obtener connection string:
az communication list-key -n shimin-acs -g <RG>
```

> Las credenciales SharePoint (`TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`) ya estaban en Azure App Settings de la versión Streamlit y se reutilizan. Verificar que el App Registration `0104b363-...` tenga el permiso `Sites.Read.All` (Graph) consentido por admin del tenant SHIMIN.

---

## 2. Mounts de Azure Files

| Path container | Share Azure Files | Propósito | Estado |
|---|---|---|---|
| `/srv/app_principal/database` | `shimin-db` (apphhdrive) | SQLite `proyectos 9.db`, drafts, sesiones, wiki entries | ✅ |
| `/srv/app_principal/storage` | `shimin-storage` (apphhdrive) | wiki, manifests, exports, `proposal_drafts/` | ✅ |
| `/srv/app_principal/storage/proposal_drafts/<owner_id_safe>/<slug>/` | (subdir de shimin-storage) | Antecedentes PDF/DOCX + texto extraído + guía LLM, **aislado por usuario** | cubierto por mount |

> El path de drafts incluye `owner_id_safe` (email sanitizado, ej. `cristian.reyes_shimin.cl`). Esto da aislamiento físico entre usuarios además del filtro SQL por `owner_id`.

No hace falta crear shares nuevos, pero **asegurar que `storage/proposal_drafts/` se cree con permiso de escritura recursivo** en el mount.

---

## 3. Endpoints API nuevos

### Sesiones chat ✅
- `GET /api/sessions` (listar), `POST /api/sessions` (crear)
- `GET /api/sessions/{id}` (detalle + history)
- `PATCH /api/sessions/{id}` (renombrar), `DELETE /api/sessions/{id}`
- `POST /api/chat` ahora acepta `session_id` y persiste mensajes + trace + sources

### Drafts ✅
| Endpoint | Propósito |
|---|---|
| `GET /api/drafts` | Listar drafts del usuario actual |
| `POST /api/drafts` | Crear draft (`{title, cliente?}`) |
| `GET /api/drafts/{slug}` | Detalle + archivos + guía markdown |
| `DELETE /api/drafts/{slug}` | Borrar (BD + filesystem) |
| `POST /api/drafts/{slug}/upload` | Upload multipart PDF/DOCX |
| `GET /api/drafts/{slug}/files/{filename}` | Descargar original |
| `POST /api/drafts/{slug}/build-guide` | Generar guía LLM (`.md`) |
| `GET /api/drafts/sharepoint-preview/{codigo}` | Listar antecedentes en SharePoint (sin descargar) |
| `POST /api/drafts/{slug}/import-sharepoint` | Importar carpeta `01 Informacion Cliente` de O-XXXX |

### Otros (recordatorio, ya activos) ✅
- `POST /api/sync/new`, `/api/sync/backfill-wiki`, `/api/sync/status`
- `POST /api/library/search`, `POST /api/wiki/entries/{id}/validate`
- `GET /api/exports/file/{filename}` (descarga de archivos generados por agente)

### Ingesta + reportes email (nuevos 2026-05-14) ✅
| Endpoint | Propósito |
|---|---|
| `POST /api/ingest/upload` (multipart) | Sube PDF/DOCX/XLSX individual, extrae texto, envía reporte por email |
| `POST /api/admin/email-test` | Verifica configuración ACS — envía email de prueba (body opcional `{to,subject,body}`) |
| `POST /api/master/refresh` | Ahora envía email tras refrescar el Excel master |
| `POST /api/sync/ganadas` | Ahora envía email con resumen ingestadas/errores tras la corrida |

---

## 4. Tablas SQLite nuevas

Schema generado al arrancar (idempotente, `if not exists`):

| Tabla | Definida en | Estado |
|---|---|---|
| `chat_sessions` (id, user_id, title, created_at, updated_at, last_message_at, message_count, working_context) | `services/chat_sessions.py:_ensure_tables` | ✅ |
| `chat_messages` (id, session_id, role, content, trace, sources, tables, created_at) | mismo | ✅ |
| `proposal_drafts` (slug, owner_id, title, cliente, status, created_at, updated_at) | `services/proposal_drafts.py:_ensure_tables` | ✅ |
| `proposal_draft_files` (id, slug, filename, kind, size, chars_extracted, uploaded_at) | mismo | ✅ |
| `proposal_draft_chunks` (id, slug, source_file, text, char_start, chunk_index) | mismo | ✅ |
| `wiki_entries` con columnas extra (`propuestas_referenciadas`, `filtros_aplicables`, `times_used`, `validated_at`, `validation_status`) | `services/structured_wiki.py:_ensure_tables` | ✅ |

---

## 5. Dependencias Python nuevas

| Paquete | Versión | Propósito | Estado |
|---|---|---|---|
| `python-docx` | 1.1.2 | extraer texto de DOCX | ✅ ya en `requirements.txt` |
| `PyPDF2` | 3.0.1 | extraer texto de PDF | ✅ |
| `python-multipart` | 0.0.20 | upload de archivos a FastAPI | ✅ **agregado** |
| `azure-communication-email` | 1.0.0 | enviar reportes de ingesta por email | ✅ **agregado** |
| `APScheduler` | 3.10.4 | scheduler embebido (cron sin GitHub Actions) | ✅ **agregado** |
| `python-docx`, `reportlab`, `xlsxwriter` | varias | exports con formato SHIMIN | ✅ |

Tras agregar deps, rebuild de imagen Docker:
```bash
az acr build -r apphshimin -t shimin-backend:v2 ./backend
az webapp config container set -n apphhshimin -g <RG> \
  --docker-custom-image-name apphshimin.azurecr.io/shimin-backend:v2
```

---

## 6. Storage local que debe persistir (volúmenes)

Estructura completa en `/srv/app_principal/storage/`:
- `proposal_drafts/<owner_id_safe>/<slug>/antecedentes/` — PDFs/DOCX originales (uploads + imports SharePoint)
- `proposal_drafts/<owner_id_safe>/<slug>/texts/` — texto extraído (.txt)
- `proposal_drafts/<owner_id_safe>/<slug>/guia.md` — guía generada por LLM
- `llm_wiki/proposals/O-XXXX.md` — páginas wiki por propuesta (1508)
- `llm_wiki/entries/*.md` — entradas curadas wiki
- `exports/*.{pdf,docx,xlsx}` — documentos generados por agente (TTL: limpiar mensual)
- `sync_manifest.csv` — historial de sync SharePoint

Todo cubierto por mount existente `shimin-storage`. Confirmado en `.gitignore`.

---

## 7. Tools del agente

| Tool | Para qué | Estado |
|---|---|---|
| `search_master`, `search_rag`, `search_wiki_entries`, `search_entities`, `search_proposal_index` | Capa de búsqueda con filtros + sinónimos PT/EN | ✅ |
| `compute_master_stats`, `compute_economics`, `compute_proposal_support` | Análisis estructurado | ✅ |
| `get_proposal_detail`, `read_pdf_deep` | Detalle por propuesta | ✅ |
| `save_library_entry`, `load_skill` | Memoria + routing skills | ✅ |
| `generate_document` | PDF/Word/Excel con formato SHIMIN + logo | ✅ |
| `search_entregables_hh`, `get_horas_detalle` | HH reales staffing | ✅ |
| `get_proyecto_staffing`, `get_persona_historial`, `listar_proyectos_staffing` | Proyectos SH-XXXX | ✅ |
| `list_my_drafts`, `get_draft_context`, `search_draft_chunks` | Drafts del usuario | ✅ |
| `import_draft_from_sharepoint` | Trae antecedentes O-XXXX desde SharePoint al draft | ✅ |

Total: **19 tools** registradas.

---

## 8. Skills

| Skill | Estado |
|---|---|
| `armar_propuesta` | ✅ jerarquía ganada/perdida + integración staffing + drafts + SharePoint import |
| `recomendar_por_tema` | ✅ regla ganada/perdida marcada explícitamente |
| `comparar_propuestas` | ✅ |
| `datos_economicos` | ✅ distingue HH licitadas (master) vs reales (staffing) |
| `buscar_evidencia` | ✅ |
| `planificar_proyecto` | ✅ |
| `estadisticas_propuestas` | ✅ |
| `analizar_entregables_hh` | ✅ HH reales con desglose por persona |

Total: **8 skills** cargadas. Cualquier `.md` nuevo en `backend/app/skills/<name>/SKILL.md` se autocarga.

---

## 9. Scheduler embebido (APScheduler dentro del backend) — **app autónoma**

Ya **NO usamos GitHub Actions**. El scheduler corre dentro del mismo proceso uvicorn (`backend/app/services/scheduler.py`), arrancado en el `@app.on_event("startup")` de `main.py`. La app es autónoma: sube a Azure App Service y el cron vive ahí.

Jobs registrados:
1. **`sync_ganadas_periodic`** — cron `day=*/2 hour=2 minute=15` (cada 2 días, 02:15 hora Chile)
   → `ProposalSyncService.sync_ganadas(limit=20)` → email de resumen
2. **`master_refresh_daily`** — cron `hour=2 minute=10` (diario, 02:10 hora Chile)
   → `MasterRepository.refresh_from_excel()` → email si hubo cambios

Configuración via App Settings (todos opcionales con default razonable):

| Variable | Default | Propósito |
|---|---|---|
| `SYNC_SCHEDULE_ENABLED` | `true` | Apagar el scheduler (útil para staging) |
| `SYNC_SCHEDULE_EVERY_DAYS` | `2` | Cada cuántos días corre `sync_ganadas` |
| `SYNC_SCHEDULE_HOUR` | `2` | Hora local del trigger |
| `SYNC_SCHEDULE_MINUTE` | `15` | Minuto local |
| `SYNC_SCHEDULE_LIMIT` | `20` | Máximo de propuestas por corrida |
| `SYNC_SCHEDULE_TZ` | `America/Santiago` | Zona horaria IANA |

Control desde la API:
- `GET /api/admin/scheduler/status` — próxima corrida + última ejecución
- `POST /api/admin/scheduler/trigger` body `{"job":"sync_ganadas"}` — disparar ahora

> **Importante para Azure App Service**: con plan B1/B2 conviene activar **Always On** en la configuración del App Service (Settings → Configuration → General settings → Always On = ON). Sin eso, el container se duerme tras 20 min de inactividad y el scheduler se detiene hasta el siguiente request. Con Always On, el proceso uvicorn vive 24/7 y el cron dispara aunque nadie use la app.

Política opcional pendiente: limpiar drafts inactivos >90 días (TBD).

---

## 10. UI / Static Web App

Vistas en sidebar (orden):
1. **Chat** ✅ con sidebar de sesiones toggle, panel proceso/fuentes toggle
2. **Master** ✅ con filtros estructurados + búsqueda flexible cod_proy
3. **Wiki / Librería** ✅ CRUD + validate + sync SharePoint panel
4. **Propuestas en armado** ✅ (drafts: upload local + import SharePoint + guía LLM)
5. **Ajustes** (footer) ✅ — antes "Operación", colapsada

Identidad SHIMIN aplicada:
- Logo `frontend/public/logo-shimin.png` + `backend/app/assets/logo-shimin.png` (embebido en PDF/DOCX/XLSX export)
- Paleta cobre/dorado/azul-noche en `theme/shimin.css`
- ThinkingIndicator animado mientras el agente piensa

`staticwebapp.config.json` ✅ — auth Entra ID built-in con tenant `e6912f7f-...`. Los nuevos endpoints `/api/drafts/*` están automáticamente protegidos por la regla `{ "route": "/api/*", "allowedRoles": ["authenticated"] }`.

---

## 11. Permisos App Registration Entra ID

App Registration `0104b363-efc0-488d-af2e-2cb652dd82e9` permisos requeridos:
- `Sites.Read.All` (Graph) ✅ — para SharePoint `/sites/Gerenciacomercial`
- `User.Read` ✅ — para login Static Web App
- `openid`, `profile`, `email` ✅

**Pendiente confirmar**:
- Redirect URI agregado: `https://<SWA-URL>/.auth/login/aad/callback` (cuando se cree el Static Web App)
- Optional claims en ID Token: `email`, `preferred_username` (para que `user_context.py` lea el header correcto)
- Supported account types restringido a SHIMIN tenant (no multi-tenant)

---

## 12. Checklist pre-release Azure

Antes de hacer `git push` + `az acr build`:

- [ ] `.env` local funciona end-to-end (chat + staffing + sharepoint + drafts)
- [x] `python-multipart` en `requirements.txt` (✅ agregado v0.0.20)
- [ ] Tests integrales pasan (`python backend/scripts/test_full_system.py`)
- [ ] Sin secrets nuevos en código (audit con `git log -p .env`)
- [x] `docs/AZURE_PENDING_CHANGES.md` revisado (este doc) ✅
- [ ] App Settings actualizados en Azure con `STAFFING_API_URL` + `EXTERNAL_API_KEY`
- [ ] Smoke test post-deploy:
  - `GET /api/config/status` 200
  - Crear draft + upload PDF + ver guía LLM
  - Import desde SharePoint (O-0254 tiene un docx de prueba)
  - Chat con `search_entregables_hh` (HH reales staffing)

---

## Historial de cambios

| Fecha | Qué se agregó |
|---|---|
| 2026-05-12 | Sesiones chat por usuario (`chat_sessions`, `chat_messages`) |
| 2026-05-12 | Toggle sidebars chat (lista sesiones + proceso agente) — persiste en localStorage |
| 2026-05-12 | Sinónimos PT/EN/ES en agente (diccionario minero multilingüe en system prompt) |
| 2026-05-12 | Exports con formato SHIMIN + logo (DOCX header, PDF reportlab con portada, XLSX con hoja "Portada") |
| 2026-05-12 | Endpoint `/api/exports/file/{name}` con archivos únicos para descargas con link directo |
| 2026-05-13 | Integración Staffing API (5 tools + skill `analizar_entregables_hh`) |
| 2026-05-13 | Regla ganada/perdida como **principio general del agente** (system prompt nivel) |
| 2026-05-13 | Vista "Operación" colapsada en "Ajustes" (mismo destino, menú más limpio) |
| 2026-05-13 | Búsqueda flexible cod_proy (SH-0428 ↔ SH-428 ↔ 428) en MasterRepository |
| 2026-05-13 | Drafts de propuestas (CRUD + upload PDF/DOCX + extract + chunks + guía LLM) |
| 2026-05-13 | Storage drafts **por usuario**: `<owner_id_safe>/<slug>/` (aislamiento físico) |
| 2026-05-13 | Importación de antecedentes desde SharePoint (`01 Informacion Cliente` de O-XXXX) |
| 2026-05-13 | Tools del agente para drafts: `list_my_drafts`, `get_draft_context`, `search_draft_chunks`, `import_draft_from_sharepoint` |
| 2026-05-13 | Skill `armar_propuesta` detecta draft activo y lo combina con master/RAG/staffing |
| 2026-05-14 | Reportes de ingesta por email via Azure Communication Services (`services/email_client.py` + `ingestion_reporter.py`) |
| 2026-05-14 | Endpoints `/api/ingest/upload`, `/api/admin/email-test` para ingesta puntual + verificación ACS |
| 2026-05-14 | `sync_ganadas` y `master/refresh` envían reporte HTML al finalizar (best-effort, no rompen si ACS no está configurado) |
| 2026-05-14 | **Scheduler embebido APScheduler** dentro del backend — eliminado `sync-daily.yml` (GitHub Actions). App autónoma con cron en mismo proceso uvicorn. Endpoints `/api/admin/scheduler/{status,trigger}` |
| 2026-05-14 | Vista **Entregables / HH** (sidenav) — pivots por proyecto/disciplina/rol/entregable/persona sobre `hh_estimate_rows` (licitadas locales) + `StaffingClient.analisis_hh` (reales). Filtro plausibilidad (`confidence ≥ 0.65`, `0 < hours ≤ 20000`). |
| 2026-05-14 | **Sub-agente `EntregablesAgent`** — `/api/entregables/ask` adapta respuesta a tipo_servicio (IP/IC/IB/ID). Detecta código y consulta licitadas + reales según pregunta. |
| 2026-05-14 | Setting `HH_EXCEL_SOURCE` + `HH_EXCEL_CACHE_DIR` — path adaptable (local hoy, `blob://...` mañana) sin tocar código. |
