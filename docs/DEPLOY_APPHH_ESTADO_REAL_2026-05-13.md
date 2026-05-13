# Estado Real Del Deploy AppHH

Fecha de actualización: 2026-05-13

Este documento deja registrado el estado real del despliegue hecho sobre los recursos Azure existentes de appHH, incluyendo qué quedó funcionando, dónde está cada componente, dónde quedaron los datos y qué decisiones técnicas se tomaron durante la ejecución.

## Resumen Ejecutivo

El sistema quedó desplegado sobre los recursos existentes del grupo `appHH`.

- Backend productivo: App Service `apphhshimin`
- Frontend productivo: Static Web App `shimin-frontend`
- Registro de contenedores: ACR `apphshimin`
- Storage principal: Storage Account `apphhdrive`
- Autenticación: Microsoft Entra ID reutilizando el App Registration existente `0104b363-efc0-488d-af2e-2cb652dd82e9`
- Repositorio GitHub: `https://github.com/cReyesIlic/appHHReact.git`

El backend quedó funcionando con datos reales y el frontend quedó publicado y protegido por autenticación AAD.

## URLs Finales

### Frontend

- Static Web App pública: `https://delightful-grass-04d44f20f.7.azurestaticapps.net`

Comportamiento actual:

- si el usuario entra sin autenticación, el sitio redirige a `/.auth/login/aad`
- el callback AAD ya quedó agregado al App Registration

### Backend

- App Service backend: `https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net`

Endpoints verificados:

- `/api/config/status`
- `/api/sync/status`

Comportamiento actual:

- el backend responde correctamente
- el acceso directo público devuelve `401 Unauthorized` en la verificación actual, lo que reduce exposición directa

## Recursos Azure Utilizados

### Grupo de recursos

- Resource Group: `appHH`

### App Service

- Nombre: `apphhshimin`
- Plan: `ASP-appshimin`
- SKU actual: `B2`
- Región: `chilecentral`
- Runtime final: `DOCKER|apphshimin.azurecr.io/shimin-backend:v1`
- Always On: activado
- HTTP/2: activado
- HTTPS only: activado
- Health check: `/api/config/status`

### Azure Container Registry

- Nombre: `apphshimin`
- Login server: `apphshimin.azurecr.io`
- Imagen publicada: `apphshimin.azurecr.io/shimin-backend:v1`

Nota importante:

- `az acr build` no funcionó en esta suscripción/región para este registro por el error `listBuildSourceUploadUrl` en `chilecentral`
- la solución aplicada fue build local con Docker y `docker push` al ACR

### Static Web App

- Nombre: `shimin-frontend`
- Región: `eastus2`
- Hostname actual: `delightful-grass-04d44f20f.7.azurestaticapps.net`
- SKU final: `Standard`

Nota importante:

- el SKU `Free` no permite `linked backends`
- se subió a `Standard` para poder enlazar el App Service backend con `/api`

### Azure OpenAI

- Recurso: `testapphhopenai`
- Región: `eastus`

Deployments verificados:

- `gpt-5.4`
- `gpt-5.4-mini`
- `gpt-5.4-nano`
- `text-embedding-3-small`
- `text-embedding-3-large`

### Document Intelligence

- Recurso: `docIntelhhSHIMIN`
- Región: `eastus`
- Estado en este deploy: no utilizado directamente

## Repositorio GitHub

- Remoto final: `https://github.com/cReyesIlic/appHHReact.git`
- Rama principal: `main`

Se dejó creado y sincronizado el workflow autogenerado por Azure Static Web Apps:

- `.github/workflows/azure-static-web-apps-delightful-grass-04d44f20f.yml`

Workflow adicional existente en el repo:

- `.github/workflows/sync-daily.yml`

## Estado Del Frontend

El frontend ya estaba preparado para SWA y se dejó operativo.

Archivos relevantes:

- `frontend/staticwebapp.config.json`
- `frontend/package.json`
- `.github/workflows/azure-static-web-apps-delightful-grass-04d44f20f.yml`

Validaciones hechas:

- `npm run build` ejecutó correctamente
- el hostname de SWA responde con redirección a AAD
- el backend quedó enlazado a la SWA

Configuración AAD aplicada en frontend:

- `openIdIssuer`: tenant SHIMIN
- `clientIdSettingName`: `AAD_CLIENT_ID`
- `AAD_CLIENT_ID` cargado en App Settings de la Static Web App

## Estado Del Backend

