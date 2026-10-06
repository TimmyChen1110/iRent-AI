"use client";

import { AlertTriangle } from "lucide-react";
import type { MapVehiclePoint } from "./useFleetMap";
import { MARKER_COLORS } from "@/data/fleetMapData";
import { cn } from "@/lib/utils";

const BOUNDS = { west: 121.52, east: 121.58, south: 25.015, north: 25.07 };

/** Stylized fallback when WebGL / tiles are unavailable: same markers on a dark grid. */
export function TaipeiFallback({ points, selectedId, onSelect, dimmed }: { points: MapVehiclePoint[]; selectedId: string | null; onSelect: (id: string) => void; dimmed: (p: MapVehiclePoint) => boolean }) {
  return (
    <div className="relative h-full w-full bg-[#0b0e14] [background-image:linear-gradient(rgba(255,255,255,0.04)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.04)_1px,transparent_1px)] [background-size:48px_48px]">
      {points.map((p) => {
        const x = ((p.lngLat[0] - BOUNDS.west) / (BOUNDS.east - BOUNDS.west)) * 100;
        const y = ((BOUNDS.north - p.lngLat[1]) / (BOUNDS.north - BOUNDS.south)) * 100;
        return (
          <button
            key={p.id}
            onClick={() => onSelect(p.id)}
            className={cn("absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-black/60 transition", dimmed(p) && "opacity-25", selectedId === p.id && "scale-150")}
            style={{ left: `${x}%`, top: `${y}%`, background: MARKER_COLORS[p.status] }}
            title={p.plate}
          />
        );
      })}
      <div className="glass-strong absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-xl px-3.5 py-2 text-[12px] text-white/80">
        <AlertTriangle className="h-3.5 w-3.5 text-amber-300" />
        3D 地圖暫時無法使用，已切換為簡化車隊視圖
      </div>
    </div>
  );
}
