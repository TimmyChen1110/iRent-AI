"use client";

import { useEffect, useRef, useState } from "react";
import type { Map as MapLibreMap, Marker as MapLibreMarker } from "maplibre-gl";
import { MAPLIBRE_WORKER_URL, TAIPEI_DARK_STYLE } from "@/config/map";
export interface LatLng { lat: number; lng: number }

/** 地圖需要的最小車輛資料（DevVehicle 與車隊頁的轉換結果都符合）。座標＝後端 demo_vehicles.lat/lng。 */
export interface MapVehicle {
  vehicle_id: string; plate: string; location: LatLng
  status: "AVAILABLE" | "RENTED" | "MAINTENANCE" | "PARKED"; is_demo: boolean
}

/** 臺大二活一帶（既有模擬車輛所在位置）。 */
const DEFAULT_CENTER: [number, number] = [121.5397, 25.0174];

const STATUS_COLOR: Record<MapVehicle["status"], string> = { AVAILABLE: "#34d399", RENTED: "#818cf8", MAINTENANCE: "#fb923c", PARKED: "#71717a" };

async function loadMapLibre() {
  const lib = await import("maplibre-gl");
  lib.setWorkerUrl(MAPLIBRE_WORKER_URL);
  return lib;
}

function markerEl(label: string, color: string, opts: { demo: boolean; selected: boolean; draft?: boolean }) {
  const el = document.createElement("div");
  el.style.cssText = "display:flex;flex-direction:column;align-items:center;cursor:pointer;";
  const chip = document.createElement("div");
  chip.textContent = label;
  chip.style.cssText = [
    "font:600 11px ui-monospace,monospace;padding:3px 7px;border-radius:8px;white-space:nowrap;",
    `background:${opts.draft ? "#fbbf24" : "rgba(15,18,26,.92)"};color:${opts.draft ? "#111" : "#fff"};`,
    `border:1.5px solid ${opts.selected ? "#fff" : color};`,
    opts.selected ? "box-shadow:0 0 0 3px rgba(255,255,255,.25);" : "",
  ].join("");
  if (opts.demo && !opts.draft) {
    const tag = document.createElement("span");
    tag.textContent = " DEMO";
    tag.style.cssText = "color:#fbbf24;font-size:9px;";
    chip.appendChild(tag);
  }
  const pin = document.createElement("div");
  pin.style.cssText = `width:10px;height:10px;border-radius:50%;margin-top:3px;background:${opts.draft ? "#fbbf24" : color};border:2px solid #fff;`;
  el.append(chip, pin);
  return el;
}

/**
 * 車輛地圖：標記位置＝後端 demo_vehicles 的 lat/lng（App 地圖同一組座標）。
 * 編輯模式（Demo 測試車輛頁）：點地圖放置「新車輛」草稿標記；草稿與選取中的車輛標記可拖曳。
 * readOnly（車輛管理頁）：只能點選車輛，不能放置或拖曳。
 */
