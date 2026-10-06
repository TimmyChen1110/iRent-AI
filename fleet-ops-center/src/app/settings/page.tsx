"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api } from "@/lib/ops/api";
import type { Channel } from "@/lib/ops/types";
import { useOps } from "@/store/OpsStore";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { fadeUp, stagger } from "@/components/ui/motion";

const input = "rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-[13px] text-white/90 focus:outline-none";
const pick = (s: Record<string, string>) => Object.fromEntries(Object.entries(s).filter(([k]) => k.startsWith("require_photo_") || k === "escalate_on_overdue" || k.startsWith("default_assignee_")));

export default function SettingsPage() {
  const { health, people, pushToast } = useOps();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [sla, setSla] = useState({ p1: "5", p2: "240", p3: "1440" });
  const [rules, setRules] = useState<Record<string, string>>({ require_photo_cleaning: "1", require_photo_repair: "0", escalate_on_overdue: "1", default_assignee_cleaning_id: "", default_assignee_repair_id: "" });
  const [testing, setTesting] = useState(false);
  const [pre, setPre] = useState<Record<string, string>>({});

  useEffect(() => {
    api.health().then((h) => setChannels(h.channels)).catch(() => {});
    api.settings().then((r) => { setSla({ p1: r.settings.sla_minutes_p1, p2: r.settings.sla_minutes_p2, p3: r.settings.sla_minutes_p3 }); setRules((x) => ({ ...x, ...pick(r.settings) })); }).catch(() => {});
  }, []);

  const saveRules = async () => { try { const r = await api.putSettings(rules); setRules((x) => ({ ...x, ...pick(r.settings) })); pushToast({ tone: "success", title: "規則已儲存" }); } catch (e) { pushToast({ tone: "warning", title: (e as Error).message }); } };
  const saveSla = async () => { try { const r = await api.putSettings({ sla_minutes_p1: sla.p1, sla_minutes_p2: sla.p2, sla_minutes_p3: sla.p3 }); setSla({ p1: r.settings.sla_minutes_p1, p2: r.settings.sla_minutes_p2, p3: r.settings.sla_minutes_p3 }); pushToast({ tone: "success", title: "SLA 門檻已儲存" }); } catch (e) { pushToast({ tone: "warning", title: (e as Error).message }); } };
  const testHook = async () => { setTesting(true); try { const r = await api.testWebhook(); pushToast({ tone: r.ok ? "success" : "warning", title: r.detail }); } catch (e) { pushToast({ tone: "warning", title: (e as Error).message }); } finally { setTesting(false); } };
  const pregenerate = async (force: boolean) => {
    if (!health?.gemini_configured) { pushToast({ tone: "warning", title: "Gemini API Key 未設定" }); return; }
    for (const [k, cid] of Object.entries(health.demo_cases)) {
      setPre((p) => ({ ...p, [k]: "生成中…" }));
      try { const r = await api.generateDrafts(cid, force); setPre((p) => ({ ...p, [k]: r.cached ? "已有快取" : "已生成" })); } catch (e) { setPre((p) => ({ ...p, [k]: `失敗：${(e as Error).message}` })); }
    }
  };
  const check = (k: string, label: string) => <label className="flex items-center gap-2 text-[13px] text-white/85"><input type="checkbox" checked={rules[k] === "1"} onChange={(e) => setRules((r) => ({ ...r, [k]: e.target.checked ? "1" : "0" }))} />{label}</label>;

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp}><h2 className="text-[22px] font-semibold tracking-tight text-white">整備與通知設定</h2><p className="mt-1 text-[13px] text-muted">清楚區分可用、未設定與尚未支援；URL 與金鑰不會回傳前端。</p></motion.div>
      <GlassPanel variants={fadeUp}>
        <SectionHeader title="系統能力" />
        <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted"><Badge tone="success">可用 · 任務 / 看板 / SQLite</Badge><Badge tone={health?.gemini_configured ? "success" : "neutral"}>{health?.gemini_configured ? "可用 · Gemini AI" : "未設定 · Gemini AI"}</Badge><span>未設定 Gemini 時，只有 AI 重判與文案生成不可用。</span></div>
      </GlassPanel>
      <GlassPanel variants={fadeUp}>
        <SectionHeader title="通知管道" />
        <div className="grid gap-3 md:grid-cols-3">
          {channels.map((c) => (
            <div key={c.id} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3.5" style={{ opacity: c.available ? 1 : 0.6 }}>
              <div className="flex items-center justify-between"><b className="text-[13px] text-white/90">{c.label}</b><Badge tone={!c.available ? "neutral" : c.configured ? "success" : "warning"}>{!c.available ? "未接入" : c.configured ? "已設定" : "未設定"}</Badge></div>
              <div className="mt-1.5 text-[12px] text-muted">{c.note}</div>
              {c.id === "webhook" && !c.configured && <div className="mt-1 text-[11px] text-dim">設定環境變數 NOTIFICATION_WEBHOOK_URL 後重啟 server</div>}
              {c.id === "webhook" && c.configured && <Button size="sm" className="mt-2" disabled={testing} onClick={testHook}>{testing ? "發送中…" : "發送測試通知"}</Button>}
            </div>
          ))}
        </div>
      </GlassPanel>
      {health?.demo_mode && (
        <GlassPanel variants={fadeUp}>
          <SectionHeader title="Demo 預生成文案" subtitle="上台前先對兩個示範案例各呼叫一次 Gemini，現場任務詳情秒開。快取依案件保存，重置 Demo 不會清掉。" />
          <div className="flex flex-wrap items-center gap-2"><Button size="sm" variant="primary" disabled={!health.gemini_configured} onClick={() => pregenerate(false)}>預生成（有快取則略過）</Button><Button size="sm" disabled={!health.gemini_configured} onClick={() => pregenerate(true)}>全部重新生成</Button>{Object.entries(pre).map(([k, v]) => <Badge key={k} tone="neutral">{k === "damage" ? "車損" : "髒汙"}：{v}</Badge>)}</div>
        </GlassPanel>
      )}
      <GlassPanel variants={fadeUp}>
        <SectionHeader title="整備規則" />
        <div className="space-y-2.5">
          {check("require_photo_cleaning", "清潔任務完工前須至少一張完工照（監理台與手機版皆適用）")}
          {check("require_photo_repair", "維修任務完工前須至少一張完工照")}
          {check("escalate_on_overdue", "SLA 逾時時自動再發一次 webhook 升級推播")}
          <div className="flex flex-wrap gap-4 text-[13px] text-white/85">
            <label className="flex items-center gap-2">清潔任務預設指派<select className={input} value={rules.default_assignee_cleaning_id} onChange={(e) => setRules((r) => ({ ...r, default_assignee_cleaning_id: e.target.value }))}><option value="">不自動</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
            <label className="flex items-center gap-2">維修任務預設指派<select className={input} value={rules.default_assignee_repair_id} onChange={(e) => setRules((r) => ({ ...r, default_assignee_repair_id: e.target.value }))}><option value="">不自動</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          </div>
          <div><Button variant="primary" onClick={saveRules}>儲存規則</Button></div>
          <p className="text-[11.5px] text-dim">自動指派只在任務建立且從未被人指派過時執行一次；人工改過就不再覆蓋。</p>
        </div>
      </GlassPanel>
      <GlassPanel variants={fadeUp}>
        <SectionHeader title="SLA 門檻（待處理 → 開工，分鐘）" subtitle="預設 P1 5 分、P2 4 小時、P3 當日。逾時任務會在通知中心產生「SLA 逾時」事件。" />
        <div className="flex flex-wrap items-center gap-3">
          {(["p1", "p2", "p3"] as const).map((k) => <label key={k} className="flex items-center gap-2 text-[13px] text-white/85"><Badge tone={k === "p1" ? "danger" : k === "p2" ? "warning" : "success"}>{k.toUpperCase()}</Badge><input className={`${input} w-24`} type="number" min={1} max={10080} value={sla[k]} onChange={(e) => setSla((s) => ({ ...s, [k]: e.target.value }))} /></label>)}
          <Button variant="primary" onClick={saveSla}>儲存</Button>
        </div>
      </GlassPanel>
    </motion.div>
  );
}
