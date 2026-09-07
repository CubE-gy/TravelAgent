import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LocationList } from "@/components/LocationList";

describe("LocationList", () => {
  it("renders business roles and selects a resolved location", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<LocationList locations={[]} onSelect={onSelect} selectedLocationId={null} state={{ trip_id: "trip-1", revision: 1, origin: { query: "南京", resolution_status: "resolved", candidates: [], resolved_location: { poi_id: "home", name: "南京站", address: "南京市玄武区", coordinate: { latitude: 32, longitude: 118 } } }, destination: null, return_destination: null, outbound_departure_station: null, outbound_arrival_station: null, accommodation: null, places: [] }} />);
    expect(screen.getByText("出发地")).toBeInTheDocument();
    expect(screen.getByText("南京站")).toBeInTheDocument();
    expect(screen.getByText("已确认")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "南京站" }));
    expect(onSelect).toHaveBeenCalledWith("origin-home");
  });

  it("guides an ambiguous attraction back to the Agent instead of exposing a picker", () => {
    render(<LocationList locations={[]} onSelect={vi.fn()} selectedLocationId={null} state={{ trip_id: "trip-1", revision: 1, origin: null, destination: null, return_destination: null, outbound_departure_station: null, outbound_arrival_station: null, accommodation: null, places: [{ query: "万达广场", resolution_status: "ambiguous", candidates: [{ poi_id: "poi-1", name: "北京万达广场", address: "北京市朝阳区", coordinate: { latitude: 39.9, longitude: 116.4 } }], resolved_location: null }] }} />);
    expect(screen.getByText(/请在对话中补充完整名称/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /北京万达广场/ })).not.toBeInTheDocument();
  });

  it("does not show station candidate buttons in the workspace", () => {
    render(<LocationList locations={[]} onSelect={vi.fn()} selectedLocationId={null} state={{ trip_id: "trip-1", revision: 1, origin: null, destination: null, return_destination: null, outbound_departure_station: { query: "北京高铁站", resolution_status: "ambiguous", candidates: [{ poi_id: "beijing-south", name: "北京南站", address: "北京市丰台区", coordinate: { latitude: 39.865, longitude: 116.379 } }, { poi_id: "beijing-fengtai", name: "北京丰台站", address: "北京市丰台区", coordinate: { latitude: 39.85, longitude: 116.31 } }], resolved_location: null }, outbound_arrival_station: null, accommodation: null, places: [] }} />);
    expect(screen.getByText(/请在对话中补充完整名称/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /北京南站/ })).not.toBeInTheDocument();
  });

  it("renders a transport-only station and selects its map marker", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<LocationList locations={[{ id: "intercity_station-station", role: "intercity_station", roleLabel: "城际站点", roles: ["intercity_station"], roleLabels: ["城际站点"], selectionIds: ["intercity_station-station"], location: { poi_id: "station", name: "北京南站", address: "北京市丰台区", coordinate: { latitude: 39.865, longitude: 116.379 } } }]} onSelect={onSelect} selectedLocationId={null} state={null} />);
    expect(screen.getByText("城际站点")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "北京南站" }));
    expect(onSelect).toHaveBeenCalledWith("intercity_station-station");
  });
});
