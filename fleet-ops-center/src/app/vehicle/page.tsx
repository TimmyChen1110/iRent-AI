"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowLeft } from "lucide-react";
import { useOps } from "@/store/OpsStore";
import { VehicleWorkspace } from "@/components/workspace/VehicleWorkspace";
import { StatusPill } from "@/components/ui/Badge";

export default function VehiclePage() {
  return <Suspense><VehicleView /></Suspense>;
}

function VehicleView() {
  const params = useSearchParams();
  const car = (params.get("car") || "").toUpperCase();
  const { getVehicle, loaded } = useOps();
  const vehicle = getVehicle(car);
  if (!vehicle) return <div className="py-20 text-center text-muted">{loaded ? <>找不到車輛 {car}。<Link href="/fleet" className="text-sky-300 hover:underline">返回車隊</Link></> : "載入中…"}</div>;
  return (
    <div className="space-y-5">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href="/fleet" className="grid h-9 w-9 place-items-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-white/70 hover:text-white"><ArrowLeft className="h-4 w-4" /></Link>
          <div>
            <h2 className="text-[22px] font-semibold tracking-tight text-white">{vehicle.model} <span className="font-mono text-[16px] text-white/50">{vehicle.plate}</span></h2>
            <p className="mt-0.5 text-[13px] text-muted">{vehicle.station} · {vehicle.city || "—"} · {vehicle.lastInspection}</p>
          </div>
        </div>
        <StatusPill status={vehicle.status} pulse={vehicle.status === "damage"} />
      </motion.div>
      <VehicleWorkspace key={vehicle.id} vehicle={vehicle} initialHotspotId={vehicle.hotspots[0]?.id ?? null} />
    </div>
  );
}
