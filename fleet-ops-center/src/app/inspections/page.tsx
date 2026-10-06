"use client";
/* eslint-disable @next/next/no-img-element -- evidence photos served by the backend */

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, CheckCircle2, AlertTriangle, Loader2, ShieldCheck, Smartphone, Car, Armchair, ClipboardList, Cpu } from "lucide-react";
import { api } from "@/lib/ops/api";
import type { ComparisonResult, InspectionDetail, InspectionIncidentRef, InspectionResult, InspectionRow } from "@/lib/ops/types";
import { useOps } from "@/store/OpsStore";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { fadeUp, stagger } from "@/components/ui/motion";
import { fmt } from "@/lib/ops/time";
import { cn, pct } from "@/lib/utils";

/**
 * 檢查紀錄（Inspection History）：iOS App 每一筆租約的取車／還車檢查、Before/After 照片、AI 比對結果與衍生案件。
 * 「沒有異常」也是稽核紀錄；案件本身仍由事件中心／數位分身裁決（同一套 /api/ops/cases）。
 */
const RESULT_META: Record<InspectionResult, { label: string; tone: "danger" | "success" | "info" | "neutral" | "warning"; icon: React.ReactNode }> = {
  ISSUES: { label: "有異常", tone: "danger", icon: <AlertTriangle className="h-3 w-3" /> },
  PASSED: { label: "通過", tone: "success", icon: <CheckCircle2 className="h-3 w-3" /> },
  ANALYZING: { label: "分析中", tone: "info", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
  PENDING: { label: "拍攝中", tone: "neutral", icon: <Smartphone className="h-3 w-3" /> },
  FAILED: { label: "待人工複核", tone: "warning", icon: <AlertTriangle className="h-3 w-3" /> },
};

const CMP_META: Record<ComparisonResult, { label: string; tone: "danger" | "success" | "info" | "neutral" | "warning" }> = {
  NEW_DAMAGE: { label: "新增車損", tone: "danger" },
  EXISTING_DAMAGE: { label: "既有損傷（不開案）", tone: "info" },
  NO_NEW_DAMAGE: { label: "無新增車損", tone: "success" },
  UNCOMPARABLE: { label: "無法比對", tone: "warning" },
  NO_BASELINE: { label: "缺取車基準", tone: "warning" },
  CLEANING_REQUIRED: { label: "需要清潔", tone: "danger" },
  CLEAN: { label: "整潔可接受", tone: "success" },
  UNREADABLE: { label: "無法判讀", tone: "warning" },
};

const REVIEW_LABEL: Record<string, string> = { unreviewed: "待裁決", confirmed_open: "已確認 · 整備中", confirmed_done: "已確認 · 完成", rejected: "誤判", retake: "待補件", normal: "正常" };

export default function InspectionsPage() {
  return <Suspense><InspectionsView /></Suspense>;
}

function InspectionsView() {
  const { tick, loaded } = useOps();
  const params = useSearchParams();
  const selectedId = params.get("rental");
  const [rows, setRows] = useState<InspectionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 跟著 OpsStore 的 5 秒輪詢／SSE 一起刷新
  useEffect(() => {
    let alive = true;
    api.inspections().then((r) => { if (alive) { setRows(r.inspections); setError(null); } }).catch((e) => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [tick]);

  if (selectedId) return <InspectionDetailView rentalId={selectedId} />;

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp} className="flex items-end justify-between">
        <div>
          <h2 className="text-[22px] font-semibold tracking-tight text-white">檢查紀錄</h2>
          <p className="mt-1 text-[13px] text-muted">iOS App 每一筆租約的取車基準與還車檢查。AI 只比對「取車 vs 還車」的變化；正常通過的紀錄同樣保留以供稽核。</p>
        </div>
        <Badge tone="info"><Smartphone className="h-3 w-3" /> 來源：iRent iOS App · POST /v1/mobile-inspections/photos</Badge>
      </motion.div>

      <GlassPanel variants={fadeUp} padded={false} className="overflow-hidden">
        <table className="w-full text-left text-[13px]">
          <thead>
            <tr className="border-b border-white/[0.06] text-[10.5px] uppercase tracking-wider text-white/40">
              <th className="px-5 py-3 font-medium">租約</th><th className="px-4 py-3 font-medium">車輛</th><th className="px-4 py-3 font-medium">取車</th><th className="px-4 py-3 font-medium">還車</th><th className="px-4 py-3 font-medium">照片</th><th className="px-4 py-3 font-medium">檢查結果</th><th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((r, i) => {
              const m = RESULT_META[r.result];
              return (
                <motion.tr key={r.rental_id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.03, 0.3) }} className="border-b border-white/[0.04] transition hover:bg-white/[0.03]">
                  <td className="px-5 py-3"><Link href={`/inspections?rental=${encodeURIComponent(r.rental_id)}`} className="font-mono font-medium text-white/90 hover:text-sky-200">{r.rental_id}</Link>{r.source === "demo_seed" && <span className="ml-2 text-[10px] text-amber-300/80">示範固定資料</span>}</td>
                  <td className="px-4 py-3"><span className="font-mono text-white/90">{r.plate}</span><span className="ml-2 text-white/45">{r.vehicle_model || ""}</span></td>
                  <td className="px-4 py-3 text-white/75">{r.pickup_at ? fmt(r.pickup_at).slice(11) : <span className="text-white/35">{r.pickup.exterior.received}/4 · {r.pickup.interior.received}/1</span>}</td>
                  <td className="px-4 py-3 text-white/75">{r.return_at ? fmt(r.return_at).slice(11) : <span className="text-white/35">{r.return.exterior.received}/4 · {r.return.interior.received}/1</span>}</td>
                  <td className="px-4 py-3 text-white/60">{r.pickup.received.length + r.return.received.length} / 10</td>
                  <td className="px-4 py-3"><Badge tone={m.tone}>{m.icon} {r.result === "ISSUES" ? `${r.issue_count} 件異常` : m.label}</Badge></td>
                  <td className="px-4 py-3 text-right"><Link href={`/inspections?rental=${encodeURIComponent(r.rental_id)}`} className="text-[12px] text-sky-300 hover:underline">查看</Link></td>
                </motion.tr>
              );
            })}
          </tbody>
        </table>
        {rows && rows.length === 0 && <div className="p-10 text-center text-[13px] text-muted">還沒有任何 App 檢查紀錄。用 iOS App 完成一次取車拍攝後就會出現在這裡。</div>}
        {!rows && !error && <div className="p-10 text-center text-[13px] text-muted">{loaded ? "載入檢查紀錄…" : "連線中…"}</div>}
        {error && <div className="p-10 text-center text-[13px] text-rose-300">無法取得檢查紀錄：{error}</div>}
      </GlassPanel>
    </motion.div>
  );
}

