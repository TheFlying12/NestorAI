/**
 * REST API helpers for the NestorAI cloud service.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

async function apiFetch<T>(
  path: string,
  token: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(options.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${path} failed ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export interface MeResponse {
  user_id: string;
  email: string | null;
  has_api_key: boolean;
  auth_provider: string;
}

export async function getMe(token: string): Promise<MeResponse> {
  return apiFetch<MeResponse>("/api/auth/me", token);
}

export async function storeApiKey(
  token: string,
  apiKey: string,
  provider: "openai" | "gemini" = "openai"
): Promise<void> {
  await apiFetch("/api/auth/apikey", token, {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey, provider }),
  });
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export async function getConversationMessages(
  token: string,
  skillId: string,
  limit = 50
): Promise<ChatMessage[]> {
  const data = await apiFetch<{ messages: ChatMessage[] }>(
    `/api/conversations/messages?skill_id=${encodeURIComponent(skillId)}&limit=${limit}`,
    token
  );
  return data.messages;
}
