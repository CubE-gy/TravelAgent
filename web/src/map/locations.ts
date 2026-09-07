import type { PublicTransportPlan, ResolvedLocation, TripRecommendation, TripState } from "@/api/types";

export type MapMarkerRole = "intercity_station" | "outbound_departure_station" | "outbound_arrival_station" | "origin" | "destination" | "return_destination" | "accommodation" | "place" | "recommendation_accommodation" | "recommendation_place";

export interface MapLocation {
  id: string;
  role: MapMarkerRole;
  roleLabel: string;
  roles: MapMarkerRole[];
  roleLabels: string[];
  selectionIds: string[];
  location: ResolvedLocation;
}

const roleLabels: Record<MapMarkerRole, string> = {
  intercity_station: "城际站点",
  outbound_departure_station: "去程出发站",
  outbound_arrival_station: "去程到达站",
  origin: "出发地",
  destination: "目的地",
  return_destination: "返程地",
  accommodation: "酒店",
  place: "景点",
  recommendation_accommodation: "推荐酒店",
  recommendation_place: "推荐景点",
};

const rolePriority: MapMarkerRole[] = [
  "intercity_station",
  "outbound_departure_station",
  "outbound_arrival_station",
  "accommodation",
  "origin",
  "return_destination",
  "destination",
  "place",
];

function selectionId(role: MapMarkerRole, location: ResolvedLocation): string {
  return `${role}-${location.poi_id}`;
}

function intercityStationNodes(plan: PublicTransportPlan | null): ResolvedLocation[] {
  if (!plan) return [];
  const intercityNodeKinds = new Set([
    "outbound_departure_node",
    "outbound_arrival_node",
    "return_departure_node",
    "return_arrival_node",
  ]);
  return plan.nodes
    .filter((node) => intercityNodeKinds.has(node.kind))
    .map((node) => node.location);
}

export function mapLocationsFromWorkspace(
  state: TripState | null,
  publicTransportPlan: PublicTransportPlan | null,
): MapLocation[] {
  const stateLocations: Array<{ role: MapMarkerRole; location: ResolvedLocation | null }> = state ? [
    { role: "origin", location: state.origin?.resolved_location ?? null },
    { role: "destination", location: state.destination?.resolved_location ?? null },
    { role: "return_destination", location: state.return_destination?.resolved_location ?? null },
    { role: "outbound_departure_station", location: state.outbound_departure_station?.resolved_location ?? null },
    { role: "outbound_arrival_station", location: state.outbound_arrival_station?.resolved_location ?? null },
    { role: "accommodation", location: state.accommodation?.resolved_location ?? null },
    ...state.places.map((place) => ({ role: "place" as const, location: place.resolved_location })),
  ] : [];
  const locations: Array<{ role: MapMarkerRole; location: ResolvedLocation | null }> = [
    ...intercityStationNodes(publicTransportPlan).map((location) => ({ role: "intercity_station" as const, location })),
    ...stateLocations,
  ];
  const locationsByPoiId = new Map<string, Array<{ role: MapMarkerRole; location: ResolvedLocation }>>();
  for (const entry of locations) {
    if (!entry.location) continue;
    const entries = locationsByPoiId.get(entry.location.poi_id) ?? [];
    entries.push({ role: entry.role, location: entry.location });
    locationsByPoiId.set(entry.location.poi_id, entries);
  }
  return [...locationsByPoiId.values()].map((entries) => {
    const station = entries.some(({ location }) => /^150[12]/.test(location.category_code ?? ""));
    const roles = [...new Set([...entries.map((entry) => entry.role), ...(station ? ["intercity_station" as const] : [])])].sort(
      (left, right) => rolePriority.indexOf(left) - rolePriority.indexOf(right),
    );
    const role = roles[0];
    const location = entries[0].location;
    return {
      id: selectionId(role, location),
      role,
      roleLabel: roleLabels[role],
      roles,
      roleLabels: roles.map((item) => roleLabels[item]),
      selectionIds: roles.map((item) => selectionId(item, location)),
      location,
    };
  });
}

export function mapLocationsWithRecommendations(
  state: TripState | null, publicTransportPlan: PublicTransportPlan | null,
  recommendations: TripRecommendation[],
): MapLocation[] {
  const persisted = mapLocationsFromWorkspace(state, publicTransportPlan);
  const savedPoiIds = new Set(persisted.map((item) => item.location.poi_id));
  const temporary = recommendations
    .filter((item) => !savedPoiIds.has(item.location.poi_id))
    .map((item) => {
      const role: MapMarkerRole = item.kind === "accommodation" ? "recommendation_accommodation" : "recommendation_place";
      return { id: `recommendation-${item.location.poi_id}`, role, roleLabel: roleLabels[role], roles: [role], roleLabels: [roleLabels[role]], selectionIds: [`recommendation-${item.location.poi_id}`], location: item.location };
    });
  return [...persisted, ...temporary];
}

export function mapLocationsFromState(state: TripState | null): MapLocation[] {
  return mapLocationsFromWorkspace(state, null);
}

export function reconcileSelectedLocationId(
  selectedLocationId: string | null,
  locations: MapLocation[],
): string | null {
  if (selectedLocationId === null) return null;
  return locations.some((location) => location.selectionIds.includes(selectedLocationId))
    ? selectedLocationId
    : null;
}

export const markerColors: Record<MapMarkerRole, string> = {
  intercity_station: "#0f766e",
  outbound_departure_station: "#0891b2",
  outbound_arrival_station: "#7c3aed",
  origin: "#15803d",
  destination: "#2563eb",
  return_destination: "#7c3aed",
  accommodation: "#ea580c",
  place: "#dc2626",
  recommendation_accommodation: "#f59e0b",
  recommendation_place: "#a855f7",
};
