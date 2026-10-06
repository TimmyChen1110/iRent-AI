"use client";

import { motion } from "framer-motion";
import { Car, ScanSearch, AlertTriangle, SprayCan, FileWarning, Hourglass, ClipboardCheck, CheckCircle2, Sparkles, Ban, BadgeCheck } from "lucide-react";
import type { TimelineEvent, TimelineKind } from "@/types";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { cn } from "@/lib/utils";

const META: Record<TimelineKind, { icon: React.ReactNode; cls: string; ring: string }> = {
  return: { icon: <Car />, cls: "text-sky-300 bg-sky-400/10", ring: "ring-sky-400/20" },
  inspection: { icon: <ScanSearch />, cls: "text-violet-300 bg-violet-400/10", ring: "ring-violet-400/20" },
  damage: { icon: <AlertTriangle />, cls: "text-rose-300 bg-rose-400/10", ring: "ring-rose-400/25" },
  cleaning: { icon: <SprayCan />, cls: "text-amber-300 bg-amber-400/10", ring: "ring-amber-400/20" },
  incident: { icon: <FileWarning />, cls: "text-rose-200 bg-rose-400/10", ring: "ring-rose-400/20" },
  waiting: { icon: <Hourglass />, cls: "text-white/60 bg-white/[0.06]", ring: "ring-white/10" },
  task: { icon: <ClipboardCheck />, cls: "text-sky-200 bg-sky-400/10", ring: "ring-sky-400/20" },
  resolved: { icon: <CheckCircle2 />, cls: "text-emerald-300 bg-emerald-400/10", ring: "ring-emerald-400/20" },
  ai: { icon: <Sparkles />, cls: "text-sky-200 bg-sky-400/10", ring: "ring-sky-400/20" },
  suspended: { icon: <Ban />, cls: "text-zinc-200 bg-white/[0.07]", ring: "ring-white/10" },
  available: { icon: <BadgeCheck />, cls: "text-emerald-200 bg-emerald-400/15", ring: "ring-emerald-400/30" },
};

export function VehicleTimeline({ events, className, compact }: { events: TimelineEvent[]; className?: string; compact?: boolean }) {
  return (
    <GlassPanel className={className}>
      <SectionHeader title="車輛時間軸" subtitle="還車 → AI 檢測 → 事件 → 處置" />
      <motion.ol className="relative">
        <span className="absolute left-[15px] top-2 bottom-2 w-px bg-gradient-to-b from-white/[0.12] via-white/[0.08] to-transparent" />
        {events.map((e, i) => {
          const m = META[e.kind];
          const last = i === events.length - 1;
          return (
            <motion.li
              key={e.id}
              layout
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.35, delay: Math.min(i * 0.05, 0.4) }}
              className={cn("relative flex gap-3", compact ? "pb-3" : "pb-4", last && "pb-0")}
            >
              <span className={cn("relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full ring-1 [&>svg]:h-3.5 [&>svg]:w-3.5", m.cls, m.ring, last && e.kind === "waiting" && "warning-ring")}>
                {m.icon}
              </span>
              <div className="min-w-0 flex-1 pt-1">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-[13px] font-medium text-white/90">{e.title}</span>
                  <span className="tabular shrink-0 font-mono text-[11px] text-white/40">{e.time}</span>
                </div>
                {(e.detail || e.meta) && (
                  <div className="mt-0.5 flex items-center gap-2 text-[12px] text-muted">
                    {e.detail && <span>{e.detail}</span>}
                    {e.meta && <span className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10.5px] text-white/70">{e.meta}</span>}
                  </div>
                )}
              </div>
            </motion.li>
          );
        })}
      </motion.ol>
    </GlassPanel>
  );
}
