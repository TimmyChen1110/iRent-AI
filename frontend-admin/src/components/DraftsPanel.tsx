import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Audience, Draft, Drafts, NotificationLogEntry, Task } from '../lib/types'
import { useStore } from '../lib/store-context'
import { fmt } from '../lib/time'
import { useToast } from './toast-context'

const AUD: Array<{ key: Audience; label: string; hint: string }> = [
  { key: 'user', label: '用戶通知', hint: '中性、不歸咎、無術語與分數，附申訴管道' },
  { key: 'cs', label: '客服摘要', hint: '資訊密集：信心、覆蓋度、建議處置、爭議風險' },
  { key: 'worker', label: '派工單', hint: '工作指示：項目、工具、預估工時' },
]
const FIELD_TXT: Record<string, string> = {
  title: '標題', body: '內文', evidence_note: '判定依據', dispute_channel_note: '申訴管道',
  summary: '摘要', confidence_note: '信心說明', coverage_caveat: '覆蓋度提醒', recommended_action: '建議處置',
  dispute_risk: '爭議風險', dispute_risk_reason: '風險理由',
  type: '類型', priority: '優先', items: '工作項目', special_tools: '特殊工具／耗材', estimated_minutes: '預估工時（分）',
}

interface Props {
  task: Task
  drafts: Drafts
  log: NotificationLogEntry[]
  onChange: (d: Drafts) => void
  onSent: (detail: { notification_log: NotificationLogEntry[]; task: Task }) => void
}

