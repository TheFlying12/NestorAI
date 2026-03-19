import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MessageBubble, TypingIndicator } from "@/components/MessageBubble";
import type { Message } from "@/components/MessageBubble";

const userMessage: Message = {
  id: "1",
  role: "user",
  text: "Hello, Nestor!",
  timestamp: new Date("2024-01-01T10:00:00Z"),
};

const assistantMessage: Message = {
  id: "2",
  role: "assistant",
  text: "Hi! How can I help you?",
  timestamp: new Date("2024-01-01T10:00:01Z"),
};

describe("MessageBubble", () => {
  it("renders user message text", () => {
    render(<MessageBubble message={userMessage} />);
    expect(screen.getByText("Hello, Nestor!")).toBeInTheDocument();
  });

  it("renders assistant message text", () => {
    render(<MessageBubble message={assistantMessage} />);
    expect(screen.getByText("Hi! How can I help you?")).toBeInTheDocument();
  });

  it("mounts without crashing for user role", () => {
    const { container } = render(<MessageBubble message={userMessage} />);
    expect(container.firstChild).not.toBeNull();
  });

  it("mounts without crashing for assistant role", () => {
    const { container } = render(<MessageBubble message={assistantMessage} />);
    expect(container.firstChild).not.toBeNull();
  });
});

describe("TypingIndicator", () => {
  it("mounts without crashing", () => {
    const { container } = render(<TypingIndicator />);
    expect(container.firstChild).not.toBeNull();
  });
});
