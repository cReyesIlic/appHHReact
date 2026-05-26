# Política de almacenamiento — Azure Files vs Azure Blob

Decisión arquitectónica para el plataforma SHIMIN Proposal Intelligence sobre dónde vive cada tipo de dato. La meta es **costo predecible a 5000+ propuestas** sin perder rendimiento donde importa.

Última revisión: 2026-05-26.

---

## Regla en una línea

> Azure Files solo para datos que necesitan **semántica de filesystem** (sqlite, manifests, rewrite frecuente).
> Todo lo demás (PDFs, Excels, exports, artefactos derivados) → **Azure Blob**.

---

## Clasificación por tipo de dato

| Dato | Tamaño típico | Patrón acceso | Mutabilidad | Destino | Justificación |
|---|---|---|---|---|---|
| `database/proyectos 9.db` | ~800 MB y crecerá | Read/write constante por backend | Mutable, transaccional | **Files** | SQLite **requiere** file locks POSIX. En Blob se rompe. |
| `storage/proposals/{COD}/*.pdf` | 1–50 MB por PDF, 1486 carpetas | Lectura solo al ingestar (cold) | Inmutable post-descarga | **Blob** | Inmutable y leído 1 sola vez → workload textbook de Blob. ~5× más barato por GB. |
| `storage/emitted_offer_assets/pdf/{COD}/*.pdf` | igual | igual | igual | **Blob** | igual |
| `storage/emitted_offer_assets/excel/{COD}/*.xlsx` | <1 MB | Lectura al ingestar + Azure Function | Inmutable post-descarga | **Blob** | igual |
| `storage/emitted_offer_assets/zip_extracted/` | variable | Cold después de procesar | Inmutable | **Blob** | igual |
| `storage/llm_wiki.md` | <10 MB | Read constante (agente) | Mutable | **Files** | Lectura caliente, edición esporádica vía API. |
| `storage/llm_wiki/proposals/{COD}.md` | <100 KB × 1500 | Read frecuente (agente) | Mutable (auto-compilada) | **Files** | El agente la consulta en runtime → necesita low-latency reads. |
| `storage/llm_wiki/entries/` | <100 KB × N | Read/write API | Mutable | **Files** | Edición CRUD desde frontend. |
| `storage/hybrid_rag_embeddings*/` | crece con corpus | Read en cada query | Inmutable por chunk | **Files** (por ahora) | Reads constantes y latencia matters. Reevaluar si el corpus pasa 5 GB. |
| `storage/*.csv` manifests | <10 MB cada | Append/rewrite frecuente | Mutable | **Files** | Append-only logs, escritos en sync. |
| `storage/audit_*.json` | <1 MB | Write 1×, read raro | Inmutable | **Blob** | Auditorías son cold por definición. |
| `storage/exports/*` (PDF/Word generados) | 1–20 MB | Write 1×, descarga del usuario | Inmutable, efímera (TTL 30d) | **Blob** | Una descarga y se olvida. Blob + lifecycle rule auto-expira. |
| `backendlogs/`, `logs/`, `download.log` | crece | Append | Mutable | **Files** (chico) o stdout → App Insights | Los logs grandes mejor a App Insights, no a un filesystem. |

---

## Costo comparativo (referencia Chile Central)

| | Azure Files (Standard SMB) | Azure Blob (Hot LRS) |
|---|---|---|
| Storage | ~$0.06 / GB·mes | ~$0.018 / GB·mes |
| Read ops | gratis (incluido) | $0.004 / 10k |
| Write ops | gratis (incluido) | $0.05 / 10k |

Con la carga actual aproximada (PDFs ~30 GB proyectados a 5k propuestas):

| Escenario | Files puro | Files + Blob política |
|---|---|---|
| 30 GB PDFs + 2 GB SQLite + 1 GB wiki + 1 GB embeddings = 34 GB | $2.04/mes | SQLite/Files (4 GB) $0.24 + Blob (30 GB) $0.54 = **$0.78/mes** |
| A 100 GB total | $6/mes | $0.20 + $1.80 = **$2/mes** |

Ahorro de 60–70% del costo de storage. El delta crece a medida que aumentan PDFs.

---

## Plan de migración (por fases, no rompe nada hasta fase 3)

