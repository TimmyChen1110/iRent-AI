"use client";
/* eslint-disable @next/next/no-img-element -- 後端提供的證據／完工照 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Camera, Play, CheckCircle2, Hand, LogOut, Hexagon } from "lucide-react";
import { api } from "@/lib/ops/api";
import type { MyTask, TaskAction } from "@/lib/ops/types";
import { rel, slaState, syncClock } from "@/lib/ops/time";
import { useAuth } from "@/store/AuthStore";
import { useOps } from "@/store/OpsStore";
import { Button } from "@/components/ui/Button";
import { PriorityBadge, Badge } from "@/components/ui/Badge";
import { PRIORITY_MAP } from "@/lib/ops/adapters";
import { cn } from "@/lib/utils";

/** 站點整備人員手機版：登入身分 → 我的任務 → 接單 → 開工 → 拍完工照 → 完工。 */
export default function MobilePage() {
  const { user, logout } = useAuth();
  const { pushToast } = useOps();
  const [tasks, setTasks] = useState<MyTask[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [uploadFor, setUploadFor] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => { try { const r = await api.myTasks(); syncClock(r.server_time); setTasks(r.tasks); } catch { /* offline */ } }, []);
  useEffect(() => { const t = setTimeout(load, 0); const id = setInterval(load, 5000); return () => { clearTimeout(t); clearInterval(id); }; }, [load]);

  const run = async (t: MyTask, action: TaskAction) => {
    setBusy(t.id);
    try { await api.patchTask(t.id, { action }); await load(); pushToast({ tone: "success", title: action === "claim" ? `已接下 ${t.car}` : action === "complete" ? `${t.car} 完工` : `${t.car} 開工` }); }
    catch (e) { pushToast({ tone: "warning", title: (e as Error).message }); } finally { setBusy(null); }
  };
  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; e.target.value = "";
    if (!f || uploadFor == null) return;
    setBusy(uploadFor);
    try { await api.uploadPhoto(uploadFor, f); await load(); pushToast({ tone: "success", title: "完工照已上傳" }); } catch (err) { pushToast({ tone: "warning", title: (err as Error).message }); } finally { setBusy(null); }
  };

  return (
    <div className="mx-auto max-w-[560px] space-y-3 px-4 pb-12 pt-4">
      <input ref={fileRef} type="file" accept="image/*" capture="environment" hidden onChange={onFile} />
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-sky-400/30 to-violet-500/20 ring-1 ring-white/10"><Hexagon className="h-4.5 w-4.5 text-sky-200" /></div>
        <div className="leading-tight"><div className="text-[15px] font-semibold text-white/95">整備任務</div><div className="text-[11px] text-dim">站點人員手機版</div></div>
        <span className="flex-1" />
        <Button size="sm" variant="ghost" icon={<LogOut />} onClick={logout}>登出</Button>
      </div>
      <div className="glass flex items-center gap-2 rounded-xl px-3 py-2 text-[12.5px]"><span className="label-xs">登入身分</span><b className="text-white/90">{user?.name}</b><Badge tone="success">{user?.role === "station" ? "站點人員" : "管理者"}</Badge></div>
      <div className="text-[12px] text-muted">{tasks.filter((t) => t.mine).length} 件指派給我 · {tasks.filter((t) => !t.mine).length} 件未指派可接</div>
      <AnimatePresence initial={false}>
        {tasks.map((t) => {
          const canFinish = t.allowed_actions.includes("complete");
          const expanded = open === t.id;
          const sla = slaState(t);
          return (
            <motion.div key={t.id} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 60 }} className={cn("glass rounded-2xl p-4", t.priority === "P1" && "border-rose-400/20")}>
              <button onClick={() => setOpen(expanded ? null : t.id)} className="flex w-full flex-wrap items-center gap-2 text-left">
                <span className="font-mono text-[18px] font-semibold text-white/95">{t.car}</span>
                <Badge tone={t.task_type === "cleaning" ? "warning" : "info"}>{t.task_type === "cleaning" ? "清潔" : "維修"}</Badge>
                <PriorityBadge priority={PRIORITY_MAP[t.priority || "P2"]} />
                {!t.mine && <Badge tone="neutral">未指派</Badge>}
                {t.mine && t.status === "pending" && <Badge tone="success">已接單 · 待開工</Badge>}
                {t.status === "in_progress" && <Badge tone="info">處理中</Badge>}
                <span className="flex-1" />
                {t.status === "pending" && sla.kind !== "none" && <span className={cn("text-[11.5px]", sla.kind === "over" ? "text-rose-300" : sla.kind === "soon" ? "text-amber-300" : "text-white/55")}>{sla.label}</span>}
              </button>
              <div className="mt-1.5 text-[14px] font-medium text-white/90">{t.title}</div>
              <div className="mt-1 flex items-center gap-3 text-[11.5px] text-muted"><span>建立 {rel(t.created_at)}</span>{t.photos.length > 0 && <Badge tone="success"><Camera className="h-3 w-3" /> {t.photos.length}</Badge>}</div>
              {expanded && <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-white/[0.03] p-2.5 font-sans text-[12px] leading-relaxed text-white/75">{t.description}</pre>}
              {expanded && t.photos.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{t.photos.map((p) => <img key={p.id} src={p.url} alt="" className="h-14 w-[72px] rounded-md object-cover" />)}</div>}
              <div className="mt-3 flex gap-2">
                {t.allowed_actions.includes("claim") && <Button variant="primary" size="lg" block icon={<Hand />} disabled={busy === t.id} onClick={() => run(t, "claim")}>我來接單</Button>}
                {t.allowed_actions.includes("start") && <Button variant="primary" size="lg" block icon={<Play />} disabled={busy === t.id} onClick={() => run(t, "start")}>開工</Button>}
                {t.allowed_actions.includes("upload_photo") && <>
                  <Button size="lg" block icon={<Camera />} disabled={busy === t.id} onClick={() => { setUploadFor(t.id); fileRef.current?.click(); }}>拍完工照</Button>
                  <Button variant="success" size="lg" block icon={<CheckCircle2 />} disabled={busy === t.id || !canFinish} title={canFinish ? "" : t.completion_requirements.message || ""} onClick={() => run(t, "complete")}>完工</Button>
                </>}
              </div>
              {t.allowed_actions.includes("upload_photo") && !canFinish && <div className="mt-1.5 text-[11.5px] text-amber-300/90">{t.completion_requirements.message}，照片會成為下次借車的基準照</div>}
            </motion.div>
          );
        })}
      </AnimatePresence>
      {tasks.length === 0 && <div className="glass rounded-2xl p-8 text-center text-[13px] text-muted">目前沒有任務，新任務會自動出現</div>}
      <div className="text-center text-[11px] text-dim">操作會以 {user?.name} 身分寫入任務歷程{user?.role === "admin" && <> · <a href="/ops/" className="text-sky-300">管理者介面</a></>}</div>
    </div>
  );
}
