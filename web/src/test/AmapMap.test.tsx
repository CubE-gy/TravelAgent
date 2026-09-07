import { render, screen, waitFor } from "@testing-library/react";
import AMapLoader from "@amap/amap-jsapi-loader";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AmapMap } from "@/map/AmapMap";

vi.mock("@amap/amap-jsapi-loader", () => ({ default: { load: vi.fn() } }));

describe("AmapMap", () => {
  beforeEach(() => vi.resetAllMocks());

  it("frames a confirmed city without inventing a POI marker", async () => {
    const map = { add: vi.fn(), addControl: vi.fn(), clearMap: vi.fn(), destroy: vi.fn(), setFitView: vi.fn(), setCenter: vi.fn(), setZoomAndCenter: vi.fn() };
    const marker = vi.fn();
    vi.mocked(AMapLoader.load).mockResolvedValue({ Map: class { constructor() { return map; } }, Marker: class { constructor() { marker(); } }, Scale: class {}, ToolBar: class {}, InfoWindow: class {} } as never);
    render(<AmapMap city={{ name: "南京市", adcode: "320100", city_code: "025", center: { longitude: 118.8, latitude: 32.06 } }} locations={[]} onSelectLocation={vi.fn()} selectedLocationId={null} />);
    await waitFor(() => expect(map.setZoomAndCenter).toHaveBeenCalledWith(11, [118.8, 32.06]));
    expect(marker).not.toHaveBeenCalled();
    expect(screen.getByText(/已定位南京市/)).toBeInTheDocument();
  });

  it("closes removed marker details and restores the city view", async () => {
    const map = { add: vi.fn(), addControl: vi.fn(), clearMap: vi.fn(), destroy: vi.fn(), setFitView: vi.fn(), setCenter: vi.fn(), setZoomAndCenter: vi.fn() };
    const close = vi.fn();
    vi.mocked(AMapLoader.load).mockResolvedValue({ Map: class { constructor() { return map; } }, Marker: class { on() {} }, Scale: class {}, ToolBar: class {}, InfoWindow: class { open() {} close() { close(); } } } as never);
    const city = { name: "南京市", adcode: "320100", city_code: "025", center: { longitude: 118.8, latitude: 32.06 } };
    const locations = [{ id: "place-sun", role: "place" as const, roleLabel: "景点", roles: ["place" as const], roleLabels: ["景点"], selectionIds: ["place-sun"], location: { poi_id: "sun", name: "中山陵", address: null, coordinate: { latitude: 32.06, longitude: 118.85 } } }];
    const view = render(<AmapMap city={city} locations={locations} onSelectLocation={vi.fn()} selectedLocationId="place-sun" />);
    await waitFor(() => expect(map.setFitView).toHaveBeenCalledTimes(1));
    view.rerender(<AmapMap city={city} locations={[]} onSelectLocation={vi.fn()} selectedLocationId={null} />);
    expect(close).toHaveBeenCalled();
    expect(map.setZoomAndCenter).toHaveBeenCalledWith(11, [118.8, 32.06]);
  });

  it("shows an empty-map state after the SDK initializes", async () => {
    const map = { add: vi.fn(), addControl: vi.fn(), clearMap: vi.fn(), destroy: vi.fn(), setFitView: vi.fn(), setCenter: vi.fn(), setZoomAndCenter: vi.fn() };
    vi.mocked(AMapLoader.load).mockResolvedValue({ Map: class { constructor() { return map; } }, Marker: class {}, Scale: class {}, ToolBar: class {}, InfoWindow: class {} } as never);
    render(<AmapMap locations={[]} onSelectLocation={vi.fn()} selectedLocationId={null} />);
    expect(await screen.findByText("尚无已确认地点可显示在地图上。")).toBeInTheDocument();
    await waitFor(() => expect(map.setZoomAndCenter).toHaveBeenCalledWith(5, [116.397428, 39.90923]));
  });

  it("shows a clear error when the SDK fails to load", async () => {
    vi.mocked(AMapLoader.load).mockRejectedValue(new Error("network"));
    render(<AmapMap locations={[]} onSelectLocation={vi.fn()} selectedLocationId={null} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("高德地图加载失败");
  });

  it("keeps a visible warning when transport nodes come from a stale plan", async () => {
    const map = { add: vi.fn(), addControl: vi.fn(), clearMap: vi.fn(), destroy: vi.fn(), setFitView: vi.fn(), setCenter: vi.fn(), setZoomAndCenter: vi.fn() };
    vi.mocked(AMapLoader.load).mockResolvedValue({ Map: class { constructor() { return map; } }, Marker: class {}, Scale: class {}, ToolBar: class {}, InfoWindow: class {} } as never);
    render(<AmapMap locations={[]} onSelectLocation={vi.fn()} selectedLocationId={null} transportPlanStale />);
    expect(await screen.findByRole("status")).toHaveTextContent("交通方案已过期");
  });

  it("centers on a selected location without fitting again and keeps details concise", async () => {
    const map = { add: vi.fn(), addControl: vi.fn(), clearMap: vi.fn(), destroy: vi.fn(), setFitView: vi.fn(), setCenter: vi.fn(), setZoomAndCenter: vi.fn() };
    const infoWindowOptions: Array<{ content: HTMLElement }> = [];
    vi.mocked(AMapLoader.load).mockResolvedValue({ Map: class { constructor() { return map; } }, Marker: class { on() {} }, Scale: class {}, ToolBar: class {}, InfoWindow: class { constructor(options: { content: HTMLElement }) { infoWindowOptions.push(options); } open() {} close() {} } } as never);
    const locations = [{ id: "place-palace", role: "place" as const, roleLabel: "景点", roles: ["place" as const], roleLabels: ["景点"], selectionIds: ["place-palace"], location: { poi_id: "poi-secret", name: "故宫", address: "北京市东城区", coordinate: { latitude: 39.916, longitude: 116.397 } } }];
    const view = render(<AmapMap locations={locations} onSelectLocation={vi.fn()} selectedLocationId={null} />);
    await waitFor(() => expect(map.setFitView).toHaveBeenCalledTimes(1));
    map.setFitView.mockClear();
    view.rerender(<AmapMap locations={locations} onSelectLocation={vi.fn()} selectedLocationId="place-palace" />);
    await waitFor(() => expect(map.setCenter).toHaveBeenCalledWith([116.397, 39.916]));
    expect(map.setFitView).not.toHaveBeenCalled();
    expect(infoWindowOptions[0].content.textContent).toBe("景点｜故宫｜北京市东城区");
  });
});
