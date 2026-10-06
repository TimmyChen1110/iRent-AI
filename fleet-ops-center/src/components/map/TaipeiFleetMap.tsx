"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { RotateCcw, MousePointer2 } from "lucide-react";
import type { Map as MapLibreMap, Marker as MapLibreMarker, GeoJSONSource } from "maplibre-gl";
import { CLUSTER_ZOOM, DISTRICT_CHIP_ZOOM, MAPLIBRE_WORKER_URL, TAIPEI_CAMERA, TAIPEI_DARK_STYLE, VEHICLE_FOCUS_ZOOM } from "@/config/map";
import { MARKER_COLORS, WORKLOAD_WEIGHT } from "@/data/fleetMapData";
import type { DistrictSummary, MapVehiclePoint } from "./useFleetMap";
import type { Vehicle } from "@/types";
import { FleetMapFilters, matchesFilter, type MapFilter, type MapMode } from "./FleetMapFilters";
import { VehicleMapPopup } from "./VehicleMapPopup";
import { TaipeiFallback } from "./TaipeiFallback";
import { cn } from "@/lib/utils";

export interface TaipeiFleetMapProps {
  points: MapVehiclePoint[];
  districts: DistrictSummary[];
  vehicleById: Record<string, Vehicle>;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** Increment to fly to the selected vehicle again. */
  flyToken: number;
  onOpenTwin: (vehicleId: string) => void;
  /** Hand-off phase: popup fades out and the selected marker's halo intensifies. */
  focusing?: boolean;
  /** Increment when returning from the vehicle twin: the map eases back to the city view. */
  returnToken?: number;
  /** Demo 主角車牌：常駐顯示、標籤與加強脈衝。 */
  heroId?: string | null;
  className?: string;
}

const ALERT = new Set(["damage", "cleaning", "pending-review", "maintenance", "unavailable"]);
/** Statuses that stay highlighted in "incidents" mode (alerts + recovery lifecycle). */
const OPS = new Set([...ALERT, "ready"]);

/**
 * Loads MapLibre and points it at a static worker served from /public.
 * The bundled worker URL breaks under Turbopack, so the worker file is copied to public/maplibre/.
 */
async function loadMapLibre() {
  const lib = await import("maplibre-gl");
  lib.setWorkerUrl(MAPLIBRE_WORKER_URL);
  return lib;
}

/**
 * Taipei 3D city map (MapLibre + OpenFreeMap tiles, no token). Markers are DOM
 * elements diffed by id; cluster chips appear below CLUSTER_ZOOM; workload mode adds a heatmap.
 */
