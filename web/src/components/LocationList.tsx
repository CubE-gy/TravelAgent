import type { LocationIntent, TripState, TripStateLocationField } from "@/api/types";
import type { MapLocation } from "@/map/locations";

type LocationEntry = { id: string; field: TripStateLocationField; label: string; location: LocationIntent | null; placeIndex?: number };

function entriesFromState(state: TripState): LocationEntry[] {
  return [
    { id: "origin", field: "origin" as const, label: "出发地", location: state.origin },
    { id: "destination", field: "destination" as const, label: "目的地", location: state.destination },
    { id: "return_destination", field: "return_destination" as const, label: "返程地", location: state.return_destination },
    { id: "outbound-departure-station", field: "outbound_departure_station" as const, label: "去程出发站", location: state.outbound_departure_station },
    { id: "outbound-arrival-station", field: "outbound_arrival_station" as const, label: "去程到达站", location: state.outbound_arrival_station },
    { id: "accommodation", field: "accommodation" as const, label: "酒店", location: state.accommodation },
    ...state.places.map((location, placeIndex) => ({ id: `places-${placeIndex}`, field: "places" as const, label: `景点 ${placeIndex + 1}`, location, placeIndex })),
  ].filter((entry) => entry.location !== null);
}

function markerSelectionId(field: TripStateLocationField, poiId: string): string {
  return `${field === "places" ? "place" : field}-${poiId}`;
}

function markerForSelectionId(locations: MapLocation[], selectionId: string): MapLocation | undefined {
  return locations.find((location) => location.selectionIds.includes(selectionId));
}

function locationCardClassName(selected: boolean): string {
  return `rounded-xl border p-4 transition-colors ${selected ? "border-sky-400 bg-sky-50 shadow-sm" : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/50"}`;
}

function roleBadgeClassName(role: MapLocation["role"] | undefined): string {
  return { intercity_station: "bg-teal-50 text-teal-700", outbound_departure_station: "bg-cyan-50 text-cyan-700", outbound_arrival_station: "bg-violet-50 text-violet-700", origin: "bg-emerald-50 text-emerald-700", destination: "bg-blue-50 text-blue-700", return_destination: "bg-violet-50 text-violet-700", accommodation: "bg-orange-50 text-orange-700", place: "bg-rose-50 text-rose-700", recommendation_accommodation: "bg-amber-50 text-amber-700", recommendation_place: "bg-violet-50 text-violet-700" }[role ?? "place"];
}

export function LocationList({ state, locations, transportPlanStale = false, selectedLocationId, onSelect }: {
  state: TripState | null;
  locations: MapLocation[];
  transportPlanStale?: boolean;
  selectedLocationId: string | null;
  onSelect: (locationId: string) => void;
}) {
  const entries = state ? entriesFromState(state) : [];
  const resolvedPoiIds = new Set(entries.flatMap((entry) => entry.location?.resolved_location ? [entry.location.resolved_location.poi_id] : []));
  const intercityStations = locations.filter((location) => location.roles.includes("intercity_station") && !resolvedPoiIds.has(location.location.poi_id));
  if (!entries.length && !intercityStations.length) return <p className="text-sm text-slate-600">尚未记录地点。</p>;
  return <ul className="space-y-3" aria-label="地点列表">
    {entries.map((entry) => {
      const location = entry.location!;
      const resolved = location.resolved_location;
      const marker = resolved ? markerForSelectionId(locations, markerSelectionId(entry.field, resolved.poi_id)) : undefined;
      const selected = selectedLocationId !== null && marker?.selectionIds.includes(selectedLocationId) === true;
      return <li className={locationCardClassName(selected)} key={entry.id}>
        <p className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${roleBadgeClassName(marker?.role)}`}>{marker?.roleLabels.join("、") ?? entry.label}</p>
        {resolved ? <button className="mt-2 block text-left text-sm font-semibold underline-offset-2 hover:underline" onClick={() => onSelect(marker?.id ?? markerSelectionId(entry.field, resolved.poi_id))} type="button">{resolved.name}</button> : <p className="mt-2 text-sm font-semibold">{location.query}</p>}
        {resolved?.address ? <p className="mt-1 text-xs leading-5 text-slate-500">{resolved.address}</p> : null}
        {location.resolved_city ? <p className="mt-1 text-xs leading-5 text-slate-500">{location.resolved_city.name} · 城市范围，尚未指定具体出发或抵达地点</p> : null}
        {location.resolution_status === "resolved" ? <p className="mt-3 text-xs font-medium text-emerald-700">已确认</p> : null}
        {location.resolution_status === "unresolved" ? <p className="mt-3 text-xs font-medium text-amber-700">尚未定位，可在对话中补充或重试</p> : null}
        {location.resolution_status === "ambiguous" ? <div className="mt-3 space-y-2"><p className="text-xs text-amber-700">需要一点线索：请在对话中补充完整名称、所在区域或地址。</p></div> : null}
      </li>;
    })}
    {intercityStations.map((station) => {
      const selected = selectedLocationId !== null && station.selectionIds.includes(selectedLocationId);
      return <li className={locationCardClassName(selected)} key={station.id}>
        <p className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${roleBadgeClassName(station.role)}`}>{station.roleLabels.join("、")}</p>
        <button className="mt-2 block text-left text-sm font-semibold underline-offset-2 hover:underline" onClick={() => onSelect(station.id)} type="button">{station.location.name}</button>
        {station.location.address ? <p className="mt-1 text-xs leading-5 text-slate-500">{station.location.address}</p> : null}
        <p className={`mt-3 text-xs font-medium ${transportPlanStale ? "text-amber-700" : "text-slate-500"}`}>{transportPlanStale ? "来自过期交通方案" : "已保存交通方案"}</p>
      </li>;
    })}
  </ul>;
}
