"use client";

import { useState } from "react";
import { api } from "@/lib/ops/api";
import type { Audience, Draft, Drafts, NotificationLogEntry, Task } from "@/lib/ops/types";
import { fmt } from "@/lib/ops/time";
import { useOps } from "@/store/OpsStore";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";

const AUD: Array<{ key: Audience; label: string; hint: string }> = [
  { key: "user", label: "用戶通知", hint: "中性、不歸咎、無術語與分數，附申訴管道" },
  { key: "cs", label: "客服摘要", hint: "資訊密集：信心、覆蓋度、建議處置、爭議風險" },
  { key: "worker", label: "派工單", hint: "工作指示：項目、工具、預估工時" },
];
const FIELD_TXT: Record<string, string> = {
  title: "標題", body: "內文", evidence_note: "判定依據", dispute_channel_note: "申訴管道", summary: "摘要", confidence_note: "信心說明",
  coverage_caveat: "覆蓋度提醒", recommended_action: "建議處置", dispute_risk: "爭議風險", dispute_risk_reason: "風險理由",
  type: "類型", priority: "優先", items: "工作項目", special_tools: "特殊工具／耗材", estimated_minutes: "預估工時（分）",
};

/** 三對象通知文案：生成（Gemini，依案件快取）→ 編輯 → 發送（只有 webhook 真的會送）。 */
export function DraftsPanel({ task, drafts, log, onChange, onSent }: { task: Task; drafts: Drafts; log: NotificationLogEntry[]; onChange: (d: Drafts) => void; onSent: (detail: { notification_log: NotificationLogEntry[]; task: Task }) => void }) {
  const { health, pushToast, refresh } = useOps();
  const [tab, setTab] = useState<Audience>("cs");
  const [gen, setGen] = useState(false);
  // 編輯稿以「分頁 + 草稿版本」為鍵；切換分頁或草稿更新時自動丟棄（不用 effect）。
  const [editState, setEditState] = useState<{ key: string; value: Record<string, unknown> | null }>({ key: "", value: null });
  const [channel, setChannel] = useState("webhook");
  const [sending, setSending] = useState(false);
  const draft: Draft | undefined = drafts[tab];
  const draftKey = `${tab}:${draft?.generated_at}:${draft?.edited_at}`;
  const edit = editState.key === draftKey ? editState.value : null;
  const setEdit = (v: Record<string, unknown> | null) => setEditState({ key: draftKey, value: v });

  const generate = async (force: boolean) => {
    setGen(true);
    try { const r = await api.generateDrafts(task.case_id, force); onChange(r.drafts); pushToast({ tone: "success", title: r.cached ? "已載入快取文案" : "文案已生成" }); }
    catch (e) { pushToast({ tone: "warning", title: (e as Error).message }); } finally { setGen(false); }
  };
  const save = async () => {
    if (!edit) return;
    try { const d = await api.putDraft(task.case_id, tab, edit); onChange({ ...drafts, [tab]: d }); setEdit(null); pushToast({ tone: "success", title: "文案已儲存" }); }
    catch (e) { pushToast({ tone: "warning", title: (e as Error).message }); }
  };
  const send = async () => {
    setSending(true);
    try { const r = await api.sendDraft(task.id, tab, channel); onSent(r); refresh(); pushToast({ tone: r.ok ? "success" : "warning", title: r.entry.detail || (r.ok ? "已送出" : "未送出") }); }
    catch (e) { pushToast({ tone: "warning", title: (e as Error).message }); } finally { setSending(false); }
  };

  const content = edit ?? draft?.content ?? {};
  const setField = (k: string, v: unknown) => setEdit({ ...content, [k]: v });
  const channels = health?.channels || [];
  const chosen = channels.find((c) => c.id === channel);
  const input = "w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-white/90 focus:border-white/20 focus:outline-none";

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <div className="flex rounded-lg bg-white/[0.05] p-0.5">
          {AUD.map((a) => <button key={a.key} onClick={() => setTab(a.key)} className={cn("rounded-md px-2.5 py-1 text-[11.5px] transition", tab === a.key ? "bg-white/[0.12] text-white" : "text-white/55 hover:text-white")}>{a.label}{drafts[a.key]?.edited_at && " ✎"}</button>)}
        </div>
        <span className="flex-1" />
        {Object.keys(drafts).length === 0
          ? <Button size="sm" variant="primary" disabled={gen || !health?.gemini_configured} onClick={() => generate(false)}>{gen ? "生成中（約 10 秒）…" : "✦ 生成三對象文案"}</Button>
          : <Button size="sm" disabled={gen || !health?.gemini_configured} onClick={() => generate(true)}>{gen ? "生成中…" : "↻ 重新生成"}</Button>}
      </div>
      <div className="mb-2 text-[11px] text-dim">{AUD.find((a) => a.key === tab)?.hint}</div>

      {!draft ? (
        <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 text-[12px] text-muted">
          {health?.gemini_configured ? "尚未生成文案。生成會呼叫一次 Gemini（三個對象一次產出），結果依案件快取。" : "Gemini API Key 未設定，無法生成文案；任務處理、完工照與基準照流程不受影響。"}
        </div>
      ) : (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px]">
            <Badge tone={draft.grounding_ok ? "success" : "warning"}>{draft.grounding_ok ? "✓ 防幻覺查核通過" : "⚠ 查核有問題"}</Badge>
            <span className="text-dim">{draft.model === "manual" ? "人工撰寫" : `模型 ${draft.model || "—"} · 生成 ${fmt(draft.generated_at)}`}{draft.edited_at && ` · 人工修改 ${fmt(draft.edited_at)}`}</span>
          </div>
          {!draft.grounding_ok && draft.grounding_notes.length > 0 && <div className="mb-2 rounded-lg border border-amber-400/20 bg-amber-400/[0.06] p-2.5 text-[12px] text-amber-100">{draft.grounding_notes.join("；")}</div>}
          <div className="grid gap-2">
            {Object.entries(content).map(([k, v]) => (
              <label key={k} className="grid gap-1">
                <span className="label-xs">{FIELD_TXT[k] || k}</span>
                {Array.isArray(v) ? <textarea className={input} rows={2} value={(v as unknown[]).join("\n")} onChange={(e) => setField(k, e.target.value.split("\n").filter(Boolean))} />
                  : typeof v === "number" ? <input className={input} type="number" value={v} onChange={(e) => setField(k, Number(e.target.value))} />
                    : String(v).length > 40 ? <textarea className={input} rows={3} value={String(v ?? "")} onChange={(e) => setField(k, e.target.value)} />
                      : <input className={input} value={String(v ?? "")} onChange={(e) => setField(k, e.target.value)} />}
              </label>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {edit && <><Button size="sm" variant="primary" onClick={save}>儲存修改</Button><Button size="sm" variant="ghost" onClick={() => setEdit(null)}>取消</Button></>}
            <span className="flex-1" />
            <select className={cn(input, "w-auto")} value={channel} onChange={(e) => setChannel(e.target.value)}>
              {channels.map((c) => <option key={c.id} value={c.id}>{c.label}{!c.available ? "（未接入）" : !c.configured ? "（未設定）" : ""}</option>)}
            </select>
            <Button size="sm" variant="primary" disabled={sending || !!edit || !chosen?.available} onClick={send} title={chosen && !chosen.available ? chosen.note : edit ? "請先儲存修改" : ""}>{sending ? "發送中…" : "發送"}</Button>
          </div>
        </>
      )}

      {log.length > 0 && (
        <div className="mt-3 divide-y divide-white/[0.05] rounded-lg border border-white/[0.06] text-[11.5px]">
          {log.map((l) => (
            <div key={l.id} className="flex items-center gap-2 px-2.5 py-1.5">
              <span className="font-mono text-white/45">{fmt(l.at)}</span>
              <span className="text-white/70">{{ user: "用戶通知", cs: "客服摘要", worker: "派工單" }[l.audience || ""] || l.audience || "—"} · {l.channel}</span>
              <span className="flex-1" />
              <Badge tone={l.status === "sent" ? "success" : l.status === "failed" ? "danger" : "neutral"}>{{ sent: "已送出", failed: "失敗", unsupported: "未接入", skipped: "未設定" }[l.status] || l.status}</Badge>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
