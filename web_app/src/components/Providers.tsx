"use client";

import { ClerkProvider } from "@clerk/nextjs";

// Mirror middleware.ts: wrap with ClerkProvider only when the publishable
// key is available (production). In local/MVP mode the app runs auth-free.
export function Providers({ children }: { children: React.ReactNode }) {
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return <>{children}</>;
  }
  return <ClerkProvider>{children}</ClerkProvider>;
}
