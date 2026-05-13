# Mapeo Frontend Backend Y Checklist De Verificacion

Fecha: 2026-05-13

Este documento deja un mapa práctico del flujo completo entre frontend, autenticación, backend y datos para detectar rápido fallas como las que aparecieron durante el despliegue y para verificar cambios futuros sin repetir el mismo problema.

## Objetivo

Responder tres preguntas cada vez que algo falle:

1. El frontend está llamando al destino correcto.
2. La autenticación de Static Web App está entregando identidad válida.
3. El backend está recibiendo esas llamadas con datos y mounts correctos.

## Mapa General Del Flujo

```text
Usuario navegador
  -> Static Web App
  -> /.auth/login/aad
  -> Microsoft Entra ID
  -> callback /.auth/login/aad/callback
  -> Static Web App autenticada
  -> fetch /api/...
  -> linked backend
  -> App Service apphhshimin
  -> FastAPI
  -> SQLite + wiki + manifests en Azure Files
  -> Azure OpenAI / SharePoint / storage
```

## Estado Real Desplegado

### Frontend

- Static Web App: `https://delightful-grass-04d44f20f.7.azurestaticapps.net`
- Config auth: `frontend/staticwebapp.config.json`
- Deploy automático: `.github/workflows/azure-static-web-apps-delightful-grass-04d44f20f.yml`
- SKU: `Standard`

### Backend

- App Service: `apphhshimin`
- URL: `https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net`
- Runtime: `DOCKER|apphshimin.azurecr.io/shimin-backend:v1`

### Linking SWA -> Backend

- SWA linked backend configurado
- Región backend link: `chilecentral`
- El frontend productivo debe llamar siempre rutas relativas `/api/...`

### Datos

- Base SQLite en share `shimin-db`
- Wiki y manifests en share `shimin-storage`
- Mounts en App Service:
  - `/srv/app_principal/database`
  - `/srv/app_principal/storage`

## Mapa Por Capa

### 1. Frontend -> API base

Archivo dueño:

- `frontend/src/lib/api.js`

Regla correcta:

- en desarrollo local usa `http://127.0.0.1:8010`
- en producción usa `""` para que las llamadas salgan como `/api/...`

Problema real que ocurrió:

- el bundle publicado llevaba fallback a `http://127.0.0.1:8010`
- eso sacó las llamadas fuera de la SWA
- produjo errores CORS y `Failed to fetch`

Síntoma típico:

- DevTools muestra requests a `127.0.0.1:8010`

Diagnóstico:

- si ves `127.0.0.1` o `localhost:8010` en producción, el problema es frontend o caché del bundle

Verificación rápida:

```bash
npm run build
rg "127.0.0.1:8010|localhost:8010" frontend/dist
```

Resultado correcto:

- no debe haber coincidencias en `frontend/dist`

### 2. Static Web App -> Autenticación

Archivo dueño:

- `frontend/staticwebapp.config.json`

Dependencias críticas:

- `AAD_CLIENT_ID` en App Settings de la SWA
- callback en Entra ID
- emisión de `id_token` habilitada en App Registration

Problema real que ocurrió:

- la SWA usaba `response_type=id_token`
- la app registration tenía `enableIdTokenIssuance=false`
- el login completaba visualmente pero volvía a pedir autenticación

Síntoma típico:

- bucle al iniciar sesión sin error visible

Verificación rápida:

```bash
az ad app show --id 0104b363-efc0-488d-af2e-2cb652dd82e9 --query "web.implicitGrantSettings" -o json
az ad app show --id 0104b363-efc0-488d-af2e-2cb652dd82e9 --query "web.redirectUris" -o json
```

Resultado correcto:

- `enableIdTokenIssuance: true`
- debe existir `https://delightful-grass-04d44f20f.7.azurestaticapps.net/.auth/login/aad/callback`

### 3. SWA -> linked backend

No depende de CORS si el frontend llama `/api/...`.

Requisito importante:

- SWA en `Standard`

Problema real que ocurrió:

- con `Free` no se pudo usar `linked backends`

Verificación rápida:

```bash
az staticwebapp show -n shimin-frontend -g appHH --query "{sku:sku.name,linkedBackends:linkedBackends}" -o json
```

Resultado correcto:

- `sku: Standard`
- `linkedBackends` con `provisioningState: Succeeded`

### 4. Backend -> CORS

Archivo dueño:

- `backend/app/main.py`
- `backend/app/core/config.py`

Estado actual:

- CORS explícito solo para `localhost` y `127.0.0.1` de desarrollo

Esto es correcto mientras producción use SWA linked backend con rutas relativas.

Conclusión operativa:

- si producción llama `/api/...`, CORS no debe ser el primer sospechoso
- si producción llama dominio directo del App Service desde el navegador, sí aparecerá CORS

Verificación rápida:

```bash
curl.exe -I https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net/api/config/status
```

Interpretación:

- si el navegador de producción intenta hablar directamente con esta URL, el diseño está mal en el frontend o no se está usando el linked backend

### 5. SWA auth -> Backend identity

Archivos dueños:

- `backend/app/services/user_context.py`
- `backend/app/api/routes.py`

Cómo se resuelve el usuario:

- `x-ms-client-principal-name`
- `x-user-email`
- fallback a `cristian.reyes@shimin.cl`

Riesgo importante:

- ese fallback es cómodo para desarrollo local, pero puede esconder problemas de headers si una ruta llegara sin identidad esperada

Hoy no fue la causa del bug, pero es un punto frágil.

Recomendación:

