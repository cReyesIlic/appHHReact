# Azure Deployment Plan

> **Status:** Validated (pipeline registry release)

Generated: 2026-07-21 (America/Santiago)

---

## 1. Project Overview

**Goal:** Repair and deploy the synchronization path for the existing SHIMIN Proposal Intelligence production application, refresh the Planilla Master from its current SharePoint source, verify SharePoint -> AI extraction -> RAG -> embeddings -> Wiki end to end, and expose durable per-project coverage/quality/version data with automatic reprocessing.

**Path:** Modify an existing Azure production application. No infrastructure replacement or new Azure resources.

### Confirmed production findings

- Microsoft Graph authentication is working with the active App Registration.
- Two real proposal sync attempts downloaded files but failed on duplicate `rag_parent_sections.parent_id` values.
- The pending-winners queue contains 501 proposals and can repeat/stall on the same first batch.
- The embedded APScheduler is configured for `America/Santiago`, but its CronTrigger instances currently resolve in UTC.
- Master refresh currently re-imports a cached/local Excel and only downloads the configured blob when the local file is absent.
- The configured Master blob was last updated on 2026-03-10.
- The exact current Master workbook was found in SharePoint (`Documentos/SH001-REG-GC-005 Planilla Master.xlsx`), last modified on 2026-07-20T22:21:29Z.
- The first repair release (`116cbff`) is live and healthy; production synchronization of `O-2637` processed 12 PDF/DOCX/XLSX files into 18 parent chunks, 348 child chunks/embeddings, and a Wiki page.
- A real main-chat trace successfully called Master, Wiki, RAG, and staffing tools; the static registry contains 22 exposed tools and 22 handlers.
- The first release smoke test exposed an independent startup race: the budget extractor received a successful Azure Function response but SQLite could not open its mounted parent directory.
- Root cause was confirmed from the SQLite header: the 812 MB database was in WAL mode on an Azure Files SMB mount. WAL uses shared-memory sidecars and is not supported safely on a network filesystem across container restarts.

---

## 2. Requirements

| Attribute | Value |
|-----------|-------|
| Classification | Production, internal SHIMIN application |
| Scale | Small (<1,000 users), document-heavy background processing |
| Budget | Preserve current resources and SKUs; no new recurring infrastructure cost |
| Subscription | Azure subscription 1 (`7bd77a3d-c2d9-4766-98a1-fc11527db7c5`) - confirmed by user |
| Primary location | Chile Central - confirmed by user |
| Data sources | SharePoint GerenciaComercial, Azure Blob fallback, mounted Azure Files/SQLite |
| Policy constraints | Existing Security Center built-in assignment; no additional deny policies detected |

---

## 3. Components Detected

| Component | Type | Technology | Path |
|-----------|------|------------|------|
| Backend | API + embedded scheduler | Python 3.12, FastAPI, APScheduler | `backend/` |
| Frontend | SPA | React + Vite | `frontend/` |
| Proposal storage/index | Persistent data | Azure Files + SQLite + Azure OpenAI embeddings | mounted under `/srv/app_principal` |
| Budget extractor | Azure Function | Python | `budget-extractor-function/` (outside this deployment scope) |
| Deployment pipeline | CI/CD | GitHub Actions + Azure CLI + ACR | `.github/workflows/deploy-backend.yml` |

No GitHub Copilot SDK markers were detected.

---

## 4. Recipe Selection

**Selected:** AZCLI through the existing GitHub Actions/ACR/App Service pipeline.

**Rationale:** The application already has tested Azure CLI deployment automation, Dockerfiles, an ACR repository, and an App Service container. Introducing AZD/Bicep/Terraform for this code-only repair would create unnecessary infrastructure drift.

---

## 5. Architecture

**Stack:** Existing App Service container architecture.

### Existing service mapping

| Component | Azure Service | Existing SKU/location |
|-----------|---------------|-----------------------|
| Backend container | App Service `apphhshimin` | Linux container on B2 plan, Chile Central |
| Container image | ACR `apphshimin` | Standard, Chile Central |
| Persistent files/SQLite | Storage `apphhdrive` | Standard_LRS, Chile Central |
| LLM and embeddings | Azure OpenAI `testapphhopenai` | East US, existing deployments |
| Frontend | Static Web App `shimin-frontend` | Existing, East US 2 |
| Source documents | Microsoft 365 SharePoint | GerenciaComercial |

