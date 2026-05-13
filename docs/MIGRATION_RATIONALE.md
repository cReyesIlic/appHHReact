# Migración SHIMIN Proposal Intelligence — qué cambia y por qué

> Documento para entender la migración sin detalle técnico. La parte ejecutable está en `DEPLOY_APPHH_FINAL.md`.

---

## En una frase

Reemplazamos la app vieja en Streamlit (que nadie usa) por una nueva plataforma agéntica conversacional sobre los **mismos recursos Azure** que ya tienes pagando, ganando: chat libre con tool-calling, librería curada de 1 508 propuestas, búsqueda por sinónimos, sesiones por usuario, exportar a PDF/Word/Excel, todo con tu marca SHIMIN. Costo incremental: **~$10–15 USD/mes**.

---

## 📍 Punto de partida (hoy)

| Recurso Azure | Estado actual |
|---|---|
| `apphhshimin` (App Service) | Streamlit viejo. Nadie lo usa. |
| `apphshimin` (Container Registry) | Imagen Streamlit. |
| `ASP-appshimin` (Plan B1, ~$13/mes) | Pagado, infrautilizado. |
| `apphhdrive` (Storage) | Blob con `databases/proyectos 9.db` (Master) + PDFs. |
| `testapphhopenai` | Modelos Azure OpenAI: gpt-5.4, gpt-5.4-mini, gpt-5.4-nano, embeddings. |
| `docIntelhhSHIMIN` | Document Intelligence (no usado). |

**Problemas que tiene la versión Streamlit (por lo que nadie la usa):**
- Interfaz fea (Streamlit default, sin marca SHIMIN).
- Búsqueda rígida: hay que poner términos exactos. *"Tranque"* no encuentra *"depósito de relaves"*.
- Una sola sesión por usuario, sin historial.
- Sin distinguir tipos de pregunta (estadística vs comparar vs armar propuesta).
- No exporta documentos.
- Solo lee Master; no aprovecha 1 500 PDFs de propuestas pasadas.
- No tiene capa de conocimiento curado (lecciones, criterios, referencias).

---

## 🎯 Qué se construyó (este repo)

### 1. Agente conversacional con herramientas (estilo Claude Code)

El agente decide qué tool usar según la pregunta. **12 tools registradas**, **7 skills** que actúan como playbooks:

| Skill | Cuándo se activa |
|---|---|
| `armar_propuesta` | *"estoy armando una propuesta de…"* |
| `recomendar_por_tema` | *"qué propuestas hay de…"*, *"experiencia en…"* |
| `estadisticas_propuestas` | *"cuántas ganadas tiene…"*, *"distribución…"* |
| `comparar_propuestas` | *"compara X con Y"* |
| `datos_economicos` | *"cuánto cuesta…"*, *"HH…"*, *"monto…"* |
| `buscar_evidencia` | *"qué dice el alcance de…"* |
| `planificar_proyecto` | *"plan para…"*, *"etapas de…"* |

**Por qué importa**: en vez de tener un buscador genérico, cada tipo de pregunta tiene un protocolo de respuesta probado. La respuesta es **más completa, mejor estructurada y citada con fuente** (master / RAG / wiki).

### 2. Tres capas de conocimiento integradas

- **Master** (planilla Excel SHIMIN): 2 752 ofertas con cliente, estado, monto, HH, tipo de servicio.
- **RAG** (full-text search en PDFs): 1 508 propuestas con 51 770 fragmentos vectorizados + búsqueda lexical. El agente cita texto exacto.
- **Wiki / Biblioteca curada**: 1 508 páginas resumen (una por propuesta) + entradas tipo "lecciones aprendidas" que el agente prefiere antes que releer PDFs.

**Por qué importa**: el agente no se inventa nada. Cada respuesta cita el código (O-XXXX) y la fuente. Distingue **evidencia** (lo que dice el PDF) de **inferencia** (lo que deduce).

### 3. Búsqueda con sinónimos del dominio minero

