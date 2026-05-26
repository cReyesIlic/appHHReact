# Setup de GitHub Actions para deploy automatico

Workflows en `.github/workflows/`:
- `deploy-backend.yml` — build + push a ACR + update `apphhshimin`
- `deploy-budget-function.yml` — deploy de `apphh-budget-extractor`

Ambos disparan en `push` a `main` que toque sus paths respectivos del repo actual, o manualmente con `workflow_dispatch`.

---

## 1. Crear el Service Principal (una sola vez)

Esto da a GitHub Actions permisos para deployar a tu suscripción Azure.

```bash
az ad sp create-for-rbac \
  --name "github-actions-appHHReact" \
  --role contributor \
  --scopes /subscriptions/7bd77a3d-c2d9-4766-98a1-fc11527db7c5/resourceGroups/appHH \
  --sdk-auth
```

Devuelve un JSON como:
```json
{
  "clientId": "...",
  "clientSecret": "...",
  "subscriptionId": "7bd77a3d-c2d9-4766-98a1-fc11527db7c5",
  "tenantId": "e6912f7f-971b-4479-8cc7-cf5cfe63913c",
  ...
}
```

**Copia el JSON completo** — es el secret de GitHub.

---

## 2. Agregar secret a GitHub

Repo: `cReyesIlic/appHHReact`. Necesitas hacerlo desde la UI o `gh` CLI.

### Vía UI

1. Ir a https://github.com/cReyesIlic/appHHReact/settings/secrets/actions
2. **New repository secret**
3. Nombre: `AZURE_CREDENTIALS`
4. Value: el JSON completo del paso 1
5. Save

### Vía gh CLI (si lo tienes)

```bash
echo '{...el JSON del paso 1...}' | gh secret set AZURE_CREDENTIALS -R cReyesIlic/appHHReact
```

---

## 3. (Opcional) Crear environment "production"

Los workflows usan `environment: production`. Esto permite:
- Required reviewers (pedir aprobación manual antes del deploy)
- Wait timer
- Branch protection

Si NO quieres environments aún, edita los YAMLs y borra la línea `environment: production`.

Si los quieres:
1. https://github.com/cReyesIlic/appHHReact/settings/environments
2. **New environment** → nombre `production`
3. (Opcional) marcar **Required reviewers** con tu usuario para que cada deploy requiera tu OK manual

---

## 4. Primer deploy

Una vez agregado el secret:

```bash
# Cualquier cambio en backend/ o budget-extractor-function/ + push dispara el workflow
git add backend budget-extractor-function .github deploy/GITHUB_ACTIONS_SETUP.md
git commit -m "ci: github actions deploy backend + budget function"
git push origin main
```

O dispara manualmente desde la UI:
1. https://github.com/cReyesIlic/appHHReact/actions
2. Click en el workflow
3. **Run workflow** → seleccionar branch `main` → Run

---

## 5. Verificar

Después del push, en https://github.com/cReyesIlic/appHHReact/actions deberías ver:

| Step | Backend | Function |
|---|---|---|
| Checkout | ✓ | ✓ |
| Azure login | ✓ | ✓ |
| Build & push | ~3-5 min | n/a |
| Pip install | n/a | ~1 min |
| Deploy | ~30s | ~3-5 min |
| Health check | ~10s | ~10s |

URLs de verificación post-deploy:
- Backend: https://apphhshimin-awabbnayfbawf2b5.chilecentral-01.azurewebsites.net/api/config/status
- Function: https://apphh-budget-extractor.azurewebsites.net/api/health

---

## 6. Rollback manual

Si algo sale mal, vuelve a la imagen anterior:

```bash
# Backend
az webapp config container set -g appHH -n apphhshimin \
  --docker-custom-image-name apphshimin.azurecr.io/shimin-backend:3f60e40
az webapp restart -g appHH -n apphhshimin

# Function (re-deploy versión anterior desde GH Actions: Actions → workflow → corrida anterior → Re-run)
```

Alternativa para rollback de backend via Actions:

1. Ir a GitHub Actions y buscar el SHA corto de una corrida exitosa anterior.
2. Ejecutar manualmente el mismo comando `az webapp config container set` apuntando a ese tag.
3. Reiniciar `apphhshimin`.

---

## 7. Path filters explicados

Los workflows solo se disparan si el push **toca** ciertos paths:

| Workflow | Paths que lo disparan |
|---|---|
| `deploy-backend.yml` | `backend/**` |
| `deploy-budget-function.yml` | `budget-extractor-function/**` |

Cambios solo en `frontend/`, `docs/`, `deploy/` no disparan ningún deploy. Útil para evitar deploys innecesarios.

---

## 8. Troubleshooting

| Error | Causa | Solución |
|---|---|---|
| `Error: No subscriptions found for ...` | Service principal sin permisos en la suscripción | Re-ejecutar `az ad sp create-for-rbac` con el `--scopes` correcto |
| `AcrPushDenied` | SP no puede push a ACR | Agregar rol AcrPush: `az role assignment create --assignee <clientId> --role AcrPush --scope $(az acr show -n apphshimin --query id -o tsv)` |
| Health check 504 | Container tarda en arrancar | Aumentar el sleep entre intentos o el número de intentos en el workflow |
| `Functions-action` falla con build/deploy | App settings o empaquetado inconsistentes | Verificar `SCM_DO_BUILD_DURING_DEPLOYMENT=true`, `ENABLE_ORYX_BUILD=true` y el contenido de `budget-extractor-function/` |

---

## Estado actual (al 2026-05-26)

- [x] Service principal: **falta crear** (paso 1)
- [x] Secret `AZURE_CREDENTIALS` en GitHub: **falta agregar** (paso 2)
- [x] Workflows `.yml`: creados y ajustados al root real del repo, esperando primer push
- [ ] Environment `production`: opcional
- [ ] Primer deploy ejecutado: pendiente

Próximo paso: ejecutar los pasos 1 y 2, luego hacer push.
