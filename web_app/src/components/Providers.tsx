"use client";

import { ClerkProvider, Show, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <header style={{ display: "flex", gap: "8px", padding: "8px 16px", justifyContent: "flex-end" }}>
        <Show when="signed-out">
          <SignInButton>
            <button style={{ color: "#fff", background: "transparent", border: "1px solid rgba(255,255,255,0.4)", borderRadius: "6px", padding: "6px 14px", cursor: "pointer", fontSize: "14px" }}>
              Sign in
            </button>
          </SignInButton>
          <SignUpButton>
            <button style={{ color: "#fff", background: "rgba(255,255,255,0.15)", border: "1px solid rgba(255,255,255,0.4)", borderRadius: "6px", padding: "6px 14px", cursor: "pointer", fontSize: "14px" }}>
              Sign up
            </button>
          </SignUpButton>
        </Show>
        <Show when="signed-in">
          <UserButton />
        </Show>
      </header>
      {children}
    </ClerkProvider>
  );
}
