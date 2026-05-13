import { useState } from "react";
import { createRoot } from "react-dom/client";

import "./theme/shimin.css";
import "./theme/base.css";
import "./theme/app.css";

import { Shell } from "./components/layout/Shell.jsx";
import { TopBar } from "./components/layout/TopBar.jsx";
import { ChatView } from "./components/chat/ChatView.jsx";
import { MasterView } from "./components/master/MasterView.jsx";
import { LibraryView } from "./components/library/LibraryView.jsx";
import { OpsView } from "./components/ops/OpsView.jsx";

const VIEW_META = {
  chat: { title: "Agente SHIMIN", subtitle: "tool calling + filtros estructurados" },
  master: { title: "Planilla Master", subtitle: "datos tabulares de propuestas" },
  library: { title: "Wiki / Librería curada", subtitle: "espacio entre Master y RAG" },
  ops: { title: "Operación", subtitle: "estado del sistema e índices" },
};

function App() {
  const [view, setView] = useState("chat");
  const meta = VIEW_META[view] || {};

  return (
    <Shell active={view} onChange={setView} onOpenSettings={() => setView("ops")}>
      <TopBar title={meta.title} subtitle={meta.subtitle} />
      {view === "chat" && <ChatView />}
      {view === "master" && <MasterView />}
      {view === "library" && <LibraryView />}
      {view === "ops" && <OpsView />}
    </Shell>
  );
}

createRoot(document.getElementById("root")).render(<App />);