El agente expande automáticamente: *"depósito de relaves"* → también busca *"tranque"*, *"relavera"*, *"embalse"*. *"Dewatering"* → también *"desagüe mina"*, *"drenaje"*, *"abatimiento"*. *"O-2200"* / *"SH-0428"* / *"428"* — todas las variantes encuentran lo mismo.

**Por qué importa**: nadie escribe los términos exactos. Con búsqueda literal, perdíamos 50 % de los matches relevantes.

### 4. Sesiones por usuario (estilo ChatGPT)

Cada usuario tiene su propia lista de conversaciones. Click en una sesión carga el historial completo. Botón "Nueva conversación". Renombrar / eliminar.

### 5. Exportar respuesta en 4 formatos

PDF (con header SHIMIN si Typst está disponible), PDF simple, Word (.docx), Excel (.xlsx con hoja por tabla). Click en botones bajo la respuesta del agente.

### 6. Sincronización automática

GitHub Actions corre todos los días a las 02:00 hora Chile: detecta propuestas nuevas en SharePoint → descarga PDF → indexa en RAG → embebe → compila página wiki. Master se refresca desde el Excel. **Sin intervención manual**.

### 7. Frontend con identidad SHIMIN

Refactor completo del frontend (React + Vite). Paleta cobre/dorado/azul-noche que ya existía pero no se aplicaba. Logo SHIMIN. 4 vistas: Chat, Master, Wiki/Librería, Operación. Filtros estructurados como chips (estado, cliente, tipo, disciplina). Indicador animado mientras el agente piensa.

---

## 💸 Cambios en infraestructura — qué y por qué

| Cambio | Por qué |
|---|---|
| **App Service Plan B1 → B2** | B1 tiene 1.75 GB RAM. El backend (FastAPI + embeddings + agente + PDF parser) necesita 2-2.5 GB en pico. B2 da 3.5 GB. Costo: +$13/mes. |
| Reemplazar Streamlit por **FastAPI containerizado** | Streamlit no soporta tool-calling, no escala, no permite UI custom decente. FastAPI + React es estándar moderno y mucho más eficiente. |
| Agregar **Static Web App** (Free tier) al frente | Da SSL, dominio custom, **SSO con Entra ID built-in** y proxy al backend. Sin costo. Reemplaza la necesidad de implementar OAuth manualmente. |
| Migrar SQLite a **Azure Files** (no Blob) | Blob no permite escrituras concurrentes en el mismo archivo. Azure Files sí, y SQLite con WAL funciona estable. Costo: +$2/mes. |
| Mover secrets a **Key Vault** | Hoy están en `.env`. Key Vault da rotación, auditoría, sin exposición en commit. Gratis para nuestro volumen. |
| Activar **Always On** | Sin esto, el container se duerme tras 20 min de idle y la primera consulta tarda 5-10 s. Con B2 es gratis. |
| Activar **Health Check** | Si el container se queda colgado, Azure lo reinicia solo. Sin esto, queda muerto hasta intervención manual. |
| **GitHub Actions** para cron diario | Alternativa: Container Apps Job ($1/mes) o Logic App ($0.50/mes). GitHub es gratis y versionable. |

**Lo que NO cambia**:
- Azure OpenAI `testapphhopenai` — sin cambios, los modelos siguen iguales.
- Container Registry `apphshimin` — mismo registry, solo nueva imagen.
- Storage `apphhdrive` — mismo storage, solo agrega un File Share dentro.
- Plan `ASP-appshimin` — mismo plan (solo upgrade B1 → B2).
- Document Intelligence `docIntelhhSHIMIN` — reservado para futuro (mejor parsing PDFs).

---

## 🔐 OAuth / sesiones — qué cambia para el usuario

**Antes**:
- URL pública sin auth (o con un login manual mediocre).
- Sin distinguir quién pregunta qué.

**Después**:
- Usuario abre `https://shimin.azurestaticapps.net`.
- Si no está logueado, Microsoft pide credenciales corporativas (`@shimin.cl`).
- Si pertenece al tenant SHIMIN, entra; si no, se le bloquea.
- El backend sabe automáticamente quién es (vía Entra ID) y carga sus sesiones.
- Logout disponible en `/logout`.

