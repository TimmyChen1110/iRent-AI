"use client";
/* eslint-disable @next/next/no-img-element -- 照片由後端提供 */

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowLeft, ScanSearch } from "lucide-react";
import { useOps } from "@/store/OpsStore";
import { api } from "@/lib/ops/api";
import type { RentalDetail, RentalRow, StagePhotos } from "@/lib/ops/types";
import { CASE_REVIEW_LABEL, PLATE_META, REVIEW_META, SOURCE_META, duration } from "@/lib/ops/console";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { fadeUp, stagger } from "@/components/ui/motion";
import { fmt } from "@/lib/ops/time";
import { cn, pct } from "@/lib/utils";

export default function RentalsPage() { return <Suspense><RentalsView /></Suspense>; }

/** 租還車紀錄：每一筆 App 建立的租車 Session（/api/ops/rentals）。預設只列真實 App 租約，固定劇本需切換才顯示。 */
function RentalsView() {
  const { tick, loaded } = useOps();
  const params = useSearchParams();
  const sessionId = params.get("session");
  const [includeOther, setIncludeOther] = useState(false);
  const [rows, setRows] = useState<RentalRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.rentals(includeOther).then((r) => { if (alive) { setRows(r.rentals); setError(null); } }).catch((e) => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [tick, includeOther]);

  if (sessionId) return <RentalDetailView sessionId={sessionId} />;

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp} className="flex items-end justify-between gap-4">
        <div>
          <h2 className="text-[22px] font-semibold tracking-tight text-white">租還車紀錄</h2>
          <p className="mt-1 text-[13px] text-muted">每一筆由 iOS App 建立的租車：取車車牌辨識、取車／還車照片、AI 檢測與異常案件。</p>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-[12.5px] text-white/65">
          <input type="checkbox" checked={includeOther} onChange={(e) => setIncludeOther(e.target.checked)} data-testid="include-other" />顯示固定劇本租約
        </label>
      </motion.div>
      <GlassPanel variants={fadeUp} padded={false} className="overflow-hidden">
        <table className="w-full text-left text-[13px]" data-testid="rentals-table">
          <thead><tr className="border-b border-white/[0.06] text-[10.5px] uppercase tracking-wider text-white/40">
            <th className="px-5 py-3 font-medium">車牌</th><th className="px-4 py-3 font-medium">開始租車</th><th className="px-4 py-3 font-medium">還車完成</th><th className="px-4 py-3 font-medium">租車狀態</th><th className="px-4 py-3 font-medium">取車車牌辨識</th><th className="px-4 py-3 font-medium">照片</th><th className="px-4 py-3 font-medium">AI 檢測</th><th className="px-4 py-3 font-medium">異常</th>
          </tr></thead>
          <tbody>
            {(rows ?? []).map((r) => (
              <tr key={r.session_id} data-testid={`rental-row-${r.session_id}`} className="border-b border-white/[0.04] transition hover:bg-white/[0.03]">
                <td className="px-5 py-3"><Link href={`/rentals?session=${encodeURIComponent(r.session_id)}`} className="font-mono font-medium text-white/90 hover:text-sky-200">{r.plate}</Link>
                  {r.data_source !== "app" && <span className="ml-2"><Badge tone={SOURCE_META[r.data_source].tone}>{SOURCE_META[r.data_source].label}</Badge></span>}</td>
                <td className="px-4 py-3 text-white/70">{fmt(r.started_at).slice(5, 16)}</td>
                <td className="px-4 py-3 text-white/70">{r.returned_at ? fmt(r.returned_at).slice(5, 16) : "—"}</td>
                <td className="px-4 py-3 text-white/80">{r.state_label}</td>
                <td className="px-4 py-3"><Badge tone={PLATE_META[r.pickup_plate_status].tone}>{PLATE_META[r.pickup_plate_status].label}</Badge></td>
                <td className="px-4 py-3 text-white/60">取 {r.pickup_photos}・還 {r.return_photos}</td>
                <td className="px-4 py-3">{r.review_state ? <Badge tone={REVIEW_META[r.review_state].tone}>{REVIEW_META[r.review_state].label}</Badge> : <span className="text-white/35">—</span>}</td>
                <td className="px-4 py-3 text-white/70">{r.incident_count ? `${r.incident_count} 件${r.unreviewed_count ? `（${r.unreviewed_count} 待審）` : ""}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows && rows.length === 0 && <div className="p-10 text-center text-[13px] text-muted">目前尚無租還車紀錄。用 iOS App 租一台車後就會出現在這裡。</div>}
        {!rows && !error && <div className="p-10 text-center text-[13px] text-muted">{loaded ? "載入中…" : "連線中…"}</div>}
        {error && <div className="p-10 text-center text-[13px] text-rose-300">無法取得租還車紀錄：{error}</div>}
      </GlassPanel>
    </motion.div>
  );
}

function RentalDetailView({ sessionId }: { sessionId: string }) {
  const { tick, openIncident } = useOps();
  const [d, setD] = useState<RentalDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.rental(sessionId).then((r) => { if (alive) { setD(r); setError(null); } }).catch((e) => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [sessionId, tick]);

  if (error) return <div className="py-20 text-center text-rose-300">{error} <Link href="/rentals" className="ml-2 text-sky-300 hover:underline">返回列表</Link></div>;
  if (!d) return <div className="py-20 text-center text-muted">載入 {sessionId}…</div>;
  const r = d.rental;

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5" data-testid="rental-detail">
      <motion.div variants={fadeUp} className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Link href="/rentals" aria-label="返回" className="grid h-9 w-9 place-items-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-white/70 hover:text-white"><ArrowLeft className="h-4 w-4" /></Link>
          <div>
            <h2 className="font-mono text-[22px] font-semibold tracking-tight text-white">{r.plate}</h2>
            <p className="mt-0.5 text-[13px] text-muted">{r.model ?? "—"}・{r.session_id}・租約 {r.rental_id}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {r.data_source !== "app" && <Badge tone={SOURCE_META[r.data_source].tone}>{SOURCE_META[r.data_source].label}</Badge>}
          <Badge tone="info">{r.state_label}</Badge>
          {d.inspection.result && <Link href={`/inspections?rental=${encodeURIComponent(r.rental_id)}`}><Button size="sm" variant="secondary" icon={<ScanSearch className="h-3.5 w-3.5" />}>AI 檢測與審核</Button></Link>}
        </div>
      </motion.div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <GlassPanel variants={fadeUp}>
          <SectionHeader title="租車資訊" />
          <div className="grid grid-cols-2 gap-3 text-[13px] text-white/80 md:grid-cols-4">
            <div><div className="label-xs">開始租車</div>{fmt(r.started_at)}</div>
            <div><div className="label-xs">還車完成</div>{r.returned_at ? fmt(r.returned_at) : "—"}</div>
            <div><div className="label-xs">使用時間</div>{duration(r.used_seconds)}</div>
            <div><div className="label-xs">里程</div>{d.session.start_odometer_km} → {d.session.end_odometer_km ?? "—"} km{r.distance_km != null ? `（${r.distance_km} km）` : ""}</div>
            <div><div className="label-xs">取車車牌辨識</div><Badge tone={PLATE_META[d.pickup.plate_status].tone}>{PLATE_META[d.pickup.plate_status].label}</Badge></div>
            <div><div className="label-xs">辨識結果</div><span className="font-mono">{d.pickup.plate_texts.join("、") || "—"}</span></div>
            <div><div className="label-xs">AI 檢測</div>{d.inspection.review_state ? <Badge tone={REVIEW_META[d.inspection.review_state].tone}>{REVIEW_META[d.inspection.review_state].label}</Badge> : "—"}</div>
            <div><div className="label-xs">檢測次數</div>{d.session.inspection_attempts}</div>
          </div>
          {d.session.last_error && <div className="mt-3 rounded-lg bg-amber-500/10 px-3 py-2 text-[12px] text-amber-200">最近一次檢測錯誤：{d.session.last_error}</div>}
        </GlassPanel>

        <GlassPanel variants={fadeUp}>
          <SectionHeader title="流程時間軸" />
          <ol className="space-y-2.5" data-testid="rental-timeline">
            {d.timeline.map((t) => (
              <li key={t.label} className="flex items-start gap-3 text-[12.5px]">
                <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-sky-400" />
                <span className="flex-1 text-white/85">{t.label}</span>
                <span className="tabular text-white/50">{fmt(t.at).slice(5, 19)}</span>
              </li>
            ))}
          </ol>
        </GlassPanel>
      </div>

      <StagePanel title="取車照片" subtitle="每張都經裝置端 Core ML 車牌／角度檢查" stage={d.pickup} />
      <StagePanel title="還車照片" subtitle="送後端 Gemini 與取車照逐角度比對" stage={d.return} />

      <GlassPanel variants={fadeUp}>
        <SectionHeader title="異常案件" subtitle="AI 檢測發現的車損／髒污；點擊可查看證據並人工審核" />
        {d.inspection.incidents.length === 0 ? <div className="text-[13px] text-muted">{d.inspection.result ? "本次未發現異常。" : "尚未完成還車檢測。"}</div> : (
          <div className="grid gap-2 md:grid-cols-2">
            {d.inspection.incidents.map((i) => (
              <button key={i.case_id} onClick={() => openIncident(i.case_id)} className={cn("flex items-center justify-between rounded-xl border px-3 py-2.5 text-left text-[13px]", i.kind === "damage" ? "border-rose-400/20 bg-rose-400/[0.05]" : "border-amber-400/20 bg-amber-400/[0.05]")}>
                <span>{i.kind === "damage" ? "車損" : i.kind === "cleaning" ? "車內髒污" : "照片重複"}・{i.label ?? i.view_angle}{i.confidence != null ? `・${pct(i.confidence)}` : ""}</span>
                <Badge tone={i.review_status === "unreviewed" ? "danger" : "violet"}>{CASE_REVIEW_LABEL[i.review_status ?? "unreviewed"]}</Badge>
              </button>
            ))}
          </div>
        )}
      </GlassPanel>
    </motion.div>
  );
}

function StagePanel({ title, subtitle, stage }: { title: string; subtitle: string; stage: StagePhotos }) {
  return (
    <GlassPanel variants={fadeUp}>
      <SectionHeader title={title} subtitle={subtitle} action={<span className="text-[12px] text-white/50">{stage.photos.length} 張</span>} />
      {stage.photos.length === 0 ? <div className="text-[13px] text-muted">尚無照片。</div> : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {stage.photos.map((p) => (
            <figure key={p.angle} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2">
              <div className="always-dark aspect-[4/3] overflow-hidden rounded-lg bg-black/40">{p.url ? <img src={p.url} alt={`${title} ${p.angle}`} className="h-full w-full object-cover" /> : null}</div>
              <figcaption className="mt-1.5 text-[11.5px] text-white/70">
                <div className="font-medium text-white/85">{p.angle}</div>
                {p.angle !== "車內" && <div>車牌 <span className="font-mono">{p.plate_text ?? "未辨識"}</span>{p.plate_confidence != null ? `・${pct(p.plate_confidence)}` : ""}{p.plate_source !== "ocr" ? `（${p.plate_source === "manual" ? "手動輸入" : p.plate_source === "user_confirmed_mismatch" ? "使用者確認不符" : p.plate_source}）` : ""}</div>}
                <div className="text-white/45">{p.validation_mode === "coreml" ? "Core ML" : p.validation_mode === "demo" ? "Demo 劇本" : p.validation_mode === "preloaded" ? "預載照片" : p.validation_mode}・{fmt(p.captured_at).slice(11, 19)}</div>
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </GlassPanel>
  );
}
