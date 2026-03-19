import "@testing-library/jest-dom";
import { vi } from "vitest";

// Mock next/navigation — these hooks throw in jsdom
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

// Mock Clerk — return a default signed-in user state
vi.mock("@clerk/nextjs", () => ({
  useUser: () => ({
    isLoaded: true,
    isSignedIn: true,
    user: {
      id: "test-user-id",
      primaryEmailAddress: { emailAddress: "test@example.com" },
      firstName: "Test",
      lastName: "User",
      fullName: "Test User",
    },
  }),
  useAuth: () => ({
    isLoaded: true,
    isSignedIn: true,
    userId: "test-user-id",
    getToken: vi.fn().mockResolvedValue("mock-token"),
  }),
  ClerkProvider: ({ children }: { children: React.ReactNode }) => children,
  SignIn: () => null,
  SignUp: () => null,
}));
