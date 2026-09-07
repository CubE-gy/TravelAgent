import { describe, expect, it } from "vitest";

import { mapLocationsFromState, mapLocationsFromWorkspace, reconcileSelectedLocationId } from "@/map/locations";

describe("mapLocationsFromState", () => {
  it("maps only resolved business locations to role markers", () => {
    const markers = mapLocationsFromState({
      trip_id: "trip-1",
      revision: 1,
      origin: { query: "南京", resolution_status: "resolved", candidates: [], resolved_location: { poi_id: "origin", name: "南京站", address: null, coordinate: { latitude: 32, longitude: 118 } } },
      destination: { query: "北京", resolution_status: "unresolved", candidates: [], resolved_location: null },
      return_destination: null, outbound_departure_station: null, outbound_arrival_station: null,
      accommodation: { query: "王府井酒店", resolution_status: "resolved", candidates: [], resolved_location: { poi_id: "hotel", name: "王府井酒店", address: "北京市东城区", coordinate: { latitude: 39.9, longitude: 116.4 } } },
      places: [{ query: "故宫", resolution_status: "ambiguous", candidates: [], resolved_location: null }],
    });
    expect(markers).toEqual([
      expect.objectContaining({ role: "origin", roleLabel: "出发地", location: expect.objectContaining({ poi_id: "origin" }) }),
      expect.objectContaining({ role: "accommodation", roleLabel: "酒店", location: expect.objectContaining({ poi_id: "hotel" }) }),
    ]);
  });

  it("returns no markers without a state", () => {
    expect(mapLocationsFromState(null)).toEqual([]);
  });

  it("maps confirmed outbound stations with distinct marker roles", () => {
    const markers = mapLocationsFromState({
      trip_id: "trip-1", revision: 1, origin: null, destination: null, return_destination: null,
      outbound_departure_station: { query: "北京高铁站", resolution_status: "resolved", candidates: [], resolved_location: { poi_id: "beijing-south", name: "北京南站", address: null, coordinate: { latitude: 39.865, longitude: 116.379 } } },
      outbound_arrival_station: { query: "南京高铁站", resolution_status: "resolved", candidates: [], resolved_location: { poi_id: "nanjing-south", name: "南京南站", address: null, coordinate: { latitude: 31.97, longitude: 118.8 } } },
      accommodation: null, places: [],
    });
    expect(markers).toEqual(expect.arrayContaining([
      expect.objectContaining({ role: "outbound_departure_station", roleLabel: "去程出发站" }),
      expect.objectContaining({ role: "outbound_arrival_station", roleLabel: "去程到达站" }),
    ]));
  });

  it("adds intercity stations and merges entries that share a poi ID", () => {
    const station = { poi_id: "station", name: "北京南站", address: "北京市丰台区", coordinate: { latitude: 39.865, longitude: 116.379 } };
    const markers = mapLocationsFromWorkspace({
      trip_id: "trip-1", revision: 1,
      origin: { query: "北京南站", resolution_status: "resolved", candidates: [], resolved_location: station },
      destination: null, return_destination: null, outbound_departure_station: null, outbound_arrival_station: null, accommodation: null, places: [],
    }, {
      trip_id: "trip-1", source_state_revision: 1, stale: false,
      nodes: [
        { node_id: "node-1", kind: "outbound_departure_node", location: station },
        { node_id: "node-2", kind: "place", location: { poi_id: "place", name: "故宫", address: null, coordinate: { latitude: 39.9, longitude: 116.4 } } },
      ],
    });
    expect(markers).toHaveLength(1);
    expect(markers[0]).toMatchObject({
      id: "intercity_station-station",
      role: "intercity_station",
      roleLabels: ["城际站点", "出发地"],
      selectionIds: ["intercity_station-station", "origin-station"],
    });
  });

  it("clears a selection that no longer belongs to the refreshed map locations", () => {
    const locations = mapLocationsFromState({
      trip_id: "trip-1", revision: 1,
      origin: { query: "南京", resolution_status: "resolved", candidates: [], resolved_location: { poi_id: "home", name: "南京站", address: null, coordinate: { latitude: 32, longitude: 118 } } },
      destination: null, return_destination: null, outbound_departure_station: null, outbound_arrival_station: null, accommodation: null, places: [],
    });
    expect(reconcileSelectedLocationId("origin-home", locations)).toBe("origin-home");
    expect(reconcileSelectedLocationId("place-deleted", locations)).toBeNull();
  });
});
