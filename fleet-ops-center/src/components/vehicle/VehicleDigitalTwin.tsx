"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { RotateCcw, Pause, Play, Crosshair, MousePointer2, Car, Armchair } from "lucide-react";
import type { DamageHotspot, HotspotLocation, TwinMode, Vehicle } from "@/types";
import { LOCATION_LABELS } from "@/data/vehicleGeometry";
import { cn, pct, cleanlinessLabel } from "@/lib/utils";
import { StatusPill } from "@/components/ui/Badge";
import { DigitalTwinAnnotation } from "./DigitalTwinAnnotation";

const VehicleScene = dynamic(() => import("./VehicleScene"), {
  ssr: false,
  loading: () => <SceneSkeleton />,
});

export interface VehicleDigitalTwinProps {
  vehicle: Vehicle;
  hotspots?: DamageHotspot[];
  selectedHotspotId: string | null;
  onSelectHotspot: (id: string | null) => void;
  mode: TwinMode;
  onModeChange: (mode: TwinMode) => void;
  onViewEvidence?: (hotspot: DamageHotspot) => void;
  className?: string;
  compact?: boolean;
}

export function VehicleDigitalTwin({
  vehicle,
  hotspots,
  selectedHotspotId,
  onSelectHotspot,
  mode,
  onModeChange,
  onViewEvidence,
  className,
  compact,
}: VehicleDigitalTwinProps) {
  const list = hotspots ?? vehicle.hotspots;
  const selected = list.find((h) => h.id === selectedHotspotId) ?? null;
  const [autoRotate, setAutoRotate] = useState(true);
  const [resetToken, setResetToken] = useState(0);
  const [picked, setPicked] = useState<HotspotLocation | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!selectedHotspotId && tooltipRef.current) tooltipRef.current.style.opacity = "0";
  }, [selectedHotspotId]);

  useEffect(() => {
    if (!picked) return;
    const t = setTimeout(() => setPicked(null), 2600);
    return () => clearTimeout(t);
  }, [picked]);

  const reset = useCallback(() => {
    onSelectHotspot(null);
    setResetToken((n) => n + 1);
  }, [onSelectHotspot]);

  const pickedHotspot = picked ? list.find((h) => h.location === picked) : null;
  const interiorCount = list.filter((h) => h.mode === "interior").length;
  const exteriorCount = list.filter((h) => h.mode === "exterior").length;

  return (
    <div className={cn("always-dark relative overflow-hidden rounded-2xl glass", compact ? "h-[400px]" : "h-full min-h-[560px]", className)}>
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_50%_at_50%_45%,rgba(110,168,255,0.10),transparent_70%)]" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-[#07090d]/70 to-transparent" />

      <div className="absolute inset-0">
        <VehicleScene
          hotspots={list}
          selectedHotspotId={selectedHotspotId}
          onSelectHotspot={onSelectHotspot}
          onPickRegion={(loc) => {
            const hit = list.find((h) => h.location === loc);
            if (hit) onSelectHotspot(hit.id);
            else setPicked(loc);
          }}
          autoRotate={autoRotate}
          resetToken={resetToken}
          mode={mode}
          tooltipRef={tooltipRef}
        />
        <div
          ref={tooltipRef}
          className="pointer-events-none absolute left-0 top-0 z-10 whitespace-nowrap rounded-lg border border-white/10 bg-black/75 px-2.5 py-1.5 text-[11px] font-medium text-white shadow-xl backdrop-blur before:mr-1.5 before:inline-block before:h-1.5 before:w-1.5 before:rounded-full before:bg-rose-400 before:content-[''] data-[kind=cleaning]:before:bg-amber-400"
          style={{ opacity: 0, transition: "opacity 150ms" }}
        />
      </div>

      {/* top-left: identity */}
      <div className="pointer-events-none absolute left-4 top-4 flex items-center gap-3">
        <div className="glass-strong pointer-events-auto rounded-xl px-3.5 py-2.5">
          <div className="label-xs">數位分身</div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className="text-[15px] font-semibold text-white/95">{vehicle.model}</span>
            <span className="font-mono text-[12px] text-white/55">{vehicle.plate}</span>
          </div>
        </div>
        <StatusPill status={vehicle.status} pulse={vehicle.status === "damage"} className="pointer-events-auto" />
      </div>

      {/* top-right: mode + controls */}
      <div className="absolute right-4 top-4 flex items-center gap-2">
        <div className="glass-strong flex rounded-lg p-0.5">
          <ModeTab active={mode === "exterior"} onClick={() => onModeChange("exterior")} icon={<Car className="h-3.5 w-3.5" />} label="車外" count={exteriorCount} tone="rose" />
          <ModeTab active={mode === "interior"} onClick={() => onModeChange("interior")} icon={<Armchair className="h-3.5 w-3.5" />} label="車內" count={interiorCount} tone="amber" />
        </div>
        <IconButton title={autoRotate ? "暫停旋轉" : "恢復旋轉"} onClick={() => setAutoRotate((a) => !a)}>
          {autoRotate ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
        </IconButton>
        <IconButton title="重設視角" onClick={reset}>
          <RotateCcw className="h-3.5 w-3.5" />
        </IconButton>
      </div>

      {/* right: hotspot legend for the current mode */}
      {list.some((h) => h.mode === mode) && (
        <div className="absolute right-4 top-16 flex flex-col items-end gap-1.5">
          {list
            .filter((h) => h.mode === mode)
            .map((h) => (
              <button
                key={h.id}
                onClick={() => onSelectHotspot(h.id === selectedHotspotId ? null : h.id)}
                className={cn(
                  "glass-strong flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11.5px] transition",
                  h.id === selectedHotspotId ? "text-white ring-1 ring-white/20" : "text-white/65 hover:text-white",
                )}
              >
                <span className={cn("h-1.5 w-1.5 rounded-full", h.kind === "damage" ? "bg-rose-400" : "bg-amber-400", h.id === selectedHotspotId && "soft-pulse")} />
                {h.label}
                <span className="tabular text-white/45">{pct(h.confidence)}</span>
              </button>
            ))}
        </div>
      )}

      {/* interior mode header */}
      <AnimatePresence>
        {mode === "interior" && !selected && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className="glass-strong absolute bottom-4 left-4 w-[296px] rounded-2xl p-4"
          >
            <div className="label-xs">車內狀況</div>
            <div className={cn("mt-1 text-[15px] font-semibold", vehicle.interior.flagged ? "text-amber-100" : "text-emerald-200")}>
              {vehicle.interior.flagged ? "需要清潔" : "車內乾淨"}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div>
                <div className="label-xs">整潔程度</div>
                <div className={cn("mt-0.5 text-lg font-semibold tracking-wide", vehicle.interior.flagged ? "text-amber-200" : "text-emerald-200")}>{cleanlinessLabel[vehicle.interior.cleanliness]}</div>
              </div>
              <div>
                <div className="label-xs">AI 信心度</div>
                <div className="tabular mt-0.5 text-lg font-semibold text-white">{pct(vehicle.interior.confidence)}</div>
              </div>
            </div>
            {vehicle.interior.detected.length > 0 && (
              <p className="mt-2 text-[12px] text-muted">點擊車內標記可檢視各項偵測結果。</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* selected hotspot annotation */}
      <AnimatePresence mode="wait">
        {selected && <DigitalTwinAnnotation key={selected.id} hotspot={selected} vehicle={vehicle} onClose={() => onSelectHotspot(null)} onViewEvidence={onViewEvidence} />}
      </AnimatePresence>

      {/* region pick feedback when no anomaly */}
      <AnimatePresence>
        {!selected && picked && !pickedHotspot && mode === "exterior" && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className="glass-strong absolute bottom-4 left-4 flex items-center gap-2.5 rounded-xl px-3.5 py-2.5 text-[12px]"
          >
            <Crosshair className="h-3.5 w-3.5 text-emerald-300" />
            <span className="text-white/85">{LOCATION_LABELS[picked]}</span>
            <span className="text-emerald-300">無異常</span>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="pointer-events-none absolute bottom-4 right-4 flex items-center gap-1.5 text-[11px] text-white/35">
        <MousePointer2 className="h-3 w-3" />
        拖曳旋轉 · 滾輪縮放 · 點擊標記
      </div>
    </div>
  );
}

function ModeTab({ active, onClick, icon, label, count, tone }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string; count: number; tone: "rose" | "amber" }) {
  return (
    <button
      onClick={onClick}
      className={cn("flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[11.5px] font-medium transition", active ? "bg-white/[0.12] text-white" : "text-white/55 hover:text-white")}
    >
      {icon}
      {label}
      {count > 0 && <span className={cn("rounded-full px-1.5 text-[10px] font-semibold", tone === "rose" ? "bg-rose-400/20 text-rose-200" : "bg-amber-400/20 text-amber-200")}>{count}</span>}
    </button>
  );
}

function IconButton({ children, title, onClick }: { children: React.ReactNode; title: string; onClick: () => void }) {
  return (
    <button title={title} onClick={onClick} className="glass-strong grid h-8 w-8 place-items-center rounded-lg text-white/70 transition hover:text-white">
      {children}
    </button>
  );
}

function SceneSkeleton() {
  return (
    <div className="flex h-full w-full items-center justify-center">
      <div className="flex flex-col items-center gap-3 text-white/40">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/10 border-t-white/60" />
        <span className="text-xs">載入數位分身中</span>
      </div>
    </div>
  );
}
