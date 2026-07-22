function resolveApiBase() {
  if (import.meta.env.VITE_API_BASE !== undefined) {
    return import.meta.env.VITE_API_BASE;
  }

  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host === "localhost" || host === "127.0.0.1") {
      return "http://127.0.0.1:8010";
    }
  }

  return "";
}

const API_BASE = resolveApiBase();

export class ApiError extends Error {
  constructor(message, { status, detail, path } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.path = path;
  }
}

async function jsonFetch(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, options);
  } catch (exc) {
    // Network-level (CORS, offline, DNS)
    throw new ApiError(`Sin conexión con el backend (${exc.message})`, { status: 0, path });
  }
  if (!response.ok) {
    const raw = await response.text();
    let detail = raw;
    try {
      const parsed = JSON.parse(raw);
      detail = parsed.detail || parsed.message || parsed.error || raw;
    } catch {
      /* texto plano */
    }
    const friendly =
      response.status === 404 ? `No encontrado: ${detail}` :
      response.status === 401 ? "No autenticado — vuelve a iniciar sesión" :
      response.status === 403 ? "Sin permisos para esta acción" :
      response.status === 502 ? `Error del proveedor externo: ${detail}` :
      response.status === 504 ? "Timeout — el sync tardó demasiado, vuelve a intentar con menos elementos" :
      response.status >= 500 ? `Error del servidor (${response.status}): ${detail}` :
      detail;
    throw new ApiError(friendly, { status: response.status, detail, path });
  }
  return response.json();
}

