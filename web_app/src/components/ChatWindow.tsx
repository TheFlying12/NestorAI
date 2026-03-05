"use client";

import { useEffect, useRef } from "react";
import { Message, MessageBubble, TypingIndicator } from "./MessageBubble";

interface Props {
  messages: Message[];
  isTyping: boolean;
  onSend: (text: string) => void;
  disabled: boolean;
}

export function ChatWindow({ messages, isTyping, onSend, disabled }: Props) {
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, isTyping]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    const text = inputRef.current?.value.trim();
    if (!text || disabled) return;
    onSend(text);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Message list */}
      <div
        ref={listRef}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "20px 16px 8px",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {messages.length === 0 && (
          <div
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--text-muted)",
              fontSize: "14px",
            }}
          >
            Start a conversation with Nestor
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {isTyping && <TypingIndicator />}
      </div>

      {/* Input */}
      <div
        style={{
          borderTop: "1px solid var(--border)",
          padding: "12px 16px",
          display: "flex",
          gap: "8px",
          alignItems: "flex-end",
          background: "var(--bg)",
        }}
      >
        <textarea
          ref={inputRef}
          placeholder="Message Nestor…"
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={1}
          style={{
            flex: 1,
            resize: "none",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "12px",
            padding: "10px 14px",
            color: "var(--text)",
            outline: "none",
            maxHeight: "120px",
            overflowY: "auto",
            lineHeight: "1.5",
          }}
          onInput={(e) => {
            const el = e.currentTarget;
            el.style.height = "auto";
            el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
          }}
        />
        <button
          onClick={submit}
          disabled={disabled}
          style={{
            background: disabled ? "var(--border)" : "var(--accent)",
            color: "white",
            borderRadius: "10px",
            padding: "10px 16px",
            fontWeight: 600,
            fontSize: "14px",
            transition: "background 0.15s",
            flexShrink: 0,
          }}
        >
          Send
        </button>
      </div>
    </div>
  );
}
