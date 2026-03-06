"use client";

export default function SettingsPage() {
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
      </div>

      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "12px",
          padding: "16px 20px",
        }}
      >
        <p style={{ fontSize: "13px", color: "var(--text-muted)", marginBottom: "4px" }}>Mode</p>
        <p style={{ fontWeight: 500 }}>MVP — single local user</p>
        <p style={{ fontSize: "13px", color: "var(--text-muted)", marginTop: "12px", marginBottom: "4px" }}>LLM</p>
        <p style={{ fontWeight: 500 }}>
          Using <code>OPENAI_API_KEY</code> from environment
        </p>
      </div>
    </div>
  );
}
