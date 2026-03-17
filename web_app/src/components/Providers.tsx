"use client";

// MVP / local mode: no auth wrapper.
// Add ClerkProvider back here when deploying to production.
export function Providers({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
