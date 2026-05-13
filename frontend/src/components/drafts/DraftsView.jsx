import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FilePlus, Trash2, Upload, Sparkles, FileText, File as FileIcon, Loader2, Cloud, Search } from "lucide-react";
import {
  listDrafts,
  createDraft,
  getDraft,
  deleteDraft,
  uploadDraftFile,
  buildDraftGuide,
  getDraftFileUrl,
  previewSharepointAntecedentes,
  importDraftFromSharepoint,
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
    getDraft(activeSlug).then(setActive).catch(() => setActive(null));
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
        setActiveSlug(null);
        setActive(null);
      }
      await reload();
    } finally {
      setBusy(null);
    }
  };

  const handleUpload = async (files) => {
    if (!activeSlug || !files?.length) return;
    setBusy("upload");
    try {
      for (const f of files) {
        await uploadDraftFile(activeSlug, f);
      }
      await reload();
    } catch (exc) {
      alert(`Error subiendo: ${exc.message}`);
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
      await buildDraftGuide(activeSlug);
      await reload();
    } catch (exc) {
      alert(`Error generando guía: ${exc.message}`);
    } finally {
      setBusy(null);
    }
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
              description="Crea un draft a la izquierda, sube PDFs o DOCX del cliente (RFP, especificaciones, bases técnicas) y el agente extraerá los puntos clave en una guía .md que podrás usar para armar la propuesta."
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
                    disabled={busy === "guide" || (active.files || []).length === 0}
                    title={
                      (active.files || []).length === 0
                        ? "Sube archivos primero"
                        : "Generar guía con LLM a partir de los antecedentes"
                    }
                  >
                    {busy === "guide" ? "Generando guía…" : "Generar guía con LLM"}
                  </Button>
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
                          <a
                            key={f.id || f.filename}
                            className="draft-file"
                            href={getDraftFileUrl(active.slug, f.filename)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <Icon size={14} style={{ color: "var(--accent)" }} />
                            <span>{f.filename}</span>
                            <small className="dim">
                              {f.kind.toUpperCase()} · {formatBytes(f.size)} · {f.chars_extracted} chars
                            </small>
                          </a>
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
                    description="Sube los antecedentes del cliente (PDFs/DOCX del RFP, bases técnicas) y haz click en 'Generar guía con LLM'. Tarda ~30 s y produce un .md con: alcance, entregables, disciplinas, criterios, riesgos y próximos pasos."
                  />
                )}
              </Card>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(2)} MB`;
}