function InspectionDetailView({ rentalId }: { rentalId: string }) {
  const { tick, openIncident } = useOps();
  const [detail, setDetail] = useState<InspectionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.inspection(rentalId).then((r) => { if (alive) { setDetail(r.inspection); setError(null); } }).catch((e) => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [rentalId, tick]);

  const exterior = useMemo(() => detail?.comparisons.filter((c) => c.category === "exterior") ?? [], [detail]);
  const interior = useMemo(() => detail?.comparisons.find((c) => c.category === "interior") ?? null, [detail]);

  if (error) return <div className="py-20 text-center text-rose-300">{error} <Link href="/inspections" className="ml-2 text-sky-300 hover:underline">返回列表</Link></div>;
  if (!detail) return <div className="py-20 text-center text-muted">載入 {rentalId}…</div>;
  const m = RESULT_META[detail.result];
  const passed = detail.result === "PASSED";

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp} className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href="/inspections" className="grid h-9 w-9 place-items-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-white/70 hover:text-white"><ArrowLeft className="h-4 w-4" /></Link>
          <div>
            <h2 className="font-mono text-[22px] font-semibold tracking-tight text-white">{detail.rental_id}</h2>
            <p className="mt-0.5 text-[13px] text-muted">{detail.vehicle_model || "共享車輛"} · <span className="font-mono">{detail.plate}</span> · 取車 {detail.pickup_at ? fmt(detail.pickup_at) : "—"} · 還車 {detail.return_at ? fmt(detail.return_at) : "—"}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={m.tone}>{m.icon} {m.label}</Badge>
          <Link href={`/vehicle?car=${encodeURIComponent(detail.plate)}`}><Button variant="secondary" icon={<Car />}>開啟數位分身</Button></Link>
        </div>
      </motion.div>

      {/* 結果摘要 */}
      <motion.div variants={fadeUp}>
        <GlassPanel className={cn(passed ? "border-emerald-400/20" : detail.result === "ISSUES" ? "border-rose-400/20" : "")}>
          {passed ? (
            <div className="flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-emerald-400/12 text-emerald-300"><ShieldCheck className="h-5 w-5" /></span>
              <div>
                <div className="text-[16px] font-semibold text-emerald-100">Inspection Passed</div>
                <div className="mt-1 text-[13px] text-white/75">No new damage detected · Interior condition acceptable</div>
                <div className="mt-0.5 text-[12px] text-muted">未建立任何案件；取車與還車照片仍完整保留於下方供稽核。</div>
              </div>
            </div>
          ) : detail.result === "ISSUES" ? (
            <div>
              <div className="flex items-center gap-2 text-[16px] font-semibold text-rose-100"><AlertTriangle className="h-4 w-4 text-rose-300" />AI 偵測到 {detail.issue_count} 件異常</div>
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                {detail.incidents.map((inc) => <IncidentRow key={inc.case_id} inc={inc} onOpen={() => openIncident(inc.case_id)} />)}
              </div>
            </div>
          ) : (
            <div className="text-[13px] text-white/80">{detail.result === "ANALYZING" ? "還車照片已齊，後端 AI 正在比對取車與還車紀錄…" : detail.result === "FAILED" ? `AI 比對未完成（${detail.analysis.error || "未知原因"}），紀錄已保存待人工複核。` : `使用者拍攝中：取車 ${detail.pickup.received.length}/5、還車 ${detail.return.received.length}/5。`}</div>
          )}
          <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-muted">
            <Badge tone="neutral"><Cpu className="h-3 w-3" /> 分析來源：{detail.analysis.source === "demo_fixture" ? "deterministic demo fixture" : detail.analysis.source === "pipeline" ? "Gemini 級聯 pipeline" : "—"}</Badge>
            <Badge tone="neutral">裝置端驗證：{detail.comparisons.find((c) => c.return_photo)?.return_photo?.validation_mode === "demo" ? "Demo 劇本" : detail.source === "demo_seed" ? "示範固定照片" : "Core ML（PlateDetector / PlateOCR / ViewClassifier）"}</Badge>
            {detail.baseline && <Badge tone="neutral">取車基準：既有損傷 {detail.baseline.existing_damage.length} 處</Badge>}
          </div>
        </GlassPanel>
      </motion.div>

      {/* 取車 / 還車 Before-After */}
      <motion.div variants={fadeUp}>
        <GlassPanel>
          <SectionHeader title="車外 Before / After" subtitle="取車基準照 vs 還車照，依角度配對後送入車損比對" action={<Badge tone="info"><Car className="h-3 w-3" /> 4 角度</Badge>} />
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {exterior.map((c) => (
              <div key={c.angle} className={cn("rounded-xl border p-3", c.result === "NEW_DAMAGE" ? "border-rose-400/25 bg-rose-400/[0.04]" : "border-white/[0.06] bg-white/[0.02]")}>
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-[13px] font-semibold text-white/90">{c.angle} <span className="font-mono text-[10.5px] text-white/40">{c.angle_code}</span></span>
                  {c.result ? <Badge tone={CMP_META[c.result].tone}>{CMP_META[c.result].label}</Badge> : <Badge tone="neutral">未比對</Badge>}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Photo label="取車" url={c.pickup_photo?.url ?? null} />
                  <Photo label="還車" url={c.return_photo?.url ?? null} accent={c.result === "NEW_DAMAGE"} boxes={c.result === "NEW_DAMAGE" ? c.boxes : []} />
                </div>
                {c.findings.length > 0 && (
                  <ul className="mt-2 space-y-1 text-[11.5px]">
                    {c.findings.map((f, i) => (
                      <li key={i} className="flex items-center justify-between gap-2 text-white/80">
                        <span><span className={cn("mr-1.5 inline-block h-1.5 w-1.5 rounded-full", f.status === "NEW_DAMAGE" ? "bg-rose-400" : "bg-sky-400")} />{f.label}{f.type ? ` · ${f.type}` : ""}</span>
                        <span className="tabular text-white/55">{f.confidence != null ? pct(f.confidence) : f.status === "EXISTING_DAMAGE" ? "既有" : ""}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {c.case_id && <button onClick={() => openIncident(c.case_id!)} className="mt-2 text-[11.5px] text-sky-300 hover:underline">案件 {c.case_id} →</button>}
                <PhotoMeta photo={c.return_photo ?? c.pickup_photo} />
              </div>
            ))}
          </div>
        </GlassPanel>
      </motion.div>

      <motion.div variants={fadeUp} className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <GlassPanel>
          <SectionHeader title="車內整潔分析" subtitle="還車車內照：除損傷比對外另跑 Cleanliness Analysis" action={<Badge tone="info"><Armchair className="h-3 w-3" /> 1 張</Badge>} />
          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_260px]">
            <div className="grid grid-cols-2 gap-2">
              <Photo label="取車" url={interior?.pickup_photo?.url ?? null} />
              <Photo label="還車" url={interior?.return_photo?.url ?? null} accent={detail.interior?.result === "CLEANING_REQUIRED"} boxes={detail.interior?.result === "CLEANING_REQUIRED" ? interior?.boxes ?? [] : []} />
            </div>
            <div>
              {detail.interior ? (
                <>
                  <div className="flex items-center justify-between"><span className="label-xs">結果</span><Badge tone={CMP_META[detail.interior.result].tone}>{CMP_META[detail.interior.result].label}</Badge></div>
                  <div className="mt-2 flex items-center justify-between text-[13px]"><span className="label-xs">cleanliness</span><span className="font-medium text-white/90">{detail.interior.cleanliness ?? "—"}</span></div>
                  <div className="mt-1 flex items-center justify-between text-[13px]"><span className="label-xs">confidence</span><span className="tabular font-medium text-white/90">{detail.interior.confidence != null ? pct(detail.interior.confidence) : "—"}</span></div>
                  {detail.interior.findings.length > 0 && (
                    <div className="mt-3">
                      <div className="label-xs mb-1.5">findings</div>
                      <div className="flex flex-wrap gap-1.5">{detail.interior.findings.map((f, i) => <Badge key={i} tone="warning">{f.label}</Badge>)}</div>
                    </div>
                  )}
                  <p className="mt-3 text-[12px] text-muted">{detail.interior.summary}</p>
                </>
              ) : <p className="text-[12.5px] text-muted">尚未分析。</p>}
            </div>
          </div>
        </GlassPanel>

        <GlassPanel>
          <SectionHeader title="取車基準（Pickup Baseline）" subtitle="既有車損在此登記，還車時不重複判定" />
          {detail.baseline ? (
            <>
              <div className="text-[12px] text-muted">{detail.baseline.note}</div>
              {detail.baseline.existing_damage.length === 0 ? (
                <div className="mt-3 rounded-lg border border-dashed border-white/10 p-3 text-[12px] text-muted">取車時未登記既有損傷。</div>
              ) : (
                <ul className="mt-3 space-y-2">
                  {detail.baseline.existing_damage.map((d, i) => (
                    <li key={i} className="rounded-lg border border-sky-400/15 bg-sky-400/[0.05] p-3 text-[12.5px]">
                      <div className="flex items-center justify-between"><span className="font-medium text-white/90">{d.label} · {d.type}</span><span className="tabular text-white/60">{d.confidence != null ? pct(d.confidence) : ""}</span></div>
                      <div className="mt-0.5 text-[11px] text-muted">Status: EXISTING_DAMAGE · twin: {d.region}</div>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : <div className="text-[12.5px] text-muted">取車照片尚未齊全（{detail.pickup.received.length}/5）。</div>}
          <div className="mt-4 border-t border-white/[0.06] pt-3">
            <div className="label-xs mb-1.5">衍生案件</div>
            {detail.incidents.length === 0 ? <div className="text-[12px] text-muted">無（正常 inspection 不建立 Incident）。</div> : detail.incidents.map((inc) => (
              <button key={inc.case_id} onClick={() => openIncident(inc.case_id)} className="mb-1.5 flex w-full items-center justify-between rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-left text-[12px] hover:border-white/15">
                <span className="font-mono text-white/85">{inc.case_id}</span>
                <span className="text-white/55">{REVIEW_LABEL[inc.review_status ?? "unreviewed"]}{inc.tasks?.length ? ` · 任務 #${inc.tasks[0].id}` : ""}</span>
              </button>
            ))}
          </div>
        </GlassPanel>
      </motion.div>
      <AnimatePresence />
    </motion.div>
  );
}

function IncidentRow({ inc, onOpen }: { inc: InspectionDetail["incidents"][number]; onOpen: () => void }) {
  const damage = inc.kind === "damage";
  return (
    <button onClick={onOpen} className={cn("flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition", damage ? "border-rose-400/20 bg-rose-400/[0.06] hover:bg-rose-400/[0.1]" : "border-amber-400/20 bg-amber-400/[0.06] hover:bg-amber-400/[0.1]")}>
      <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-lg", damage ? "bg-rose-400/15 text-rose-300" : "bg-amber-400/15 text-amber-300")}>{damage ? <AlertTriangle className="h-4 w-4" /> : <Armchair className="h-4 w-4" />}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-semibold text-white/95">{damage ? "Damage" : "Cleaning"} · {inc.label}{inc.damage_type ? ` · ${inc.damage_type}` : ""} <span className="tabular font-normal text-white/60">{inc.confidence != null ? pct(inc.confidence) : ""}</span></span>
        <span className="block truncate text-[11px] text-white/55">{inc.case_id} · {REVIEW_LABEL[inc.review_status ?? "unreviewed"]}{inc.region ? ` · twin ${inc.region}` : ""}</span>
      </span>
      <ClipboardList className="h-3.5 w-3.5 text-white/40" />
    </button>
  );
}

function Photo({ label, url, accent, boxes = [] }: { label: string; url: string | null; accent?: boolean; boxes?: Array<{ box_2d: number[]; label: string }> }) {
  return (
    <div className="always-dark relative aspect-[4/3] overflow-hidden rounded-lg bg-black/40 ring-1 ring-white/[0.06]">
      {url ? <img src={url} alt={label} className="h-full w-full object-cover" draggable={false} /> : <div className="grid h-full w-full place-items-center text-[11px] text-white/35">無照片</div>}
      {boxes.map((b, i) => {
        const [y0, x0, y1, x1] = b.box_2d;
        return <span key={i} className="pointer-events-none absolute rounded border-2 border-rose-400/90" style={{ left: `${x0 / 10}%`, top: `${y0 / 10}%`, width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%` }} />;
      })}
      <span className={cn("pointer-events-none absolute left-1.5 top-1.5 rounded px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wider backdrop-blur", accent ? "bg-rose-500/80 text-white" : "bg-black/60 text-white/85")}>{label}</span>
    </div>
  );
}

function PhotoMeta({ photo }: { photo: InspectionDetail["comparisons"][number]["return_photo"] }) {
  if (!photo) return null;
  const v = photo.validation;
  return (
    <div className="mt-2 text-[10.5px] text-white/40">
      {photo.validation_mode === "seed" ? "示範固定照片" : `${photo.validation_mode === "demo" ? "Demo 劇本" : "Core ML"} ✓`}
      {v.plate_text ? ` · 車牌 ${v.plate_text}${v.plate_confidence != null ? ` ${pct(v.plate_confidence)}` : ""}` : ""}
      {v.view ? ` · 角度 ${v.view}${v.view_confidence != null ? ` ${pct(v.view_confidence)}` : ""}` : ""}
      {` · ${fmt(photo.captured_at).slice(11)}`}
    </div>
  );
}

export type { InspectionIncidentRef };
