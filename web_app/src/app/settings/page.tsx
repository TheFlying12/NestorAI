"use client";

import dynamic from "next/dynamic";

// Clerk hooks (useAuth, useUser) require a browser context — skip SSR entirely.
const SettingsContent = dynamic(() => import("./SettingsContent"), {
  ssr: false,
});

export default function SettingsPage() {
  return <SettingsContent />;
}
