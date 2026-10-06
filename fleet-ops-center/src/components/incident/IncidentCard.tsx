"use client";

import { motion } from "framer-motion";
import { AlertTriangle, SprayCan, ChevronRight } from "lucide-react";
import type { Incident } from "@/types";
import { PriorityBadge, Badge } from "@/components/ui/Badge";
import { cn, pct } from "@/lib/utils";

const STATUS_LABEL: Record<Incident["status"], { label: string; tone: "danger" | "success" | "neutral" | "violet" }> = {
  open: { label: "待裁決", tone: "danger" },
  confirmed: { label: "已確認", tone: "success" },
  "false-positive": { label: "誤判", tone: "neutral" },
  "manual-review": { label: "待補件", tone: "violet" },
};

export function IncidentCard({
  incident,
  active,
  onClick,
  compact,
}: {
  incident: Incident;
  active?: boolean;
  onClick?: () => void;
  compact?: boolean;
}) {
  const isDamage = incident.kind === "damage";
  const st = STATUS_LABEL[incident.status];
  return (
    <motion.button
      layout
      whileHover={{ y: -1 }}
      onClick={onClick}
      className={cn(
        "group relative w-full rounded-xl border p-3.5 text-left transition-colors",
        active ? "border-white/20 bg-white/[0.06]" : "border-white/[0.06] bg-white/[0.02] hover:border-white/15 hover:bg-white/[0.04]",
        incident.status === "open" && incident.priority === "high" && !active && "warning-ring",
      )}
    >
      <div className="flex items-start gap-3">
        <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-lg", isDamage ? "bg-rose-400/12 text-rose-300" : "bg-amber-400/12 text-amber-300")}>
          {isDamage ? <AlertTriangle className="h-4 w-4" /> : <SprayCan className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate font-mono text-[11.5px] text-white/50">{incident.shortId}</span>
            <PriorityBadge priority={incident.priority} />
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-[13.5px] font-semibold text-white/95">{incident.plate}</span>
            <span className="truncate text-[12.5px] text-white/70">{incident.classification}</span>
          </div>
          {!compact && (
            <div className="mt-1.5 flex items-center gap-2 text-[11.5px] text-muted">
              <span className="truncate">{incident.location}</span>
              <span className="text-white/20">·</span>
              <span className="tabular">{incident.confidence ? pct(incident.confidence) : incident.aiLevel}</span>
              <span className="text-white/20">·</span>
              <span>{incident.detectedAt}</span>
              <Badge tone={st.tone} className="ml-auto">
                {st.label}
              </Badge>
            </div>
          )}
        </div>
        <ChevronRight className="mt-2 h-4 w-4 shrink-0 text-white/25 transition group-hover:text-white/60" />
      </div>
    </motion.button>
  );
}