**Reusa el App Registration que YA existe** en tu tenant (`0104b363-efc0-488d-af2e-2cb652dd82e9`). Solo hay que agregar un redirect URI nuevo (el de Static Web App) y permisos `User.Read`. **No requiere App Registration nueva.**

---

## 💵 Costos antes vs después

| | Hoy (Streamlit infrautilizado) | Después (nueva app activa) |
|---|---|---|
| App Service Plan | B1 ~$13/mes | B2 ~$26/mes |
| Container Registry | Basic ~$5/mes | Basic ~$5/mes |
| Storage | Blob (Master) | Blob + File Share +$2/mes |
| Static Web App | — | $0 (Free) |
| Key Vault | — | $0 |
| Logs/Insights | — | $0 (5 GB free) |
| Azure OpenAI | ~$0 (sin uso real) | ~$3-10/mes (uso interno SHIMIN) |
| **Total** | **~$18/mes** | **~$36–43/mes** |
| **Delta** | | **+$18–25/mes** |

Por **$20 USD/mes más** se obtiene:
- Plataforma usable que el equipo va a usar (vs Streamlit muerto).
- 1 508 propuestas indexadas + sintetizadas (vs solo Master).
- Búsqueda inteligente con sinónimos (vs literal).
- 7 skills de agente (vs prompt simple).
- Exportar documentos (vs copy-paste).
- Auth corporativa real (vs ad-hoc).
- Auto-sync diario (vs proceso manual).

---

## ⏱️ Plan de migración (resumen ejecutivo)

| Etapa | Tiempo estimado | Riesgo |
|---|---|---|
| Audit + verificar SKU del plan | 15 min | Cero |
| Upgrade plan B1 → B2 | 1 min (no downtime) | Bajo — Azure swap rolling |
| Build imagen + subir File Share | 30 min | Bajo |
| Apuntar App Service a la nueva imagen | 5 min (Streamlit deja de servir) | Medio — verificar que el container arranca antes de quitar el viejo |
| Crear Static Web App + linkear backend | 15 min + build inicial | Bajo |
| Configurar redirect URI en Entra ID | 5 min en portal | Bajo |
| Probar login + sesión E2E | 15 min | — |
| Mover secrets a Key Vault | 30 min | Bajo |
| Configurar cron + budget alert | 10 min | Cero |
| **Total horas-hombre** | **~2-3 horas** | |

**Rollback**: si algo falla, `az webapp config container set` con la imagen Streamlit vieja restablece el estado anterior. Cero pérdida de datos.

---

## 🎯 Qué hay que aprobar / decidir

1. **Upgrade del plan a B2** (+$13/mes). Si presupuesto es estricto, alternativas:
   - Quedar en B1, optimizar imagen para 1.5 GB (más trabajo, riesgo de OOM).
   - Migrar a Container Apps Consumption (~$10/mes, con cold-start 3-8 s).
2. **OK para eliminar Streamlit viejo** del App Service `apphhshimin`. (Confirmado por usuario: "nadie las usa, naide la va a extrañar").
3. **Quién es el "admin" de la App Registration `0104b363...`** para agregar el redirect URI nuevo. Si no eres tú, coordinar.
4. **Repo GitHub** para conectar a Static Web App (si el repo es privado, dar permiso al workflow).
5. **Confirmar dominio**: ¿queremos `shimin-frontend.azurestaticapps.net` (gratis) o algo tipo `propuestas.shimin.cl` (requiere DNS + cert custom)?

---

## 📂 Documentos relacionados

- `DEPLOY_APPHH_FINAL.md` — pasos técnicos ejecutables uno por uno.
- `deploy/01-storage.sh`, `02-build-push.sh`, `03-app-service.sh`, `04-static-web-app.sh` — scripts idempotentes.
- `.github/workflows/sync-daily.yml` — cron diario.
- `frontend/staticwebapp.config.json` — config OAuth Entra (a commitear).