- mantenerlo solo si se acepta para dev local
- si se quiere endurecer producción, condicionar el fallback a entorno local

Verificación rápida:

```bash
curl.exe -I https://delightful-grass-04d44f20f.7.azurestaticapps.net
```

Resultado correcto:

- `302` hacia `/.auth/login/aad...`

Luego, autenticado, la SWA debe poder resolver `rolesSource` vía `/api/me`.

### 6. Backend -> Datos y mounts

Archivos dueños:

- `backend/app/core/config.py`

Rutas críticas en runtime:

- SQLite: `/srv/app_principal/database/proyectos 9.db`
- wiki root: `/srv/app_principal/storage/llm_wiki.md`
- páginas wiki: `/srv/app_principal/storage/llm_wiki/proposals`
- entries: `/srv/app_principal/storage/llm_wiki/entries`

Problema real que ocurrió:

- con un solo share no se respetaban bien las rutas esperadas

Solución aplicada:

- share `shimin-db` para `/database`
- share `shimin-storage` para `/storage`

Verificación rápida:

```bash
az webapp config storage-account list -n apphhshimin -g appHH -o json
```

Resultado correcto:

- mount `/srv/app_principal/database` -> `shimin-db`
- mount `/srv/app_principal/storage` -> `shimin-storage`

Además:

```bash
curl.exe https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net/api/config/status
curl.exe https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net/api/sync/status
```

Resultado correcto:

- no debe haber warnings de coverage
- deben aparecer conteos de wiki, rag, entities, hh_excel

### 7. Backend -> Imagen y despliegue

Dependencias críticas:

- App Service apunta a `apphshimin.azurecr.io/shimin-backend:v1`
- ACR `apphshimin`

Problema real que ocurrió:

- `az acr build` falló en `chilecentral`

Solución aplicada:

- build local Docker
- push manual al ACR

Verificación rápida:

```bash
az webapp show -n apphhshimin -g appHH --query "siteConfig.linuxFxVersion" -o tsv
az acr repository show-tags -n apphshimin --repository shimin-backend -o table
```

Resultado correcto:

- App Service debe apuntar al tag que existe en ACR

## Tabla De Fallas Tipicas

| Síntoma | Capa probable | Qué revisar primero |
|---|---|---|
| Login entra en bucle | Entra ID / SWA auth | `enableIdTokenIssuance`, redirect URI, `AAD_CLIENT_ID` |
| Requests a `127.0.0.1:8010` | Frontend | `frontend/src/lib/api.js`, bundle desplegado, caché |
| CORS en producción | Frontend o linked backend | si está llamando `/api/...` o App Service directo |
| SWA carga pero `/api` falla | linked backend | SKU `Standard`, backend link, backend health |
| `/api/me` falla autenticado | backend identity | headers SWA, `rolesSource`, `user_context.py` |
| chat carga pero no encuentra datos | mounts / storage | shares, mounts, `config/status`, `sync/status` |
| App Service no levanta nueva versión | imagen/container | tag en ACR, `linuxFxVersion`, restart |

## Checklist Minimo Antes De Dar Por Bueno Un Deploy

### Frontend

1. `npm run build`
2. `rg "127.0.0.1:8010|localhost:8010" frontend/dist`
3. confirmar que el workflow SWA corrió en GitHub

### SWA y Auth

1. `az staticwebapp show ...` confirma `Standard`
2. `linkedBackends` en `Succeeded`
3. `AAD_CLIENT_ID` presente
4. App Registration con callback SWA
5. `enableIdTokenIssuance=true`

### Backend

1. `linuxFxVersion` correcto
2. mounts correctos
3. `/api/config/status` responde
4. `/api/sync/status` responde

### Datos

1. `rag_proposals > 0`
2. `wiki_pages_existing > 0`
3. `entity_index.entities > 0`
4. sin `coverage_warnings`

## Checklist De Diagnóstico Rápido Cuando Falle Algo

### Si falla el login

1. revisar redirect URI
2. revisar `enableIdTokenIssuance`
3. probar en incógnito
4. revisar que la SWA esté leyendo `AAD_CLIENT_ID`

### Si falla el chat o sesiones

1. abrir DevTools Network
2. verificar si la llamada es `/api/...` o `127.0.0.1`
3. si es `127.0.0.1`, frontend roto o bundle viejo
4. si es `/api/...`, revisar `/api/me` y `/api/config/status`

### Si faltan datos

1. revisar mounts
2. revisar `/api/config/status`
3. revisar `/api/sync/status`
4. revisar shares `shimin-db` y `shimin-storage`

## Recomendaciones Para Evitar Recaídas

1. Mantener `frontend/src/lib/api.js` con fallback solo para `localhost` y nunca para producción.
2. No usar la URL directa del App Service en el frontend productivo.
3. Cada cambio frontend debe validarse con búsqueda en `frontend/dist` para detectar URLs locales hardcodeadas.
4. Cada cambio de auth debe verificar explícitamente `enableIdTokenIssuance` y redirect URIs.
5. Cada cambio de storage debe verificarse en mounts reales del App Service, no solo en el código.
6. Si se endurece seguridad, revisar el fallback de usuario en `backend/app/services/user_context.py`.

## Conclusión Operativa

El error reciente fue una combinación de dos capas distintas:

- auth: faltaba `enableIdTokenIssuance=true` en Entra ID
- frontend: el bundle productivo apuntaba a `127.0.0.1:8010`

El backend en sí estaba funcionando y con datos correctos. El valor de este mapa es que deja claro el orden correcto de revisión para no culpar a la capa equivocada en el próximo incidente.