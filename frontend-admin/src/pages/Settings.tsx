import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Channel } from '../lib/types'
import { useToast } from '../components/Toast'

export function Settings() {
  const [channels, setChannels] = useState<Channel[]>([])
  const [sla, setSla] = useState({ p1: '5', p2: '240', p3: '1440' })
  const [saving, setSaving] = useState(false)
  const toast = useToast()

  useEffect(() => {
    api.health().then(h => setChannels(h.channels)).catch(() => {})
    api.settings().then(r => setSla({ p1: r.settings.sla_minutes_p1, p2: r.settings.sla_minutes_p2, p3: r.settings.sla_minutes_p3 })).catch(() => {})
  }, [])

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
              </div>
            ))}
          </div>
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
