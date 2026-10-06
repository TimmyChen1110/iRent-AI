"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, MapPin, Lock, Unlock, Ban, BadgeCheck, CalendarClock, Wrench, SprayCan, Camera } from "lucide-react";
import type { Vehicle, Task } from "@/types";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { Button } from "@/components/ui/Button";
import { useOps } from "@/store/OpsStore";
import { cn, taskStatusLabel } from "@/lib/utils";

/** 車輛身分、狀態晶片（由後端事實推導）、站點、AI 檢測摘要、進行中任務與鎖定。 */
export function VehicleStatusPanel({ vehicle, tasks, className }: { vehicle: Vehicle; tasks: Task[]; className?: string }) {
  const { lockCar, openTask, stations, relocateCar } = useOps();
  const openTasks = tasks.filter((t) => t.vehicleId === vehicle.id && t.status !== "completed" && t.status !== "cancelled");
  const attention = vehicle.exterior.flagged || vehicle.interior.flagged;

  const headline =
    vehicle.status === "unavailable"
      ? { key: "unavailable", icon: <Ban className="h-4 w-4" />, label: "暫停營運", cls: "text-zinc-100 bg-white/[0.07] ring-white/12" }
      : vehicle.status === "ready"
        ? { key: "ready", icon: <BadgeCheck className="h-4 w-4" />, label: "整備完成", cls: "text-teal-100 bg-teal-400/10 ring-teal-400/25" }
        : attention
          ? { key: "attention", icon: <AlertTriangle className="h-4 w-4" />, label: "需要處理", cls: "text-amber-200 bg-amber-400/10 ring-amber-400/20" }
          : { key: "available", icon: <CheckCircle2 className="h-4 w-4" />, label: "可出租", cls: "text-emerald-200 bg-emerald-400/10 ring-emerald-400/20" };

  const reason =
    headline.key === "unavailable"
      ? [vehicle.manualLock ? `手動鎖定${vehicle.lockReason ? `：${vehicle.lockReason}` : ""}` : null, ...openTasks.map((t) => (t.type === "cleaning" ? "清潔" : "維修"))].filter(Boolean).filter((v, i, a) => a.indexOf(v) === i).join("＋")
      : headline.key === "ready" ? "整備任務已完成" : null;

  return (
    <GlassPanel className={cn("flex flex-col", className)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[17px] font-semibold tracking-tight text-white/95">{vehicle.model}</div>
          <div className="mt-0.5 font-mono text-[13px] text-white/55">{vehicle.plate}</div>
        </div>
        <div className="text-right">
          <div className="label-xs">車輛狀態</div>
          <div className="relative mt-1 h-8 w-[196px]">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={headline.key} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }} className={cn("absolute right-0 top-0 inline-flex h-8 items-center gap-2 whitespace-nowrap rounded-lg px-2.5 text-[12.5px] font-medium ring-1", headline.cls)}>
                {headline.icon}
                {headline.label}
              </motion.div>
            </AnimatePresence>
          </div>
          <AnimatePresence>
            {reason && <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-1 text-[11px] text-muted">原因：{reason}</motion.div>}
          </AnimatePresence>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
        <div>
          <dt className="label-xs flex items-center gap-1.5"><MapPin className="h-3 w-3" />目前站點</dt>
          <dd className="mt-1">
            <select
              className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-2 py-1 text-[12.5px] text-white/90 focus:outline-none"
              value={vehicle.stationId ?? ""}
              onChange={(e) => relocateCar(vehicle.id, e.target.value || null)}
              title="派單系統未串接前，可手動指定站點"
            >
              <option value="">自動指派</option>
              {stations.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </dd>
          <dd className="mt-0.5 text-[11.5px] text-muted">{vehicle.city || "—"}{vehicle.district ? ` · ${vehicle.district}` : ""}</dd>
        </div>
        <div>
          <dt className="label-xs flex items-center gap-1.5"><Camera className="h-3 w-3" />基準照 / 完工紀錄</dt>
          <dd className="mt-1 text-[13.5px] font-medium text-white/90">{vehicle.baselineCount} 張完工照</dd>
          <dd className="text-[11.5px] text-muted">{vehicle.completedTasks} 次整備完成 · {vehicle.lastInspection}</dd>
        </div>
      </dl>

      <AnimatePresence>
        {vehicle.estimatedReady && openTasks.length > 0 && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
            <div className="mt-4 flex items-center justify-between rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-2">
              <span className="flex items-center gap-1.5 text-[12px] text-white/60"><CalendarClock className="h-3.5 w-3.5" /> 最早 SLA 開工期限</span>
              <span className="text-[13px] font-semibold text-white/95">{vehicle.estimatedReady}</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="mt-4">
        <div className="label-xs mb-2">AI 檢測</div>
        <div className="divide-y divide-white/[0.06] rounded-xl border border-white/[0.06] bg-white/[0.02]">
          <Row label="車外" ok={!vehicle.exterior.flagged} okText="無新增車損" badText={vehicle.exterior.result} />
          <Row label="車內" ok={!vehicle.interior.flagged} okText="乾淨" badText="需要清潔" />
          {openTasks.map((t) => (
            <button key={t.id} onClick={() => openTask(t.taskId)} className="flex w-full items-center justify-between px-3.5 py-2 text-left text-[13px] hover:bg-white/[0.03]">
              <span className="flex items-center gap-2 text-white/80">
                {t.type === "cleaning" ? <SprayCan className="h-3.5 w-3.5 text-amber-300" /> : <Wrench className="h-3.5 w-3.5 text-sky-300" />}
                {t.title}
              </span>
              <span className="flex items-center gap-2 text-[11px] text-white/55">
                {taskStatusLabel[t.status === "cancelled" ? "completed" : t.status]}
                <span className="font-mono text-white/40">{t.id}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="mt-auto pt-4">
        <Button
          variant={vehicle.manualLock ? "success" : "secondary"}
          size="sm"
          block
          icon={vehicle.manualLock ? <Unlock /> : <Lock />}
          onClick={() => {
            if (vehicle.manualLock) return void lockCar(vehicle.id, false);
            const why = window.prompt("鎖定原因（選填）", "") ?? null;
            if (why === null) return;
            void lockCar(vehicle.id, true, why || undefined);
          }}
        >
          {vehicle.manualLock ? "解除手動鎖定（恢復派單）" : "手動鎖定派單"}
        </Button>
      </div>
    </GlassPanel>
  );
}

function Row({ label, ok, okText, badText }: { label: string; ok: boolean; okText: string; badText: string }) {
  return (
    <div className="flex items-center justify-between px-3.5 py-2 text-[13px]">
      <span className="text-white/70">{label}</span>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span key={String(ok)} initial={{ opacity: 0, x: 6 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -6 }} transition={{ duration: 0.2 }} className={cn("flex items-center gap-1.5 font-medium", ok ? "text-emerald-300" : "text-amber-300")}>
          {ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
          {ok ? okText : badText}
        </motion.span>
      </AnimatePresence>
    </div>
  );
}
