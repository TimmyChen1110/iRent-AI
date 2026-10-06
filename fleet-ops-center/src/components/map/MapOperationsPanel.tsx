"use client";

import { AlertTriangle, SprayCan, ArrowRight } from "lucide-react";
import { motion } from "framer-motion";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { Button } from "@/components/ui/Button";
import { StatusPill } from "@/components/ui/Badge";
import { AIMapInsight } from "./AIMapInsight";
import type { FleetMapModel } from "./useFleetMap";
import type { CityNode } from "@/data/fleetMapData";
import type { Incident, Vehicle } from "@/types";
import { cn, formatNumber, pct } from "@/lib/utils";

function Stat({ label, value, tone }: { label: string; value: number; tone?: "danger" | "warning" | "violet" | "success" }) {
  const cls = { danger: "text-rose-300", warning: "text-amber-300", violet: "text-violet-300", success: "text-emerald-300" };
  return (
    <div className="rounded-lg bg-white/[0.03] px-3 py-2">
      <div className="label-xs">{label}</div>
      <div className={cn("tabular mt-0.5 text-[18px] font-semibold", tone ? cls[tone] : "text-white")}>{formatNumber(value)}</div>
    </div>
  );
}

/** Level 1 panel: national network summary + regional status + AI insight. */
export function NetworkPanel({ model, onInspectCity }: { model: FleetMapModel; onInspectCity: (id: CityNode["id"]) => void }) {
  const { network, cityNodes } = model;
  const top = [...cityNodes].sort((a, b) => b.workload - a.workload)[0];
  const target = cityNodes.find((c) => c.enabled) ?? top;
  if (!top) {
    return <GlassPanel className="flex h-full items-center justify-center text-[13px] text-muted">載入車隊網絡…</GlassPanel>;
  }
  return (
    <GlassPanel className="flex h-full flex-col">
      <div className="label-xs">車隊網絡</div>
      <div className="mt-1 text-[15px] font-semibold text-white/95">全國車隊即時概況</div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Stat label="車輛總數" value={network.vehicles} />
        <Stat label="進行中事件" value={network.incidents} tone="danger" />
        <Stat label="待清潔" value={network.cleaning} tone="warning" />
        <Stat label="待人工審核" value={network.pendingReview} tone="violet" />
      </div>

      <div className="mt-4">
        <div className="label-xs mb-2">區域狀態</div>
        <div className="divide-y divide-white/[0.05] rounded-xl border border-white/[0.06] bg-white/[0.02]">
          {cityNodes.map((c) => {
            const tone = c.workload >= 0.8 ? "text-rose-300" : c.workload >= 0.45 ? "text-amber-300" : "text-emerald-300";
            return (
              <button key={c.id} onClick={() => c.enabled && onInspectCity(c.id)} disabled={!c.enabled} className={cn("flex w-full items-center justify-between px-3 py-2 text-left text-[13px] transition", c.enabled ? "hover:bg-white/[0.03]" : "cursor-default")}>
                <span className="flex items-center gap-2 text-white/85">
                  <span className={cn("h-1.5 w-1.5 rounded-full", c.workload >= 0.8 ? "bg-rose-400" : c.workload >= 0.45 ? "bg-amber-400" : "bg-emerald-400")} />
                  {c.name}
                  <span className="tabular text-[11px] text-white/40">{formatNumber(c.vehicles)} 台</span>
                </span>
                <span className={cn("flex items-center gap-1.5 text-[12px] font-medium", tone)}>
                  {c.statusLabel}
                  {c.enabled && <ArrowRight className="h-3 w-3" />}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <AIMapInsight
        className="mt-auto pt-4"
        title={`${top.name}目前營運負載最高`}
        lines={[`${top.damage} 件車損事件`, `${top.cleaning} 台待清潔`, `${top.pendingReview} 件待人工審核`]}
        recommendation={`優先處理${top.name}營運事項`}
        action={`檢視${target.name}`}
        onAction={() => onInspectCity(target.id)}
      />
    </GlassPanel>
  );
}

/** Level 2 panel: Taipei operations counts + live incidents + district insight. */
export function TaipeiOperationsPanel({ model, incidents, onInvestigate, selectedVehicleId, heroId }: { model: FleetMapModel; incidents: Incident[]; onInvestigate: (vehicleId: string) => void; selectedVehicleId: string | null; heroId: string | null }) {
  const { taipei, districtSummaries, storeVehicleById } = model;
  const taipeiPoints = new Set(model.points.filter((p) => p.cityId === "taipei").map((p) => p.vehicleId));
  const hot = [...districtSummaries.filter((d) => d.cityId === "taipei")].sort((a, b) => b.workload - a.workload)[0] ?? { name: "台北", id: "", alerts: 0 };
  const hotPoints = model.points.filter((p) => `${p.cityId}:${p.district}` === hot.id);
  const hotDamage = hotPoints.filter((p) => p.status === "damage").length;
  const hotCleaning = hotPoints.filter((p) => p.status === "cleaning").length;

  // Live incidents: open/manual-review incidents for store vehicles that sit on the Taipei map, ABC-1234 first.
  const live = incidents
    .filter((i) => (i.status === "open" || i.status === "manual-review") && storeVehicleById[i.vehicleId] && taipeiPoints.has(i.vehicleId))
    .reduce<{ vehicle: Vehicle; items: Incident[] }[]>((acc, i) => {
      const g = acc.find((x) => x.vehicle.id === i.vehicleId);
      if (g) g.items.push(i);
      else acc.push({ vehicle: storeVehicleById[i.vehicleId], items: [i] });
      return acc;
    }, [])
    .sort((a, b) => (a.vehicle.id === heroId ? -1 : b.vehicle.id === heroId ? 1 : 0) || a.items[0].aiLevel.localeCompare(b.items[0].aiLevel))
    .slice(0, 8);
  const recovering = Object.values(storeVehicleById).filter((v) => taipeiPoints.has(v.id) && (v.status === "unavailable" || v.status === "ready")).slice(0, 6);

  return (
    <GlassPanel className="flex h-full flex-col">
      <div className="label-xs">台北營運</div>
      <div className="mt-1 text-[15px] font-semibold text-white/95">城市車隊即時狀態</div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Stat label="車輛" value={taipei.vehicles} />
        <Stat label="正常" value={taipei.healthy} tone="success" />
        <Stat label="車損" value={taipei.damage} tone="danger" />
        <Stat label="待清潔" value={taipei.cleaning} tone="warning" />
      </div>

      <div className="mt-4 min-h-0 flex-1">
        <div className="label-xs mb-2">即時事件</div>
        <div className="space-y-2">
          {live.map(({ vehicle, items }) => (
            <motion.button
              layout
              key={vehicle.id}
              onClick={() => onInvestigate(vehicle.id)}
              className={cn("w-full rounded-xl border p-3 text-left transition", selectedVehicleId === vehicle.id ? "border-white/20 bg-white/[0.06]" : "border-white/[0.06] bg-white/[0.02] hover:border-white/15", vehicle.id === heroId && items.some((i) => i.kind === "damage") && "warning-ring")}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[13px] font-semibold text-white/95">{vehicle.plate}</span>
                <StatusPill status={vehicle.status} />
              </div>
              <div className="mt-0.5 text-[11.5px] text-muted">{vehicle.station}{vehicle.district ? ` · ${vehicle.district}` : ""}</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {items.map((i) => (
                  <span key={i.id} className={cn("flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium", i.kind === "damage" ? "bg-rose-400/10 text-rose-200" : "bg-amber-400/10 text-amber-200")}>
                    {i.kind === "damage" ? <AlertTriangle className="h-3 w-3" /> : <SprayCan className="h-3 w-3" />}
                    {i.classification} · {i.confidence ? pct(i.confidence) : i.aiLevel}
                  </span>
                ))}
              </div>
              {vehicle.id === heroId && <div className="mt-2 text-[11.5px] font-medium text-sky-300">點擊調查 →</div>}
            </motion.button>
          ))}
          {recovering.map((v) => (
            <button key={v.id} onClick={() => onInvestigate(v.id)} className="flex w-full items-center justify-between rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-left hover:border-white/15">
              <span>
                <span className="font-mono text-[13px] font-semibold text-white/95">{v.plate}</span>
                <span className="ml-2 text-[11.5px] text-muted">{v.status === "ready" ? "整備完成" : `整備進行中${v.estimatedReady ? ` · 開工期限 ${v.estimatedReady}` : ""}`}</span>
              </span>
              <StatusPill status={v.status} />
            </button>
          ))}
          {live.length === 0 && recovering.length === 0 && <div className="rounded-xl border border-dashed border-white/10 p-4 text-center text-[12px] text-muted">台北目前沒有待處理事件。</div>}
        </div>
      </div>

      <AIMapInsight
        className="mt-4"
        title={`${hot.name}目前營運負載最高`}
        lines={[`${hot.alerts} 件進行中事件`, `${hotCleaning} 項清潔任務`, `${hotDamage} 件車損案件`]}
        recommendation={`優先調度${hot.name}應變團隊`}
      />
      {heroId && live.some((g) => g.vehicle.id === heroId) && (
        <Button variant="primary" block className="mt-3" onClick={() => onInvestigate(heroId)}>
          調查 {heroId}
        </Button>
      )}
    </GlassPanel>
  );
}
