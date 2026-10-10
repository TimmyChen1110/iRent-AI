"use client";
/* eslint-disable @next/next/no-img-element -- 後端提供的證據／完工照 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { X, AlertTriangle, SprayCan, CheckCircle2, XCircle, Camera, Car, Play, RotateCcw, Bell, Undo2, ScanSearch } from "lucide-react";
import { api } from "@/lib/ops/api";
import type { TaskDetail, TaskAction } from "@/lib/ops/types";
import { fmt } from "@/lib/ops/time";
import { STATUS_TXT, zhStatus } from "@/lib/ops/labels";
import { useOps } from "@/store/OpsStore";
import { useAuth } from "@/store/AuthStore";
import { Button } from "@/components/ui/Button";
import { PriorityBadge, Badge } from "@/components/ui/Badge";
import { ConfidenceBar } from "@/components/ui/ConfidenceBar";
import { PRIORITY_MAP } from "@/lib/ops/adapters";
import { cn, pct } from "@/lib/utils";

/**
 * 右側抽屜：
 *  - 案件模式（drawerIncidentId）：AI 判定 + 借還照證據 + 人工裁決（confirm / reject / retake）。
 *  - 任務模式（drawerTaskId）：任務詳情、負責人、動作、通知文案、完工照、處理歷程、備註。
 */
export function TaskDrawer() {
  const ops = useOps();
  const { drawerIncidentId, drawerTaskId, closeDrawer } = ops;
  const open = Boolean(drawerIncidentId || drawerTaskId);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeDrawer();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeDrawer]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div key="backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={closeDrawer} className="fixed inset-0 z-[60] bg-black/50 backdrop-blur-[2px]" />
          <motion.aside key="drawer" initial={{ x: 40, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 40, opacity: 0 }} transition={{ type: "spring", stiffness: 300, damping: 32 }} className="glass-strong fixed inset-y-3 right-3 z-[61] flex w-[520px] max-w-[calc(100vw-24px)] flex-col overflow-hidden rounded-2xl">
            {drawerTaskId ? <TaskPane taskId={drawerTaskId} onClose={closeDrawer} /> : drawerIncidentId ? <CasePane caseId={drawerIncidentId} onClose={closeDrawer} /> : null}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

/* ------------------------------- 案件裁決 ------------------------------- */

