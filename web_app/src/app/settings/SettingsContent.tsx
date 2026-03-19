"use client";

import { useEffect, useState } from "react";
import { useAuth, useUser } from "@clerk/nextjs";
import { getMe, storeApiKey } from "@/lib/api";

export default function SettingsContent() {
  const { getToken } = useAuth();
  const { user } = useUser();

  const [hasKey, setHasKey] = useState<boolean | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  useEffect(() => {
    async function fetchStatus() {
      try {
        const token = await getToken();
        if (!token) return;
        const me = await getMe(token);
        setHasKey(me.has_llm_key);
      } catch {
        // non-critical
      }
    }
    fetchStatus();
  }, [getToken]);

  async function handleSave() {
    if (!apiKeyInput.trim()) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      const token = await getToken();
      if (!token) throw new Error("Not signed in");
      await storeApiKey(apiKeyInput.trim(), token);
      setHasKey(true);
      setApiKeyInput("");
      setSaveMsg("Key saved.");
    } catch (err: unknown) {
      setSaveMsg(err instanceof Error ? err.message : "Failed to save key.");
    } finally {
      setSaving(false);
    }
  }

  const card: React.CSSProperties = {
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: "12px",
    padding: "16px 20px",
    marginBottom: "16px",
  };
  const label: React.CSSProperties = {
    fontSize: "13px",
    color: "var(--text-muted)",
    marginBottom: "4px",
  };
  const inputStyle: React.CSSProperties = {
    width: "100%",
    background: "var(--bg)",
    border: "1px solid var(--border)",
    borderRadius: "8px",
    padding: "8px 12px",
    color: "var(--text)",
    fontSize: "14px",
    boxSizing: "border-box",
    marginBottom: "8px",
  };
  const btnStyle = (disabled: boolean): React.CSSProperties => ({
    background: disabled ? "rgba(255,255,255,0.08)" : "rgba(255,255,255,0.15)",
    border: "1px solid rgba(255,255,255,0.3)",
    borderRadius: "6px",
    padding: "6px 16px",
    color: "#fff",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: "14px",
  });

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)", padding: "32px 20px", maxWidth: "520px", margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "32px" }}>
        <a href="/chat" style={{ color: "var(--text-muted)", fontSize: "20px" }}>←</a>
        <h1 style={{ fontSize: "20px", fontWeight: 700, flex: 1 }}>Settings</h1>
        <a href="/" style={{ fontSize: "13px", color: "var(--text-muted)", textDecoration: "none" }}>Home</a>
      </div>

      {/* Account */}
      <div style={card}>
        <p style={label}>Account</p>
        <p style={{ fontWeight: 500, marginBottom: "8px" }}>{user?.primaryEmailAddress?.emailAddress ?? "—"}</p>
        <a href="/account" style={{ fontSize: "13px", color: "var(--accent)", textDecoration: "none" }}>
          Phone, email &amp; skill channels →
        </a>
      </div>

      {/* LLM API Key */}
      <div style={card}>
        <p style={label}>LLM API Key (optional)</p>
        <p style={{ fontSize: "13px", marginBottom: "12px", color: "var(--text-muted)" }}>
          {hasKey === null
            ? "Checking…"
            : hasKey
            ? "A key is saved. Paste a new one below to replace it."
            : "No key saved — using the system key. Add your own OpenAI-compatible key to use your own quota."}
        </p>
        <input
          type="password"
          placeholder="sk-..."
          value={apiKeyInput}
          onChange={(e) => setApiKeyInput(e.target.value)}
          style={inputStyle}
        />
        <button
          onClick={handleSave}
          disabled={saving || !apiKeyInput.trim()}
          style={btnStyle(saving || !apiKeyInput.trim())}
        >
          {saving ? "Saving…" : "Save key"}
        </button>
        {saveMsg && (
          <p style={{ marginTop: "8px", fontSize: "13px", color: saveMsg === "Key saved." ? "#4ade80" : "var(--danger)" }}>
            {saveMsg}
          </p>
        )}
      </div>
    </div>
  );
}
