"use client";

import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCheck } from "lucide-react";
import { useOps } from "@/store/OpsStore";
import { EVENT_TXT, zhStatus } from "@/lib/ops/labels";
import { rel, slaState } from "@/lib/ops/time";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { Button } from "@/components/ui/Button";
import { PriorityBadge, Badge } from "@/components/ui/Badge";
import { fadeUp, stagger } from "@/components/ui/motion";
import { PRIORITY_MAP } from "@/lib/ops/adapters";
import { cn } from "@/lib/utils";

type Filter = "action" | "all" | "unread" | "P1" | "P2" | "P3" | "failed" | "approaching" | "overdue";
const ACTION_TYPES = new Set(["task_created", "notify_failed", "sla_overdue"]);
const LABEL: Record<Filter, string> = { action: "需要行動", all: "全部", unread: "未讀", P1: "P1", P2: "P2", P3: "P3", failed: "推播失敗", approaching: "即將逾時", overdue: "逾時" };

export default function InboxPage() {
  const { events, rawTasks, summary, markRead, openTask, loaded } = useOps();
  const [filter, setFilter] = useState<Filter>("action");
  const approaching = useMemo(() => rawTasks.filter((t) => t.status === "pending" && slaState(t).kind === "soon"), [rawTasks]);
  const shown = useMemo(() => events.filter((e) => filter === "unread" ? !e.is_read : filter === "failed" ? e.type === "notify_failed" : filter === "overdue" ? e.type === "sla_overdue" : filter === "approaching" ? false : filter === "all" ? true : filter === "action" ? ACTION_TYPES.has(e.type) : e.priority === filter), [events, filter]);
  const count = (f: Filter) => f === "all" ? events.length : f === "action" ? events.filter((e) => ACTION_TYPES.has(e.type)).length : f === "unread" ? events.filter((e) => !e.is_read).length : f === "failed" ? events.filter((e) => e.type === "notify_failed").length : f === "approaching" ? approaching.length : f === "overdue" ? events.filter((e) => e.type === "sla_overdue").length : events.filter((e) => e.priority === f).length;

  const kpi = (label: string, value: number | string, sub: string, warn: boolean, f: Filter) => (
    <button onClick={() => setFilter(f)} className={cn("glass rounded-2xl px-4 py-3 text-left transition", filter === f && "ring-1 ring-white/20")}>
      <div className="label-xs">{label}</div><div className={cn("tabular mt-1.5 text-[24px] font-semibold leading-none", warn ? "text-rose-300" : "text-white")}>{value}</div><div className="mt-1 text-[10.5px] text-dim">{sub}</div>
    </button>
  );

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp} className="flex items-end justify-between">
        <div><h2 className="text-[22px] font-semibold tracking-tight text-white">通知中心</h2><p className="mt-1 text-[13px] text-muted">預設只列需要行動的事：新任務、推播失敗、SLA 逾時；其餘在「全部」。</p></div>
        <Button size="sm" icon={<CheckCheck />} disabled={!events.some((e) => !e.is_read)} onClick={() => markRead(null)}>全部標為已讀</Button>
      </motion.div>
      <motion.div variants={fadeUp} className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {kpi("待處理任務", summary?.pending ?? "—", `處理中 ${summary?.in_progress ?? "—"} · 今日完成 ${summary?.completed_today ?? "—"}`, false, "action")}
        {kpi("P1 未開工", summary?.p1_not_started ?? "—", "即時預警，SLA 5 分鐘", (summary?.p1_not_started || 0) > 0, "P1")}
        {kpi("SLA 逾時", summary?.overdue ?? "—", "待處理且超過開工期限", (summary?.overdue || 0) > 0, "overdue")}
        {kpi("即將到期", approaching.length, "剩餘時間低於 SLA 的 20%", approaching.length > 0, "approaching")}
        {kpi("推播失敗", summary?.notify_failed ?? "—", "可於任務詳情重發", (summary?.notify_failed || 0) > 0, "failed")}
      </motion.div>
      <motion.div variants={fadeUp} className="flex flex-wrap gap-2">
        {(Object.keys(LABEL) as Filter[]).map((f) => <button key={f} onClick={() => setFilter(f)} className={cn("rounded-full border px-3 py-1 text-[12px] transition", filter === f ? "border-white/25 bg-white/[0.1] text-white" : "border-white/[0.08] text-white/60 hover:text-white")}>{LABEL[f]}<span className="ml-1.5 text-white/40">{count(f)}</span></button>)}
      </motion.div>
      {(filter === "action" || filter === "approaching") && approaching.length > 0 && (
        <GlassPanel variants={fadeUp} className="border-l-4 border-l-amber-400/60">
          <div className="label-xs mb-2">SLA 即將到期 · 需安排開工</div>
          <div className="space-y-1.5">{approaching.map((t) => <button key={t.id} onClick={() => openTask(t.id)} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-[13px] hover:bg-white/[0.04]"><span className="font-mono font-semibold text-white/90">{t.car}</span><PriorityBadge priority={PRIORITY_MAP[t.priority || "P2"]} /><span className="truncate text-white/75">{t.title}</span><span className="ml-auto text-[11.5px] text-amber-300">{slaState(t).label}</span></button>)}</div>
        </GlassPanel>
      )}
      <GlassPanel variants={fadeUp} padded={false}>
        <AnimatePresence initial={false}>
          {shown.map((e) => (
            <motion.button key={e.id} layout initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} onClick={() => { if (!e.is_read) markRead([e.id]); if (e.task_id) openTask(e.task_id); }} className={cn("flex w-full items-center gap-3 border-b border-white/[0.04] px-5 py-3 text-left transition hover:bg-white/[0.03]", Boolean(e.is_read) && "opacity-60")}>
              <span className={cn("h-2 w-2 shrink-0 rounded-full", e.priority === "P1" ? "bg-rose-400" : e.priority === "P2" ? "bg-amber-400" : "bg-emerald-400", !e.is_read && "soft-pulse")} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-[13px]"><span className="font-medium text-white/90">{EVENT_TXT[e.type] || e.type}</span>{e.car && <span className="font-mono text-white/70">{e.car}</span>}{e.priority && <PriorityBadge priority={PRIORITY_MAP[e.priority]} />}{e.title && <span className="truncate text-white/60">{e.title}</span>}</div>
                <div className="truncate text-[11.5px] text-muted">{zhStatus(e.detail || e.case_id || "")}</div>
              </div>
              {e.task_id && <Badge tone="neutral">#{e.task_id}</Badge>}
              <span className="shrink-0 text-[11px] text-white/40" title={e.at}>{rel(e.at)}</span>
            </motion.button>
          ))}
        </AnimatePresence>
        {shown.length === 0 && <div className="p-8 text-center text-[12.5px] text-muted">{loaded ? "目前沒有事件。案件裁決後，任務與通知結果會出現在這裡。" : "載入中…"}</div>}
      </GlassPanel>
    </motion.div>
  );
}