function CasePane({ caseId, onClose }: { caseId: string; onClose: () => void }) {
  const { cases, decideCase, undoCase, openTask, getVehicle } = useOps();
  const c = cases.find((x) => x.case_id === caseId);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [hot, setHot] = useState<number | null>(null);
  if (!c) return <Empty onClose={onClose} text="找不到案件（可能已被重置）" />;
  const damage = c.mode === "pair";
  const vehicle = getVehicle(c.car);
  const act = async (d: "confirm" | "reject" | "retake") => {
    setBusy(true);
    try { await decideCase(c.case_id, d, note || undefined); if (d !== "confirm") onClose(); } catch { /* toast shown */ } finally { setBusy(false); }
  };
  const task = c.tasks.find((t) => t.status !== "cancelled");

  return (
    <>
      <Head onClose={onClose} label="AI 案件" title={c.case_id} sub={<><Car className="h-3.5 w-3.5" />{c.car} · {c.angle}{vehicle && <Link href={`/fleet?car=${encodeURIComponent(c.car)}`} onClick={onClose} className="text-sky-300 hover:underline">車輛管理</Link>}</>} />
      <div className="flex-1 overflow-y-auto p-5">
        <div className={cn("rounded-xl border p-4", damage ? "border-rose-400/15 bg-rose-400/[0.05]" : "border-amber-400/15 bg-amber-400/[0.05]")}>
          <div className="flex items-center gap-2">
            <span className={cn("grid h-8 w-8 place-items-center rounded-lg", damage ? "bg-rose-400/15 text-rose-300" : "bg-amber-400/15 text-amber-300", c.review_status === "unreviewed" && "warning-ring")}>{damage ? <AlertTriangle className="h-4 w-4" /> : <SprayCan className="h-4 w-4" />}</span>
            <div><div className="label-xs">AI 判定</div><div className="text-[14px] font-semibold text-white/95">{damage ? (c.ai_found ? "發現新增車損" : "未發現新增車損") : `車內「${c.cleanliness}」`}{c.kind ? ` · ${c.kind}` : ""}</div></div>
            <PriorityBadge priority={PRIORITY_MAP[c.ai_level]} className="ml-auto" />
          </div>
          <div className="mt-3"><ConfidenceBar value={c.ai_conf ?? 0} label="AI 信心度" /></div>
          <div className="mt-3 space-y-1.5">
            {damage ? c.damages.map((d, i) => (
              <div key={i} onMouseEnter={() => setHot(i)} onMouseLeave={() => setHot(null)} className="rounded-lg bg-white/[0.04] px-2.5 py-2 text-[12px]">
                <div className="flex items-center gap-2 text-white/90"><span className="grid h-4.5 w-4.5 place-items-center rounded-full bg-rose-400/20 text-[10px] font-semibold text-rose-200">{i + 1}</span>{d.location} · {d.type}{d.severity && <Badge tone={d.severity === "high" ? "danger" : "neutral"}>{d.severity}</Badge>}{typeof d.confidence === "number" && <span className="ml-auto tabular text-white/55">{pct(d.confidence)}</span>}</div>
                {d.reasoning && <div className="mt-1 text-muted">{d.reasoning}</div>}
              </div>
            )) : (
              <div className="rounded-lg bg-white/[0.04] px-2.5 py-2 text-[12px] text-white/85">
                {c.issues.length ? `AI 盤點問題：${c.issues.join("、")}` : "未列出具體問題"}{typeof c.score === "number" && <span className="ml-2 text-white/55">整潔分數 {c.score}/100</span>}
              </div>
            )}
          </div>
          {c.pricing && typeof c.pricing === "object" && "estimate" in c.pricing && (
            <div className="mt-3 text-[11.5px] text-muted">估價參考：{String((c.pricing as Record<string, unknown>).estimate)}</div>
          )}
        </div>

        <div className="mt-4">
          <div className="label-xs mb-2">證據照片 · AI 標註框</div>
          <div className={cn("grid gap-2", damage ? "grid-cols-2" : "grid-cols-1")}>
            {damage ? <><Photo src={c.photos.pickup} label="借車基準照" /><Photo src={c.photos.return} label="還車照（AI 證據）" boxes={c.boxes} hot={hot} /></> : <Photo src={c.photos.photo} label="還車車內照（AI 證據）" boxes={c.boxes} hot={hot} />}
          </div>
        </div>

        <div className="mt-5">
          <div className="label-xs mb-2">人工裁決</div>
          {c.review_status === "unreviewed" ? (
            <div className="space-y-2">
              <input className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-[12.5px] text-white/90 placeholder:text-white/30 focus:outline-none" placeholder="稽核備註（選填，會存入訓練標籤）" value={note} onChange={(e) => setNote(e.target.value)} />
              <Button block size="lg" variant="danger" icon={<CheckCircle2 />} disabled={busy} onClick={() => act("confirm")}>確認{damage ? "車損" : "髒污"}並建立{damage ? "維修" : "清潔"}任務</Button>
              <Button block size="lg" variant="secondary" icon={<XCircle />} disabled={busy} onClick={() => act("reject")}>駁回 AI 判定（誤判）</Button>
              <Button block size="lg" variant="ghost" icon={<Camera />} disabled={busy} onClick={() => act("retake")}>要求補件</Button>
              <p className="pt-1 text-center text-[11.5px] text-dim">確認後由後端自動建單、依類型指派並發送通知；每次裁決都會存成訓練標籤。</p>
            </div>
          ) : (
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3.5">
              <div className="flex items-center justify-between text-[13px]">
                <span className="text-white/85">{c.decision?.decision === "confirm" ? "已確認異常" : c.decision?.decision === "reject" ? "已駁回 AI 判定" : "已要求補件"}</span>
                <span className="font-mono text-[11px] text-white/45">{fmt(c.decision?.decided_at)}</span>
              </div>
              {task && <Button size="sm" variant="primary" block className="mt-3" onClick={() => openTask(task.id)}>開啟任務 #{task.id} · {STATUS_TXT[task.status]}</Button>}
              <Button size="sm" variant="ghost" block className="mt-2" icon={<Undo2 />} disabled={busy} onClick={async () => { setBusy(true); try { await undoCase(c.case_id); } finally { setBusy(false); } }}>復原裁決（取消待處理任務）</Button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

/* ------------------------------- 任務詳情 ------------------------------- */

const ACTION_VIEW: Array<{ action: TaskAction; label: string; variant: "primary" | "success" | "secondary" | "ghost"; icon: React.ReactNode }> = [
  { action: "start", label: "開始處理", variant: "primary", icon: <Play /> },
  { action: "complete", label: "標記完成", variant: "success", icon: <CheckCircle2 /> },
  { action: "reopen", label: "重新開啟", variant: "secondary", icon: <RotateCcw /> },
  { action: "return_to_pending", label: "退回待處理", variant: "ghost", icon: <Undo2 /> },
];

function TaskPane({ taskId, onClose }: { taskId: number; onClose: () => void }) {
  const { people, tick, refresh, pushToast } = useOps();
  const { user } = useAuth();
  const [d, setD] = useState<TaskDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [hot, setHot] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try { const r = await api.task(taskId); setD(r); setErr(null); } catch (e) { setErr((e as Error).message); }
  }, [taskId]);
  useEffect(() => { const id = setTimeout(load, 0); return () => clearTimeout(id); }, [load, tick]);

  const act = async (fn: () => Promise<TaskDetail>, ok?: string) => {
    setBusy(true);
    try { const r = await fn(); setD(r); refresh(); if (ok) pushToast({ tone: "success", title: ok }); }
    catch (e) { pushToast({ tone: "warning", title: (e as Error).message || "操作失敗" }); load(); }
    finally { setBusy(false); }
  };
  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; e.target.value = "";
    if (!f) return;
    setBusy(true);
    try { await api.uploadPhoto(taskId, f); await load(); refresh(); pushToast({ tone: "success", title: "完工照已上傳" }); }
    catch (err) { pushToast({ tone: "warning", title: (err as Error).message }); } finally { setBusy(false); }
  };

  if (err) return <Empty onClose={onClose} text={err} />;
  if (!d) return <Empty onClose={onClose} text="載入中…" />;
  const t = d.task;
  const damage = d.case.mode !== "interior";
  const canUpload = t.allowed_actions.includes("upload_photo");

  return (
    <>
      <Head onClose={onClose} label={`任務 #${t.id}`} title={t.title} sub={<><Car className="h-3.5 w-3.5" />{t.car} · {t.task_type === "cleaning" ? "清潔" : "維修"}{t.car && <Link href={`/fleet?car=${encodeURIComponent(t.car)}`} onClick={onClose} className="text-sky-300 hover:underline">車輛管理</Link>}</>} />
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={onFile} />
      <div className="flex-1 space-y-5 overflow-y-auto p-5">
        <section className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={t.status === "completed" ? "success" : t.status === "in_progress" ? "info" : t.status === "cancelled" ? "neutral" : "danger"}>{STATUS_TXT[t.status]}</Badge>
            <PriorityBadge priority={PRIORITY_MAP[t.priority || "P2"]} />
            {t.is_demo && <Badge tone="info">DEMO</Badge>}
            <span className="flex-1" />
            <Badge tone={t.notification_status === "sent" ? "success" : t.notification_status === "failed" ? "danger" : "neutral"}><Bell className="h-3 w-3" />{{ not_sent: "推播未發送", sent: "推播已送出", failed: "推播失敗", skipped: "管道未設定" }[t.notification_status]}</Badge>
            {t.notification_status === "failed" && <Button size="sm" disabled={busy} onClick={() => act(() => api.retryNotify(taskId), "已重新發送")}>重發</Button>}
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5 text-[12.5px]">
            <div><dt className="label-xs">負責人</dt><dd className="mt-1">
              <select className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-2 py-1 text-[12.5px] text-white/90" value={t.assignee_id ?? ""} disabled={busy || !t.allowed_actions.includes("assign")} onChange={(e) => act(() => api.patchTask(taskId, { action: "assign", assignee_id: e.target.value ? Number(e.target.value) : null }), "已更新負責人")}>
                <option value="">未指派</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select></dd></div>
            <div><dt className="label-xs">SLA</dt><dd className="mt-1 text-white/90">{t.sla_minutes} 分鐘內開工 {t.overdue && <Badge tone="danger">逾時</Badge>}</dd></div>
            <div><dt className="label-xs">建立</dt><dd className="mt-1 font-mono text-white/80">{fmt(t.created_at)}</dd></div>
            <div><dt className="label-xs">開工期限</dt><dd className="mt-1 font-mono text-white/80">{fmt(t.sla_due_at)}</dd></div>
          </dl>
          <div className="mt-3 flex flex-wrap gap-2">
            {ACTION_VIEW.filter((x) => t.allowed_actions.includes(x.action)).map((x) => <Button key={x.action} size="sm" variant={x.variant} icon={x.icon} disabled={busy} onClick={() => act(() => api.patchTask(taskId, { action: x.action }))}>{x.label}</Button>)}
            {canUpload && <Button size="sm" variant="secondary" icon={<Camera />} disabled={busy} onClick={() => fileRef.current?.click()}>上傳完工照</Button>}
            {!t.completion_requirements.satisfied && <span className="self-center text-[11.5px] text-amber-300">{t.completion_requirements.message}</span>}
          </div>
        </section>

        <section>
          <div className="label-xs mb-2 flex items-center gap-1.5"><ScanSearch className="h-3 w-3" />證據 · AI 判定 → 人工裁決</div>
          <div className="mb-2 grid grid-cols-2 gap-2 text-[12px]">
            <div className="rounded-lg bg-white/[0.03] px-3 py-2"><div className="label-xs">AI 判定</div><div className="mt-0.5 font-medium text-white/90">{d.case.mode === "interior" ? String(d.case.assessment?.level || "無法確認") : d.case.assessment?.new_damage_found ? "發現新增車損" : "未發現新增車損"}</div><div className="text-muted">{d.case.ai_level || "未分級"}{typeof d.case.ai_conf === "number" ? ` · 信心 ${pct(d.case.ai_conf)}` : ""}</div></div>
            <div className="rounded-lg bg-white/[0.03] px-3 py-2"><div className="label-xs">人工裁決</div><div className="mt-0.5 font-medium text-white/90">{d.case.decision ? ({ confirm: "確認異常並建立任務", reject: "駁回 AI 判定", retake: "要求補件" } as Record<string, string>)[d.case.decision.decision] || d.case.decision.decision : "尚未裁決"}</div><div className="text-muted">{d.case.decision ? fmt(d.case.decision.decided_at) : "—"}</div></div>
          </div>
          <div className={cn("grid gap-2", damage ? "grid-cols-2" : "grid-cols-1")}>
            {damage ? <><Photo src={d.case.photos.pickup} label="借車基準照" /><Photo src={d.case.photos.return} label="還車照（AI 證據）" boxes={d.case.boxes} hot={hot} /></> : <Photo src={d.case.photos.photo} label="還車車內照（AI 證據）" boxes={d.case.boxes} hot={hot} />}
          </div>
          {d.case.boxes.length > 0 && <div className="mt-2 space-y-1">{d.case.boxes.map((b, i) => <div key={i} onMouseEnter={() => setHot(i)} onMouseLeave={() => setHot(null)} className="flex items-center gap-2 rounded-md bg-white/[0.03] px-2.5 py-1.5 text-[12px] text-white/85"><span className="grid h-4.5 w-4.5 place-items-center rounded-full bg-rose-400/20 text-[10px] font-semibold text-rose-200">{i + 1}</span>{b.label}{b.description && <span className="truncate text-muted">· {b.description}</span>}</div>)}</div>}
        </section>

        <section><div className="label-xs mb-2">工作內容</div><pre className="whitespace-pre-wrap rounded-lg bg-white/[0.03] p-3 font-sans text-[12.5px] leading-relaxed text-white/80">{t.description || "—"}</pre></section>

        <section>
          <div className="label-xs mb-2 flex items-center justify-between"><span className="flex items-center gap-1.5"><Camera className="h-3 w-3" />完工照</span>{t.status === "completed" && d.photos.length > 0 ? <Badge tone="success">✓ 已成為基準照</Badge> : d.photos.length > 0 ? <Badge tone="info">完成任務後成為基準照</Badge> : <Badge tone="neutral">尚無完工照</Badge>}</div>
          {d.photos.length > 0 ? <div className="grid grid-cols-3 gap-2">{d.photos.map((p) => <div key={p.id} className="overflow-hidden rounded-lg border border-white/[0.06]"><img src={p.url} alt={p.filename} className="aspect-[4/3] w-full object-cover" /><div className="px-2 py-1 text-[10.5px] text-muted">{p.by || "—"} · {fmt(p.at)}</div></div>)}</div>
            : <div className="rounded-lg border border-dashed border-white/10 p-3 text-[12px] text-muted">{t.completion_requirements.photo_required ? t.completion_requirements.message : "此類任務不強制完工照；仍可上傳作為下次借車基準照。"}</div>}
        </section>

        <section>
          <div className="label-xs mb-2">處理歷程</div>
          <ol className="space-y-2">
            {t.events.map((e, i) => (
              <li key={i} className="flex gap-3 text-[12px]">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-white/30" />
                <div className="min-w-0 flex-1"><div className="flex items-center justify-between gap-2"><span className="text-white/85">{zhStatus(e.detail || e.event)}</span><span className="shrink-0 font-mono text-[10.5px] text-white/40">{fmt(e.at)}</span></div>{e.actor_name && <div className="text-[11px] text-dim">{e.actor_name} · {e.actor_role}</div>}</div>
              </li>
            ))}
          </ol>
          <div className="mt-3 flex gap-2">
            <input className="flex-1 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-[12.5px] text-white/90 placeholder:text-white/30 focus:outline-none" placeholder={`以 ${user?.name ?? "—"} 身分加入備註`} value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && note.trim()) { act(() => api.patchTask(taskId, { note }), "備註已加入歷程"); setNote(""); } }} />
            <Button size="sm" disabled={busy || !note.trim()} onClick={() => { act(() => api.patchTask(taskId, { note }), "備註已加入歷程"); setNote(""); }}>加入</Button>
          </div>
        </section>
      </div>
    </>
  );
}

