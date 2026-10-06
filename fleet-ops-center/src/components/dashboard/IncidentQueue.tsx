"use client";

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { useOps } from "@/store/OpsStore";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { IncidentCard } from "@/components/incident/IncidentCard";
import { cn } from "@/lib/utils";

export function IncidentQueue({ className, limit = 5 }: { className?: string; limit?: number }) {
  const { incidents, openIncident } = useOps();
  const list = incidents.filter((i) => i.status === "open" || i.status === "manual-review").sort((a, b) => a.aiLevel.localeCompare(b.aiLevel)).slice(0, limit);
  return (
    <GlassPanel className={cn("flex flex-col", className)}>
      <SectionHeader
        title="事件佇列"
        subtitle={`${incidents.filter((i) => i.status === "open").length} 件待裁決 · ${incidents.filter((i) => i.status === "manual-review").length} 件待補件`}
        action={
          <Link href="/incidents" className="flex items-center gap-1 text-[12px] text-sky-300 hover:underline">
            事件中心 <ArrowUpRight className="h-3.5 w-3.5" />
          </Link>
        }
      />
      <div className="flex flex-col gap-2">
        {list.map((i) => (
          <IncidentCard key={i.id} incident={i} onClick={() => openIncident(i.id)} />
        ))}
        {list.length === 0 && <div className="rounded-xl border border-dashed border-white/10 p-6 text-center text-[12.5px] text-muted">目前沒有待處理事件。</div>}
      </div>
    </GlassPanel>
  );
}
