# Azure Deployment Plan

> **Status:** Validated

Generated: 2026-07-21 (America/Santiago)

---

## 1. Project Overview

**Goal:** Repair and deploy the synchronization path for the existing SHIMIN Proposal Intelligence production application, refresh the Planilla Master from its current SharePoint source, and verify SharePoint -> AI extraction -> RAG -> embeddings -> Wiki end to end.

**Path:** Modify an existing Azure production application. No infrastructure replacement or new Azure resources.

### Confirmed production findings

- Microsoft Graph authentication is working with the active App Registration.
- Two real proposal sync attempts downloaded files but failed on duplicate `rag_parent_sections.parent_id` values.
- The pending-winners queue contains 501 proposals and can repeat/stall on the same first batch.
- The embedded APScheduler is configured for `America/Santiago`, but its CronTrigger instances currently resolve in UTC.
- Master refresh currently re-imports a cached/local Excel and only downloads the configured blob when the local file is absent.
- The configured Master blob was last updated on 2026-03-10.
- The exact current Master workbook was found in SharePoint (`Documentos/SH001-REG-GC-005 Planilla Master.xlsx`), last modified on 2026-07-20T22:21:29Z.

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
9. Refresh Master, synchronize a controlled proposal, and compare RAG/embedding/Wiki counters in production.
10. Leave the production scheduler enabled for an automatic daily Master refresh followed by the proposal synchronization job.

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
- [x] Implement synchronization and Master refresh fixes
- [x] Run focused tests and backend system checks
- [x] Add `.dockerignore` and verify the container build context
- [x] Update status to `Ready for Validation`

### Phase 3: Validation

- [x] Invoke `azure-validate`
- [x] Add AZCLI recipe validation steps
- [x] All applicable validation checks pass
- [x] Record proof and update status to `Validated`

### Phase 4: Deployment

- [ ] Invoke `azure-deploy`
- [ ] Build and publish immutable backend image
- [ ] Update App Service and verify health
- [ ] Refresh current SharePoint Master
- [ ] Run controlled end-to-end synchronization
- [ ] Update status to `Deployed`

---

## 8. Validation Proof

Validation completed on 2026-07-21 before deployment. Bicep compilation,
template validation, and What-If are not applicable because this change deploys
application code to existing resources and contains no infrastructure templates.

| Check | Command Run | Result | Timestamp |
|-------|-------------|--------|-----------|
| Python syntax | `python -m compileall -q backend/app backend/tests` | Passed | 2026-07-21 |
| Reliability tests | `python -m unittest discover -s backend/tests -v` | 4 passed | 2026-07-21 |
| Workflow syntax | `yaml.safe_load(.github/workflows/deploy-backend.yml)` | Passed; 11 steps | 2026-07-21 |
| Whitespace | `git diff --check -- <deployment files>` | Passed; unrelated user-owned frontend workflow excluded | 2026-07-21 |
| Docker build | `docker build -t shimin-backend:validation -f backend/Dockerfile backend` | Passed; context reduced to 9.86 kB | 2026-07-21 |
| Container startup | Run validation image and GET `/api/config/status` | HTTP 200; scheduler started with two daily jobs in `America/Santiago` | 2026-07-21 |
| Azure CLI/auth | `az version`; `az account show` | CLI 2.80.0; correct confirmed subscription/tenant | 2026-07-21 |
| Existing resources | `az webapp show`; `az acr show`; `az acr check-health` | App Service running; ACR succeeded; registry auth/pull/DNS passed | 2026-07-21 |
| Azure Policy | `az policy assignment list` | Only existing Security Center built-in assignment; no deployment blocker | 2026-07-21 |
| Static role review | Review recipe and deployment model | No IaC or role changes; App Service has no managed identity and existing connection-based integrations are preserved | 2026-07-21 |

ACR Tasks pre-build was also attempted, but Azure reports that
`listBuildSourceUploadUrl` is unavailable for ACR in Chile Central. This is not a
deployment blocker: the existing GitHub workflow builds with Docker and pushes
directly to the same validated registry, and the identical Docker build passed
locally.

**Validated by:** `azure-validate` workflow, 2026-07-21T19:11:37-04:00

---

## 9. Files Expected to Change

| File | Purpose |
|------|---------|
| `backend/app/rag/parent_child.py` | Collision-safe replacement and embedding cleanup |
| `backend/app/services/proposal_sync_service.py` | Fair pending queue |
| `backend/app/services/scheduler.py` | Correct timezone and current Master refresh |
| `backend/app/services/sharepoint_client.py` | Exact Master discovery/download |
| `backend/app/services/master_repository.py` | Atomic SharePoint-first refresh with fallback |
| `backend/app/api/routes.py` | Async/source-aware Master refresh response |
| `backend/.dockerignore` | Minimal and secret-safe Docker build context |
| `backend/tests/test_sync_reliability.py` | Regression coverage |
| `.github/workflows/deploy-backend.yml` | Mandatory tests before image build/deployment |
| `.azure/deployment-plan.md` | Deployment workflow evidence |

---

## 10. Next Step

Deploy the validated commit through the existing GitHub Actions pipeline, then
refresh the live Master and run the controlled production synchronization check.
