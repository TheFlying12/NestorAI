"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { ChatWindow } from "@/components/ChatWindow";
import { SkillSelector, SkillId } from "@/components/SkillSelector";
import { Message } from "@/components/MessageBubble";
import { NestorWS, WsInbound, WsState } from "@/lib/ws";
import { getConversationMessages } from "@/lib/api";

let msgCounter = 0;
function newId() {
  return `msg_${++msgCounter}_${Date.now()}`;
}

export default function ChatContent() {
  const { getToken } = useAuth();
  const wsRef = useRef<NestorWS | null>(null);
  const streamingIdRef = useRef<string | null>(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [wsState, setWsState] = useState<WsState>("disconnected");
  const [skill, setSkill] = useState<SkillId>("general");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const handleWsMessage = useCallback((msg: WsInbound) => {
    if (msg.type === "typing") {
      setIsTyping(true);
    } else if (msg.type === "token") {
      setIsTyping(false);
      if (!streamingIdRef.current) {
        const id = newId();
        streamingIdRef.current = id;
        setMessages((prev) => [
          ...prev,
          { id, role: "assistant", text: msg.text, timestamp: new Date() },
        ]);
      } else {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === streamingIdRef.current
              ? { ...m, text: m.text + msg.text }
              : m
          )
        );
      }
    } else if (msg.type === "reply") {
      setIsTyping(false);
      if (streamingIdRef.current) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === streamingIdRef.current ? { ...m, text: msg.text } : m
          )
        );
        streamingIdRef.current = null;
      } else {
        setMessages((prev) => [
          ...prev,
          { id: newId(), role: "assistant", text: msg.text, timestamp: new Date() },
        ]);
      }
    }
  }, []);

  // Connect WebSocket on mount
  useEffect(() => {
    const ws = new NestorWS(handleWsMessage, setWsState, getToken);
    wsRef.current = ws;
    ws.connect();
    return () => ws.disconnect();
  }, [handleWsMessage, getToken]);

  // Load conversation history when skill changes
  useEffect(() => {
    let cancelled = false;
    streamingIdRef.current = null;
    setMessages([]);

    async function loadHistory() {
      try {
        const token = await getToken();
        const msgs = await getConversationMessages(skill, token);
        if (cancelled) return;
        setMessages(
          msgs.map((m) => ({
            id: newId(),
            role: m.role as "user" | "assistant",
            text: m.content,
            timestamp: new Date(m.created_at),
          }))
        );
      } catch {
        // History loading is non-critical
      }
    }

    loadHistory();
    return () => { cancelled = true; };
  }, [skill, getToken]);

  // Register service worker for PWA
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
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
          <Link
            href="/"
            style={{ fontWeight: 700, fontSize: "15px", color: "var(--text)", textDecoration: "none", flex: 1 }}
          >
            Nestor
          </Link>
          <span style={{ fontSize: "12px", color: statusColor[wsState] }}>
            ● {statusLabel[wsState]}
          </span>
          {wsState === "disconnected" || wsState === "error" ? (
            <button
              onClick={() => wsRef.current?.connect()}
              style={{ fontSize: "12px", color: "#fff", background: "rgba(255,255,255,0.15)", border: "1px solid rgba(255,255,255,0.3)", borderRadius: "4px", padding: "2px 8px", cursor: "pointer" }}
            >
              Reconnect
            </button>
          ) : null}
          <Link
            href="/settings"
            aria-label="Settings"
            style={{ fontSize: "18px", color: "var(--text-muted)", textDecoration: "none", lineHeight: 1 }}
          >
            ⚙
          </Link>
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
