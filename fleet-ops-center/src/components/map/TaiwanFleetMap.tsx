"use client";

import dynamic from "next/dynamic";
import { useRef, useState } from "react";
import { RotateCcw, MousePointer2 } from "lucide-react";
import type { CityNode } from "@/data/fleetMapData";
import { cn, formatNumber } from "@/lib/utils";

const TaiwanScene = dynamic(() => import("./TaiwanScene"), { ssr: false, loading: () => <div className="flex h-full items-center justify-center text-xs text-white/40">載入台灣車隊網絡</div> });

export function TaiwanFleetMap({ cities, focusCity, onSelectCity, className }: { cities: CityNode[]; focusCity: CityNode["id"] | null; onSelectCity: (id: CityNode["id"]) => void; className?: string }) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [resetToken, setResetToken] = useState(0);
  const labelRefs = useRef<Record<string, HTMLDivElement | null>>({});

  return (
    <div className={cn("always-dark relative h-full w-full overflow-hidden rounded-2xl glass", className)}>
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(55%_45%_at_50%_50%,rgba(110,168,255,0.08),transparent_70%)]" />
      <div className="absolute inset-0">
        <TaiwanScene cities={cities} hovered={hovered} onHover={setHovered} onSelect={onSelectCity} focusCity={focusCity} resetToken={resetToken} labelRefs={labelRefs} />
      </div>

      {/* projected city labels */}
      {cities.map((c) => {
        const alerts = c.damage + c.cleaning;
        const tone = c.workload >= 0.8 ? "text-rose-300" : c.workload >= 0.45 ? "text-amber-300" : "text-sky-300";
        return (
          <div
            key={c.id}
            ref={(el) => { labelRefs.current[c.id] = el; }}
            onClick={() => onSelectCity(c.id)}
            className={cn("glass-strong absolute left-0 top-0 cursor-pointer select-none rounded-xl px-2.5 py-1.5 transition-opacity duration-200", hovered && hovered !== c.id ? "opacity-50" : "opacity-100", !c.enabled && "cursor-default")}
            style={{ transform: "translate(-9999px,-9999px)" }}
          >
            <div className="flex items-center gap-2">
              <span className="text-[11.5px] font-semibold tracking-wide text-white/95">{c.name}</span>
              <span className={cn("text-[10px] font-medium", tone)}>{c.statusLabel}</span>
            </div>
            <div className="mt-0.5 text-[10px] text-white/55">
              <span className="tabular text-white/80">{formatNumber(c.vehicles)}</span> 台 · <span className="tabular text-white/80">{alerts}</span> 項異常
            </div>
          </div>
        );
      })}

      <div className="pointer-events-none absolute left-4 top-4">
        <div className="glass-strong pointer-events-auto rounded-xl px-3.5 py-2.5">
          <div className="label-xs">National View</div>
          <div className="mt-0.5 text-[15px] font-semibold text-white/95">台灣車隊網絡</div>
          <div className="text-[11px] text-muted">全國車隊即時營運狀態</div>
        </div>
      </div>
      <div className="absolute right-4 top-4">
        <button title="重設視角" onClick={() => setResetToken((n) => n + 1)} className="glass-strong grid h-8 w-8 place-items-center rounded-lg text-white/70 hover:text-white">
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="pointer-events-none absolute bottom-4 left-4 flex items-center gap-3 text-[11px] text-white/45">
        <span className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-rose-400" />高負載</span>
        <span className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-amber-400" />中等</span>
        <span className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-sky-400" />正常</span>
      </div>
      <div className="pointer-events-none absolute bottom-4 right-4 flex items-center gap-1.5 text-[11px] text-white/35">
        <MousePointer2 className="h-3 w-3" />
        拖曳旋轉 · 滾輪縮放 · 點擊城市進入
      </div>
    </div>
  );
}
