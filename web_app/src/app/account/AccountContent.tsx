"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { getMe, savePhone, saveNotificationEmail, getSkillChannels, saveSkillChannel, SkillChannel } from "@/lib/api";
import { SKILLS, SkillId } from "@/lib/skills";

export default function AccountContent() {
  const { getToken } = useAuth();

  // Phone number state
  const [currentPhone, setCurrentPhone] = useState<string | null>(null);
  const [phoneInput, setPhoneInput] = useState("");
  const [savingPhone, setSavingPhone] = useState(false);
  const [phoneMsg, setPhoneMsg] = useState<string | null>(null);

  // Notification email state
  const [currentNotifEmail, setCurrentNotifEmail] = useState<string | null>(null);
  const [notifEmailInput, setNotifEmailInput] = useState("");
  const [savingNotifEmail, setSavingNotifEmail] = useState(false);
  const [notifEmailMsg, setNotifEmailMsg] = useState<string | null>(null);

  // Skill channel prefs: skill_id → channel
  const [channelPrefs, setChannelPrefs] = useState<Record<string, "web" | "sms" | "email">>({});
  const [channelMsgs, setChannelMsgs] = useState<Record<string, string>>({});

  useEffect(() => {
    async function load() {
      try {
        const token = await getToken();
        if (!token) return;
        const [me, channels] = await Promise.all([getMe(token), getSkillChannels(token)]);
        setCurrentPhone(me.phone_number);
        setCurrentNotifEmail(me.notification_email);
        const prefs: Record<string, "web" | "sms" | "email"> = {};
        for (const c of channels) {
          prefs[c.skill_id] = c.channel;
        }
        setChannelPrefs(prefs);
      } catch {
        // non-critical
      }
    }
    load();
  }, [getToken]);

  async function handleSavePhone() {
    if (!phoneInput.trim()) return;
    setSavingPhone(true);
    setPhoneMsg(null);
    try {
      const token = await getToken();
      if (!token) throw new Error("Not signed in");
      await savePhone(phoneInput.trim(), token);
      setCurrentPhone(phoneInput.trim());
      setPhoneInput("");
      setPhoneMsg("Phone number saved.");
    } catch (err: unknown) {
      setPhoneMsg(err instanceof Error ? err.message : "Failed to save phone number.");
    } finally {
      setSavingPhone(false);
    }
  }

  async function handleSaveNotifEmail() {
    if (!notifEmailInput.trim()) return;
    setSavingNotifEmail(true);
    setNotifEmailMsg(null);
    try {
      const token = await getToken();
      if (!token) throw new Error("Not signed in");
      await saveNotificationEmail(notifEmailInput.trim(), token);
      setCurrentNotifEmail(notifEmailInput.trim());
      setNotifEmailInput("");
      setNotifEmailMsg("Notification email saved.");
    } catch (err: unknown) {
      setNotifEmailMsg(err instanceof Error ? err.message : "Failed to save email.");
    } finally {
      setSavingNotifEmail(false);
    }
  }

  async function handleChannelChange(skillId: SkillId, channel: "web" | "sms" | "email") {
    // Client-side validation: sms requires phone, email requires notification email
    if (channel === "sms" && !currentPhone) {
      setChannelMsgs((prev) => ({ ...prev, [skillId]: "Add a phone number above first." }));
      return;
    }
    if (channel === "email" && !currentNotifEmail) {
      setChannelMsgs((prev) => ({ ...prev, [skillId]: "Add a notification email above first." }));
      return;
    }
    // Optimistic update
    setChannelPrefs((prev) => ({ ...prev, [skillId]: channel }));
    setChannelMsgs((prev) => ({ ...prev, [skillId]: "" }));
    try {
      const token = await getToken();
      if (!token) throw new Error("Not signed in");
      await saveSkillChannel(skillId, channel, token);
    } catch (err: unknown) {
      setChannelMsgs((prev) => ({
        ...prev,
        [skillId]: err instanceof Error ? err.message : "Failed to save.",
      }));
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
        <h1 style={{ fontSize: "20px", fontWeight: 700, flex: 1 }}>Account</h1>
        <a href="/" style={{ fontSize: "13px", color: "var(--text-muted)", textDecoration: "none" }}>Home</a>
      </div>

      {/* Phone number */}
      <div style={card}>
        <p style={label}>Phone number (SMS)</p>
        <p style={{ fontSize: "13px", marginBottom: "12px", color: "var(--text-muted)" }}>
          {currentPhone
            ? `Current: ${currentPhone}. Paste a new number to replace it.`
            : "Add your phone number to text Nestor directly and receive budget alerts via SMS."}
        </p>
        <input
          type="tel"
          placeholder="+14155550100"
          value={phoneInput}
          onChange={(e) => setPhoneInput(e.target.value)}
          style={inputStyle}
        />
        <button
          onClick={handleSavePhone}
          disabled={savingPhone || !phoneInput.trim()}
          style={btnStyle(savingPhone || !phoneInput.trim())}
        >
          {savingPhone ? "Saving…" : "Save phone"}
        </button>
        {phoneMsg && (
          <p style={{ marginTop: "8px", fontSize: "13px", color: phoneMsg === "Phone number saved." ? "#4ade80" : "var(--danger)" }}>
            {phoneMsg}
          </p>
        )}
      </div>

      {/* Notification email */}
      <div style={card}>
        <p style={label}>Notification email</p>
        <p style={{ fontSize: "13px", marginBottom: "12px", color: "var(--text-muted)" }}>
          {currentNotifEmail
            ? `Current: ${currentNotifEmail}. Paste a new address to replace it.`
            : "Add an email to receive budget alerts and other notifications."}
        </p>
        <input
          type="email"
          placeholder="you@example.com"
          value={notifEmailInput}
          onChange={(e) => setNotifEmailInput(e.target.value)}
          style={inputStyle}
        />
        <button
          onClick={handleSaveNotifEmail}
          disabled={savingNotifEmail || !notifEmailInput.trim()}
          style={btnStyle(savingNotifEmail || !notifEmailInput.trim())}
        >
          {savingNotifEmail ? "Saving…" : "Save email"}
        </button>
        {notifEmailMsg && (
          <p style={{ marginTop: "8px", fontSize: "13px", color: notifEmailMsg === "Notification email saved." ? "#4ade80" : "var(--danger)" }}>
            {notifEmailMsg}
          </p>
        )}
      </div>

      {/* Skill delivery channel preferences */}
      <div style={card}>
        <p style={label}>Skill reply channel</p>
        <p style={{ fontSize: "13px", marginBottom: "16px", color: "var(--text-muted)" }}>
          Choose where each skill sends its reply. When set to SMS or email, the web chat shows a redirect notification instead of the full reply.
        </p>
        {SKILLS.map((skill) => {
          const selected = channelPrefs[skill.id] ?? "web";
          const msg = channelMsgs[skill.id];
          return (
            <div key={skill.id} style={{ marginBottom: "14px" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px" }}>
                <span style={{ fontSize: "14px", fontWeight: 500 }}>{skill.label}</span>
                <select
                  value={selected}
                  onChange={(e) => handleChannelChange(skill.id, e.target.value as "web" | "sms" | "email")}
                  style={{
                    background: "var(--bg)",
                    border: "1px solid var(--border)",
                    borderRadius: "6px",
                    padding: "4px 8px",
                    color: "var(--text)",
                    fontSize: "13px",
                    cursor: "pointer",
                  }}
                >
                  <option value="web">Web (default)</option>
                  <option value="sms">SMS</option>
                  <option value="email">Email</option>
                </select>
              </div>
              {msg && (
                <p style={{ marginTop: "4px", fontSize: "12px", color: "var(--danger)" }}>{msg}</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
