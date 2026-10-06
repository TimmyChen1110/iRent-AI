"use client";

import { motion } from "framer-motion";
import { X, Box, AlertTriangle, SprayCan, Wrench, BadgeCheck } from "lucide-react";
import type { MapVehiclePoint } from "./useFleetMap";
import type { Vehicle } from "@/types";
import { StatusPill } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { pct, cleanlinessLabel } from "@/lib/utils";

/** Popup anchored to a map marker. Store-backed vehicles show live AI findings. */
export function VehicleMapPopup({ point, vehicle, onClose, onOpenTwin }: { point: MapVehiclePoint; vehicle?: Vehicle; onClose: () => void; onOpenTwin?: (vehicleId: string) => void }) {
  const recovering = vehicle && (vehicle.status === "unavailable" || vehicle.status === "maintenance");
  return (
    <motion.div initial={{ opacity: 0, y: 8, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 6, scale: 0.97 }} transition={{ duration: 0.22 }} className="glass-strong w-[270px] rounded-2xl p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[14px] font-semibold text-white/95">{vehicle?.station ?? "iRent 車輛"}</div>
          <div className="font-mono text-[12px] text-white/55">{point.plate}</div>
        </div>
        <button onClick={onClose} className="text-white/40 hover:text-white"><X className="h-4 w-4" /></button>
      </div>
      <div className="mt-2.5"><StatusPill status={point.status} pulse={point.status === "damage"} /></div>

      {vehicle ? (
        <div className="mt-3 space-y-1.5">
          {vehicle.exterior.flagged && (
            <Row icon={<AlertTriangle className="h-3.5 w-3.5 text-rose-300" />} label={`${vehicle.exterior.location} · ${vehicle.exterior.type}`} value={pct(vehicle.exterior.confidence)} />
          )}
          {vehicle.interior.flagged && (
            <Row icon={<SprayCan className="h-3.5 w-3.5 text-amber-300" />} label={`車內 · ${cleanlinessLabel[vehicle.interior.cleanliness]}`} value={pct(vehicle.interior.confidence)} />
          )}
          {recovering && <Row icon={<Wrench className="h-3.5 w-3.5 text-sky-300" />} label="整備進行中" value={vehicle.estimatedReady ?? ""} />}
          {vehicle.status === "ready" && <Row icon={<BadgeCheck className="h-3.5 w-3.5 text-teal-300" />} label="整備完成，待恢復上線" value="" />}
          {!vehicle.exterior.flagged && !vehicle.interior.flagged && !recovering && vehicle.status !== "ready" && (
            <div className="text-[12px] text-muted">最近一次 AI 檢測無異常 · {vehicle.station}</div>
          )}
        </div>
      ) : (
        <div className="mt-3 text-[12px] text-muted">尚無資料</div>
      )}

      {vehicle && onOpenTwin && (
        <Button size="sm" variant="primary" block className="mt-3" icon={<Box />} onClick={() => onOpenTwin(vehicle.id)}>
          開啟數位分身
        </Button>
      )}
    </motion.div>
  );
}

function Row({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg bg-white/[0.04] px-2.5 py-1.5 text-[12px]">
      <span className="flex items-center gap-2 text-white/85">{icon}{label}</span>
      <span className="tabular font-semibold text-white/90">{value}</span>
    </div>
  );
}
