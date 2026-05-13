import { useEffect, useRef } from "react";
import { Message } from "./Message.jsx";
import { ThinkingIndicator } from "./ThinkingIndicator.jsx";

export function MessageList({ messages, busy, latestTables = [], latestSources = [] }) {
  const endRef = useRef(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, busy]);

  // Solo el último mensaje del agente lleva botones de export (con sus tablas/sources)
  const lastAssistantIdx = messages.reduce(
    (acc, msg, idx) => (msg.role === "assistant" ? idx : acc),
    -1
  );

  return (
    <div className="message-list">
      {messages.map((msg, idx) => (
        <Message
          key={idx}
          role={msg.role}
          content={msg.content}
          meta={msg.meta || (msg.role === "user" ? "Tú" : "Agente SHIMIN")}
          exportable={idx === lastAssistantIdx}
          tables={idx === lastAssistantIdx ? latestTables : []}
          sources={idx === lastAssistantIdx ? latestSources : []}
        />
      ))}
      {busy && <ThinkingIndicator />}
      <div ref={endRef} />
    </div>
  );
}
