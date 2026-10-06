"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, SprayCan, ChevronRight, Radio, Sparkles, ClipboardList, Wrench, BadgeCheck } from "lucide-react";
import type { Incident, Vehicle } from "@/types";
import { useOps } from "@/store/OpsStore";
import { Button } from "@/components/ui/Button";
import { cn, pct } from "@/lib/utils";
import { fadeUp } from "@/components/ui/motion";

/** 即時事件條：這台車所有待裁決的 AI 案件；裁決後收斂成整備進度。 */
export function LiveIncident({ vehicle, incidents, activeHotspotId, onSelect }: { vehicle: Vehicle; incidents: Incident[]; activeHotspotId: string | null; onSelect: (hotspotId: string) => void }) {
  const { openIncident, tasks } = useOps();
  const alerts = incidents.filter((i) => i.vehicleId === vehicle.id && i.status === "open");
  const open = tasks.filter((t) => t.vehicleId === vehicle.id && t.status !== "completed" && t.status !== "cancelled");
  const live = alerts.length > 0;
  const recovering = !live && open.length > 0;
  const ready = !live && !recovering && vehicle.status === "ready";
  if (!live && !recovering && !ready) return null;

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div key={live ? "live" : recovering ? "recovery" : "ready"} variants={fadeUp} initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.3 }}
        className={cn("glass relative flex items-center gap-4 overflow-hidden rounded-2xl px-4 py-3", live && "border-rose-400/20 shadow-[0_0_0_1px_rgba(251,113,133,0.08),0_20px_60px_-30px_rgba(251,113,133,0.35)]")}>
        {live && <span className="pointer-events-none absolute inset-y-0 left-0 w-1 bg-gradient-to-b from-rose-400/80 via-rose-400/40 to-transparent" />}
        {live ? (
          <>
            <div className="flex shrink-0 items-center gap-3 pl-1">
              <span className="relative grid h-9 w-9 place-items-center rounded-xl bg-rose-400/12 text-rose-300"><Radio className="h-4 w-4" /><span className="absolute inset-0 rounded-xl bg-rose-400/20 warning-ring" /></span>
              <div className="leading-tight">
                <div className="flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-rose-300"><span className="h-1.5 w-1.5 rounded-full bg-rose-400 soft-pulse" />即時事件</div>
                <div className="mt-0.5 text-[13.5px] font-semibold text-white/95">{vehicle.plate} <span className="font-normal text-white/60">· {vehicle.model !== "共享車輛" ? `${vehicle.model} · ` : ""}{vehicle.station}</span></div>
                <div className="text-[11px] text-muted">{vehicle.rentalId && vehicle.lastReturned.time ? `還車 ${vehicle.lastReturned.time} · ` : ""}AI 標記 {alerts.length} 件待裁決</div>
              </div>
            </div>
            <span className="h-9 w-px bg-white/[0.08]" />
            <div className="flex min-w-0 flex-1 gap-2 overflow-x-auto">
              {alerts.map((a) => {
                const damage = a.kind === "damage";
                const active = a.hotspotId === activeHotspotId;
                return (
                  <button key={a.id} onClick={() => a.hotspotId && onSelect(a.hotspotId)} className={cn("group flex shrink-0 items-center gap-2.5 rounded-xl border px-3 py-1.5 text-left transition", damage ? "border-rose-400/20 bg-rose-400/[0.07] hover:bg-rose-400/[0.12]" : "border-amber-400/20 bg-amber-400/[0.07] hover:bg-amber-400/[0.12]", active && "ring-1 ring-white/30")}>
                    <span className={cn("grid h-7 w-7 place-items-center rounded-lg", damage ? "bg-rose-400/15 text-rose-300" : "bg-amber-400/15 text-amber-300")}>{damage ? <AlertTriangle className="h-3.5 w-3.5" /> : <SprayCan className="h-3.5 w-3.5" />}</span>
                    <span className="leading-tight">
                      <span className="block text-[12.5px] font-semibold text-white/95">{damage ? "車損警示" : "清潔警示"} <span className="font-mono text-[10.5px] text-white/50">{a.aiLevel}</span></span>
                      <span className="block max-w-[220px] truncate text-[11px] text-white/60">{a.location} · <span className="tabular">{a.confidence ? pct(a.confidence) : "—"}</span></span>
                    </span>
                    <ChevronRight className="h-3.5 w-3.5 text-white/30 transition group-hover:translate-x-0.5 group-hover:text-white/70" />
                  </button>
                );
              })}
            </div>
            <div className="hidden shrink-0 items-center gap-2 text-[11.5px] xl:flex"><Sparkles className="h-3.5 w-3.5 text-sky-300" /><span className="text-white/55">AI 建議：</span><span className="font-medium text-amber-100">暫停營運並建立整備任務</span></div>
            <Button variant="primary" size="sm" className="shrink-0" icon={<ClipboardList />} onClick={() => openIncident(alerts.find((a) => a.kind === "damage")?.id ?? alerts[0].id)}>審核案件</Button>
          </>
        ) : recovering ? (
          <>
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-sky-400/12 text-sky-300"><Wrench className="h-4 w-4" /></span>
            <div className="min-w-0 flex-1 leading-tight">
              <div className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-sky-300">整備進行中</div>
              <div className="mt-0.5 truncate text-[13px] text-white/85">{vehicle.plate} 暫停營運中 · {open.length} 項進行中任務{vehicle.estimatedReady ? <> · 最早開工期限 <span className="font-semibold text-white">{vehicle.estimatedReady}</span></> : null}</div>
            </div>
          </>
        ) : (
          <>
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-teal-400/12 text-teal-200"><BadgeCheck className="h-4 w-4" /></span>
            <div className="min-w-0 flex-1 leading-tight">
              <div className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-teal-300">整備完成</div>
              <div className="mt-0.5 text-[13px] text-white/85">{vehicle.plate} 的整備任務已完成，車輛已恢復可派。</div>
            </div>
          </>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
