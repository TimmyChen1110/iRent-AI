"use client";

import { cn } from "@/lib/utils";
import type { VehicleStatus } from "@/types";

export type MapFilter = "all" | "damage" | "cleaning" | "pending-review" | "maintenance";
export type MapMode = "vehicles" | "incidents" | "workload";

export const FILTERS: { id: MapFilter; label: string; dot?: string }[] = [
  { id: "all", label: "全部" },
  { id: "damage", label: "車損", dot: "bg-rose-400" },
  { id: "cleaning", label: "清潔", dot: "bg-amber-400" },
  { id: "pending-review", label: "待審核", dot: "bg-violet-400" },
  { id: "maintenance", label: "維修", dot: "bg-orange-400" },
];

export const MODES: { id: MapMode; label: string }[] = [
  { id: "vehicles", label: "車輛" },
  { id: "incidents", label: "事件" },
  { id: "workload", label: "營運負載" },
];

/** Whether a vehicle status matches a filter. */
export function matchesFilter(status: VehicleStatus, filter: MapFilter) {
  if (filter === "all") return true;
  if (filter === "maintenance") return status === "maintenance" || status === "unavailable";
  return status === filter;
}

export function FleetMapFilters({ filter, mode, onFilter, onMode }: { filter: MapFilter; mode: MapMode; onFilter: (f: MapFilter) => void; onMode: (m: MapMode) => void }) {
  return (
    <div className="flex items-center gap-2">
      <div className="glass-strong flex rounded-lg p-0.5">
        {MODES.map((m) => (
          <button key={m.id} onClick={() => onMode(m.id)} className={cn("h-7 rounded-md px-2.5 text-[11.5px] font-medium transition", mode === m.id ? "bg-white/[0.12] text-white" : "text-white/55 hover:text-white")}>
            {m.label}
          </button>
        ))}
      </div>
      <div className="glass-strong flex rounded-lg p-0.5">
        {FILTERS.map((f) => (
          <button key={f.id} onClick={() => onFilter(f.id)} className={cn("flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[11.5px] font-medium transition", filter === f.id ? "bg-white/[0.12] text-white" : "text-white/55 hover:text-white")}>
            {f.dot && <span className={cn("h-1.5 w-1.5 rounded-full", f.dot)} />}
            {f.label}
          </button>
        ))}
      </div>
    </div>
  );
}