El backend quedó ejecutándose desde App Service con la imagen publicada en ACR.

Configuración aplicada:

- imagen Docker desde ACR
- variables de entorno cargadas como App Settings del App Service
- mounts Azure Files corregidos
- `healthCheckPath` fijado por `az rest`

Validaciones hechas:

- `/api/config/status` responde
- `/api/sync/status` responde
- el backend ve correctamente base SQLite, wiki y RAG

Resultados relevantes observados en `/api/config/status`:

- `wiki_pages_existing`: 1508
- `rag_proposals`: 1508
- wiki cargada correctamente
- embeddings cargados correctamente
- índices de entidades cargados correctamente
- sin `coverage_warnings`

## Variables De Entorno Y Secretos

No se dejó Key Vault en este despliegue.

Decisión tomada:

- usar App Settings del App Service como ubicación final de secretos de producción
- dejar `.env` solo como fuente local de carga y desarrollo

Estado actual:

- los secretos y variables productivas están cargados como App Settings en `apphhshimin`
- no falta ninguna variable del `.env` en producción
- las únicas variables extra en App Service son las propias del runtime/container:
  - `DOCKER_REGISTRY_SERVER_URL`
  - `DOCKER_REGISTRY_SERVER_USERNAME`
  - `DOCKER_REGISTRY_SERVER_PASSWORD`
  - `WEBSITES_PORT`
  - `WEBSITES_ENABLE_APP_SERVICE_STORAGE`

Variables relevantes confirmadas en App Service:

- `DATABASE_DIR`
- `SECRET_OPENAIKEY`
- `AZURE_CONNECTION_STRING`
- `CLIENT_ID`
- `CLIENT_SECRET`
- `TENANT_ID`
- `SHAREPOINT_SITE`
- `SITE_URL_OFERTAS`
- `SITE_URL_PROYECTOS`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_OPENAI_PLANNER_DEPLOYMENT`
- `AZURE_OPENAI_INDEX_DEPLOYMENT`
- `AZURE_OPENAI_ANSWER_DEPLOYMENT`
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`

## Dónde Quedaron Los Datos

### Base de datos SQLite

#### Local

- `database/proyectos 9.db`

#### Azure

- Storage Account: `apphhdrive`
- File Share: `shimin-db`
- Ruta en el share: `proyectos 9.db`
- Mount dentro del contenedor: `/srv/app_principal/database`
- Ruta efectiva usada por la app: `/srv/app_principal/database/proyectos 9.db`

Nota:

- inicialmente se probó con un solo share
- se corrigió a dos shares separados porque App Service monta shares completos, no subdirectorios internos del share

### Storage de wiki, manifiestos y artefactos de soporte

#### Local

- `storage/llm_wiki.md`
- `storage/llm_wiki/index.md`
- `storage/llm_wiki/proposals/`
- `storage/llm_wiki/entries/`
- `storage/wiki_ingestion_manifest.csv`
- `storage/wiki_ingestion_emitted_manifest.csv`
- `storage/rag_parent_child_manifest.csv`
- `storage/rag_parent_child_emitted_manifest.csv`
- `storage/hh_excel_ingestion_manifest.csv`

#### Azure

- Storage Account: `apphhdrive`
- File Share: `shimin-storage`
- Mount dentro del contenedor: `/srv/app_principal/storage`

Estructura importante dentro de Azure Files:

- `llm_wiki.md`
- `llm_wiki/`
- `llm_wiki/proposals/`
- `llm_wiki/entries/`
- `wiki_ingestion_manifest.csv`
- `wiki_ingestion_emitted_manifest.csv`
- `rag_parent_child_manifest.csv`
- `rag_parent_child_emitted_manifest.csv`
- `hh_excel_ingestion_manifest.csv`

### Otros datos existentes en storage

También quedaron presentes en el share de storage carpetas auxiliares como:

- `commercial_offers_latest/`
- `emitted_offer_assets/`
- `emitted_offer_assets_test/`
- `emitted_offer_assets_test_o2362/`

Estas carpetas siguen asociadas al pipeline de sync/ingestión y no fueron eliminadas.

## Dónde Quedaron Los Wiki En Markdown

Hay dos niveles de wiki en Markdown.

### Wiki raíz consolidada

#### Local

- `storage/llm_wiki.md`

#### Azure

- Share: `shimin-storage`
- Ruta: `llm_wiki.md`
- Ruta montada en runtime: `/srv/app_principal/storage/llm_wiki.md`

### Páginas individuales por propuesta

