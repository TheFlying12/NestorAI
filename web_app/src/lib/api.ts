/**
 * REST API helpers for the NestorAI cloud service.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

async function apiFetch<T>(
  path: string,
  token: string | null,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> ?? {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
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
  token: string | null,
  limit = 50,
): Promise<ChatMessage[]> {
  const data = await apiFetch<{ messages: ChatMessage[] }>(
    `/api/conversations/messages?skill_id=${encodeURIComponent(skillId)}&limit=${limit}`,
    token,
  );
  return data.messages;
}

export async function storeApiKey(apiKey: string, token: string): Promise<void> {
  await apiFetch<{ status: string }>("/api/auth/apikey", token, {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export async function getMe(
  token: string,
): Promise<{
  user_id: string;
  email: string | null;
  has_llm_key: boolean;
  phone_number: string | null;
  notification_email: string | null;
}> {
  return apiFetch("/api/auth/me", token);
}

export async function savePhone(phone: string, token: string): Promise<void> {
  await apiFetch<{ status: string }>("/api/me/phone", token, {
    method: "POST",
    body: JSON.stringify({ phone_number: phone }),
  });
}

export async function saveNotificationEmail(email: string, token: string): Promise<void> {
  await apiFetch<{ status: string }>("/api/me/notification-email", token, {
    method: "POST",
    body: JSON.stringify({ notification_email: email }),
  });
}
