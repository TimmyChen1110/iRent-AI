"use client";

import { motion } from "framer-motion";
import { Car, HeartPulse, SprayCan, AlertTriangle, UserSearch, TrendingUp, TrendingDown, Minus } from "lucide-react";
import type { KPI } from "@/types";
import { CountUp } from "@/components/ui/CountUp";
import { fadeUp } from "@/components/ui/motion";
import { cn } from "@/lib/utils";

const ICONS: Record<string, React.ReactNode> = {
  total: <Car />,
  healthy: <HeartPulse />,
  cleaning: <SprayCan />,
  damage: <AlertTriangle />,
  pending: <UserSearch />,
};

const TONES: Record<KPI["tone"], { icon: string; glow: string }> = {
  neutral: { icon: "bg-white/[0.06] text-white/80", glow: "from-white/[0.06]" },
  positive: { icon: "bg-emerald-400/12 text-emerald-300", glow: "from-emerald-400/[0.08]" },
  warning: { icon: "bg-amber-400/12 text-amber-300", glow: "from-amber-400/[0.08]" },
  danger: { icon: "bg-rose-400/12 text-rose-300", glow: "from-rose-400/[0.1]" },
  info: { icon: "bg-violet-400/12 text-violet-300", glow: "from-violet-400/[0.08]" },
};

export function KPICard({ kpi, onClick, active }: { kpi: KPI; onClick?: () => void; active?: boolean }) {
  const t = TONES[kpi.tone];
  const good = kpi.tone === "danger" || kpi.tone === "warning" || kpi.tone === "info" ? kpi.trend < 0 : kpi.trend > 0;
  const TrendIcon = kpi.trend === 0 ? Minus : kpi.trend > 0 ? TrendingUp : TrendingDown;
  return (
    <motion.button
      variants={fadeUp}
      whileHover={{ y: -2 }}
      onClick={onClick}
      className={cn(
        "glass relative overflow-hidden rounded-2xl px-4 py-3 text-left transition-colors",
        active && "ring-1 ring-white/20",
        onClick && "cursor-pointer",
      )}
    >
      <div className={cn("pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-gradient-to-br to-transparent blur-2xl", t.glow)} />
      <div className="flex items-center justify-between">
        <span className="label-xs">{kpi.label}</span>
        <span className={cn("grid h-6 w-6 place-items-center rounded-lg [&>svg]:h-3.5 [&>svg]:w-3.5", t.icon, kpi.id === "damage" && kpi.value > 0 && "warning-ring")}>{ICONS[kpi.id]}</span>
      </div>
      <div className="mt-1.5 flex items-end justify-between">
        <CountUp value={kpi.value} className="tabular text-[24px] font-semibold leading-none tracking-tight text-white" />
        <span className={cn("flex items-center gap-1 text-[11px] font-medium", kpi.trend === 0 ? "text-white/40" : good ? "text-emerald-300" : "text-rose-300")}>
          <TrendIcon className="h-3 w-3" />
          {kpi.trend > 0 ? "+" : ""}
          {kpi.trendLabel.includes("今日") ? kpi.trend : `${kpi.trend}%`}
        </span>
      </div>
      <div className="mt-0.5 text-[10.5px] text-dim">{kpi.trendLabel}</div>
    </motion.button>
  );
}