#### Local

- `storage/llm_wiki/proposals/O-XXXX.md`

#### Azure

- Share: `shimin-storage`
- Ruta: `llm_wiki/proposals/O-XXXX.md`
- Ruta montada en runtime: `/srv/app_principal/storage/llm_wiki/proposals/O-XXXX.md`

### Entradas estructuradas de wiki

#### Local

- `storage/llm_wiki/entries/`

#### Azure

- Share: `shimin-storage`
- Ruta: `llm_wiki/entries/`
- Ruta montada en runtime: `/srv/app_principal/storage/llm_wiki/entries/`

## Mounts Finales En App Service

Mounts finales configurados:

- `shimin-data` -> share `shimin-db` -> mount `/srv/app_principal/database`
- `shimin-storage` -> share `shimin-storage` -> mount `/srv/app_principal/storage`

Esto es importante porque el backend resuelve rutas relativas desde `/srv/app_principal`.

## App Registration / Entra ID

Se reutilizó el App Registration existente:

- Client ID: `0104b363-efc0-488d-af2e-2cb652dd82e9`

Redirect URIs confirmadas:

- `https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net/oauth2callback`
- `http://localhost:8501`
- `https://delightful-grass-04d44f20f.7.azurestaticapps.net/.auth/login/aad/callback`

## Qué Quedó Automatizado

### Deploy del frontend

Quedó automatizado por GitHub Actions vía Static Web Apps:

- `.github/workflows/azure-static-web-apps-delightful-grass-04d44f20f.yml`

### Sync diario

Quedó versionado el workflow:

- `.github/workflows/sync-daily.yml`

Ese workflow llama al backend para:

- sincronizar propuestas nuevas desde SharePoint
- refrescar Master
- hacer backfill de wiki
- consultar estado final

## Problemas Encontrados Y Soluciones Aplicadas

### 1. `az acr build` no funcionó en `chilecentral`

Problema:

- fallo de ACR Tasks con `listBuildSourceUploadUrl`

Solución:

- build local con Docker
- `az acr login`
- `docker push apphshimin.azurecr.io/shimin-backend:v1`

### 2. Azure Files con un solo share no funcionaba bien para este layout

Problema:

- App Service monta el share completo, no una subcarpeta del share

Solución:

- separar en dos shares:
  - `shimin-db`
  - `shimin-storage`

### 3. `healthCheckPath` no se pudo fijar bien con `az webapp config set --generic-configurations`

Problema:

- parsing JSON defectuoso desde PowerShell/Azure CLI en este caso

Solución:

- usar `az rest` sobre `/config/web`

### 4. `linked backends` no funcionó con SWA Free

Problema:

- Azure exige `Standard` para esta capacidad

Solución:

- upgrade de SWA a `Standard`

## Estado Actual De Verificación

Verificaciones completadas:

- repo publicado en GitHub
- workflow SWA creado por Azure
- frontend compilado con éxito
- frontend respondiendo y redirigiendo a AAD
- backend enlazado a la SWA
- callback AAD agregado al App Registration
- backend respondiendo con datos reales
- wiki y RAG montados correctamente
- base SQLite disponible en runtime

## Qué Faltaría Revisar Manualmente

Aunque el deploy técnico quedó listo, conviene hacer una prueba funcional manual desde navegador con cuenta SHIMIN:

1. ingresar a la URL del frontend
2. autenticar vía Entra ID
3. abrir chat
4. consultar una propuesta real
5. probar sesión e historial
6. probar exportación
7. disparar un sync manual si se desea

## Archivos Del Repo Más Importantes Para Operación

- `frontend/staticwebapp.config.json`
- `.github/workflows/azure-static-web-apps-delightful-grass-04d44f20f.yml`
- `.github/workflows/sync-daily.yml`
- `deploy/01-storage.sh`
- `deploy/02-build-push.sh`
- `deploy/03-app-service.sh`
- `deploy/04-static-web-app.sh`
- `docs/DEPLOY_APPHH_FINAL.md`
- `docs/DEPLOY_AZURE.md`

## Recomendación Operativa

Usar este documento como estado real del ambiente y no como plan teórico. Si más adelante se quiere actualizar la app, el flujo recomendado es:

1. cambiar código local
2. build Docker local
3. push nueva imagen al ACR con nuevo tag
4. actualizar App Service al nuevo tag
5. push a GitHub para que SWA redeploye frontend si hubo cambios front
6. verificar `/api/config/status` y la URL del frontend