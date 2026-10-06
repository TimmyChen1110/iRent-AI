"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Sparkles, AlertTriangle, Zap, ClipboardList, Wrench, SprayCan, CalendarClock, BadgeCheck, CheckCircle2, UserSearch, Loader2, Check, Unlock } from "lucide-react";
import type { Task, Vehicle } from "@/types";
import { useOps } from "@/store/OpsStore";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { Button } from "@/components/ui/Button";
import { cn, pct, taskStatusLabel } from "@/lib/utils";

/**
 * 把 AI 判定轉成營運決策。一鍵執行 = 對這台車所有未裁決案件送出 confirm，
 * 由後端建立維修／清潔任務並發通知（與監理台同一條裁決路徑）。
 */
export function AIRecommendationPanel({ vehicle, className }: { vehicle: Vehicle; className?: string }) {
  const { incidents, tasks, getPlan, executePlan, openIncident, openTask, pushToast, lockCar } = useOps();
  const [running, setRunning] = useState<{ steps: string[]; done: number } | null>(null);

  const plan = getPlan(vehicle.id);
  const open = tasks.filter((t) => t.vehicleId === vehicle.id && t.status !== "completed" && t.status !== "cancelled");
  const review = incidents.filter((i) => i.vehicleId === vehicle.id && i.status === "manual-review");
  const firstOpen = incidents.find((i) => i.vehicleId === vehicle.id && i.status === "open");

  const state: "executing" | "recommend" | "recovery" | "locked" | "ready" | "review" | "clear" = running
    ? "executing"
    : open.length > 0 ? "recovery"
      : vehicle.manualLock ? "locked"
        : plan ? "recommend"
          : vehicle.status === "ready" ? "ready"
            : review.length > 0 ? "review"
              : "clear";

  const run = async () => {
    if (!plan) return;
    const steps = ["暫停車輛派單", ...plan.caseIds.map((c) => `確認案件 ${c} 並建立任務`), "通知整備團隊"];
    setRunning({ steps, done: 0 });
    const tickTo = (n: number) => setRunning((r) => (r ? { ...r, done: n } : r));
    try {
      tickTo(1);
      await new Promise((r) => setTimeout(r, 450));
      const created = await executePlan(vehicle.id);
      tickTo(steps.length);
      await new Promise((r) => setTimeout(r, 700));
      pushToast({ tone: "success", title: "AI 方案已執行", detail: `${vehicle.plate} 已建立任務 ${created.join("、") || "（任務已存在）"}` });
    } catch (e) {
      pushToast({ tone: "warning", title: "執行失敗", detail: (e as Error).message });
    } finally {
      setRunning(null);
    }
  };

  return (
    <GlassPanel className={cn("overflow-hidden", className)} padded={false}>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div key={state} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.25 }} className="p-5">
          {state === "executing" && running && (
            <>
              <Header icon={<Zap className="h-3.5 w-3.5" />} label="AI 建議" />
              <div className="mt-3 rounded-xl border border-sky-400/15 bg-sky-400/[0.05] p-4">
                <div className="flex items-center gap-2 text-[12.5px] font-medium text-sky-100">
                  {running.done >= running.steps.length ? <Check className="h-4 w-4 text-emerald-300" /> : <Loader2 className="h-4 w-4 animate-spin text-sky-300" />}
                  {running.done >= running.steps.length ? "執行完成" : "正在執行 AI 方案…"}
                </div>
                <ol className="mt-3 space-y-1.5">
                  {running.steps.map((s, i) => (
                    <li key={s} className={cn("flex items-center gap-2.5 text-[12.5px]", i < running.done ? "text-white/90" : "text-white/35")}>
                      <span className={cn("grid h-4.5 w-4.5 place-items-center rounded-full border", i < running.done ? "border-emerald-400/40 bg-emerald-400/20 text-emerald-300" : "border-white/10")}>{i < running.done && <Check className="h-2.5 w-2.5" strokeWidth={3} />}</span>
                      {s}
                    </li>
                  ))}
                </ol>
              </div>
            </>
          )}

          {state === "recommend" && plan && (
            <>
              <Header icon={<Sparkles className="h-3.5 w-3.5" />} label="AI 建議" />
              <div className="mt-2.5 flex items-center gap-2 text-[15px] font-semibold text-amber-100">
                <AlertTriangle className="h-4 w-4 text-amber-300" />
                暫停車輛營運並建立整備任務
              </div>
              <div className="mt-4">
                <div className="label-xs mb-1.5">原因（AI 判定，待裁決）</div>
                <ul className="space-y-1">
                  {plan.reasons.map((r, i) => (
                    <li key={i} className="flex items-center justify-between gap-3 text-[12.5px]">
                      <span className="flex items-center gap-2 text-white/85"><span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", r.kind === "damage" ? "bg-rose-400" : "bg-amber-400")} />{r.label}</span>
                      <span className="tabular font-medium text-white/70">{r.confidence ? pct(r.confidence) : "—"}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="mt-4">
                <div className="label-xs mb-1.5">執行內容</div>
                <ol className="space-y-1">
                  {plan.steps.map((s, i) => (
                    <li key={s.id} className="flex items-center gap-2.5 text-[12.5px] text-white/85">
                      <span className="grid h-4.5 w-4.5 shrink-0 place-items-center rounded-full bg-white/[0.07] text-[10px] font-semibold text-white/70">{i + 1}</span>
                      <span className="flex-1">{s.label}</span>
                      {s.team && <span className="truncate text-[11px] text-white/45">{s.team}</span>}
                    </li>
                  ))}
                </ol>
              </div>
              <div className="mt-3 flex items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2 text-[12px]">
                <span className="flex items-center gap-1.5 text-white/60"><CalendarClock className="h-3.5 w-3.5" /> 開工 SLA</span>
                <span className="font-medium text-white/90">{plan.estimatedReady}</span>
              </div>
              <div className="mt-4 flex flex-col gap-2">
                <Button variant="primary" size="lg" block icon={<Zap />} onClick={run}>執行 AI 建議方案</Button>
                <Button variant="secondary" block icon={<ClipboardList />} onClick={() => firstOpen && openIncident(firstOpen.id)}>逐案人工審核</Button>
              </div>
            </>
          )}

          {state === "recovery" && (
            <>
              <Header icon={<Wrench className="h-3.5 w-3.5" />} label="整備進行中" tone="info" />
              <div className="mt-2.5 flex items-baseline justify-between">
                <span className="font-mono text-[15px] font-semibold text-white/95">{vehicle.plate}</span>
                <span className="text-[12px] text-white/60">暫停營運 · 整備中不可派</span>
              </div>
              <div className="mt-4 space-y-2">{open.map((t) => <TaskRow key={t.id} task={t} onOpen={() => openTask(t.taskId)} />)}</div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <div className="rounded-lg bg-white/[0.03] px-3 py-2"><div className="label-xs">最早開工期限</div><div className="mt-0.5 text-[13px] font-semibold text-white/95">{vehicle.estimatedReady ?? "—"}</div></div>
                <div className="rounded-lg bg-white/[0.03] px-3 py-2"><div className="label-xs">進行中任務</div><div className="tabular mt-0.5 text-[13px] font-semibold text-white/95">{open.length}</div></div>
              </div>
              <p className="mt-3 text-[11.5px] text-muted">任務全部完工後，車輛自動恢復可派；完工照會成為下次借車的基準照。</p>
            </>
          )}

          {state === "locked" && (
            <>
              <Header icon={<Unlock className="h-3.5 w-3.5" />} label="手動鎖定中" tone="info" />
              <div className="mt-2.5 text-[15px] font-semibold text-white/95">此車已被手動鎖定派單</div>
              <p className="mt-1.5 text-[12.5px] text-muted">{vehicle.lockReason || "未填寫原因"}。整備任務已全部完成，解除鎖定即可恢復上線。</p>
              <Button variant="success" size="lg" block className="mt-4" icon={<CheckCircle2 />} onClick={() => lockCar(vehicle.id, false)}>車輛恢復上線</Button>
            </>
          )}

          {state === "ready" && (
            <>
              <Header icon={<BadgeCheck className="h-3.5 w-3.5" />} label="整備完成" tone="success" />
              <div className="mt-2.5 text-[15px] font-semibold text-teal-100">整備任務已全部完成</div>
              <p className="mt-1.5 text-[12.5px] text-muted">車輛已自動恢復可派。完工照已可作為下次借車的 AI 比對基準。</p>
            </>
          )}

          {state === "review" && (
            <>
              <Header icon={<UserSearch className="h-3.5 w-3.5" />} label="待補件" tone="violet" />
              <p className="mt-2.5 text-[12.5px] text-muted">此車案件已被要求補件，等待新的照片後再由 AI 重判。</p>
              <Button variant="primary" block className="mt-4" icon={<ClipboardList />} onClick={() => openIncident(review[0].id)}>查看案件</Button>
            </>
          )}

          {state === "clear" && (
            <>
              <Header icon={<CheckCircle2 className="h-3.5 w-3.5" />} label="無需處理" tone="success" />
              <div className="mt-2.5 text-[15px] font-semibold text-emerald-100">車輛可出租</div>
              <p className="mt-1.5 text-[12.5px] text-muted">沒有待裁決的 AI 案件，也沒有進行中的整備任務。</p>
            </>
          )}
        </motion.div>
      </AnimatePresence>
    </GlassPanel>
  );
}

function Header({ icon, label, tone = "ai" }: { icon: React.ReactNode; label: string; tone?: "ai" | "info" | "success" | "violet" }) {
  const cls = { ai: "text-sky-200", info: "text-sky-200", success: "text-emerald-300", violet: "text-violet-300" }[tone];
  return <div className={cn("flex items-center gap-1.5 text-[10.5px] font-semibold tracking-[0.08em]", cls)}>{icon}{label}</div>;
}

function TaskRow({ task, onOpen }: { task: Task; onOpen: () => void }) {
  const cleaning = task.type === "cleaning";
  return (
    <button onClick={onOpen} className="flex w-full items-center gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-left hover:border-white/15">
      <span className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-md", cleaning ? "bg-amber-400/12 text-amber-300" : "bg-sky-400/12 text-sky-300")}>{cleaning ? <SprayCan className="h-3.5 w-3.5" /> : <Wrench className="h-3.5 w-3.5" />}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-[12.5px] font-medium text-white/90">{task.title}</span>
          <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", task.sla.overdue ? "bg-rose-400/15 text-rose-200" : "bg-white/[0.06] text-white/70")}>{task.sla.overdue ? "SLA 逾時" : taskStatusLabel[task.status === "cancelled" ? "completed" : task.status]}</span>
        </div>
        <div className="truncate text-[11.5px] text-muted">{task.team} · <span className="font-mono">{task.id}</span></div>
      </div>
    </button>
  );
}
