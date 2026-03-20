"use client";

import dynamic from "next/dynamic";

// Clerk hooks require a browser context — skip SSR entirely.
const AccountContent = dynamic(() => import("./AccountContent"), {
  ssr: false,
});

export default function AccountPage() {
  return <AccountContent />;
}
