"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Sparkles, Gauge, Target, UserCheck, Wrench } from "lucide-react";
import { api } from "@/lib/ops/api";
import type { Insights } from "@/lib/ops/types";
import { useOps } from "@/store/OpsStore";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { Badge } from "@/components/ui/Badge";
import { fadeUp, stagger } from "@/components/ui/motion";

const REPAIR = "#38bdf8";
const CLEAN = "#d97706";
const CLAIM = "#e11d48";

export default function InsightsPage() {
  const { tick } = useOps();
  const [d, setD] = useState<Insights | null>(null);
  useEffect(() => { api.insights().then(setD).catch(() => {}); }, [tick]);

  const hours = useMemo(() => {
    if (!d?.uploads) return [];
    const bh = d.uploads.by_hour;
    const top = new Set([...bh].map((v, h) => ({ v, h })).sort((a, b) => b.v - a.v).slice(0, 6).map((x) => x.h));
    return bh.map((v, h) => ({ h, v, top: top.has(h) }));
  }, [d]);

  if (!d) return <div className="glass rounded-2xl p-10 text-center text-[13px] text-muted">載入營運洞察…</div>;
  const up = d.uploads;
  const sum = (o?: Record<string, number>) => (o ? Object.values(o).reduce((a, b) => a + b, 0) : 0);
  const fmtMin = (m: number) => (m < 60 ? `${Math.round(m)} 分` : m < 1440 ? `${(m / 60).toFixed(1)} 時` : `${(m / 1440).toFixed(1)} 天`);
  const peak = hours.filter((x) => x.top).map((x) => x.h).sort((a, b) => a - b);
  const peakShare = up ? Math.round((hours.filter((x) => x.top).reduce((s, x) => s + x.v, 0) / up.orders) * 100) : 0;

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp}><h2 className="text-[22px] font-semibold tracking-tight text-white">AI 洞察</h2><p className="mt-1 text-[13px] text-muted">混合資料看板；每一區都標明來源（資料庫即時、離線彙整或 Demo dataset）。</p></motion.div>

      <motion.div variants={stagger} className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat icon={<Wrench />} label="整備任務總數 · 即時" value={String(d.tasks.total)} sub={`維修 ${sum(d.tasks.by_type.repair)} · 清潔 ${sum(d.tasks.by_type.cleaning)}`} />
        <Stat icon={<Gauge />} label="中位開工時間" value={d.tasks.median_minutes_to_start == null ? "—" : fmtMin(d.tasks.median_minutes_to_start)} sub={`建立 → 開始處理，n = ${d.tasks.n_started}`} />
        <Stat icon={<Target />} label="中位完工時間" value={d.tasks.median_minutes_to_complete == null ? "—" : fmtMin(d.tasks.median_minutes_to_complete)} sub={`建立 → 完成，n = ${d.tasks.n_completed}`} />
        <Stat icon={<UserCheck />} label="人工 vs AI 一致率" value={d.agreement.rate == null ? "—" : `${Math.round(d.agreement.rate * 100)}%`} sub={`${d.agreement.agreed}/${d.agreement.n} 次裁決一致`} />
      </motion.div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <GlassPanel variants={fadeUp}>
          <SectionHeader title="還車時段分布 — 清潔／整備人力該排在哪" subtitle={up ? `以訂單去重的還車上傳時間，n = ${up.orders.toLocaleString()} 單（${up.vehicles.toLocaleString()} 台車）` : "尚未產生上傳 log 彙整"} action={<Badge tone="info">離線彙整 · 非即時</Badge>} />
          {up ? (
            <>
              <Columns data={hours.map((x) => ({ label: String(x.h), value: x.v, emphasis: x.top }))} />
              <div className="mt-3 flex flex-wrap gap-2 text-[11.5px]"><Badge tone="info">尖峰 {peak.map((h) => `${h}時`).join("、")} 佔 {peakShare}%</Badge><Badge tone="neutral">離峰適合排維修與深度清潔</Badge></div>
            </>
          ) : <div className="text-[12.5px] text-muted">執行 <span className="font-mono">python3 backend/pipeline/build_ops_insights.py</span> 後才有資料。</div>}
        </GlassPanel>
        <GlassPanel variants={fadeUp}>
          <SectionHeader title="車輛事件排行 — 哪些車該優先巡檢" subtitle="人工確認任務（即時）＋ 資料集索賠樣本（離線）" action={<Badge tone="neutral">混合來源</Badge>} />
          <div className="space-y-2.5">
            {d.car_ranking.map((c) => {
              const max = Math.max(1, ...d.car_ranking.map((x) => x.repair + x.cleaning + x.claims));
              const total = c.repair + c.cleaning + c.claims;
              return (
                <div key={c.car} className="grid grid-cols-[96px_1fr_28px] items-center gap-3 text-[12.5px]" title={`維修 ${c.repair}、清潔 ${c.cleaning}、索賠 ${c.claims}`}>
                  <span className="truncate font-mono text-white/85">{c.car}</span>
                  <div className="flex h-2 gap-0.5 rounded-full bg-white/[0.05]">
                    {[["r", c.repair, REPAIR], ["c", c.cleaning, CLEAN], ["k", c.claims, CLAIM]].filter(([, v]) => (v as number) > 0).map(([k, v, col]) => <div key={k as string} className="h-full rounded-full" style={{ width: `${((v as number) / max) * 100}%`, background: col as string }} />)}
                  </div>
                  <span className="tabular text-right text-white/70">{total}</span>
                </div>
              );
            })}
            {d.car_ranking.length === 0 && <div className="text-[12.5px] text-muted">尚無資料</div>}
          </div>
          <div className="mt-3 flex gap-4 text-[11.5px] text-white/60">{[["維修任務", REPAIR], ["清潔任務", CLEAN], ["索賠紀錄", CLAIM]].map(([l, c]) => <span key={l} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ background: c }} />{l}</span>)}</div>
        </GlassPanel>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <GlassPanel variants={fadeUp}>
          <SectionHeader title="人工裁決 vs AI 判定一致率" subtitle="每次 confirm / reject 都自動存成訓練標籤（decision_events，append-only）" action={<Badge tone="success">資料庫 · 即時</Badge>} />
          {d.agreement.days.length === 0 ? <div className="text-[12.5px] text-muted">尚無裁決紀錄</div> : <Columns data={d.agreement.days.map((x) => ({ label: x.day.slice(5), value: Math.round((x.agreed / x.n) * 100), emphasis: false }))} suffix="%" />}
        </GlassPanel>
        <GlassPanel variants={fadeUp}>
          <SectionHeader title="車內整潔分布" subtitle={`離線分類，n = ${d.interior.n}（排除無法判讀 ${d.interior.excluded_unreadable} 張）`} action={<Badge tone="neutral">Demo dataset</Badge>} />
          <div className="flex h-2.5 w-full overflow-hidden rounded-full">
            {[["乾淨", d.interior.乾淨, "#34d399"], ["普通", d.interior.普通, "#fbbf24"], ["髒汙", d.interior.髒汙, "#fb7185"]].map(([l, v, c]) => <div key={l as string} className="h-full border-r-2 border-[#0d1017] last:border-0" style={{ width: `${d.interior.n ? ((v as number) / d.interior.n) * 100 : 0}%`, background: c as string }} title={`${l} ${v}`} />)}
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2">{[["乾淨", d.interior.乾淨, "#34d399"], ["普通", d.interior.普通, "#fbbf24"], ["髒汙", d.interior.髒汙, "#fb7185"]].map(([l, v, c]) => <div key={l as string} className="rounded-lg bg-white/[0.03] p-2.5"><div className="flex items-center gap-1.5 text-[11px] text-white/55"><span className="h-2 w-2 rounded-sm" style={{ background: c as string }} />{l}</div><div className="tabular mt-1 text-[16px] font-semibold text-white">{v as number}</div></div>)}</div>
          <p className="mt-3 flex items-center gap-1.5 text-[12px] text-muted"><Sparkles className="h-3.5 w-3.5 text-sky-300" />髒汙比例 {d.interior.n ? `${Math.round((d.interior.髒汙 / d.interior.n) * 100)}%` : "—"}；不代表全車隊比例。</p>
        </GlassPanel>
      </div>
    </motion.div>
  );
}

