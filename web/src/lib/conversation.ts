import type { TripConversationRead } from "@/api/types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  failed?: boolean;
}

export function chatMessage(role: ChatMessage["role"], content: string): ChatMessage {
  return { id: crypto.randomUUID(), role, content };
}

export function readChat(tripId: string): ChatMessage[] {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(`travel-chat:${tripId}`) ?? "[]");
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is ChatMessage => item && typeof item.id === "string"
      && (item.role === "user" || item.role === "assistant") && typeof item.content === "string");
  } catch { return []; }
}

export function saveChat(tripId: string, messages: ChatMessage[]) {
  try { sessionStorage.setItem(`travel-chat:${tripId}`, JSON.stringify(messages)); }
  catch { /* Conversation remains usable when browser storage is unavailable. */ }
}

export function recentConversationContext(messages: ChatMessage[]) {
  const retained: Array<Pick<ChatMessage, "role" | "content">> = [];
  let total = 0;
  for (const message of messages.filter((item) => !item.failed).slice(-10).reverse()) {
    const content = message.content.slice(0, 1000);
    if (total + content.length > 8000) break;
    retained.push({ role: message.role, content });
    total += content.length;
  }
  return retained.reverse();
}

export function agentReply(result: TripConversationRead): string {
  if (!result.assistant_message) throw new Error("Agent response is missing");
  return result.assistant_message;
}
