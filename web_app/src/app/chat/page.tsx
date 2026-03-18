"use client";

import dynamic from "next/dynamic";

// Clerk hooks (useAuth) require a browser context — skip SSR entirely.
const ChatContent = dynamic(() => import("./ChatContent"), {
  ssr: false,
});

export default function ChatPage() {
  return <ChatContent />;
}
