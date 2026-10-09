"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { useOps } from "@/store/OpsStore";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { StatusPill } from "@/components/ui/Badge";
import { statusMeta, cn } from "@/lib/utils";
import type { VehicleStatus } from "@/types";

const ORDER: VehicleStatus[] = ["rented", "healthy", "ready", "damage", "cleaning", "maintenance", "pending-review", "unavailable"];

export function FleetStatus({ className }: { className?: string }) {
  const { vehicles } = useOps();
  const counts = ORDER.map((s) => ({ status: s, count: vehicles.filter((v) => v.status === s).length })).filter((c) => c.count > 0);
  const total = vehicles.length;
  const attention = vehicles.filter((v) => v.status !== "healthy" && v.status !== "rented").slice(0, 6);

  return (
    <GlassPanel className={className}>
      <SectionHeader
        title="車隊狀態"
        subtitle={`${total} 台車 · 由後端任務與 AI 案件即時推導`}
        action={
          <Link href="/fleet" className="flex items-center gap-1 text-[12px] text-sky-300 hover:underline">
            車隊列表 <ArrowUpRight className="h-3.5 w-3.5" />
          </Link>
        }
      />
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-white/[0.05]">
        {counts.map((c, i) => (
          <motion.div
            key={c.status}
            initial={{ width: 0 }}
            animate={{ width: `${(c.count / total) * 100}%` }}
            transition={{ duration: 0.8, delay: i * 0.05, ease: [0.22, 1, 0.36, 1] }}
            className={cn("h-full", statusMeta[c.status].dot)}
            title={`${statusMeta[c.status].label}: ${c.count}`}
          />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {counts.map((c) => (
          <span key={c.status} className="flex items-center gap-1.5 text-[11.5px] text-white/70">
            <span className={cn("h-1.5 w-1.5 rounded-full", statusMeta[c.status].dot)} />
            {statusMeta[c.status].label}
            <span className="tabular text-white/40">{c.count}</span>
          </span>
        ))}
      </div>

      <div className="mt-5 divide-y divide-white/[0.05]">
        {attention.map((v) => (
          <Link key={v.id} href={`/vehicle?car=${encodeURIComponent(v.id)}`} className="flex items-center justify-between gap-3 py-2.5 transition hover:bg-white/[0.02]">
            <div className="min-w-0">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[13px] font-semibold text-white/95">{v.plate}</span>
                <span className="truncate text-[12px] text-muted">{v.model}</span>
              </div>
              <div className="text-[11.5px] text-dim">{v.location} · {v.aiStatus}</div>
            </div>
            <StatusPill status={v.status} />
          </Link>
        ))}
      </div>
    </GlassPanel>
  );
}
