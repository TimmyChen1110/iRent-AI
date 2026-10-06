"use client";

import { motion } from "framer-motion";
import { cn, pct } from "@/lib/utils";

export function ConfidenceBar({
  value,
  label = "信心度",
  className,
  tone,
}: {
  value: number;
  label?: string;
  className?: string;
  tone?: "danger" | "warning" | "success" | "info";
}) {
  const auto = value >= 0.85 ? "danger" : value >= 0.7 ? "warning" : "info";
  const t = tone ?? auto;
  const colors = {
    danger: "from-rose-400 to-rose-300",
    warning: "from-amber-400 to-amber-300",
    success: "from-emerald-400 to-emerald-300",
    info: "from-sky-400 to-sky-300",
  };
  return (
    <div className={cn("w-full", className)}>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="label-xs">{label}</span>
        <span className="tabular text-sm font-semibold text-white/90">{pct(value)}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
        <motion.div
          className={cn("h-full rounded-full bg-gradient-to-r", colors[t])}
          initial={{ width: 0 }}
          animate={{ width: `${Math.round(value * 100)}%` }}
          transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>
    </div>
  );
}