### Planned application changes

1. Make parent/child identifiers collision-safe and remove orphaned embeddings during a per-code replacement.
2. Make the winner-sync queue fair so failed/no-file entries cannot permanently starve later proposals.
3. Apply the Chile timezone explicitly to every scheduler CronTrigger.
4. Download the exact current Master workbook from SharePoint before refreshing SQLite; retain Blob/local fallback and update the Blob fallback after successful validation.
5. Return source metadata from Master refresh and preserve atomicity so an invalid workbook cannot replace the working Master.
6. Add focused tests for collision handling, queue ordering, scheduler timezone, and Master source refresh.
7. Add a Docker context allowlist/exclusion boundary so local virtual environments, secrets, databases, and storage data are never uploaded during image builds.
8. Deploy only backend changes, preserving unrelated local user changes.
9. Add `proposal_pipeline_registry`, a durable per-project table containing PDF/DOCX/Excel inventory, source signatures, RAG/embedding/Wiki results, AI quality scores, component versions, errors, and reprocesing state.
10. Detect new or modified emitted documents by Graph ID/eTag/modified time/size and fairly mix changed, new, and stale-version proposals in every run.
11. Make component-version changes automatically enqueue proposals for the newer RAG/Wiki pipeline while retaining a manual forced-reprocess action.
12. Ask the Wiki AI to score source/RAG sufficiency and Wiki coverage/fidelity; retain an objective heuristic fallback and surface both in the operations table.
13. Preserve Wiki entry identity/file paths during forced recompilation so reprocessing cannot create duplicate entries.
14. Expose the project coverage table in the frontend with PDF/DOCX/Excel counts, parsed Excel, RAG, Wiki, quality, pipeline version, and reprocess state.
15. Run five automatic Chile-time cycles daily (02:15, 07:15, 12:15, 17:15, 22:15), each refreshing Master first and then processing a fair bounded batch.
16. Ensure Azure Files mount-point directories exist in the container and before the budget extractor opens SQLite.
17. Migrate SQLite from WAL to network-safe DELETE journaling during application startup, before health traffic, and use the lightweight `/health` endpoint for deployment warm-up.

---

## 6. Provisioning Limit Checklist

This is a code-only deployment to existing resources. `azure-quotas` was invoked and the resource inventory contains zero resources to provision, so no regional quota or capacity increase is required.

| Resource Type | Number to Deploy | Total After Deployment | Limit/Quota | Notes |
|---------------|------------------|------------------------|-------------|-------|
| New Azure resources | 0 | Existing resources unchanged | Not applicable | Existing resources are provisioned and report `Succeeded` |

**Status:** All planned deployment quantities are within limits (zero new resources).

---

## 7. Execution Checklist

### Phase 1: Planning

- [x] Analyze workspace
- [x] Gather requirements from the existing production deployment and user authorization
- [x] Confirm subscription and location with user
- [x] Prepare resource inventory
- [x] Validate capacity with `azure-quotas` (zero new resources)
- [x] Scan codebase
- [x] Select AZCLI recipe
- [x] Plan architecture and repair scope
- [x] User approved this completed plan, including automatic operation

### Phase 2: Execution

- [x] Load App Service/AZCLI deployment references
- [x] Implement synchronization, Master refresh, registry, quality, and automatic reprocess fixes
- [x] Run focused tests and backend system checks
- [x] Add `.dockerignore` and verify the container build context
- [x] Update status to `Ready for Validation` for the expanded registry release

### Phase 3: Validation

- [x] Re-run `azure-validate` checks for the expanded release
- [x] All applicable validation checks pass
- [x] Record proof and update status to `Validated`

### Phase 4: Deployment

- [x] First repair release deployed (`116cbff`)
- [ ] Deploy expanded pipeline registry release
- [ ] Verify five-run production schedule and persistent registry endpoint
- [ ] Reprocess a controlled production proposal and verify AI quality/version fields
- [ ] Re-run budget extractor smoke test
- [ ] Update status to `Deployed`

---

## 8. Validation Proof

Validation completed on 2026-07-21 before deployment. Bicep compilation,
template validation, and What-If are not applicable because this change deploys
application code to existing resources and contains no infrastructure templates.

