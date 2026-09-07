import type {
  TripConversationCreateRead,
  TripConversationRead,
  TripLocationConfirmationRead,
  Trip,
  TripStateLocationField,
  TripWorkspace,
  TripRecommendation,
  TripRecommendationContext,
  ConversationContextMessage,
} from "@/api/types";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
  } catch {
    throw new ApiError("无法连接旅行服务，请检查网络或稍后重试。", 0);
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    const serviceErrors: Record<number, string> = {
      502: "旅行服务暂时未能完成处理，请稍后重试。",
      503: "旅行服务暂时不可用，请稍后重试。",
    };
    throw new ApiError(serviceErrors[response.status]
      ?? (typeof payload?.detail === "string" ? payload.detail : "输入信息未能处理，请检查后重试。"), response.status);
  }
  return response.json() as Promise<T>;
}

export function createTripFromFirstMessage(message: string, conversationContext: ConversationContextMessage[] = []) {
  return request<TripConversationCreateRead>("/trips/conversations", {
    method: "POST",
    body: JSON.stringify({ message, conversation_context: conversationContext }),
  });
}

export function getTrips() {
  return request<Trip[]>("/trips");
}

export function getTripWorkspace(tripId: string) {
  return request<TripWorkspace>(`/trips/${encodeURIComponent(tripId)}/workspace`);
}

export function sendTripMessage(
  tripId: string,
  message: string,
  expectedRevision: number,
  conversationContext: ConversationContextMessage[] = [],
  recommendationContext?: TripRecommendationContext,
) {
  return request<TripConversationRead>(`/trips/${encodeURIComponent(tripId)}/messages`, {
    method: "POST",
    body: JSON.stringify({ message, expected_revision: expectedRevision, conversation_context: conversationContext,
      ...(recommendationContext ? { recommendation_context: recommendationContext } : {}) }),
  });
}

export function selectTripRecommendation(
  tripId: string, recommendation: TripRecommendation, expectedRevision: number, recommendationSessionId?: string,
) {
  return request<TripConversationRead>(`/trips/${encodeURIComponent(tripId)}/recommendations/select`, {
    method: "POST",
    body: JSON.stringify({ kind: recommendation.kind, poi_id: recommendation.location.poi_id, expected_revision: expectedRevision,
      ...(recommendationSessionId ? { recommendation_session_id: recommendationSessionId } : {}) }),
  });
}

export function confirmTripLocation(
  tripId: string,
  field: TripStateLocationField,
  poiId: string,
  expectedRevision: number,
  placeIndex?: number,
) {
  return request<TripLocationConfirmationRead>(`/trips/${encodeURIComponent(tripId)}/locations/confirm`, {
    method: "POST",
    body: JSON.stringify({
      field,
      poi_id: poiId,
      expected_revision: expectedRevision,
      ...(field === "places" ? { place_index: placeIndex } : {}),
    }),
  });
}