export function TaipeiFleetMap({ points, districts, vehicleById, selectedId, onSelect, flyToken, onOpenTwin, focusing, returnToken = 0, heroId = null, className }: TaipeiFleetMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markersRef = useRef<Record<string, { marker: MapLibreMarker; el: HTMLDivElement; status: string }>>({});
  const clusterRef = useRef<Record<string, MapLibreMarker>>({});
  const popupRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const [fallback, setFallback] = useState(false);
  const [zoomedIn, setZoomedIn] = useState(TAIPEI_CAMERA.zoom >= CLUSTER_ZOOM);
  const [streetLevel, setStreetLevel] = useState(TAIPEI_CAMERA.zoom >= DISTRICT_CHIP_ZOOM);
  const [filter, setFilter] = useState<MapFilter>("all");
  const [mode, setMode] = useState<MapMode>("incidents");

  const selected = useMemo(() => points.find((p) => p.id === selectedId) ?? null, [points, selectedId]);
  const selectedRef = useRef<MapVehiclePoint | null>(null);
  const positionPopup = () => {
    const map = mapRef.current;
    const el = popupRef.current;
    const sel = selectedRef.current;
    if (!map || !el || !sel) return;
    const p = map.project(sel.lngLat);
    el.style.transform = `translate(-50%, -100%) translate(${p.x.toFixed(1)}px, ${(p.y - 22).toFixed(1)}px)`;
  };
  const isDimmed = useCallback(
    (p: MapVehiclePoint) => {
      if (selectedId && p.id !== selectedId) return true;
      if (!matchesFilter(p.status, filter)) return true;
      if (mode === "incidents" && !OPS.has(p.status)) return true;
      return false;
    },
    [selectedId, filter, mode],
  );

  /* ---------- init ---------- */
  useEffect(() => {
    let cancelled = false;
    let map: MapLibreMap | null = null;
    let ro: ResizeObserver | null = null;
    (async () => {
      try {
        const maplibregl = await loadMapLibre();
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (cancelled || !containerRef.current) return;
        const cam = TAIPEI_CAMERA;
        const m = new maplibregl.Map({
          container: containerRef.current,
          // Fresh copy per instance: MapLibre mutates the style object it is given (e.g. addSource/addLayer).
          style: structuredClone(TAIPEI_DARK_STYLE),
          center: cam.center,
          zoom: cam.zoom,
          pitch: cam.pitch,
          bearing: cam.bearing,
          attributionControl: { compact: true },
          maxPitch: 70,
        });
        map = m;
        mapRef.current = m;
        m.on("error", (e) => {
          // Tile fetch failures degrade gracefully; a style/WebGL failure switches to fallback.
          const msg = String((e as { error?: { message?: string } }).error?.message ?? "");
          if (/webgl|style/i.test(msg)) setFallback(true);
        });
        m.on("load", () => {
          if (cancelled) return;
          m.addSource("workload", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
          m.addLayer({
            id: "workload-heat",
            type: "heatmap",
            source: "workload",
            layout: { visibility: "none" },
            paint: {
              "heatmap-weight": ["get", "w"],
              "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 12, 1.4, 16, 3.2],
              "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 12, 40, 14.6, 110, 16, 180],
              "heatmap-opacity": 0.8,
              "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"], 0, "rgba(110,168,255,0)", 0.25, "rgba(110,168,255,0.35)", 0.5, "rgba(251,191,36,0.55)", 0.8, "rgba(251,113,133,0.8)", 1, "rgba(255,80,110,0.95)"],
            },
          });
          setReady(true);
        });
        m.on("zoom", () => {
          const z = m.getZoom();
          setZoomedIn(z >= CLUSTER_ZOOM);
          setStreetLevel(z >= DISTRICT_CHIP_ZOOM);
        });
        m.on("move", () => positionPopup());
        // The container is mounted inside an animated layer; keep the canvas in sync with its real size.
        ro = new ResizeObserver(() => { m.resize(); positionPopup(); });
        ro.observe(containerRef.current);
        m.once("load", () => m.resize());
      } catch {
        setFallback(true);
      }
    })();
    return () => {
      cancelled = true;
      Object.values(markersRef.current).forEach((m) => m.marker.remove());
      Object.values(clusterRef.current).forEach((m) => m.remove());
      markersRef.current = {};
      clusterRef.current = {};
      ro?.disconnect();
      map?.remove();
      mapRef.current = null;
    };
  }, []);

  /* ---------- popup positioning (reads refs only, so it is stable for the map "move" handler) ---------- */
  useEffect(() => {
    selectedRef.current = selected;
    positionPopup();
  }, [selected, ready]);

  /* ---------- vehicle markers (diff by id) ---------- */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (async () => {
      const maplibregl = await loadMapLibre();
      const seen = new Set<string>();
      for (const p of points) {
        seen.add(p.id);
        let entry = markersRef.current[p.id];
        if (!entry) {
          const el = document.createElement("div");
          el.className = "fleet-marker";
          el.addEventListener("click", (e) => { e.stopPropagation(); onSelect(p.id); });
          const marker = new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat(p.lngLat).addTo(map);
          entry = { marker, el, status: "" };
          markersRef.current[p.id] = entry;
        }
        const hero = p.vehicleId === heroId;
        const alert = ALERT.has(p.status);
        entry.el.style.setProperty("--c", MARKER_COLORS[p.status]);
        entry.el.dataset.status = p.status;
        entry.el.dataset.hero = hero ? "1" : "0";
        entry.el.dataset.alert = alert ? "1" : "0";
        entry.el.dataset.selected = p.id === selectedId ? "1" : "0";
        entry.el.dataset.focus = focusing && p.id === selectedId ? "1" : "0";
        entry.el.dataset.quiet = !selectedId && !hero && filter === "all" && mode !== "incidents" ? "1" : "0";
        entry.el.dataset.dim = isDimmed(p) ? "1" : "0";
        entry.el.dataset.visible = zoomedIn || hero || (OPS.has(p.status) && mode !== "vehicles") ? "1" : "0";
        if (hero) entry.el.innerHTML = `<span class="fleet-marker-label">${p.plate}${alert ? " · AI 警示" : ""}</span>`;
        entry.status = p.status;
      }
      for (const id of Object.keys(markersRef.current)) {
        if (!seen.has(id)) { markersRef.current[id].marker.remove(); delete markersRef.current[id]; }
      }
    })();
  }, [points, ready, selectedId, isDimmed, zoomedIn, mode, filter, focusing, onSelect, heroId]);

  /* ---------- district clusters ---------- */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (async () => {
      const maplibregl = await loadMapLibre();
      const want = new Set(districts.map((d) => d.id));
      for (const id of Object.keys(clusterRef.current)) if (!want.has(id)) { clusterRef.current[id].remove(); delete clusterRef.current[id]; }
      for (const d of districts) {
        let m = clusterRef.current[d.id];
        if (!m) {
          const el = document.createElement("div");
          el.className = "fleet-cluster";
          el.addEventListener("click", (e) => { e.stopPropagation(); map.flyTo({ center: d.lngLat, zoom: 15.2, duration: 900 }); });
          clusterRef.current[d.id] = m;
          m = new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat(d.lngLat).addTo(map);
          clusterRef.current[d.id] = m;
        }
        m.setLngLat(d.lngLat);
        const el = m.getElement();
        el.dataset.visible = streetLevel ? "0" : "1";
        el.dataset.hot = d.alerts >= 4 ? "1" : "0";
        el.innerHTML = `<div class="fleet-cluster-name">${d.name}</div><div class="fleet-cluster-meta"><b>${d.vehicles}</b> 台 · <span>${d.alerts} 項異常</span></div>`;
      }
    })();
  }, [districts, ready, streetLevel]);

  /* ---------- workload heatmap ---------- */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const src = map.getSource("workload") as GeoJSONSource | undefined;
    src?.setData({ type: "FeatureCollection", features: points.map((p) => ({ type: "Feature", properties: { w: WORKLOAD_WEIGHT[p.status] }, geometry: { type: "Point", coordinates: p.lngLat } })) });
    if (map.getLayer("workload-heat")) map.setLayoutProperty("workload-heat", "visibility", mode === "workload" ? "visible" : "none");
  }, [points, ready, mode]);

  /* ---------- fly to selected ---------- */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !selected) return;
    map.flyTo({ center: selected.lngLat, zoom: VEHICLE_FOCUS_ZOOM, pitch: 64, bearing: -18, duration: 1000, essential: true });
  }, [flyToken, ready, selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  /* Returning from the vehicle twin: ease back to the city composition (~900 ms). */
  useEffect(() => {
    if (!returnToken || !mapRef.current || !ready) return;
    mapRef.current.flyTo({ ...TAIPEI_CAMERA, duration: 900, essential: true });
  }, [returnToken, ready]);

  const resetCamera = () => {
    onSelect(null);
    mapRef.current?.flyTo({ ...TAIPEI_CAMERA, duration: 900 });
  };

  return (
    <div className={cn("always-dark relative h-full w-full overflow-hidden rounded-2xl glass", className)}>
      {fallback ? (
        <TaipeiFallback points={points} selectedId={selectedId} onSelect={onSelect} dimmed={isDimmed} />
      ) : (
        <div className="absolute inset-0 [&_.maplibregl-ctrl-attrib]:!bg-black/40 [&_.maplibregl-ctrl-attrib]:!text-[9px] [&_.maplibregl-ctrl-attrib_a]:!text-white/40" onClick={() => onSelect(null)}>
          {/* MapLibre CSS forces position:relative on its container, so sizing lives on this inner div. */}
          <div ref={containerRef} className="h-full w-full" />
        </div>
      )}
      {!ready && !fallback && <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-white/40">載入台北 3D 城市地圖</div>}

      {/* popup */}
      <div ref={popupRef} className="pointer-events-none absolute left-0 top-0 z-20" style={{ transform: "translate(-9999px,-9999px)" }}>
        <AnimatePresence>
          {selected && !focusing && (
            <div className="pointer-events-auto">
              <VehicleMapPopup point={selected} vehicle={selected.vehicleId ? vehicleById[selected.vehicleId] : undefined} onClose={() => onSelect(null)} onOpenTwin={onOpenTwin} />
            </div>
          )}
        </AnimatePresence>
      </div>

      <div className="pointer-events-none absolute left-4 top-4">
        <div className="glass-strong pointer-events-auto rounded-xl px-3.5 py-2.5">
          <div className="label-xs">City View</div>
          <div className="mt-0.5 text-[15px] font-semibold text-white/95">台北車隊營運</div>
          <div className="text-[11px] text-muted">{districts.map((d) => d.name).join(" · ") || "台北"}</div>
        </div>
      </div>
      <div className="absolute right-4 top-4 flex items-center gap-2">
        <FleetMapFilters filter={filter} mode={mode} onFilter={setFilter} onMode={setMode} />
        <button title="重設視角" onClick={resetCamera} className="glass-strong grid h-8 w-8 place-items-center rounded-lg text-white/70 hover:text-white">
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="pointer-events-none absolute bottom-4 right-4 flex items-center gap-1.5 text-[11px] text-white/35">
        <MousePointer2 className="h-3 w-3" />
        {zoomedIn ? "點擊車輛標記查看狀態" : "點擊行政區放大檢視車輛"}
      </div>
    </div>
  );
}

export default TaipeiFleetMap;