export function DemoVehicleMap({ vehicles, selectedId, draft = null, focus = null, readOnly = false, onMapClick, onSelect, onDraftMove, onVehicleMove }: {
  vehicles: MapVehicle[];
  selectedId: string | null;
  draft?: LatLng | null;
  /** 變動時鏡頭飛到該位置 */
  focus?: (LatLng & { token: number }) | null;
  readOnly?: boolean;
  onMapClick?: (p: LatLng) => void;
  onSelect: (id: string) => void;
  onDraftMove?: (p: LatLng) => void;
  onVehicleMove?: (id: string, p: LatLng) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const libRef = useRef<typeof import("maplibre-gl") | null>(null);
  const markersRef = useRef<Record<string, MapLibreMarker>>({});
  const draftRef = useRef<MapLibreMarker | null>(null);
  const cb = useRef({ onMapClick, onSelect, onDraftMove, onVehicleMove, readOnly });
  useEffect(() => { cb.current = { onMapClick, onSelect, onDraftMove, onVehicleMove, readOnly }; });
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const lib = await loadMapLibre();
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (cancelled || !containerRef.current) return;
        libRef.current = lib;
        const m = new lib.Map({
          container: containerRef.current,
          style: structuredClone(TAIPEI_DARK_STYLE),
          center: DEFAULT_CENTER, zoom: 15.2, pitch: 0, bearing: 0,
          attributionControl: { compact: true },
        });
        mapRef.current = m;
        m.on("error", (e) => {
          const msg = String((e as { error?: { message?: string } }).error?.message ?? "");
          if (/webgl|style/i.test(msg)) setFailed(true);
        });
        m.on("click", (e) => { if (!cb.current.readOnly) cb.current.onMapClick?.({ lat: +e.lngLat.lat.toFixed(6), lng: +e.lngLat.lng.toFixed(6) }); });
        m.on("load", () => { if (!cancelled) { m.resize(); setReady(true); } });
      } catch {
        setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      Object.values(markersRef.current).forEach((mk) => mk.remove());
      markersRef.current = {};
      draftRef.current?.remove();
      draftRef.current = null;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  /* 車輛標記：每次依資料重建（車輛數少，簡單可靠；拖曳中的標記不會因輪詢被重建，因為本頁不輪詢） */
  useEffect(() => {
    const m = mapRef.current, lib = libRef.current;
    if (!ready || !m || !lib) return;
    Object.values(markersRef.current).forEach((mk) => mk.remove());
    markersRef.current = {};
    for (const v of vehicles) {
      if (v.status === "PARKED") continue;      // 停放中的固定劇本車：車牌已讓出，不在地圖上
      const selected = v.vehicle_id === selectedId;
      const el = markerEl(v.plate, STATUS_COLOR[v.status], { demo: v.is_demo, selected });
      el.dataset.testid = `marker-${v.plate}`;
      el.addEventListener("click", (ev) => { ev.stopPropagation(); cb.current.onSelect(v.vehicle_id); });
      const mk = new lib.Marker({ element: el, anchor: "bottom", draggable: !readOnly && selected && v.status !== "RENTED" })
        .setLngLat([v.location.lng, v.location.lat]).addTo(m);
      mk.on("dragend", () => {
        const p = mk.getLngLat();
        cb.current.onVehicleMove?.(v.vehicle_id, { lat: +p.lat.toFixed(6), lng: +p.lng.toFixed(6) });
      });
      markersRef.current[v.vehicle_id] = mk;
    }
  }, [ready, vehicles, selectedId, readOnly]);

  /* 新車輛草稿標記（可拖曳） */
  useEffect(() => {
    const m = mapRef.current, lib = libRef.current;
    if (!ready || !m || !lib) return;
    if (!draft) { draftRef.current?.remove(); draftRef.current = null; return; }
    if (!draftRef.current) {
      const el = markerEl("新車輛位置", "#fbbf24", { demo: true, selected: true, draft: true });
      el.dataset.testid = "marker-draft";
      el.addEventListener("click", (ev) => ev.stopPropagation());
      const mk = new lib.Marker({ element: el, anchor: "bottom", draggable: true }).setLngLat([draft.lng, draft.lat]).addTo(m);
      mk.on("dragend", () => { const p = mk.getLngLat(); cb.current.onDraftMove?.({ lat: +p.lat.toFixed(6), lng: +p.lng.toFixed(6) }); });
      draftRef.current = mk;
    } else {
      draftRef.current.setLngLat([draft.lng, draft.lat]);
    }
  }, [ready, draft]);

  /* 第一次拿到車輛時把鏡頭框住所有車輛（預設中心不一定涵蓋全部車輛） */
  const fittedRef = useRef(false);
  useEffect(() => {
    const m = mapRef.current, lib = libRef.current;
    if (!ready || !m || !lib || fittedRef.current || focus) return;
    const pts = vehicles.filter((v) => v.status !== "PARKED").map((v) => [v.location.lng, v.location.lat] as [number, number]);
    if (!pts.length) return;
    fittedRef.current = true;
    const b = new lib.LngLatBounds(pts[0], pts[0]);
    pts.forEach((p) => b.extend(p));
    m.fitBounds(b, { padding: 90, maxZoom: 16, duration: 0 });
  }, [ready, vehicles, focus]);

  useEffect(() => {
    if (ready && focus && mapRef.current) mapRef.current.flyTo({ center: [focus.lng, focus.lat], zoom: Math.max(mapRef.current.getZoom(), 16), duration: 700 });
  }, [ready, focus]);

  return (
    <div className="relative h-full w-full overflow-hidden rounded-2xl">
      {/* MapLibre CSS 會把容器 position 改成 relative：容器放在內層、外層負責絕對定位 */}
      <div className="absolute inset-0" data-testid="demo-map"><div ref={containerRef} className="h-full w-full" /></div>
      {!ready && !failed && <div className="absolute inset-0 grid place-items-center text-[13px] text-muted">載入地圖…</div>}
      {failed && (
        <div className="absolute inset-0 grid place-items-center p-6 text-center text-[13px] text-white/70">
          地圖無法載入（瀏覽器不支援 WebGL 或無法連線圖資）。仍可在右側直接輸入經緯度。
        </div>
      )}
    </div>
  );
}