export function DraftsPanel({ task, drafts, log, onChange, onSent }: Props) {
  const { health } = useStore()
  const toast = useToast()
  const [tab, setTab] = useState<Audience>('cs')
  const [gen, setGen] = useState(false)
  const [edit, setEdit] = useState<Record<string, unknown> | null>(null)
  const [channel, setChannel] = useState('webhook')
  const [sending, setSending] = useState(false)
  const draft: Draft | undefined = drafts[tab]
  useEffect(() => { const id = setTimeout(() => setEdit(null), 0); return () => clearTimeout(id) }, [tab, draft?.generated_at, draft?.edited_at])

  const generate = async (force: boolean) => {
    setGen(true)
    try {
      const r = await api.generateDrafts(task.case_id, force)
      onChange(r.drafts); toast(r.cached ? '已載入快取文案' : '文案已生成')
    } catch (e) { toast((e as Error).message, 'warn') } finally { setGen(false) }
  }
  const save = async () => {
    if (!edit) return
    try { const d = await api.putDraft(task.case_id, tab, edit); onChange({ ...drafts, [tab]: d }); setEdit(null); toast('文案已儲存') }
    catch (e) { toast((e as Error).message, 'warn') }
  }
  const send = async () => {
    setSending(true)
    try {
      const r = await api.sendDraft(task.id, tab, channel)
      onSent(r); toast(r.entry.detail || (r.ok ? '已送出' : '未送出'), r.ok ? 'ok' : 'warn')
    } catch (e) { toast((e as Error).message, 'warn') } finally { setSending(false) }
  }

  const content = edit ?? draft?.content ?? {}
  const setField = (k: string, v: unknown) => setEdit({ ...content, [k]: v })
  const channels = health?.channels || []
  const chosen = channels.find(c => c.id === channel)

  return (
    <>
      <div className="row wrap" style={{ marginBottom: 10 }}>
        <div className="tabs">
          {AUD.map(a => <button key={a.key} className={tab === a.key ? 'active' : ''} onClick={() => setTab(a.key)}>{a.label}{drafts[a.key]?.edited_at && ' ✎'}</button>)}
        </div>
        <span className="spacer" />
        {Object.keys(drafts).length === 0
          ? <button className="btn primary sm" disabled={gen || !health?.gemini_configured} onClick={() => generate(false)}>{gen ? '生成中（約 10 秒）…' : '✦ 生成三對象文案'}</button>
          : <button className="btn sm" disabled={gen || !health?.gemini_configured} onClick={() => generate(true)}>{gen ? '生成中…' : '↻ 重新生成'}</button>}
      </div>
      <div className="small faint" style={{ marginBottom: 8 }}>{AUD.find(a => a.key === tab)?.hint}</div>

      {!draft ? (
        <div className="notice">{health?.gemini_configured
          ? '尚未生成文案。生成會呼叫一次 Gemini（三個對象一次產出），結果依案件快取。'
          : 'Gemini API Key 未設定，因此無法生成文案；任務處理、完工照與 baseline 流程不受影響。'}</div>
      ) : (
        <>
          <div className="row wrap small" style={{ marginBottom: 8 }}>
            <span className={`badge ${draft.grounding_ok ? 'ok' : 'warn'}`}>{draft.grounding_ok ? '✓ 防幻覺查核通過' : '⚠ 查核有問題'}</span>
            <span className="faint">{draft.model === 'manual' ? '人工撰寫' : `模型 ${draft.model || '—'} · 生成 ${fmt(draft.generated_at)}`}{draft.edited_at && ` · 人工修改 ${fmt(draft.edited_at)}`}</span>
          </div>
          {!draft.grounding_ok && draft.grounding_notes.length > 0 && (
            <div className="notice warn" style={{ marginBottom: 8 }}>{draft.grounding_notes.join('；')}</div>
          )}
          <div style={{ display: 'grid', gap: 8 }}>
            {Object.entries(content).map(([k, v]) => (
              <label key={k} style={{ display: 'grid', gap: 3 }}>
                <span className="micro">{FIELD_TXT[k] || k}</span>
                {Array.isArray(v)
                  ? <textarea className="textarea" rows={2} value={(v as unknown[]).join('\n')} onChange={e => setField(k, e.target.value.split('\n').filter(Boolean))} />
                  : typeof v === 'number'
                    ? <input className="input" type="number" value={v} onChange={e => setField(k, Number(e.target.value))} />
                    : String(v).length > 40
                      ? <textarea className="textarea" rows={3} value={String(v ?? '')} onChange={e => setField(k, e.target.value)} />
                      : <input className="input" value={String(v ?? '')} onChange={e => setField(k, e.target.value)} />}
              </label>
            ))}
          </div>
          <div className="row wrap" style={{ marginTop: 10 }}>
            {edit && <><button className="btn sm primary" onClick={save}>儲存修改</button><button className="btn sm ghost" onClick={() => setEdit(null)}>取消</button></>}
            <span className="spacer" />
            <select className="select" value={channel} onChange={e => setChannel(e.target.value)}>
              {channels.map(c => <option key={c.id} value={c.id}>{c.label}{!c.available ? '（未接入）' : !c.configured ? '（未設定）' : ''}</option>)}
            </select>
            <button className="btn sm primary" disabled={sending || !!edit || !chosen?.available} onClick={send}
              title={chosen && !chosen.available ? chosen.note : edit ? '請先儲存修改' : ''}>{sending ? '發送中…' : '發送'}</button>
          </div>
        </>
      )}

      {log.length > 0 && (
        <table className="table" style={{ marginTop: 12 }}>
          <thead><tr><th>時間</th><th>操作人</th><th>對象</th><th>管道</th><th>結果</th></tr></thead>
          <tbody>{log.map(l => (
            <tr key={l.id}><td className="mono small">{fmt(l.at)}</td>
              <td>{l.actor_name ? <span className="badge soft">{l.actor_name} · {l.actor_role}</span> : <span className="faint">System / Legacy</span>}</td>
              <td>{{ user: '用戶通知', cs: '客服摘要', worker: '派工單' }[l.audience || ''] || l.audience || '—'}</td>
              <td>{l.channel}</td>
              <td><span className={`badge ${l.status === 'sent' ? 'ok' : l.status === 'failed' ? 'warn' : 'soft'}`}>{{ sent: '已送出', failed: '失敗', unsupported: '未接入', skipped: '未設定' }[l.status] || l.status}</span> <span className="small faint">{l.detail}</span></td></tr>
          ))}</tbody>
        </table>
      )}
    </>
  )
}
