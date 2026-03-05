"use client";

import { useAuth, UserButton } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { getMe, storeApiKey, MeResponse } from "@/lib/api";

export default function SettingsPage() {
  const { getToken } = useAuth();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      const token = await getToken();
      if (!token) return;
      try {
        const data = await getMe(token);
        setMe(data);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load profile");
      }
    }
    load();
  }, [getToken]);

  async function handleSave() {
    if (!apiKey.trim()) return;
    setSaving(true);
    setError("");
    try {
      const token = await getToken();
      if (!token) throw new Error("Not authenticated");
      await storeApiKey(token, apiKey.trim());
      setSaved(true);
      setApiKey("");
      // Refresh
      const data = await getMe(token);
      setMe(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save API key");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--bg)",
        padding: "32px 20px",
        maxWidth: "520px",
        margin: "0 auto",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "32px" }}>
        <a href="/chat" style={{ color: "var(--text-muted)", fontSize: "20px" }}>←</a>
        <h1 style={{ fontSize: "20px", fontWeight: 700 }}>Settings</h1>
        <div style={{ marginLeft: "auto" }}>
          <UserButton afterSignOutUrl="/sign-in" />
        </div>
      </div>

      {me && (
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "12px",
            padding: "16px 20px",
            marginBottom: "20px",
          }}
        >
          <p style={{ fontSize: "13px", color: "var(--text-muted)", marginBottom: "4px" }}>Signed in as</p>
          <p style={{ fontWeight: 500 }}>{me.email ?? me.user_id}</p>
          <p style={{ fontSize: "13px", color: me.has_api_key ? "#4ade80" : "var(--text-muted)", marginTop: "8px" }}>
            {me.has_api_key ? "✓ LLM API key configured" : "No LLM API key — using system default"}
          </p>
        </div>
      )}

      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "12px",
          padding: "20px",
        }}
      >
        <h2 style={{ fontSize: "16px", fontWeight: 600, marginBottom: "6px" }}>LLM API Key (BYOK)</h2>
        <p style={{ fontSize: "13px", color: "var(--text-muted)", marginBottom: "16px" }}>
          Store your OpenAI API key. It is encrypted at rest and never logged.
        </p>
        <input
          type="password"
          placeholder="sk-..."
          value={apiKey}
          onChange={(e) => { setApiKey(e.target.value); setSaved(false); }}
          style={{
            width: "100%",
            background: "var(--bg)",
            border: "1px solid var(--border)",
            borderRadius: "8px",
            padding: "10px 12px",
            color: "var(--text)",
            marginBottom: "12px",
            outline: "none",
          }}
        />
        {error && <p style={{ color: "var(--danger)", fontSize: "13px", marginBottom: "8px" }}>{error}</p>}
        {saved && <p style={{ color: "#4ade80", fontSize: "13px", marginBottom: "8px" }}>Saved successfully.</p>}
        <button
          onClick={handleSave}
          disabled={saving || !apiKey.trim()}
          style={{
            background: saving || !apiKey.trim() ? "var(--border)" : "var(--accent)",
            color: "white",
            borderRadius: "8px",
            padding: "10px 20px",
            fontWeight: 600,
            fontSize: "14px",
          }}
        >
          {saving ? "Saving…" : "Save API Key"}
        </button>
      </div>
    </div>
  );
}
