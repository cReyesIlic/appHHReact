import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

const PHASES = [
  "Analizando la pregunta…",
  "Eligiendo skill apropiada…",
  "Consultando la wiki curada…",
  "Buscando en Master…",
  "Buscando evidencia en RAG…",
  "Calculando estadísticas / economía…",
  "Cruzando referencias entre fuentes…",
  "Componiendo respuesta…",
];

export function ThinkingIndicator() {
  const [phase, setPhase] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setPhase((p) => (p + 1) % PHASES.length);
    }, 3500);
    const tick = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => {
      clearInterval(interval);
      clearInterval(tick);
    };
  }, []);

  return (
    <article className="message thinking-indicator">
      <div className="message-meta">
        <Loader2 size={12} className="spin" /> Agente SHIMIN <span className="dim">· {elapsed}s</span>
      </div>
      <div className="message-body">
        <div className="thinking-row">
          <span className="thinking-dot dot1" />
          <span className="thinking-dot dot2" />
          <span className="thinking-dot dot3" />
          <span className="thinking-text">{PHASES[phase]}</span>
        </div>
      </div>
    </article>
  );
}
