import AMapLoader from "@amap/amap-jsapi-loader";
import { useEffect, useRef, useState } from "react";
import type { ResolvedCity } from "@/api/types";

import type { MapLocation } from "@/map/locations";
import { markerColors } from "@/map/locations";

type AMapNamespace = {
  Map: new (container: HTMLDivElement, options: object) => AMapMap;
  Marker: new (options: object) => AMapOverlay;
  Scale: new () => unknown;
  ToolBar: new () => unknown;
  InfoWindow: new (options: object) => AMapInfoWindow;
};
type AMapOverlay = { on: (event: string, callback: () => void) => void };
type AMapInfoWindow = { open: (map: AMapMap, position: [number, number]) => void; close: () => void };
type AMapMap = {
  add: (overlay: unknown | unknown[]) => void;
  addControl: (control: unknown) => void;
  clearMap: () => void;
  destroy: () => void;
  setFitView: (overlays: unknown[], immediately?: boolean, padding?: number[]) => void;
  setCenter: (center: [number, number]) => void;
  setZoomAndCenter: (zoom: number, center: [number, number]) => void;
};

declare global {
  interface Window {
    _AMapSecurityConfig?: { securityJsCode: string };
  }
}

export function AmapMap({
  locations,
  selectedLocationId,
  onSelectLocation,
  transportPlanStale = false,
  city = null,
}: {
  locations: MapLocation[];
  selectedLocationId: string | null;
  onSelectLocation: (locationId: string) => void;
  transportPlanStale?: boolean;
  city?: ResolvedCity | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<AMapMap | null>(null);
  const amapRef = useRef<AMapNamespace | null>(null);
  const previousLocationKeyRef = useRef<string | null>(null);
  const infoWindowRef = useRef<AMapInfoWindow | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);
  const jsApiKey = import.meta.env.VITE_AMAP_JS_API_KEY;
  const securityJsCode = import.meta.env.VITE_AMAP_SECURITY_JS_CODE;

  useEffect(() => {
    if (!containerRef.current) return;
    setIsReady(false);
    previousLocationKeyRef.current = null;
    if (!jsApiKey || !securityJsCode) {
      setLoadError("缺少高德 JS API 配置。");
      return;
    }
    let cancelled = false;
    window._AMapSecurityConfig = { securityJsCode };
    AMapLoader.load({ key: jsApiKey, version: "2.0", plugins: ["AMap.Scale", "AMap.ToolBar"] })
      .then((amap: AMapNamespace) => {
        if (cancelled || !containerRef.current) return;
        amapRef.current = amap;
        mapRef.current = new amap.Map(containerRef.current, { zoom: 5, center: [116.397428, 39.90923] });
        mapRef.current.addControl(new amap.Scale());
        mapRef.current.addControl(new amap.ToolBar());
        setIsReady(true);
      })
      .catch(() => {
        if (!cancelled) setLoadError("高德地图加载失败，请检查网络和域名白名单。");
      });
    return () => {
      cancelled = true;
      infoWindowRef.current?.close();
      infoWindowRef.current = null;
      mapRef.current?.destroy();
      mapRef.current = null;
      amapRef.current = null;
    };
  }, [jsApiKey, securityJsCode]);

  useEffect(() => {
    const map = mapRef.current;
    const amap = amapRef.current;
    if (!isReady || !map || !amap) return;
    const locationKey = `${city?.adcode ?? ""}|` + locations.map(({ id, location }) => `${id}:${location.coordinate.longitude},${location.coordinate.latitude}`).join("|");
    const locationsChanged = previousLocationKeyRef.current !== locationKey;
    map.clearMap();
    infoWindowRef.current?.close();
    infoWindowRef.current = null;
    if (!locations.length) {
      if (locationsChanged) map.setZoomAndCenter(city ? 11 : 5,
        city ? [city.center.longitude, city.center.latitude] : [116.397428, 39.90923]);
      previousLocationKeyRef.current = locationKey;
      return;
    }
    const markers = locations.map(({ id, location, role, roleLabel, selectionIds }) => {
      const isSelected = selectedLocationId !== null && selectionIds.includes(selectedLocationId);
      const label = document.createElement("span");
      label.textContent = `${roleLabel} · ${location.name}`;
      label.style.cssText = `background:${markerColors[role]};border:2px solid ${isSelected ? "#0f172a" : "white"};border-radius:8px;color:white;font-size:12px;padding:5px 8px;box-shadow:0 2px 6px #0002`;
      const marker = new amap.Marker({
        position: [location.coordinate.longitude, location.coordinate.latitude],
        title: `${roleLabel}：${location.name}`,
        label: { content: label.outerHTML, direction: "top" },
      });
      marker.on("click", () => onSelectLocation(id));
      return marker;
    });
    map.add(markers);
    if (locationsChanged) map.setFitView(markers, false, [64, 64, 64, 64]);
    previousLocationKeyRef.current = locationKey;
    const selected = locations.find((location) => selectedLocationId !== null && location.selectionIds.includes(selectedLocationId));
    if (selected) {
      const position: [number, number] = [selected.location.coordinate.longitude, selected.location.coordinate.latitude];
      const content = document.createElement("div");
      content.className = "amap-location-detail";
      content.textContent = `${selected.roleLabels.join("、")}｜${selected.location.name}${selected.location.address ? `｜${selected.location.address}` : ""}`;
      map.setCenter(position);
      infoWindowRef.current = new amap.InfoWindow({ content, offset: [0, -24] });
      infoWindowRef.current.open(map, position);
    }
  }, [isReady, locations, onSelectLocation, selectedLocationId, city]);

  const legendItems = [["#15803d", "出发地"], ["#2563eb", "目的地"], ["#7c3aed", "返程地"], ["#ea580c", "酒店"], ["#dc2626", "景点"], ["#0f766e", "车站 / 机场"]];
  return (
    <section className="relative h-full min-h-[28rem] overflow-hidden rounded-2xl border border-slate-200 bg-slate-100 lg:min-h-0" aria-label="旅行地图">
      <div className="h-full min-h-[28rem] w-full lg:min-h-0" ref={containerRef} />
      <div className="absolute left-4 top-4 rounded-xl border border-white/70 bg-white/95 px-3 py-2 shadow-sm">
        <p className="text-sm font-semibold text-slate-800">{city?.name ?? "旅行地图"}</p>
        <p className="mt-1 text-xs text-slate-500">{locations.length} 个地点 · 点击标记查看详情</p>
      </div>
      <div className="absolute inset-x-4 top-24 space-y-2">
        {!isReady && !loadError ? <p className="rounded-xl bg-white/95 p-3 text-sm text-slate-600" role="status">正在加载地图…</p> : null}
        {loadError ? <p className="rounded-xl bg-red-50 p-3 text-sm text-red-700 shadow-sm" role="alert">{loadError} 对话和地点清单仍可使用。</p> : null}
        {transportPlanStale ? <p className="rounded-xl bg-amber-50/95 p-3 text-sm text-amber-800 shadow-sm" role="status">交通方案已过期；地图仍保留旧站点供空间参考。</p> : null}
        {isReady && !locations.length ? <p className="rounded-xl bg-white/95 p-3 text-sm text-slate-600 shadow-sm">{city ? `已定位${city.name}。继续告诉我景点、酒店或车站，我会把具体地点标记在这里。` : "尚无已确认地点可显示在地图上。"}</p> : null}
      </div>
      <div className="absolute inset-x-4 bottom-7 flex flex-wrap gap-x-3 gap-y-2 rounded-xl bg-white/95 px-3 py-2 shadow-sm">
        {legendItems.map(([color, label]) => <span className="flex items-center gap-1 text-[11px] text-slate-600" key={label}><i className="size-2 rounded-full" style={{ backgroundColor: color }} />{label}</span>)}
      </div>
    </section>
  );
}
