"use client";

import { useCallback, useRef, useState } from "react";
import { motion } from "framer-motion";
import type { DamageHotspot, TwinMode, Vehicle } from "@/types";
import { useOps } from "@/store/OpsStore";
import { VehicleDigitalTwin } from "@/components/vehicle/VehicleDigitalTwin";
import { VehicleStatusPanel } from "@/components/vehicle/VehicleStatusPanel";
import { InspectionPanel } from "@/components/vehicle/InspectionPanel";
import { VehicleTimeline } from "@/components/vehicle/VehicleTimeline";
import { BeforeAfterComparison } from "@/components/evidence/BeforeAfterComparison";
import { AIRecommendationPanel } from "@/components/incident/AIRecommendationPanel";
import { fadeUp, stagger } from "@/components/ui/motion";
import { cn } from "@/lib/utils";

/** 數位分身工作區：3D 分身 + 狀態 + AI 建議 + 檢測 + 證據 + 時間軸（總覽、車輛頁、事件中心、指揮中心共用）。 */
export function VehicleWorkspace({ vehicle, initialHotspotId = null, selectedHotspotId: controlledId, onSelectHotspot: controlledOnSelect, layout = "full", className }: {
  vehicle: Vehicle; initialHotspotId?: string | null; selectedHotspotId?: string | null; onSelectHotspot?: (id: string | null) => void; layout?: "full" | "stacked"; className?: string;
}) {
  const { tasks } = useOps();
  const [localId, setLocalId] = useState<string | null>(initialHotspotId);
  const [mode, setMode] = useState<TwinMode>(() => vehicle.hotspots.find((h) => h.id === initialHotspotId)?.mode ?? "exterior");
  const [evidenceFocus, setEvidenceFocus] = useState<{ hotspot: DamageHotspot; token: number } | null>(null);
  const evidenceRef = useRef<HTMLDivElement>(null);

  const rawId = controlledId !== undefined ? controlledId : localId;
  const selectedId = rawId && vehicle.hotspots.some((h) => h.id === rawId) ? rawId : null;
  const selected = vehicle.hotspots.find((h) => h.id === selectedId) ?? null;
  const effectiveMode: TwinMode = selected ? selected.mode : mode;

  const setSelected = useCallback((id: string | null) => {
    const h = id ? vehicle.hotspots.find((x) => x.id === id) : null;
    if (h) setMode(h.mode);
    if (controlledOnSelect) controlledOnSelect(id);
    else setLocalId(id);
  }, [controlledOnSelect, vehicle.hotspots]);

  const changeMode = (m: TwinMode) => { setMode(m); if (selected && selected.mode !== m) setSelected(null); };
  const viewEvidence = (h: DamageHotspot) => {
    setSelected(h.id);
    setEvidenceFocus((f) => ({ hotspot: h, token: (f?.token ?? 0) + 1 }));
    evidenceRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const full = layout === "full";

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className={cn("space-y-5", className)}>
      <motion.div variants={fadeUp} className={cn("grid gap-5", full ? "lg:grid-cols-[minmax(0,1fr)_356px]" : "")}>
        <VehicleDigitalTwin vehicle={vehicle} selectedHotspotId={selectedId} onSelectHotspot={setSelected} mode={effectiveMode} onModeChange={changeMode} onViewEvidence={viewEvidence} compact={!full} />
        <div className={cn("flex flex-col gap-5", !full && "lg:grid lg:grid-cols-2")}>
          <VehicleStatusPanel vehicle={vehicle} tasks={tasks} />
          <AIRecommendationPanel vehicle={vehicle} />
        </div>
      </motion.div>
      <motion.div variants={fadeUp} className={cn("grid gap-5", full ? "xl:grid-cols-2" : "")}>
        <InspectionPanel vehicle={vehicle} activeKind={selected?.kind ?? null} onFocus={(kind) => { const h = vehicle.hotspots.find((x) => x.kind === kind); if (h) setSelected(h.id); }} />
        <div ref={evidenceRef}><BeforeAfterComparison evidence={vehicle.evidence} focus={evidenceFocus} /></div>
      </motion.div>
      <motion.div variants={fadeUp}><VehicleTimeline events={vehicle.timeline} compact={!full} /></motion.div>
    </motion.div>
  );
}
