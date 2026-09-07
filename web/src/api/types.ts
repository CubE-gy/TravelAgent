export type LocationResolutionStatus = "unresolved" | "ambiguous" | "resolved";
export type TripStateLocationField = "origin" | "destination" | "return_destination" | "outbound_departure_station" | "outbound_arrival_station" | "accommodation" | "places";

export interface ResolvedLocation {
  poi_id: string;
  name: string;
  address: string | null;
  category_name?: string | null;
  category_code?: string | null;
  city_code?: string | null;
  coordinate: { latitude: number; longitude: number };
}

export interface ResolvedCity {
  name: string;
  adcode: string;
  city_code: string;
  center: { latitude: number; longitude: number };
}

export interface LocationIntent {
  query: string;
  resolution_status: LocationResolutionStatus;
  candidates: ResolvedLocation[];
  resolved_location: ResolvedLocation | null;
  resolved_city?: ResolvedCity | null;
}

export interface TripState {
  trip_id: string;
  revision: number;
  origin: LocationIntent | null;
  destination: LocationIntent | null;
  return_destination: LocationIntent | null;
  outbound_departure_station: LocationIntent | null;
  outbound_arrival_station: LocationIntent | null;
  accommodation: LocationIntent | null;
  places: LocationIntent[];
}

export interface Trip {
  id: string;
  name: string | null;
  start_date: string | null;
  end_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface PublicTransportPlan {
  trip_id: string;
  source_state_revision: number;
  stale: boolean;
  nodes: PublicTransportPlanNode[];
}

export interface PublicTransportPlanNode {
  node_id: string;
  kind: string;
  location: ResolvedLocation;
}

export interface TripWorkspace {
  trip: Trip;
  state: TripState | null;
  public_transport_plan: PublicTransportPlan | null;
}

export interface TripConversationCreateRead extends TripConversationRead {
  trip: Trip;
  state: TripState;
  revision: number;
}

export interface TripConversationRead {
  state: TripState;
  revision: number;
  clarification: { questions: Array<{ topic_id: string; question: string }> };
  location_failures: Array<{ field: TripStateLocationField; query: string; error_code: string; place_index?: number | null }>;
  assistant_message: string | null;
  recommendations?: TripRecommendation[];
  recommendation_session_id?: string | null;
}

export interface TripRecommendation {
  kind: "accommodation" | "places";
  location: ResolvedLocation;
}

export interface TripRecommendationContext {
  recommendation_session_id: string;
}

export interface ConversationContextMessage { role: "user" | "assistant"; content: string; }

export interface TripLocationConfirmationRead {
  state: TripState;
  revision: number;
}