function Stat({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub: string }) {
  return (
    <motion.div variants={fadeUp} className="glass rounded-2xl p-4">
      <div className="flex items-center justify-between"><span className="label-xs">{label}</span><span className="grid h-7 w-7 place-items-center rounded-lg bg-white/[0.06] text-white/70 [&>svg]:h-3.5 [&>svg]:w-3.5">{icon}</span></div>
      <div className="tabular mt-2 text-[26px] font-semibold leading-none text-white">{value}</div>
      <div className="mt-1 text-[11px] text-dim">{sub}</div>
    </motion.div>
  );
}

function Columns({ data, suffix = "" }: { data: { label: string; value: number; emphasis: boolean }[]; suffix?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 640, H = 200, padL = 36, padB = 24, padT = 14;
  const max = Math.max(1, ...data.map((d) => d.value));
  const innerW = W - padL - 12, innerH = H - padB - padT;
  const slot = innerW / data.length;
  const bw = Math.min(18, slot * 0.7);
  const y = (v: number) => padT + innerH - (v / max) * innerH;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" onMouseLeave={() => setHover(null)}>
        {[0, 0.25, 0.5, 0.75, 1].map((f) => <g key={f}><line x1={padL} x2={W - 12} y1={y(max * f)} y2={y(max * f)} stroke="rgba(255,255,255,0.06)" /><text x={padL - 8} y={y(max * f) + 4} textAnchor="end" fontSize="10" fill="rgba(255,255,255,0.4)">{Math.round(max * f)}{suffix}</text></g>)}
        {data.map((d, i) => {
          const x = padL + slot * i + (slot - bw) / 2;
          return (
            <g key={i} onMouseEnter={() => setHover(i)}>
              <rect x={padL + slot * i} y={padT} width={slot} height={innerH} fill={hover === i ? "rgba(255,255,255,0.03)" : "transparent"} />
              <motion.rect x={x} width={bw} rx={4} fill={d.emphasis ? "#7dd3fc" : "#38bdf8"} initial={{ y: y(0), height: 0 }} animate={{ y: y(d.value), height: Math.max(0, y(0) - y(d.value)) }} transition={{ duration: 0.6, delay: i * 0.02 }} opacity={hover == null || hover === i ? 1 : 0.45} />
              {(data.length <= 12 || i % Math.ceil(data.length / 12) === 0) && <text x={padL + slot * i + slot / 2} y={H - 6} textAnchor="middle" fontSize="10.5" fill="rgba(255,255,255,0.55)">{d.label}</text>}
            </g>
          );
        })}
        {hover != null && <text x={padL + slot * hover + slot / 2} y={y(data[hover].value) - 6} textAnchor="middle" fontSize="11.5" fontWeight={700} fill="#fff">{data[hover].value}{suffix}</text>}
      </svg>
    </div>
  );
}
