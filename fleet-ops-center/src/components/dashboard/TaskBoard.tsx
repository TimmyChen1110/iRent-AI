"use client";

import Link from "next/link";
import { useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, Clock, Users, ArrowUpRight, Play, Camera, AlertTriangle } from "lucide-react";
import { useOps } from "@/store/OpsStore";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { Button } from "@/components/ui/Button";
import { PriorityBadge, Badge } from "@/components/ui/Badge";
import { fadeUp, stagger } from "@/components/ui/motion";
import { cn } from "@/lib/utils";
import type { Task, TaskStatus } from "@/types";

const COLS: { id: TaskStatus; label: string; hint: string }[] = [
  { id: "assigned", label: "待處理", hint: "SLA 倒數中" },
  { id: "in-progress", label: "處理中", hint: "完工需完工照（依設定）" },
  { id: "completed", label: "已完成", hint: "完工照成為基準照" },
];

/** 整備任務看板：資料與動作全部走後端（allowed_actions 守門）。 */
export function TaskBoard({ title, subtitle, types }: { title: string; subtitle: string; types: Task["type"][] }) {
  const { tasks, taskAction, assignTask, people, openTask, loaded } = useOps();
  const [showAll, setShowAll] = useState(false);
  const list = tasks.filter((t) => types.includes(t.type) && t.status !== "cancelled");
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, "/");
  const open = list.filter((t) => t.status !== "completed").length;

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp} className="flex items-end justify-between">
        <div>
          <h2 className="text-[22px] font-semibold tracking-tight text-white">{title}</h2>
          <p className="mt-1 text-[13px] text-muted">{subtitle}</p>
        </div>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-[12px] text-muted"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> 顯示全部已完成</label>
          <div className="text-right"><div className="tabular text-[26px] font-semibold text-white">{open}</div><div className="label-xs">進行中任務</div></div>
        </div>
      </motion.div>

      <div className="grid gap-4 md:grid-cols-3">
        {COLS.map((col) => {
          const items = list.filter((t) => t.status === col.id && (col.id !== "completed" || showAll || t.createdAt.startsWith(today) || true));
          return (
            <GlassPanel key={col.id} variants={fadeUp} className="min-h-[260px]">
              <SectionHeader title={col.label} subtitle={`${items.length} 項 · ${col.hint}`} />
              <div className="space-y-2.5">
                {items.map((t) => (
                  <motion.div layout key={t.id} className={cn("rounded-xl border border-white/[0.06] bg-white/[0.02] p-3.5", t.status === "completed" && "opacity-70", t.sla.overdue && "border-rose-400/30")}>
                    <div className="flex items-center justify-between">
                      <button onClick={() => openTask(t.taskId)} className="font-mono text-[11px] text-white/45 hover:text-white">{t.id}</button>
                      <span className="flex items-center gap-1.5">
                        {t.isDemo && <Badge tone="info">DEMO</Badge>}
                        {t.sla.overdue && <Badge tone="danger"><AlertTriangle className="h-3 w-3" /> 逾時</Badge>}
                        <PriorityBadge priority={t.priority} />
                      </span>
                    </div>
                    <button onClick={() => openTask(t.taskId)} className="mt-1.5 text-left text-[13px] font-medium text-white/90 hover:underline">{t.title}</button>
                    <Link href={`/vehicle?car=${encodeURIComponent(t.vehicleId)}`} className="mt-0.5 flex items-center gap-1 text-[12px] text-sky-300 hover:underline">{t.plate}<ArrowUpRight className="h-3 w-3" /></Link>
                    <div className="mt-2.5 space-y-1 text-[11.5px] text-muted">
                      <div className="flex items-center gap-1.5">
                        <Users className="h-3 w-3" />
                        {t.allowedActions.includes("assign") ? (
                          <select className="rounded-md border border-white/[0.08] bg-white/[0.04] px-1.5 py-0.5 text-[11.5px] text-white/85" value={t.assigneeId ?? ""} onChange={(e) => assignTask(t.taskId, e.target.value ? Number(e.target.value) : null)}>
                            <option value="">未指派</option>
                            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                          </select>
                        ) : t.team}
                      </div>
                      <div className="flex items-center gap-1.5"><Clock className="h-3 w-3" />{t.status === "completed" ? `建立 ${t.createdAt}` : t.eta ? `開工期限 ${t.eta}` : `建立 ${t.createdAt}`}</div>
                    </div>
                    {t.completionMessage && t.status === "in-progress" && <div className="mt-2 flex items-center gap-1.5 text-[11px] text-amber-300"><Camera className="h-3 w-3" />{t.completionMessage}</div>}
                    <div className="mt-3 flex gap-2">
                      {t.allowedActions.includes("start") && <Button size="sm" variant="primary" block icon={<Play />} onClick={() => taskAction(t.taskId, "start")}>開始處理</Button>}
                      {t.allowedActions.includes("complete") && <Button size="sm" variant="success" block icon={<CheckCircle2 />} onClick={() => taskAction(t.taskId, "complete")}>標記完成</Button>}
                      {t.status === "in-progress" && !t.allowedActions.includes("complete") && <Button size="sm" variant="secondary" block icon={<Camera />} onClick={() => openTask(t.taskId)}>需完工照 · 開啟詳情</Button>}
                      {t.status === "completed" && <Badge tone="success"><CheckCircle2 className="h-3 w-3" /> 完成</Badge>}
                    </div>
                  </motion.div>
                ))}
                {items.length === 0 && <div className="rounded-xl border border-dashed border-white/10 p-5 text-center text-[12px] text-dim">{loaded ? "無任務" : "載入中…"}</div>}
              </div>
            </GlassPanel>
          );
        })}
      </div>
    </motion.div>
  );
}
