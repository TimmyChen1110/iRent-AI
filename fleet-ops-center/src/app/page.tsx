"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { useRouter } from "next/navigation";
import { useOps } from "@/store/OpsStore";
import { KPICard } from "@/components/dashboard/KPICard";
import { LiveIncident } from "@/components/dashboard/LiveIncident";
import { FleetStatus } from "@/components/dashboard/FleetStatus";
import { IncidentQueue } from "@/components/dashboard/IncidentQueue";
import { VehicleWorkspace } from "@/components/workspace/VehicleWorkspace";
import { fadeUp, stagger } from "@/components/ui/motion";
import { fmt } from "@/lib/ops/time";

export default function OverviewPage() {
  const { kpis, incidents, getVehicle, demoVehicleId, loaded, summary } = useOps();
  const router = useRouter();
  const vehicle = demoVehicleId ? getVehicle(demoVehicleId) : undefined;
  const [selectedHotspotId, setSelectedHotspotId] = useState<string | null>(null);
  const kpiRoute: Record<string, string> = { total: "/fleet", healthy: "/fleet?filter=healthy", cleaning: "/fleet?filter=cleaning", damage: "/fleet?filter=damage", pending: "/incidents" };

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-4">
      <motion.div variants={fadeUp} className="flex items-end justify-between">
        <div>
          <h2 className="text-[22px] font-semibold tracking-tight text-white">車隊總覽</h2>
          <p className="mt-1 text-[13px] text-muted">從 AI 辨識到營運行動。每一台還車都經過 AI 檢測，異常會第一時間出現在這裡。</p>
        </div>
        <div className="text-right text-[12px] text-dim">
          <div>{summary ? fmt(summary.server_time).slice(0, 10) : ""}</div>
          <div className="text-white/60">{summary ? `最後同步 ${fmt(summary.server_time).slice(11)}` : "連線中…"}</div>
        </div>
      </motion.div>
      <motion.div variants={stagger} className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {kpis.map((k) => <KPICard key={k.id} kpi={k} onClick={() => router.push(kpiRoute[k.id] ?? "/fleet")} />)}
      </motion.div>
      {vehicle ? (
        <>
          <LiveIncident vehicle={vehicle} incidents={incidents} activeHotspotId={selectedHotspotId} onSelect={setSelectedHotspotId} />
          <VehicleWorkspace key={vehicle.id} vehicle={vehicle} selectedHotspotId={selectedHotspotId} onSelectHotspot={setSelectedHotspotId} />
        </>
      ) : (
        <div className="glass rounded-2xl p-10 text-center text-[13px] text-muted">{loaded ? "目前沒有車輛資料" : "載入車隊資料…"}</div>
      )}
      <motion.div variants={fadeUp} className="grid gap-5 xl:grid-cols-2"><IncidentQueue /><FleetStatus /></motion.div>
    </motion.div>
  );
}