### Fase 0 — Hoy (estado actual)
Todo en File Share `shimin-data` montado en `/srv/app_principal/{database,storage}`. Backend escribe paths POSIX, no sabe que hay un mount detrás.

### Fase 1 — Monitoreo (este PR)
- Script `backend/scripts/monitor_share_usage.py` mide uso y alerta por email si pasa 70% de la cuota (35 GB de 50).
- Cron diario (GitHub Actions o scheduler interno).
- **Sin cambios al código de runtime.**

### Fase 2 — Provisionar Blob (preparación, opcional)
- Crear container `proposals` en `apphhdrive` (mismo storage account, distinta API).
- App Setting nueva: `PROPOSALS_BLOB_CONTAINER=proposals` (default vacío → mantiene comportamiento Files).
- Cliente nuevo `BlobAssetStore` que abstraiga read/write de un blob por `{kind}/{codigo}/{filename}`.
- **Sin cambios en el flujo todavía.**

### Fase 3 — Dual-write (migración suave)
- Modificar `save_pdf_locally` y `ingest_local_file` para escribir **a ambos**: File Share (legacy) + Blob (nuevo) si la env var está configurada.
- Lectura sigue desde Files. Validar que el dual-write funciona durante 1–2 semanas.

### Fase 4 — Backfill
- Script `backend/scripts/backfill_pdfs_to_blob.py` lee `storage/proposals/` y `storage/emitted_offer_assets/pdf|excel` y sube al Blob.
- Idempotente (skip si el blob ya existe con el mismo MD5).

### Fase 5 — Switch reads
- Lectura prioriza Blob; si no existe, fallback a Files.
- Después de validar, **detener** el escribir a Files para PDFs/Excels.

### Fase 6 — Cleanup
- Borrar `storage/proposals/` y `storage/emitted_offer_assets/{pdf,excel}/` del File Share.
- Aplicar lifecycle policy en Blob: PDFs > 1 año → tier Cool ($0.01/GB/mes). PDFs > 3 años → Archive.

---

## Qué NO migrar (regla firme)

- `proyectos 9.db` — **nunca** a Blob. SQLite + Blob es una receta para corrupción.
- `hybrid_rag_embeddings*` — quedarse en Files hasta que un benchmark muestre que Blob+cache también sirve.
- `llm_wiki/` — Files. La latencia de lectura importa para el agente.

---

## Lifecycle policies recomendadas (Blob)

Aplicar en `apphhdrive` después de Fase 4:

| Regla | Acción |
|---|---|
| Blob en container `proposals/pdf/` con `lastModified > 365 días` | Mover a Cool tier |
| Blob en container `proposals/pdf/` con `lastModified > 1095 días` | Mover a Archive (rehydrate ~horas para leer) |
| Blob en container `exports/` con `lastModified > 30 días` | **Borrar** (exports son efímeros) |

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Romper sync_code durante migración | Fase 3 (dual-write) corre por 2 semanas antes de cambiar reads. |
| Latencia de Blob al ingestar 1500 PDFs | Ingestar en batch + paralelismo (8 concurrentes). Blob soporta miles de rps. |
| Costo de egress si el backend lee blobs cross-region | Crear el container en `chilecentral` (misma región que `apphhshimin`). |
| Perder PDFs si fase 5 sale mal | Mantener File Share read-only durante 30 días post-switch antes de fase 6. |

---

## Decisión a tomar antes de Fase 2

- [ ] OK con costos de Blob LRS (~$1.80/mes para 100 GB).
- [ ] Confirmar región: `chilecentral` para mantener latencia local.
- [ ] Container privado (sin anonymous access).
- [ ] Auth: usar la misma `AZURE_CONNECTION_STRING` del storage account (ya en uso) o managed identity.

---

## Resumen ejecutivo

> Mover PDFs/Excels a Blob ahorra ~70% de storage cost a escala y libera el File Share para lo que realmente necesita filesystem (SQLite, wiki, manifests). La política es **dual-write durante la migración**: cero riesgo de pérdida, reversible hasta Fase 5. Recomendación: ejecutar Fase 1 (monitoreo) ahora, revisar Fase 2+ cuando el File Share pase 35 GB.
