"use client";

import { Suspense, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import { LayoutGrid, List, ChevronRight, MapPin, Lock } from "lucide-react";
import { useOps } from "@/store/OpsStore";
import { StatusPill, Badge } from "@/components/ui/Badge";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { fadeUp, stagger } from "@/components/ui/motion";
import { cn, statusMeta } from "@/lib/utils";
import type { VehicleStatus } from "@/types";

type Filter = "all" | VehicleStatus;
const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "全部" }, { id: "healthy", label: "正常" }, { id: "damage", label: "車損" }, { id: "cleaning", label: "待清潔" },
  { id: "pending-review", label: "待審核" }, { id: "unavailable", label: "暫停營運" }, { id: "ready", label: "整備完成" },
];

export default function FleetPage() { return <Suspense><FleetView /></Suspense>; }

function FleetView() {
  const { vehicles, loaded } = useOps();
  const router = useRouter();
  const params = useSearchParams();
  const initial = (params.get("filter") as Filter | null) ?? "all";
  const [filter, setFilter] = useState<Filter>(FILTERS.some((f) => f.id === initial) ? initial : "all");
  const [view, setView] = useState<"table" | "cards">("table");
  const [q, setQ] = useState("");
  const list = useMemo(() => vehicles.filter((v) => (filter === "all" || v.status === filter) && (!q || v.plate.includes(q.toUpperCase()) || v.station.includes(q))), [vehicles, filter, q]);
  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.id, f.id === "all" ? vehicles.length : vehicles.filter((v) => v.status === f.id).length])), [vehicles]);

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp} className="flex items-end justify-between">
        <div><h2 className="text-[22px] font-semibold tracking-tight text-white">車隊</h2><p className="mt-1 text-[13px] text-muted">狀態由整備任務、人工鎖定與 AI 案件即時推導。點擊任一車輛開啟數位分身。</p></div>
        <div className="flex items-center gap-2">
          <input className="h-9 w-48 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 text-[13px] text-white/90 placeholder:text-white/30 focus:outline-none" placeholder="搜尋車牌 / 站點" value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="flex rounded-lg bg-white/[0.05] p-0.5">
            <button onClick={() => setView("table")} className={cn("grid h-8 w-8 place-items-center rounded-md transition", view === "table" ? "bg-white/[0.12] text-white" : "text-white/50")}><List className="h-4 w-4" /></button>
            <button onClick={() => setView("cards")} className={cn("grid h-8 w-8 place-items-center rounded-md transition", view === "cards" ? "bg-white/[0.12] text-white" : "text-white/50")}><LayoutGrid className="h-4 w-4" /></button>
          </div>
        </div>
      </motion.div>
      <motion.div variants={fadeUp} className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button key={f.id} onClick={() => setFilter(f.id)} className={cn("flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-[12.5px] font-medium transition", filter === f.id ? "border-white/25 bg-white/[0.1] text-white" : "border-white/[0.08] text-white/60 hover:bg-white/[0.05] hover:text-white")}>
            {f.id !== "all" && <span className={cn("h-1.5 w-1.5 rounded-full", statusMeta[f.id].dot)} />}{f.label}<span className="tabular text-white/40">{counts[f.id]}</span>
          </button>
        ))}
      </motion.div>
      {view === "table" ? (
        <GlassPanel variants={fadeUp} padded={false} className="overflow-hidden">
          <table className="w-full text-left text-[13px]">
            <thead><tr className="border-b border-white/[0.06] text-[10.5px] uppercase tracking-wider text-white/40"><th className="px-5 py-3 font-medium">車牌</th><th className="px-4 py-3 font-medium">站點</th><th className="px-4 py-3 font-medium">AI 判定</th><th className="px-4 py-3 font-medium">AI 案件 / 任務</th><th className="px-4 py-3 font-medium">目前狀態</th><th className="px-4 py-3" /></tr></thead>
            <tbody>
              {list.map((v, i) => (
                <motion.tr key={v.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.02, 0.4) }} onClick={() => router.push(`/vehicle?car=${encodeURIComponent(v.id)}`)} className="group cursor-pointer border-b border-white/[0.04] transition hover:bg-white/[0.03]">
                  <td className="px-5 py-3 font-mono font-medium text-white/90">{v.plate}{v.manualLock && <Lock className="ml-2 inline h-3 w-3 text-white/40" />}</td>
                  <td className="px-4 py-3 text-white/70"><span className="flex items-center gap-1.5"><MapPin className="h-3 w-3 text-white/30" />{v.station}<span className="text-white/35">· {v.city}</span></span></td>
                  <td className="px-4 py-3"><Badge tone={v.exterior.flagged ? "danger" : v.interior.flagged ? "warning" : "success"}>{v.aiStatus}</Badge></td>
                  <td className="px-4 py-3 text-white/60">{v.caseIds.length} 案 · {v.openTaskIds.length} 任務進行中</td>
                  <td className="px-4 py-3"><StatusPill status={v.status} /></td>
                  <td className="px-4 py-3 text-right"><ChevronRight className="inline h-4 w-4 text-white/25 transition group-hover:translate-x-0.5 group-hover:text-white/70" /></td>
                </motion.tr>
              ))}
            </tbody>
          </table>
          {list.length === 0 && <div className="p-10 text-center text-[13px] text-muted">{loaded ? "沒有符合的車輛。" : "載入中…"}</div>}
        </GlassPanel>
      ) : (
        <motion.div variants={stagger} className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {list.map((v) => (
            <motion.button key={v.id} variants={fadeUp} whileHover={{ y: -2 }} onClick={() => router.push(`/vehicle?car=${encodeURIComponent(v.id)}`)} className="glass rounded-2xl p-4 text-left">
              <div className="flex items-start justify-between"><div><div className="font-mono text-[15px] font-semibold text-white/95">{v.plate}</div><div className="text-[12px] text-white/55">{v.station}</div></div><StatusPill status={v.status} /></div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-[12px]">
                <div><div className="label-xs">AI 判定</div><div className="mt-0.5 text-white/85">{v.aiStatus}</div></div>
                <div><div className="label-xs">異常標記</div><div className="mt-0.5 text-white/85">{v.hotspots.length}</div></div>
                <div><div className="label-xs">AI 案件</div><div className="mt-0.5 text-white/85">{v.caseIds.length}</div></div>
                <div><div className="label-xs">進行中任務</div><div className="mt-0.5 text-white/85">{v.openTaskIds.length}</div></div>
              </div>
            </motion.button>
          ))}
        </motion.div>
      )}
    </motion.div>
  );
}
