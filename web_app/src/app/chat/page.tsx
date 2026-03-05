"use client";

import { useAuth, UserButton } from "@clerk/nextjs";
import { useEffect, useRef, useState, useCallback } from "react";
import { ChatWindow } from "@/components/ChatWindow";
import { SkillSelector, SkillId } from "@/components/SkillSelector";
import { Message } from "@/components/MessageBubble";
import { NestorWS, WsInbound, WsState } from "@/lib/ws";

let msgCounter = 0;
function newId() {
  return `msg_${++msgCounter}_${Date.now()}`;
}

export default function ChatPage() {
  const { getToken } = useAuth();
  const wsRef = useRef<NestorWS | null>(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [wsState, setWsState] = useState<WsState>("disconnected");
  const [skill, setSkill] = useState<SkillId>("general");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const handleWsMessage = useCallback((msg: WsInbound) => {
    if (msg.type === "typing") {
      setIsTyping(true);
    } else if (msg.type === "reply") {
      setIsTyping(false);
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: "assistant", text: msg.text, timestamp: new Date() },
      ]);
    }
  }, []);

  useEffect(() => {
    let ws: NestorWS | null = null;

    async function init() {
      const token = await getToken();
      if (!token) return;

      ws = new NestorWS(token, handleWsMessage, setWsState);
      wsRef.current = ws;
      ws.connect();
    }

    init();

    return () => {
      ws?.disconnect();
    };
  }, [getToken, handleWsMessage]);

  // Register service worker for PWA
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // SW registration is non-critical
      });
    }
  }, []);

  function handleSend(text: string) {
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: "user", text, timestamp: new Date() },
    ]);
    wsRef.current?.send({ type: "message", text, skill_id: skill });
  }

  const isDisabled = wsState !== "connected";
  const statusLabel: Record<WsState, string> = {
    connected: "Connected",
    connecting: "Connecting…",
    disconnected: "Disconnected",
    error: "Connection error",
  };
  const statusColor: Record<WsState, string> = {
    connected: "#4ade80",
    connecting: "#facc15",
    disconnected: "var(--text-muted)",
    error: "var(--danger)",
  };

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      {/* Sidebar */}
      <aside
        style={{
          width: sidebarOpen ? "220px" : "0",
          minWidth: sidebarOpen ? "220px" : "0",
          background: "var(--surface)",
          borderRight: "1px solid var(--border)",
          overflow: "hidden",
          transition: "min-width 0.2s, width 0.2s",
          display: "flex",
          flexDirection: "column",
          padding: sidebarOpen ? "16px" : "0",
        }}
      >
        <p style={{ fontWeight: 700, fontSize: "18px", marginBottom: "4px" }}>Nestor</p>
        <SkillSelector selected={skill} onChange={setSkill} />
        <div style={{ marginTop: "auto" }}>
          <UserButton afterSignOutUrl="/sign-in" />
        </div>
      </aside>

      {/* Main chat area */}
      <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Top bar */}
        <div
          style={{
            height: "52px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            padding: "0 16px",
            gap: "12px",
            flexShrink: 0,
          }}
        >
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label="Toggle sidebar"
            style={{ color: "var(--text-muted)", fontSize: "20px", lineHeight: 1 }}
          >
            ☰
          </button>
          <span style={{ fontWeight: 600, fontSize: "15px", flex: 1 }}>
            {skill === "budget_assistant" ? "Budget Assistant" : "Nestor"}
          </span>
          <span style={{ fontSize: "12px", color: statusColor[wsState] }}>
            ● {statusLabel[wsState]}
          </span>
        </div>

        {/* Chat */}
        <div style={{ flex: 1, overflow: "hidden" }}>
          <ChatWindow
            messages={messages}
            isTyping={isTyping}
            onSend={handleSend}
            disabled={isDisabled}
          />
        </div>
      </main>
    </div>
  );
}
