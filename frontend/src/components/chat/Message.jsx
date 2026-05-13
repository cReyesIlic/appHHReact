import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FileText, FileSpreadsheet, FileDown, Sparkles } from "lucide-react";
import { exportAnswer } from "../../lib/api.js";
import { useState } from "react";

export function Message({ role, content, meta, exportable, tables = [], sources = [] }) {
  const isUser = role === "user";
  const [downloading, setDownloading] = useState(null);

  const handleDownload = async (kind) => {
    setDownloading(kind);
    try {
      await exportAnswer(kind, {
        title: "Respuesta SHIMIN",
        answer: content,
        tables,
        sources,
        charts: [],
      });
    } catch (exc) {
      console.error("Export failed", exc);
      alert(`Error al generar ${kind}: ${exc.message}`);
    } finally {
      setDownloading(null);
    }
  };

  return (
    <article className={`message${isUser ? " message-user" : ""}`}>
      {meta && <div className="message-meta">{meta}</div>}
      <div className="message-body">
        {isUser ? (
          <p>{content}</p>
        ) : (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content || ""}</ReactMarkdown>
        )}
      </div>
      {exportable && !isUser && content && (
        <div className="message-actions">
          <small className="dim">Descargar:</small>
          <button
            className="btn-icon export-btn"
            title="PDF con formato SHIMIN"
            disabled={downloading !== null}
            onClick={() => handleDownload("report")}
          >
            <Sparkles size={13} /> {downloading === "report" ? "…" : "PDF SHIMIN"}
          </button>
          <button
            className="btn-icon export-btn"
            title="PDF simple"
            disabled={downloading !== null}
            onClick={() => handleDownload("pdf")}
          >
            <FileDown size={13} /> {downloading === "pdf" ? "…" : "PDF"}
          </button>
          <button
            className="btn-icon export-btn"
            title="Word (.docx)"
            disabled={downloading !== null}
            onClick={() => handleDownload("docx")}
          >
            <FileText size={13} /> {downloading === "docx" ? "…" : "Word"}
          </button>
          {tables.length > 0 && (
            <button
              className="btn-icon export-btn"
              title="Excel (.xlsx)"
              disabled={downloading !== null}
              onClick={() => handleDownload("xlsx")}
            >
              <FileSpreadsheet size={13} /> {downloading === "xlsx" ? "…" : "Excel"}
            </button>
          )}
        </div>
      )}
    </article>
  );
}
