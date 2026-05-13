# Sanity Check 5 Min Release

Fecha: 2026-05-13

Checklist corto para validar en 5 minutos que frontend, autenticación, backend y datos siguen bien después de un cambio o redeploy.

## 1. Frontend Publicado

URL:

- `https://delightful-grass-04d44f20f.7.azurestaticapps.net`

Verificar:

1. abre en incógnito
2. confirma que redirige a login Microsoft si no hay sesión
3. después de login, la app carga y no queda en bucle

Si falla:

- revisar `frontend/staticwebapp.config.json`
- revisar App Registration redirect URI
- revisar `enableIdTokenIssuance`

## 2. Requests Del Frontend

Abrir DevTools Network o Console.

Verificar:

1. no debe aparecer `127.0.0.1:8010`
2. no debe aparecer `localhost:8010`
3. las llamadas deben salir como `/api/...`

Si falla:

- revisar `frontend/src/lib/api.js`
- revisar si el bundle viejo quedó cacheado
- revisar si el workflow SWA terminó el redeploy

## 3. Backend Arriba

Comandos:

```bash
curl.exe https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net/api/config/status
curl.exe https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net/api/sync/status
```

Verificar:

1. ambos responden
2. `rag_proposals` mayor que 0
3. `wiki_pages_existing` mayor que 0
4. sin `coverage_warnings`

## 4. Backend Link SWA

Comando:

```bash
az staticwebapp show -n shimin-frontend -g appHH --query "{sku:sku.name,linkedBackends:linkedBackends}" -o json
```

Verificar:

1. `sku` debe ser `Standard`
2. `linkedBackends` debe estar en `Succeeded`

## 5. Auth Entra ID

Comando:

```bash
az ad app show --id 0104b363-efc0-488d-af2e-2cb652dd82e9 --query "{implicit:web.implicitGrantSettings,redirectUris:web.redirectUris}" -o json
```

Verificar:

1. `enableIdTokenIssuance` en `true`
2. existe el callback de la SWA

Callback esperado:

- `https://delightful-grass-04d44f20f.7.azurestaticapps.net/.auth/login/aad/callback`

## 6. Imagen Correcta

Comandos:

```bash
az webapp show -n apphhshimin -g appHH --query "siteConfig.linuxFxVersion" -o tsv
az acr repository show-tags -n apphshimin --repository shimin-backend -o table
```

Verificar:

1. App Service apunta al tag esperado
2. ese tag existe en ACR

## 7. Datos Montados

Comando:

```bash
az webapp config storage-account list -n apphhshimin -g appHH -o json
```

Verificar:

1. `/srv/app_principal/database` -> `shimin-db`
2. `/srv/app_principal/storage` -> `shimin-storage`

## 8. Prueba Funcional Minima

Dentro de la app:

1. abre o crea una sesión
2. manda una pregunta corta
3. revisa que cargue historial/sesiones
4. revisa que no haya error de CORS ni `Failed to fetch`

## Resultado Esperado

Si los 8 puntos pasan:

- frontend bien
- auth bien
- linking bien
- backend bien
- datos bien

Si falla algo, usar:

- `docs/MAPEO_FRONTEND_BACKEND_VERIFICACION.md`

como guía de diagnóstico completa.