import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Channel } from '../lib/types'
import { useToast } from '../components/Toast'
import { useStore } from '../lib/store'

export function Settings() {
  const [channels, setChannels] = useState<Channel[]>([])
  const [sla, setSla] = useState({ p1: '5', p2: '240', p3: '1440' })
  const [rules, setRules] = useState({ require_photo_cleaning: '1', require_photo_repair: '0', escalate_on_overdue: '1', default_assignee_cleaning: '', default_assignee_repair: '' })
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [pre, setPre] = useState<Record<string, string>>({})
  const { health, people } = useStore()
  const toast = useToast()

  const testHook = async () => {
    setTesting(true)
    try { const r = await api.testWebhook(); toast(r.detail, r.ok ? 'ok' : 'warn') } catch (e) { toast((e as Error).message, 'warn') } finally { setTesting(false) }
  }
  const pregenerate = async (force: boolean) => {
    if (!health) return
    for (const [k, cid] of Object.entries(health.demo_cases)) {
      setPre(p => ({ ...p, [k]: '生成中…' }))
      try { const r = await api.generateDrafts(cid, force); setPre(p => ({ ...p, [k]: r.cached ? '已有快取' : '已生成' })) }
      catch (e) { setPre(p => ({ ...p, [k]: `失敗：${(e as Error).message}` })) }
    }
  }

  useEffect(() => {
    api.health().then(h => setChannels(h.channels)).catch(() => {})
    api.settings().then(r => { setSla({ p1: r.settings.sla_minutes_p1, p2: r.settings.sla_minutes_p2, p3: r.settings.sla_minutes_p3 }); setRules(x => ({ ...x, ...pick(r.settings) })) }).catch(() => {})
  }, [])

  const saveRules = async () => {
    try { const r = await api.putSettings(rules); setRules(x => ({ ...x, ...pick(r.settings) })); toast('規則已儲存') } catch (e) { toast((e as Error).message, 'warn') }
  }
  const save = async () => {
    setSaving(true)
    try {
      const r = await api.putSettings({ sla_minutes_p1: sla.p1, sla_minutes_p2: sla.p2, sla_minutes_p3: sla.p3 })
      setSla({ p1: r.settings.sla_minutes_p1, p2: r.settings.sla_minutes_p2, p3: r.settings.sla_minutes_p3 })
      toast('SLA 門檻已儲存')
    } catch (e) { toast((e as Error).message, 'warn') } finally { setSaving(false) }
  }

  return (
    <>
      <div className="topbar" style={{ position: 'static', background: 'transparent', backdropFilter: 'none', borderBottom: 0, paddingBottom: 0 }}>
        <div><h1>通知設定</h1><div className="sub">管道狀態只顯示是否設定，URL 與金鑰不會出現在前端</div></div>
      </div>
      <div className="content">
        <div className="card">
          <h2>通知管道</h2>
          <div className="kpis">
            {channels.map(c => (
              <div key={c.id} className="kpi" style={{ opacity: c.available ? 1 : .6 }}>
                <div className="row"><b>{c.label}</b><span className="spacer" />
                  <span className={`badge ${!c.available ? 'soft' : c.configured ? 'ok' : 'warn'}`}>{!c.available ? '未接入' : c.configured ? '已設定' : '未設定'}</span></div>
                <div className="sub" style={{ marginTop: 6 }}>{c.note}</div>
                {c.id === 'webhook' && !c.configured && <div className="sub">設定環境變數 NOTIFICATION_WEBHOOK_URL 後重啟 server</div>}
                {c.id === 'webhook' && c.configured && <button className="btn xs" style={{ marginTop: 8 }} disabled={testing} onClick={testHook}>{testing ? '發送中…' : '發送測試通知'}</button>}
              </div>
            ))}
          </div>
        </div>
        {health?.demo_mode && (
          <div className="card">
            <h2>Demo 預生成文案</h2>
            <div className="small muted" style={{ marginBottom: 8 }}>上台前先對兩個示範案例各呼叫一次 Gemini，現場任務詳情秒開；「重新生成」按鈕仍可現場即時展示。快取依案件保存，重置 Demo 不會清掉。</div>
            <div className="row wrap">
              <button className="btn primary sm" onClick={() => pregenerate(false)}>預生成（有快取則略過）</button>
              <button className="btn sm" onClick={() => pregenerate(true)}>全部重新生成</button>
              {Object.entries(pre).map(([k, v]) => <span key={k} className="badge soft">{k === 'damage' ? '車損' : '髒汙'}：{v}</span>)}
            </div>
          </div>
        )}
        <div className="card">
          <h2>整備規則</h2>
          <div style={{ display: 'grid', gap: 10 }}>
            <label className="row"><input type="checkbox" checked={rules.require_photo_cleaning === '1'} onChange={e => setRules(r => ({ ...r, require_photo_cleaning: e.target.checked ? '1' : '0' }))} /> 清潔任務完工前須至少一張完工照（監理台與手機版皆適用）</label>
            <label className="row"><input type="checkbox" checked={rules.require_photo_repair === '1'} onChange={e => setRules(r => ({ ...r, require_photo_repair: e.target.checked ? '1' : '0' }))} /> 維修任務完工前須至少一張完工照</label>
            <label className="row"><input type="checkbox" checked={rules.escalate_on_overdue === '1'} onChange={e => setRules(r => ({ ...r, escalate_on_overdue: e.target.checked ? '1' : '0' }))} /> SLA 逾時時自動再發一次 webhook 升級推播（kind=escalation）</label>
            <div className="row wrap" style={{ gap: 14 }}>
              <label className="row">清潔任務預設指派
                <select className="select" value={rules.default_assignee_cleaning} onChange={e => setRules(r => ({ ...r, default_assignee_cleaning: e.target.value }))}>
                  <option value="">不自動</option>{people.map(p => <option key={p.id} value={p.name}>{p.name}</option>)}</select></label>
              <label className="row">維修任務預設指派
                <select className="select" value={rules.default_assignee_repair} onChange={e => setRules(r => ({ ...r, default_assignee_repair: e.target.value }))}>
                  <option value="">不自動</option>{people.map(p => <option key={p.id} value={p.name}>{p.name}</option>)}</select></label>
            </div>
            <div><button className="btn primary" onClick={saveRules}>儲存規則</button></div>
          </div>
          <div className="small faint" style={{ marginTop: 8 }}>自動指派只在任務建立且從未被人指派過時執行一次；人工改過就不再覆蓋。</div>
        </div>
        <div className="card">
          <h2>SLA 門檻（待處理 → 開工，分鐘）</h2>
          <div className="row wrap">
            {(['p1', 'p2', 'p3'] as const).map(k => (
              <label key={k} className="row"><span className={`badge ${k}`}>{k.toUpperCase()}</span>
                <input className="input" style={{ width: 100 }} type="number" min={1} max={10080} value={sla[k]} onChange={e => setSla(s => ({ ...s, [k]: e.target.value }))} /></label>
            ))}
            <button className="btn primary" onClick={save} disabled={saving}>{saving ? '儲存中…' : '儲存'}</button>
          </div>
          <div className="small faint" style={{ marginTop: 8 }}>預設 P1 5 分、P2 4 小時、P3 當日（1440 分）。逾時任務會在通知中心產生「SLA 逾時」事件。</div>
        </div>
      </div>
    </>
  )
}

const pick = (s: Record<string, string>) => Object.fromEntries(Object.entries(s).filter(([k]) => k.startsWith('require_photo_') || k === 'escalate_on_overdue' || k.startsWith('default_assignee_')))
