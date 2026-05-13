# Cambios pendientes que afectan el deploy Azure

> Este documento se actualiza CADA VEZ que se agrega una funcionalidad nueva que requiere ajustes en el deploy a Azure (mounts, env vars, endpoints, sync, permisos, dependencias). Usar como checklist al hacer release.

Última actualización: 2026-05-13

---

## 1. Variables de entorno nuevas (App Settings en Azure)

| Variable | Valor | Dónde usar | Estado |
|---|---|---|---|
| `STAFFING_API_URL` | `https://staffing-shimin-dgedc6cachagg8fx.eastus2-01.azurewebsites.net` | `app/services/staffing_client.py` | **PENDIENTE en Azure** (ya en .env local) |
| `STAFFING_API_KEY` / `EXTERNAL_API_KEY` | (key del staffing app) | tools de staffing | **PENDIENTE en Azure** (ya en .env local) |

Comando para aplicar a App Service:
```bash
az webapp config appsettings set -n apphhshimin -g <RG> --settings \
  STAFFING_API_URL="https://staffing-shimin-dgedc6cachagg8fx.eastus2-01.azurewebsites.net" \
  EXTERNAL_API_KEY="<paste>"
```

---

## 2. Mounts de Azure Files

| Path container | Share Azure Files | Propósito | Estado |
|---|---|---|---|
| `/srv/app_principal/database` | `shimin-db` (apphhdrive) | SQLite proyectos 9.db, drafts, sesiones | ✅ ya |
| `/srv/app_principal/storage` | `shimin-storage` (apphhdrive) | wiki, manifests, exports, **proposal_drafts/** | ✅ ya |
| `/srv/app_principal/storage/proposal_drafts` | (subdir de shimin-storage) | **NUEVO**: PDFs/DOCX subidos para drafts | el mount existente cubre esto |

No hace falta crear shares nuevos, pero **asegurar que `storage/proposal_drafts/` se cree con permiso de escritura** en el mount.

---

## 3. Endpoints API nuevos

| Endpoint | Propósito |
|---|---|
| `GET /api/sessions` y CRUD | Sesiones chat por usuario ✅ |
| `GET/POST /api/sessions/{id}/messages` | History persistido ✅ |
| `GET/POST /api/sync/*` | Sync SharePoint ✅ |
| `POST /api/library/search` | Búsqueda en wiki entries ✅ |
| `GET /api/sync/status` | Cobertura wiki ✅ |
| `GET /api/exports/file/{filename}` | Descarga de archivos generados por agente ✅ |
| **NUEVO**: `POST /api/drafts` | Crear draft de propuesta |
| **NUEVO**: `GET /api/drafts` | Listar mis drafts |
| **NUEVO**: `GET /api/drafts/{slug}` | Detalle (archivos + guía) |
| **NUEVO**: `POST /api/drafts/{slug}/upload` | Subir PDF/DOCX (multipart) |
| **NUEVO**: `POST /api/drafts/{slug}/build-guide` | Disparar generación LLM de guía |
| **NUEVO**: `GET /api/drafts/{slug}/files/{name}` | Descargar original |
| **NUEVO**: `DELETE /api/drafts/{slug}` | Borrar |

---

## 4. Tablas SQLite nuevas

| Tabla | Propósito | Estado |
|---|---|---|
| `chat_sessions` + `chat_messages` | Sesiones por usuario | ✅ ya en schema |
| **NUEVO**: `proposal_drafts` | Drafts del usuario (slug, title, cliente, status, owner_id) |
| **NUEVO**: `proposal_draft_files` | Archivos subidos (slug, filename, type, size, text_extracted, created_at) |
| **NUEVO**: `proposal_draft_chunks` | RAG local del draft (chunks indexados) |

Esquema completo en `backend/app/services/proposal_drafts.py:_ensure_tables()`.

---

## 5. Dependencias Python nuevas

| Paquete | Propósito | Estado |
|---|---|---|
| `python-docx` | extraer texto de DOCX | ✅ ya está en requirements.txt |
| `PyPDF2` | extraer texto de PDF | ✅ ya está |
| `python-multipart` | upload de archivos a FastAPI | **VERIFICAR si ya está** |

```bash
cd backend && pip show python-multipart || pip install python-multipart
```

Agregar a `requirements.txt` si falta. Luego rebuild de la imagen Docker.

---

## 6. Storage local que debe persistir

Carpetas que el container DEBE poder escribir y persistir:
- `storage/proposal_drafts/<slug>/antecedentes/` — PDFs/DOCX originales
- `storage/proposal_drafts/<slug>/texts/` — texto extraído (.txt)
- `storage/proposal_drafts/<slug>/guia.md` — guía generada por LLM
- `storage/proposal_drafts/<slug>/metadata.json` — metadata

Ya cubierto por el mount existente `shimin-storage`. Verificar que NO se versionan en git (agregar a .gitignore — ya cubre `storage/`).

---

## 7. Tools del agente nuevas

| Tool | Para qué | Estado |
|---|---|---|
| `search_entregables_hh` | HH reales del staffing | ✅ |
| `get_horas_detalle` | Auditoría persona/semana | ✅ |
| `get_proyecto_staffing` | Proyecto SH-XXXX completo | ✅ |
| `get_persona_historial` | Carga histórica de una persona | ✅ |
| `listar_proyectos_staffing` | Listar SH activos | ✅ |
| **NUEVA**: `list_my_drafts` | Drafts del usuario actual |
| **NUEVA**: `get_draft_context` | Trae guía + texto extraído de un draft |
| **NUEVA**: `search_draft_chunks` | Busca dentro del draft activo |

---

## 8. Skills nuevas / modificadas

| Skill | Estado |
|---|---|
| `analizar_entregables_hh` | ✅ creada |
| `armar_propuesta` | ✅ modificada: jerarquía ganada/perdida + integración staffing |
| `recomendar_por_tema` | ✅ modificada: regla ganada/perdida |
| `datos_economicos` | ✅ modificada: distingue HH licitadas vs reales |
| **A CREAR**: `armar_propuesta_con_antecedentes` | flujo cuando hay draft activo con PDFs del cliente |

---

## 9. Cron diario sync (GitHub Actions)

Endpoints que el workflow `sync-daily.yml` debe llamar:
- `POST /api/sync/new?limit=50` ✅
- `POST /api/master/refresh` ✅
- `POST /api/sync/backfill-wiki` ✅
- **NUEVO opcional**: limpiar drafts viejos (>30 días sin actividad)? — decidir política

---

## 10. UI / Static Web App

Cambios en `frontend/`:
- Sidebar de sesiones (chat) ✅
- Vista Library (wiki) ✅
- Vista Master con filtros ✅
- **NUEVA**: vista Drafts en sidebar nav (entre Library y Ajustes)
- Toggle paneles chat ✅
- Logo SHIMIN ✅
- Botones export PDF/DOCX/XLSX con formato corporativo ✅

`staticwebapp.config.json` no requiere cambios — los nuevos endpoints están bajo `/api/*` y ya están protegidos por auth.

---

## 11. Permisos App Registration Entra ID

App Registration `0104b363-efc0-488d-af2e-2cb652dd82e9` permisos requeridos:
- `Sites.Read.All` Graph (SharePoint /sites/Gerenciacomercial) ✅
- `User.Read` (login Static Web App) ✅
- **Confirmar**: si el sync diario también debe escribir, agregar `Sites.ReadWrite.All` (hoy solo lee)

---

## 12. Checklist pre-release Azure

Antes de hacer `git push` final + `az acr build`:

- [ ] `.env` local funciona end-to-end
- [ ] Verificar `python-multipart` en requirements.txt
- [ ] Tests integrales pasan (`python backend/scripts/test_full_system.py`)
- [ ] Sin secrets nuevos en código (audit con `git log -p .env`)
- [ ] `docs/AZURE_PENDING_CHANGES.md` revisado (este doc)
- [ ] App Settings actualizados en Azure con env vars nuevas
- [ ] Smoke test post-deploy: `GET /api/config/status` + crear draft + upload PDF + ver guía

---

## Historial de cambios

| Fecha | Qué se agregó |
|---|---|
| 2026-05-12 | Sesiones chat por usuario (chat_sessions, chat_messages) |
| 2026-05-12 | Toggle sidebars chat |
| 2026-05-12 | Sinónimos PT/EN en agente |
| 2026-05-12 | Exports con formato SHIMIN + logo |
| 2026-05-12 | Endpoint `/api/exports/file/{name}` para descargas con link |
| 2026-05-13 | Integración Staffing API (5 tools + skill `analizar_entregables_hh`) |
| 2026-05-13 | Regla ganada/perdida como principio general del agente |
| 2026-05-13 | Vista "Operación" colapsada en "Ajustes" |
| 2026-05-13 | **EN PROGRESO**: Drafts de propuestas con antecedentes (PDF/DOCX) + guía LLM |