/* ------------------------------- 共用 ------------------------------- */

function Head({ onClose, label, title, sub }: { onClose: () => void; label: string; title: string; sub: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between border-b border-white/[0.06] p-5">
      <div className="min-w-0">
        <div className="label-xs">{label}</div>
        <div className="mt-1 truncate text-[15px] font-semibold text-white/95">{title}</div>
        <div className="mt-1 flex items-center gap-2 text-[12px] text-muted">{sub}</div>
      </div>
      <button onClick={onClose} className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-white/50 hover:bg-white/[0.06] hover:text-white"><X className="h-4 w-4" /></button>
    </div>
  );
}

function Empty({ onClose, text }: { onClose: () => void; text: string }) {
  return <><Head onClose={onClose} label="" title={text} sub={null} /><div className="p-5 text-[12.5px] text-muted">{text}</div></>;
}

/** 照片 + AI 標註框。box_2d = [y0, x0, y1, x1]，0–1000 正規化（與監理台同格式）。 */
function Photo({ src, label, boxes = [], hot }: { src: string | null | undefined; label: string; boxes?: Array<{ box_2d: number[]; label: string }>; hot?: number | null }) {
  if (!src) return <div className="grid aspect-[4/3] place-items-center rounded-lg border border-dashed border-white/10 text-[11.5px] text-white/35">無照片</div>;
  return (
    <div className="always-dark relative overflow-hidden rounded-lg border border-white/[0.06] bg-black/40">
      <img src={src} alt={label} className="aspect-[4/3] w-full object-cover" loading="lazy" />
      <span className="absolute left-2 top-2 rounded-md bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold text-white/85">{label}</span>
      {boxes.map((b, i) => { const [y0, x0, y1, x1] = b.box_2d; return <div key={i} className="pointer-events-none absolute rounded border-2 border-rose-400 transition-opacity" style={{ left: `${x0 / 10}%`, top: `${y0 / 10}%`, width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%`, opacity: hot == null || hot === i ? 1 : 0.35 }}><i className="absolute -left-px -top-px rounded-br bg-rose-500 px-1 text-[9px] font-bold not-italic text-white">{i + 1}</i></div>; })}
    </div>
  );
}
