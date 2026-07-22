import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FilePlus, Trash2, Upload, Sparkles, FileText, File as FileIcon, Loader2, Cloud, Search, Send, Save, MessageSquareText, RotateCcw } from "lucide-react";
import {
  listDrafts,
  createDraft,
  getDraft,
  getDraftSession,
  updateDraft,
  deleteDraft,
  uploadDraftFile,
  buildDraftGuide,
  getDraftFileUrl,
  reprocessDraftFile,
  deleteDraftFile,
  previewSharepointAntecedentes,
  importDraftFromSharepoint,
  sendChat,
  createSession,
  getSession,
} from "../../lib/api.js";
import { Button } from "../shared/Button.jsx";
import { Card } from "../shared/Card.jsx";
import { Input, Field } from "../shared/Field.jsx";
import { EmptyState } from "../shared/EmptyState.jsx";

export function DraftsView() {
  const [drafts, setDrafts] = useState([]);
  const [activeSlug, setActiveSlug] = useState(null);
  const [active, setActive] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);
  const [newTitle, setNewTitle] = useState("");
  const [newCliente, setNewCliente] = useState("");
  const [spCode, setSpCode] = useState("");
  const [spPreview, setSpPreview] = useState(null);
  const [briefText, setBriefText] = useState("");
  const [briefDirty, setBriefDirty] = useState(false);
  const [consultInput, setConsultInput] = useState("");
  const [consultMessages, setConsultMessages] = useState([]);
  const [consultBusy, setConsultBusy] = useState(false);
  const [consultSessionId, setConsultSessionId] = useState(null);
  const [consultContext, setConsultContext] = useState({});
  const fileInputRef = useRef(null);

  const reload = async () => {
    setLoading(true);
    try {
      const r = await listDrafts(50);
      setDrafts(r.drafts || []);
      if (activeSlug) {
        try {
          const d = await getDraft(activeSlug);
          setActive(d);
          setBriefText(d.brief_text || "");
          setBriefDirty(false);
        } catch {
          setActiveSlug(null);
          setActive(null);
        }
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
  }, []);

  useEffect(() => {
    if (!activeSlug) return;
    getDraft(activeSlug)
      .then((draft) => {
        setActive(draft);
        setBriefText(draft.brief_text || "");
        setBriefDirty(false);
      })
      .catch(() => setActive(null));
  }, [activeSlug]);

  useEffect(() => {
    let cancelled = false;
    setConsultMessages([]);
    setConsultContext({});
    setConsultInput("");
    setConsultSessionId(null);
    if (!activeSlug) return () => { cancelled = true; };

    const storageKey = draftSessionKey(activeSlug);
    const storedSession = localStorage.getItem(storageKey);
    const restore = async () => {
      if (storedSession) {
        try {
          return await getSession(storedSession);
        } catch {
          localStorage.removeItem(storageKey);
        }
      }
      const result = await getDraftSession(activeSlug);
      return result.session;
    };

    restore()
      .then((session) => {
        if (cancelled || !session) return;
        setConsultSessionId(session.id);
        localStorage.setItem(storageKey, session.id);
        setConsultContext(session.working_context || {});
        setConsultMessages(
          (session.messages || []).map((message) => ({
            role: message.role,
            content: message.content,
            sources: message.sources || [],
          })),
        );
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [activeSlug]);

  const handleCreate = async (e) => {
    e?.preventDefault?.();
    if (!newTitle.trim()) return;
    setBusy("create");
    try {
      const d = await createDraft({ title: newTitle, cliente: newCliente || null });
      setNewTitle("");
      setNewCliente("");
      setActiveSlug(d.slug);
      await reload();
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async (slug) => {
    if (!confirm("¿Eliminar este draft y todos sus archivos?")) return;
    setBusy("delete");
    try {
      await deleteDraft(slug);
      if (activeSlug === slug) {
        localStorage.removeItem(draftSessionKey(slug));
        setActiveSlug(null);
        setActive(null);
      }
      await reload();
    } catch (exc) {
      alert(`Error eliminando el draft: ${exc.message}`);
    } finally {
      setBusy(null);
    }
  };

  const handleUpload = async (files) => {
    if (!activeSlug || !files?.length) return;
    setBusy("upload");
    try {
      const warnings = [];
      for (const f of files) {
        const result = await uploadDraftFile(activeSlug, f);
        if (result.extraction_warning) {
          warnings.push(`${result.filename}: ${result.extraction_warning}`);
        }
      }
      await reload();
      if (warnings.length) alert(warnings.join("\n"));
    } catch (exc) {
      alert(`Error subiendo: ${exc.message}`);
    } finally {
      setBusy(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleReprocess = async (file) => {
    if (!activeSlug) return;
    setBusy(`reprocess-${file.id || file.filename}`);
    try {
      const result = await reprocessDraftFile(activeSlug, file.filename);
      await reload();
      if (result.extraction_warning) alert(result.extraction_warning);
    } catch (exc) {
      alert(`Error reprocesando: ${exc.message}`);
    } finally {
      setBusy(null);
    }
  };

  const handleDeleteFile = async (file) => {
    if (!activeSlug || !confirm(`¿Eliminar ${file.filename} y su índice de este draft?`)) return;
    setBusy(`delete-file-${file.id || file.filename}`);
    try {
      await deleteDraftFile(activeSlug, file.filename);
      await reload();
    } catch (exc) {
      alert(`Error eliminando el archivo: ${exc.message}`);
    } finally {
      setBusy(null);
    }
  };

  const handleSpPreview = async () => {
    const code = (spCode || "").trim().toUpperCase();
    if (!code) return;
    setBusy("sp-preview");
    try {
      const r = await previewSharepointAntecedentes(code);
      setSpPreview(r);
    } catch (exc) {
      alert(`Error consultando SharePoint: ${exc.message}`);
      setSpPreview(null);
    } finally {
      setBusy(null);
    }
  };

  const handleSpImport = async () => {
    const code = (spCode || "").trim().toUpperCase();
    if (!activeSlug || !code) return;
    if (!confirm(`Descargar TODOS los antecedentes de ${code} desde SharePoint a este draft?`)) return;
    setBusy("sp-import");
    try {
      const r = await importDraftFromSharepoint(activeSlug, code);
      if (r.error) {
        alert(`Error: ${r.error}`);
      } else if (r.imported === 0) {
        alert(r.note || `No se encontraron archivos en '01 Informacion Cliente' de ${code}.`);
      } else {
        alert(`Importados ${r.imported} de ${r.found} archivos. ${r.errors ? `(${r.errors} errores)` : ""}`);
      }
      setSpPreview(null);
      setSpCode("");
      await reload();
    } catch (exc) {
      alert(`Error importando: ${exc.message}`);
    } finally {
      setBusy(null);
    }
  };

  const handleBuildGuide = async () => {
    if (!activeSlug) return;
    setBusy("guide");
    try {
      if (briefDirty) {
        const updatedDraft = await updateDraft(activeSlug, { brief_text: briefText });
        setActive((current) => ({
          ...(current || {}),
          ...updatedDraft,
          guide_exists: false,
          guide_markdown: "",
        }));
        setBriefDirty(false);
      }
      await buildDraftGuide(activeSlug);
      await reload();
    } catch (exc) {
      alert(`Error generando guía: ${exc.message}`);
    } finally {
      setBusy(null);
    }
  };

  const handleSaveBrief = async () => {
    if (!activeSlug) return;
    setBusy("brief");
    try {
      await updateDraft(activeSlug, { brief_text: briefText });
      setBriefDirty(false);
      await reload();
    } catch (exc) {
      alert(`Error guardando el brief: ${exc.message}`);
    } finally {
      setBusy(null);
    }
  };

  const handleConsult = async (suggestedQuestion = null) => {
    const text = String(suggestedQuestion || consultInput || "").trim();
    if (!activeSlug || !active || !text) return;
    setConsultBusy(true);
    setConsultInput("");
    const previousMessages = consultMessages;
    setConsultMessages((current) => [...current, { role: "user", content: text }]);
    try {
      if (briefDirty) {
        const updatedDraft = await updateDraft(activeSlug, { brief_text: briefText });
        setActive((current) => ({
          ...(current || {}),
          ...updatedDraft,
          guide_exists: false,
          guide_markdown: "",
        }));
        setBriefDirty(false);
      }
      const activeDraftContext = {
        slug: active.slug,
        title: active.title,
        cliente: active.cliente || "",
        brief_text: briefText,
      };
      let sessionId = consultSessionId;
      if (!sessionId) {
        const session = await createSession(`Consulta · ${active.title}`);
        sessionId = session.id;
        setConsultSessionId(sessionId);
        localStorage.setItem(draftSessionKey(activeSlug), sessionId);
      }
      const response = await sendChat({
        message: text,
        history: previousMessages.slice(-12).map(({ role, content }) => ({ role, content })),
        selected_codes: consultContext.suggested_codes || [],
        deep_pdf_read: true,
        working_context: { ...consultContext, active_draft: activeDraftContext },
        filters: {},
        session_id: sessionId,
        create_session_if_missing: false,
      });
      setConsultMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: response.answer || "(sin respuesta)",
          sources: response.sources || [],
        },
      ]);
      setConsultContext(response.working_context || { active_draft: activeDraftContext });
      if (response.session_id) {
        setConsultSessionId(response.session_id);
        localStorage.setItem(draftSessionKey(activeSlug), response.session_id);
      }
    } catch (exc) {
      setConsultMessages((current) => [
        ...current,
        { role: "assistant", content: `❌ Error consultando la propuesta: ${exc.message}` },
      ]);
    } finally {
      setConsultBusy(false);
    }
  };

  const resetConsult = () => {
    if (!activeSlug) return;
    localStorage.removeItem(draftSessionKey(activeSlug));
    setConsultSessionId(null);
    setConsultContext({});
    setConsultMessages([]);
    setConsultInput("");
  };

  return (
    <div className="view-body" style={{ height: "100%" }}>
      <div className="drafts-layout">
        {/* Sidebar — lista + crear */}
        <aside className="drafts-sidebar">
          <Card title="Nueva propuesta">
            <form onSubmit={handleCreate} className="flex-col" style={{ gap: 8 }}>
              <Field label="Título">
                <Input
                  placeholder="Ej: Dewatering Codelco DET"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                />
              </Field>
              <Field label="Cliente (opcional)">
                <Input
                  placeholder="Codelco, Vale, Anglo…"
                  value={newCliente}
                  onChange={(e) => setNewCliente(e.target.value)}
                />
              </Field>
              <Button
                type="submit"
                variant="accent"
                icon={FilePlus}
                disabled={busy === "create" || !newTitle.trim()}
              >
                {busy === "create" ? "Creando…" : "Crear draft"}
              </Button>
            </form>
          </Card>

          <Card title={`Mis drafts (${drafts.length})`} subtitle={loading ? "cargando…" : null}>
            {drafts.length === 0 && !loading ? (
              <small className="dim">Aún sin drafts. Crea el primero arriba.</small>
            ) : (
              <div className="flex-col" style={{ gap: 4 }}>
                {drafts.map((d) => (
                  <div
                    key={d.slug}
                    className={`draft-item${activeSlug === d.slug ? " active" : ""}`}
                    onClick={() => setActiveSlug(d.slug)}
                  >
                    <div className="draft-item-title">{d.title}</div>
                    <div className="draft-item-meta">
                      {d.cliente && <span className="chip-accent" style={{ marginRight: 4 }}>{d.cliente}</span>}
                      <small className="dim">
                        {d.files_count} archivo(s) · {d.status}
                      </small>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </aside>

        {/* Detalle */}
        <section className="drafts-main">
          {!active ? (
            <EmptyState
              icon={FilePlus}
              title="Sube los antecedentes para una propuesta nueva"
              description="Crea un draft, escribe tu brief y sube los PDF/DOCX del cliente. Podrás generar una guía y conversar con la IA usando esos antecedentes y propuestas históricas."
            />
          ) : (
            <>
              <Card
                title={active.title}
                subtitle={active.cliente ? `Cliente: ${active.cliente}` : "Sin cliente especificado"}
                actions={
                  <Button
                    variant="ghost"
                    icon={Trash2}
                    onClick={() => handleDelete(active.slug)}
                    disabled={busy === "delete"}
                  >
                    Eliminar
                  </Button>
                }
              >
                <div className="flex-row" style={{ flexWrap: "wrap", gap: 10 }}>
                  <Button
                    variant="primary"
                    icon={Upload}
                    onClick={() => fileInputRef.current?.click()}
                    disabled={busy === "upload"}
                  >
                    {busy === "upload" ? "Subiendo…" : "Subir PDF / DOCX"}
                  </Button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,.docx"
                    style={{ display: "none" }}
                    onChange={(e) => handleUpload(Array.from(e.target.files || []))}
                  />
                  <Button
                    variant="accent"
                    icon={busy === "guide" ? Loader2 : Sparkles}
                    onClick={handleBuildGuide}
                    disabled={
                      busy === "guide"
                      || ((active.files || []).length === 0 && !briefText.trim())
                    }
                    title={
                      (active.files || []).length === 0 && !briefText.trim()
                        ? "Escribe el brief o sube archivos primero"
                        : "Generar guía con LLM a partir del brief y los antecedentes"
                    }
                  >
                    {busy === "guide" ? "Generando guía…" : "Generar guía con LLM"}
                  </Button>
                </div>

                <div className="draft-brief-panel">
                  <div className="card-title" style={{ fontSize: 13 }}>
                    Brief e instrucciones para la propuesta
                  </div>
                  <small className="dim">
                    Describe qué necesitas ofertar, tus ideas, restricciones y dudas. La IA combinará
                    este texto con los documentos cargados y las propuestas históricas.
                  </small>
                  <textarea
                    className="draft-brief-textarea"
                    value={briefText}
                    onChange={(event) => {
                      setBriefText(event.target.value);
                      setBriefDirty(true);
                    }}
                    placeholder="Ej.: preparar una ingeniería de detalle para el sistema de restitución; necesito sugerencias de alcance, entregables, HH, riesgos y exclusiones…"
                    rows={6}
                  />
                  <div className="flex-row" style={{ gap: 8, alignItems: "center" }}>
                    <Button
                      variant="ghost"
                      icon={busy === "brief" ? Loader2 : Save}
                      onClick={handleSaveBrief}
                      disabled={busy === "brief" || !briefDirty}
                    >
                      {busy === "brief" ? "Guardando…" : "Guardar brief"}
                    </Button>
                    <small className={briefDirty ? "draft-unsaved" : "dim"}>
                      {briefDirty ? "Cambios sin guardar" : "Brief guardado"}
                    </small>
                  </div>
                </div>

                {/* Sección: importar desde SharePoint */}
                <div
                  style={{
                    marginTop: 14,
                    padding: 12,
                    background: "var(--bg-alt)",
                    borderRadius: 8,
                    border: "1px dashed var(--border)",
                  }}
                >
                  <div className="card-title" style={{ fontSize: 13, marginBottom: 6, display: "flex", alignItems: "center", gap: 6 }}>
                    <Cloud size={14} style={{ color: "var(--accent)" }} />
                    Importar antecedentes desde SharePoint
                  </div>
                  <small className="dim" style={{ display: "block", marginBottom: 8 }}>
                    Carpeta <code>GerenciaComercial → 01 Ofertas → O-XXXX → 01 Informacion Cliente</code> (PDFs y DOCX del cliente).
                  </small>
                  <div className="flex-row" style={{ gap: 8, alignItems: "stretch", flexWrap: "wrap" }}>
                    <Input
                      placeholder="O-XXXX (ej. O-1376)"
                      value={spCode}
                      onChange={(e) => setSpCode(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleSpPreview()}
                      style={{ maxWidth: 200 }}
                    />
                    <Button
                      variant="ghost"
                      icon={Search}
                      onClick={handleSpPreview}
                      disabled={busy === "sp-preview" || !spCode.trim()}
                    >
                      {busy === "sp-preview" ? "Buscando…" : "Ver archivos"}
                    </Button>
                    {spPreview && spPreview.count > 0 && (
                      <Button
                        variant="accent"
                        icon={busy === "sp-import" ? Loader2 : Cloud}
                        onClick={handleSpImport}
                        disabled={busy === "sp-import"}
                      >
                        {busy === "sp-import" ? "Importando…" : `Importar ${spPreview.count} archivo(s)`}
                      </Button>
                    )}
                  </div>
                  {spPreview && (
                    <div style={{ marginTop: 10 }}>
                      {spPreview.error ? (
                        <small className="dim">⚠️ {spPreview.error}</small>
                      ) : spPreview.count === 0 ? (
                        <small className="dim">
                          La carpeta <code>01 Informacion Cliente</code> de <b>{spPreview.codigo}</b> está vacía o no existe.
                        </small>
                      ) : (
                        <div className="flex-col" style={{ gap: 4 }}>
                          {spPreview.files.map((f) => (
                            <small key={f.name} className="dim" style={{ display: "flex", gap: 6, alignItems: "center" }}>
                              <FileIcon size={11} style={{ color: "var(--accent)" }} />
                              <span style={{ color: "var(--text-primary)" }}>{f.name}</span>
                              <span>· {f.kind.toUpperCase()} · {formatBytes(f.size)}</span>
                            </small>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                <div style={{ marginTop: 16 }}>
                  <div className="card-title" style={{ fontSize: 13, marginBottom: 8 }}>
                    Archivos cargados ({(active.files || []).length})
                  </div>
                  {(active.files || []).length === 0 ? (
                    <small className="dim">Aún sin archivos. Acepta PDF y DOCX, hasta 50 MB c/u.</small>
                  ) : (
                    <div className="flex-col" style={{ gap: 6 }}>
                      {active.files.map((f) => {
                        const Icon = f.kind === "pdf" ? FileIcon : FileText;
                        return (
                          <div
                            key={f.id || f.filename}
                            className="draft-file"
                          >
                            <Icon size={14} style={{ color: "var(--accent)" }} />
                            <a
                              href={getDraftFileUrl(active.slug, f.filename)}
                              target="_blank"
                              rel="noreferrer"
                              style={{ color: "inherit", textDecoration: "none" }}
                            >
                              {f.filename}
                            </a>
                            <small className="dim">
                              {f.kind.toUpperCase()} · {formatBytes(f.size)} · {f.chars_extracted} chars
                            </small>
                            {Number(f.chars_extracted || 0) === 0 && (
                              <Button
                                variant="ghost"
                                icon={RotateCcw}
                                onClick={() => handleReprocess(f)}
                                disabled={busy === `reprocess-${f.id || f.filename}`}
                              >
                                Reprocesar
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              icon={Trash2}
                              onClick={() => handleDeleteFile(f)}
                              disabled={busy === `delete-file-${f.id || f.filename}`}
                            >
                              Eliminar
                            </Button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </Card>

              <Card
                title="Guía generada"
                subtitle={active.guide_exists ? "Síntesis del LLM con puntos clave del cliente" : "(aún no generada)"}
              >
                {active.guide_exists && active.guide_markdown ? (
                  <div className="message-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{active.guide_markdown}</ReactMarkdown>
                  </div>
                ) : (
                  <EmptyState
                    icon={Sparkles}
                    title="Sin guía aún"
                    description="Escribe el brief o sube antecedentes del cliente y haz click en 'Generar guía con LLM'. Produce una síntesis Markdown con alcance, entregables, disciplinas, criterios, riesgos y próximos pasos."
                  />
                )}
              </Card>

              <Card
                title="Consulta IA de esta propuesta"
                subtitle="Lee el brief, la guía y los PDF/DOCX; además contrasta propuestas históricas"
                actions={
                  <Button
                    variant="ghost"
                    icon={RotateCcw}
                    onClick={resetConsult}
                    disabled={consultBusy || consultMessages.length === 0}
                  >
                    Nueva consulta
                  </Button>
                }
              >
                <div className="draft-quick-prompts">
                  {DRAFT_PROMPTS.map((prompt) => (
                    <button
                      type="button"
                      key={prompt}
                      onClick={() => handleConsult(prompt)}
                      disabled={consultBusy || ((active.files || []).length === 0 && !briefText.trim())}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>

                <div className="draft-consult-thread">
                  {consultMessages.length === 0 ? (
                    <EmptyState
                      icon={MessageSquareText}
                      title="Pregunta sobre esta propuesta"
                      description="La conversación queda vinculada únicamente a este draft. La IA recibe automáticamente tu brief y los antecedentes cargados."
                    />
                  ) : (
                    consultMessages.map((message, index) => (
                      <div
                        key={`${message.role}-${index}`}
                        className={`draft-consult-message ${message.role}`}
                      >
                        <div className="draft-consult-role">
                          {message.role === "user" ? "Tú" : "Agente SHIMIN"}
                        </div>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {message.content || "(sin contenido)"}
                        </ReactMarkdown>
                        {(message.sources || []).some((source) => source.url) && (
                          <div className="draft-consult-sources">
                            {(message.sources || []).filter((source) => source.url).slice(0, 8).map((source, sourceIndex) => (
                              <a
                                key={`${source.url}-${sourceIndex}`}
                                href={source.url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                {source.title || source.codigo || "Abrir fuente"}
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                  {consultBusy && (
                    <div className="draft-consult-message assistant draft-consult-thinking">
                      <Loader2 size={15} /> Leyendo brief, documentos y referencias históricas…
                    </div>
                  )}
                </div>

                <div className="draft-consult-composer">
                  <textarea
                    value={consultInput}
                    onChange={(event) => setConsultInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                        event.preventDefault();
                        handleConsult();
                      }
                    }}
                    placeholder="Ej.: ¿Cómo debería estructurar el alcance y qué entregables faltan?"
                    rows={3}
                    disabled={consultBusy}
                  />
                  <Button
                    variant="accent"
                    icon={consultBusy ? Loader2 : Send}
                    onClick={() => handleConsult()}
                    disabled={
                      consultBusy
                      || !consultInput.trim()
                      || ((active.files || []).length === 0 && !briefText.trim())
                    }
                  >
                    {consultBusy ? "Analizando…" : "Consultar"}
                  </Button>
                </div>
                {(active.files || []).length === 0 && !briefText.trim() && (
                  <small className="draft-unsaved">
                    Escribe el brief o carga al menos un documento para habilitar la consulta.
                  </small>
                )}
              </Card>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

const DRAFT_PROMPTS = [
  "¿Cómo debería armar esta propuesta?",
  "Sugiere alcance y entregables",
  "Detecta riesgos, vacíos y preguntas al cliente",
  "Busca propuestas ganadas similares",
];

function draftSessionKey(slug) {
  return `shimin_draft_session_${slug}`;
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(2)} MB`;
}