export async function sendChat(payload) {
  return jsonFetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getConfigStatus() {
  return jsonFetch("/api/config/status");
}

export function getMe() {
  return jsonFetch("/api/me");
}

export function getCreditsStatus() {
  return jsonFetch("/api/credits/status");
}

export function getMemory() {
  return jsonFetch("/api/memory");
}

export function saveMemory(payload) {
  return jsonFetch("/api/memory", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteMemory(id) {
  return jsonFetch(`/api/memory/${id}`, { method: "DELETE" });
}

export function getOpsDashboard(limit = 80) {
  return jsonFetch(`/api/ops/dashboard?limit=${limit}`);
}

export function getOpsCoverage({ estado = "PG", limit = 5000 } = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (estado) params.set("estado", estado);
  return jsonFetch(`/api/ops/coverage?${params.toString()}`);
}

export function getCoverageWiki(codigo) {
  return jsonFetch(`/api/ops/coverage/${encodeURIComponent(codigo)}/wiki`);
}

export async function uploadCoverageAsset(codigo, file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/ops/coverage/${encodeURIComponent(codigo)}/upload`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(text || `HTTP ${response.status}`, { status: response.status, detail: text });
  }
  return response.json();
}

export function searchMaster(payload) {
  return jsonFetch("/api/master/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function refreshMaster() {
  return jsonFetch("/api/master/refresh", { method: "POST" });
}

export function getHHByCode(code, limit = 80) {
  return jsonFetch(`/api/hh/${encodeURIComponent(code)}?limit=${limit}`);
}

export function buildWiki(markdown) {
  return jsonFetch("/api/wiki/build", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ markdown }),
  });
}

export function getWikiSections() {
  return jsonFetch("/api/wiki/sections");
}

export function getWikiMarkdown() {
  return jsonFetch("/api/wiki/markdown");
}

export function getWikiEntries() {
  return jsonFetch("/api/wiki/entries");
}

export function getWikiEntry(id) {
  return jsonFetch(`/api/wiki/entries/${encodeURIComponent(id)}`);
}

export function getWikiQuickAccess() {
  return jsonFetch("/api/wiki/quick-access");
}

export function saveWikiEntry(entry, id = null) {
  return jsonFetch(id ? `/api/wiki/entries/${id}` : "/api/wiki/entries", {
    method: id ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  });
}

export function deleteWikiEntry(id) {
  return jsonFetch(`/api/wiki/entries/${id}`, { method: "DELETE" });
}

export function reindexWiki() {
  return jsonFetch("/api/wiki/reindex", { method: "POST" });
}

export function autoCreateWiki(payload) {
  return jsonFetch("/api/wiki/auto-create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function testWiki(query, mode = "content") {
  return jsonFetch("/api/wiki/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, mode, limit: 8 }),
  });
}

export function getFilterOptions() {
  return jsonFetch("/api/search/filter-options");
}

export function listSessions(limit = 50) {
  return jsonFetch(`/api/sessions?limit=${limit}`);
}

export function createSession(title = "Nueva conversación") {
  return jsonFetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export function getSession(sessionId) {
  return jsonFetch(`/api/sessions/${sessionId}`);
}

export function renameSession(sessionId, title) {
  return jsonFetch(`/api/sessions/${sessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export function deleteSession(sessionId) {
  return jsonFetch(`/api/sessions/${sessionId}`, { method: "DELETE" });
}

export function getSyncStatus() {
  return jsonFetch("/api/sync/status");
}

export function syncDiscoverNew(limit = 200) {
  return jsonFetch(`/api/sync/discover-new?limit=${limit}`);
}

export function syncNew(limit = 20, forceWiki = false) {
  return jsonFetch(`/api/sync/new?limit=${limit}&force_wiki=${forceWiki}`, {
    method: "POST",
  });
}

export function syncCode(codigo, forceWiki = false) {
  return jsonFetch(`/api/sync/code/${encodeURIComponent(codigo)}?force_wiki=${forceWiki}`, {
    method: "POST",
  });
}

export function syncBackfillWiki(payload = {}) {
  return jsonFetch("/api/sync/backfill-wiki", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function discoverGanadasPendientes() {
  return jsonFetch("/api/sync/ganadas-pendientes");
}

export function syncGanadas(limit = 10) {
  return jsonFetch(`/api/sync/ganadas?limit=${limit}`, { method: "POST" });
}

export async function ingestUpload(file, { kind = null, target = "rag" } = {}) {
  const form = new FormData();
  form.append("file", file);
  const inferredKind = kind || (file.name.includes(".") ? file.name.split(".").pop().toLowerCase() : "pdf");
  const url = `${API_BASE}/api/ingest/upload?kind=${encodeURIComponent(inferredKind)}&target=${encodeURIComponent(target)}`;
  const response = await fetch(url, { method: "POST", body: form });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export function adminEmailTest(payload = {}) {
  return jsonFetch("/api/admin/email-test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getSchedulerStatus() {
  return jsonFetch("/api/admin/scheduler/status");
}

export function triggerScheduler(job = "sync_ganadas") {
  return jsonFetch("/api/admin/scheduler/trigger", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job }),
  });
}

// ---- Entregables (HH licitadas + reales) ----

export function getEntregablesStats() {
  return jsonFetch("/api/entregables/stats");
}

export function getEntregablesDisciplinas(limit = 50) {
  return jsonFetch(`/api/entregables/disciplinas?limit=${limit}`);
}

export function getEntregablesAggregate({ fuente = "licitadas", view = "proyecto", codigo, cliente, tipo_servicio, disciplina, text, min_hours, ano, limit = 100 } = {}) {
  const params = new URLSearchParams({ fuente, view, limit: String(limit) });
  if (codigo) params.set("codigo", codigo);
  if (cliente) params.set("cliente", cliente);
  if (tipo_servicio) params.set("tipo_servicio", tipo_servicio);
  if (disciplina) params.set("disciplina", disciplina);
  if (text) params.set("text", text);
  if (min_hours) params.set("min_hours", String(min_hours));
  if (ano) params.set("ano", String(ano));
  return jsonFetch(`/api/entregables/aggregate?${params.toString()}`);
}

export function getEntregablesTiposServicio() {
  return jsonFetch("/api/entregables/tipos-servicio");
}

export function extractEntregablesFromSharePoint(codigo) {
  return jsonFetch(`/api/entregables/extract-budget/${encodeURIComponent(codigo)}`, {
    method: "POST",
  });
}

export function getEntregablesExtracted(codigo) {
  return jsonFetch(`/api/entregables/extracted/${encodeURIComponent(codigo)}`);
}

export function askEntregablesAgent(payload) {
  return jsonFetch("/api/entregables/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function librarySearch(payload) {
  return jsonFetch("/api/library/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function validateLibraryEntry(id) {
  return jsonFetch(`/api/wiki/entries/${id}/validate`, { method: "POST" });
}

// ---- Drafts (propuestas en armado con antecedentes) ----

export function listDrafts(limit = 50) {
  return jsonFetch(`/api/drafts?limit=${limit}`);
}

export function createDraft(payload) {
  return jsonFetch("/api/drafts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getDraft(slug) {
  return jsonFetch(`/api/drafts/${encodeURIComponent(slug)}`);
}

export function deleteDraft(slug) {
  return jsonFetch(`/api/drafts/${encodeURIComponent(slug)}`, { method: "DELETE" });
}

export async function uploadDraftFile(slug, file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/drafts/${encodeURIComponent(slug)}/upload`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export function buildDraftGuide(slug) {
  return jsonFetch(`/api/drafts/${encodeURIComponent(slug)}/build-guide`, { method: "POST" });
}

export function getDraftFileUrl(slug, filename) {
  return `${API_BASE}/api/drafts/${encodeURIComponent(slug)}/files/${encodeURIComponent(filename)}`;
}

export function previewSharepointAntecedentes(codigo) {
  return jsonFetch(`/api/drafts/sharepoint-preview/${encodeURIComponent(codigo)}`);
}

export function importDraftFromSharepoint(slug, codigo, filenames = null) {
  const payload = { codigo };
  if (filenames && filenames.length) payload.filenames = filenames;
  return jsonFetch(`/api/drafts/${encodeURIComponent(slug)}/import-sharepoint`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function exportAnswer(kind, payload) {
  const response = await fetch(`${API_BASE}/api/exports/${kind}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await response.text());
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  const extension = kind === "typst-pdf" || kind === "report" ? "pdf" : kind;
  link.download = `respuesta.${extension}`;
  link.click();
  URL.revokeObjectURL(url);
}