| Check | Command Run | Result | Timestamp |
|-------|-------------|--------|-----------|
| Python syntax | `python -m compileall -q backend/app backend/tests` | Passed | 2026-07-21 |
| Reliability tests | `python -m pytest backend/tests/test_sync_reliability.py -q` | 11 passed, including WAL-to-DELETE migration | 2026-07-21 |
| Frontend build | `npm run build` | Passed; 2,011 modules transformed | 2026-07-21 |
| Workflow syntax | `yaml.safe_load(.github/workflows/deploy-backend.yml)` | Passed; 11 steps | 2026-07-21 |
| Whitespace | `git diff --check -- <deployment files>` | Passed; unrelated user-owned frontend workflow excluded | 2026-07-21 |
| Docker build | `docker build -t shimin-backend:pipeline-registry-validation -f backend/Dockerfile backend` | Passed; context 596 kB | 2026-07-21 |
| Container startup | Run validation image and GET `/health` + `/api/sync/registry` | HTTP 200; pipeline version `2026.07.21.2` | 2026-07-21 |
| SQLite network mode | Run validation image and inspect startup bootstrap | Journal mode `delete`; `/health` and registry HTTP 200 | 2026-07-21 |
| Azure CLI/auth | `az version`; `az account show` | CLI 2.80.0; correct confirmed subscription/tenant | 2026-07-21 |
| Existing resources | `az webapp show`; `az acr show`; `az acr check-health` | App Service running; ACR succeeded; registry auth/pull/DNS passed | 2026-07-21 |
| Azure Policy | `az policy assignment list` | Only existing Security Center built-in assignment; no deployment blocker | 2026-07-21 |
| Static role review | Review recipe and deployment model | No IaC or role changes; App Service has no managed identity and existing connection-based integrations are preserved | 2026-07-21 |

ACR Tasks pre-build was also attempted, but Azure reports that
`listBuildSourceUploadUrl` is unavailable for ACR in Chile Central. This is not a
deployment blocker: the existing GitHub workflow builds with Docker and pushes
directly to the same validated registry, and the identical Docker build passed
locally.

**Validated by:** `azure-validate` workflow, expanded release revalidated 2026-07-21T19:44:20-04:00

---

## 9. Files Expected to Change

| File | Purpose |
|------|---------|
| `backend/app/rag/parent_child.py` | Collision-safe replacement and embedding cleanup |
| `backend/app/services/proposal_sync_service.py` | Fair pending queue |
| `backend/app/services/pipeline_registry.py` | Durable per-project source, quality, version, and reprocessing registry |
| `backend/app/services/scheduler.py` | Correct timezone, five daily cycles, and current Master refresh |
| `backend/app/services/sharepoint_client.py` | Exact Master discovery/download |
| `backend/app/services/wiki_auto_compiler.py` | AI RAG/Wiki quality scoring and identity-preserving recompilation |
| `backend/app/services/structured_wiki.py` | Reuse the existing Wiki file during upsert |
| `backend/app/services/ops_dashboard.py` | Coverage/quality/version API rows |
| `backend/app/services/budget_extractor_client.py` | Safe SQLite mount-point initialization |
| `backend/app/services/database_runtime.py` | WAL-to-DELETE startup migration and runtime status for Azure Files |
| `backend/app/main.py` | Prepare SQLite before scheduler/traffic |
| `backend/app/services/master_repository.py` | Atomic SharePoint-first refresh with fallback |
| `backend/app/api/routes.py` | Async/source-aware Master refresh response |
| `backend/Dockerfile` | Create Azure Files mount points in the image |
| `backend/tests/test_sync_reliability.py` | Regression coverage |
| `frontend/src/components/ops/CoverageTable.jsx` | Operational project coverage/quality/reprocess table |
| `frontend/src/components/library/SyncPanel.jsx` | Automatic schedule and pipeline status UI |
| `.github/workflows/deploy-backend.yml` | Mandatory tests, lightweight health probe, and HTTP-aware budget smoke test |
| `.azure/deployment-plan.md` | Deployment workflow evidence |

---

## 10. Next Step

Complete final validation, commit/push the scoped release, deploy it through the
existing GitHub Actions pipeline, then verify the registry, schedule, controlled
reprocess, Wiki quality, chat tool consistency, and budget extractor in production.
