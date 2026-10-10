"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { Car, CircleCheck, KeyRound, ArrowLeftRight, ScanSearch, UserCheck, TriangleAlert } from "lucide-react";
import { useOps } from "@/store/OpsStore";
import { api } from "@/lib/ops/api";
import type { Overview } from "@/lib/ops/types";
import { CASE_REVIEW_LABEL, REVIEW_META } from "@/lib/ops/console";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { Badge } from "@/components/ui/Badge";
import { fadeUp, stagger } from "@/components/ui/motion";
import { fmt } from "@/lib/ops/time";
import { cn, pct } from "@/lib/utils";

/**
 * 總覽：只呈現真實 App 租還車流程產生的資料（/api/ops/overview）。
 * 固定劇本、舊版上傳流程與資料集離線評測不計入任何數字。
 */
export default function OverviewPage() {
  const { tick } = useOps();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 跟著 OpsStore 的輪詢／SSE 一起刷新
  useEffect(() => {
    let alive = true;
    api.overview().then((r) => { if (alive) { setData(r); setError(null); } }).catch((e) => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [tick]);

  const v = data?.vehicles;
  const stats = data ? [
    { label: "車輛總數", value: v!.total, sub: `其中 Demo 測試車 ${v!.demo} 台`, icon: <Car />, href: "/fleet", tone: "neutral" },
    { label: "可租用", value: v!.available, sub: "目前可出租（不含固定劇本車）", icon: <CircleCheck />, href: "/fleet?filter=available", tone: "success" },
    { label: "租用中", value: v!.rented, sub: "含還車檢測中、待確認還車", icon: <KeyRound />, href: "/fleet?filter=rented", tone: "info" },
    { label: "今日租車／還車", value: `${data.today.rentals_started} / ${data.today.returns_completed}`, sub: "開始租車 / 完成還車", icon: <ArrowLeftRight />, href: "/rentals", tone: "neutral" },
    { label: "AI 已完成檢測", value: data.ai.completed, sub: `檢測中 ${data.ai.analyzing}・失敗 ${data.ai.failed}`, icon: <ScanSearch />, href: "/inspections", tone: "neutral" },
    { label: "待人工審核案件", value: data.ai.pending_review_cases, sub: "AI 發現異常、尚未裁決", icon: <UserCheck />, href: "/inspections?state=pending_review", tone: data.ai.pending_review_cases ? "danger" : "neutral" },
    { label: "異常車輛", value: v!.abnormal, sub: v!.abnormal ? v!.abnormal_plates.join("、") : "整備中或有待審核異常", icon: <TriangleAlert />, href: "/fleet?filter=maintenance", tone: v!.abnormal ? "warning" : "neutral" },
  ] : [];

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp} className="flex items-end justify-between">
        <div>
          <h2 className="text-[22px] font-semibold tracking-tight text-white">總覽</h2>
          <p className="mt-1 text-[13px] text-muted">{data?.scope_note ?? "App 租還車與 AI 檢測的即時狀態。"}</p>
        </div>
        <div className="text-right text-[12px] text-white/55">{data ? `最後同步 ${fmt(data.server_time).slice(11)}` : error ? "" : "連線中…"}</div>
      </motion.div>

      {error && <GlassPanel className="text-[13px] text-rose-300">無法取得總覽資料：{error}</GlassPanel>}

      <motion.div variants={stagger} className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {stats.map((s) => (
          <motion.div key={s.label} variants={fadeUp}>
            <Link href={s.href} className="glass block h-full rounded-2xl p-4 transition hover:ring-1 hover:ring-white/15" data-testid={`stat-${s.label}`}>
              <div className="flex items-center justify-between">
                <span className="text-[12px] text-white/60">{s.label}</span>
                <span className={cn("grid h-7 w-7 place-items-center rounded-lg [&>svg]:h-3.5 [&>svg]:w-3.5",
                  s.tone === "danger" ? "bg-rose-400/12 text-rose-300" : s.tone === "warning" ? "bg-amber-400/12 text-amber-300" : s.tone === "success" ? "bg-emerald-400/12 text-emerald-300" : s.tone === "info" ? "bg-sky-400/12 text-sky-300" : "bg-white/[0.06] text-white/70")}>{s.icon}</span>
              </div>
              <div className="mt-2 text-[26px] font-semibold tabular text-white">{s.value}</div>
              <div className="mt-0.5 truncate text-[11px] text-muted" title={s.sub}>{s.sub}</div>
            </Link>
          </motion.div>
        ))}
      </motion.div>

      <div className="grid gap-5 xl:grid-cols-2">
        <GlassPanel variants={fadeUp} padded={false} className="overflow-hidden">
          <div className="px-5 pt-4"><SectionHeader title="最近租還車" subtitle="App 建立的租車 Session" action={<Link href="/rentals" className="text-[12px] text-sky-300 hover:underline">全部紀錄</Link>} /></div>
          {data && data.recent_rentals.length === 0 ? (
            <div className="px-5 pb-8 pt-2 text-center text-[13px] text-muted">目前尚無租還車紀錄。用 App 租一台車後就會出現在這裡。</div>
          ) : (
            <table className="w-full text-left text-[13px]">
              <tbody>
                {data?.recent_rentals.map((r) => (
                  <tr key={r.session_id} className="border-t border-white/[0.05]">
                    <td className="px-5 py-2.5"><Link href={`/rentals?session=${encodeURIComponent(r.session_id)}`} className="font-mono font-medium text-white/90 hover:text-sky-200">{r.plate}</Link></td>
                    <td className="px-3 py-2.5 text-white/60">{fmt(r.started_at).slice(5, 16)}</td>
                    <td className="px-3 py-2.5 text-white/75">{r.state_label}</td>
                    <td className="px-5 py-2.5 text-right">{r.review_state ? <Badge tone={REVIEW_META[r.review_state].tone}>{REVIEW_META[r.review_state].label}</Badge> : <span className="text-[12px] text-white/35">尚未還車</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </GlassPanel>

        <GlassPanel variants={fadeUp} padded={false} className="overflow-hidden">
          <div className="px-5 pt-4"><SectionHeader title="最近 AI 異常" subtitle="還車檢測發現的車損／髒污案件" action={<Link href="/inspections" className="text-[12px] text-sky-300 hover:underline">AI 檢測與審核</Link>} /></div>
          {data && data.recent_incidents.length === 0 ? (
            <div className="px-5 pb-8 pt-2 text-center text-[13px] text-muted">目前尚無 AI 異常案件。</div>
          ) : (
            <ul>
              {data?.recent_incidents.map((i) => (
                <li key={i.case_id} className="border-t border-white/[0.05]">
                  <Link href={`/inspections?rental=${encodeURIComponent(i.rental_id)}`} className="flex items-center gap-3 px-5 py-2.5 hover:bg-white/[0.03]">
                    <span className={cn("h-2 w-2 shrink-0 rounded-full", i.kind === "damage" ? "bg-rose-400" : "bg-amber-400")} />
                    <span className="font-mono text-[13px] font-medium text-white/90">{i.plate}</span>
                    <span className="min-w-0 flex-1 truncate text-[12.5px] text-white/70">{i.kind === "damage" ? "車損" : i.kind === "cleaning" ? "車內髒污" : "照片重複"}・{i.label ?? i.view_angle}{i.confidence != null ? `・${pct(i.confidence)}` : ""}</span>
                    <Badge tone={i.review_status === "unreviewed" || !i.review_status ? "danger" : "violet"}>{CASE_REVIEW_LABEL[i.review_status ?? "unreviewed"]}</Badge>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </GlassPanel>
      </div>
    </motion.div>
  );
}
