"use client";

import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Filter } from "lucide-react";
import { useOps } from "@/store/OpsStore";
import { IncidentCard } from "@/components/incident/IncidentCard";
import { VehicleWorkspace } from "@/components/workspace/VehicleWorkspace";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { Button } from "@/components/ui/Button";
import { fadeUp, stagger } from "@/components/ui/motion";
import { cn } from "@/lib/utils";
import type { IncidentStatus } from "@/types";

type Tab = "all" | IncidentStatus;
const TABS: { id: Tab; label: string }[] = [{ id: "open", label: "待裁決" }, { id: "confirmed", label: "已確認" }, { id: "manual-review", label: "待補件" }, { id: "false-positive", label: "誤判" }, { id: "all", label: "全部" }];

export default function IncidentsPage() {
  const { incidents, getVehicle, openIncident, openTask, loaded, demoVehicleId } = useOps();
  const [tab, setTab] = useState<Tab>("open");
  const list = useMemo(() => (tab === "all" ? incidents : incidents.filter((i) => i.status === tab)), [incidents, tab]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = incidents.find((i) => i.id === selectedId) ?? list.find((i) => i.vehicleId === demoVehicleId) ?? list[0];
  const vehicle = selected ? getVehicle(selected.vehicleId) : undefined;

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp} className="flex items-end justify-between">
        <div><h2 className="text-[22px] font-semibold tracking-tight text-white">事件中心</h2><p className="mt-1 text-[13px] text-muted">AI 標記的案件（資料集 + 現場實測）。選取案件後，右側數位分身、AI 結果、證據與時間軸直接更新。</p></div>
      </motion.div>
      <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <motion.div variants={fadeUp}>
          <GlassPanel className="sticky top-[84px] flex max-h-[calc(100vh-110px)] flex-col">
            <div className="mb-3 flex items-center gap-2 text-[12px] text-white/60"><Filter className="h-3.5 w-3.5" /><div className="flex flex-wrap gap-1">{TABS.map((t) => <button key={t.id} onClick={() => setTab(t.id)} className={cn("rounded-md px-2 py-1 text-[11.5px] transition", tab === t.id ? "bg-white/[0.12] text-white" : "hover:bg-white/[0.05] hover:text-white")}>{t.label}<span className="ml-1 text-white/35">{t.id === "all" ? incidents.length : incidents.filter((i) => i.status === t.id).length}</span></button>)}</div></div>
            <div className="-mx-1 flex-1 space-y-2 overflow-y-auto px-1 pb-1">
              {list.map((i) => <IncidentCard key={i.id} incident={i} active={i.id === selected?.id} onClick={() => setSelectedId(i.id)} />)}
              {list.length === 0 && <div className="rounded-xl border border-dashed border-white/10 p-6 text-center text-[12.5px] text-muted">{loaded ? "沒有符合的案件。" : "載入中…"}</div>}
            </div>
          </GlassPanel>
        </motion.div>
        <div className="min-w-0">
          <AnimatePresence mode="wait">
            {selected && vehicle && (
              <motion.div key={selected.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.25 }}>
                <div className="mb-4 flex items-center justify-between">
                  <div><div className="font-mono text-[15px] font-semibold text-white/95">{selected.id}</div><div className="text-[12.5px] text-muted">{selected.classification} · {selected.location} · {selected.aiLevel}{selected.confidence ? ` · ${Math.round(selected.confidence * 100)}%` : ""}</div></div>
                  <div className="flex gap-2">
                    {selected.taskId && <Button variant="secondary" onClick={() => openTask(selected.taskId!)}>任務 #{selected.taskId}</Button>}
                    <Button variant="primary" onClick={() => openIncident(selected.id)}>{selected.status === "open" ? "審核並裁決" : "查看案件"}</Button>
                  </div>
                </div>
                <VehicleWorkspace key={selected.id} vehicle={vehicle} initialHotspotId={selected.hotspotId ?? null} layout="stacked" />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}
