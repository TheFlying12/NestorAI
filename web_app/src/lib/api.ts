/**
 * REST API helpers for the NestorAI cloud service.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${path} failed ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export async function getConversationMessages(
  skillId: string,
  limit = 50
): Promise<ChatMessage[]> {
  const data = await apiFetch<{ messages: ChatMessage[] }>(
    `/api/conversations/messages?skill_id=${encodeURIComponent(skillId)}&limit=${limit}`
  );
  return data.messages;
}
