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

async function jsonFetch(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) throw new Error(await response.text());
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
