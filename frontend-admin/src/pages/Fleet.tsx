import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { FleetResp, FleetRow, TaskPhoto } from '../lib/types'
import { useStore } from '../lib/store'
import { fmt, rel, syncClock } from '../lib/time'
import { PriorityBadge, TypeBadge } from '../components/Badges'
import { useToast } from '../components/Toast'

const ST: Record<FleetRow['status'], { label: string; cls: string }> = {
  locked: { label: '整備中・不可派', cls: 'warn' },
  review: { label: '待確認', cls: 'accent' },
  available: { label: '可派', cls: 'ok' },
}

export function Fleet() {
  const { tick, refresh } = useStore()
  const [data, setData] = useState<FleetResp | null>(null)
  const [q, setQ] = useState('')
  const [st, setSt] = useState<'' | FleetRow['status']>('')
  const [lockCar, setLockCar] = useState('')
  const [reason, setReason] = useState('')
  const [baseline, setBaseline] = useState<Record<string, TaskPhoto[]>>({})
  const nav = useNavigate(); const loc = useLocation(); const toast = useToast()

  const load = useCallback(async () => {
    try { const r = await api.fleet(); syncClock(r.server_time); setData(r) } catch { /* offline */ }
  }, [])
  useEffect(() => { load() }, [load, tick])

  const toggle = async (row: FleetRow) => {
    const locked = !row.manual_lock
    const why = locked ? (window.prompt('鎖定原因（選填）', '') ?? null) : ''
    if (locked && why === null) return
    try { const r = await api.lockCar(row.car, locked, why || undefined); setData(r); refresh(); toast(locked ? `已鎖定 ${row.car}` : `已解除 ${row.car}`) }
    catch (e) { toast((e as Error).message, 'warn') }
  }
  const addLock = async () => {
    if (!lockCar.trim()) return
    try { await api.lockCar(lockCar.trim().toUpperCase(), true, reason || undefined); setLockCar(''); setReason(''); load(); refresh(); toast('已鎖定') }
    catch (e) { toast((e as Error).message, 'warn') }
  }

  const showBaseline = async (car: string) => {
    if (baseline[car]) { setBaseline(b => { const n = { ...b }; delete n[car]; return n }); return }
    try { const r = await api.baseline(car); setBaseline(b => ({ ...b, [car]: r.photos })) } catch (e) { toast((e as Error).message, 'warn') }
  }
  const rows = (data?.fleet || []).filter(r => (!q || r.car.toUpperCase().includes(q.toUpperCase())) && (!st || r.status === st))

  return (
    <>
      <div className="topbar" style={{ position: 'static', background: 'transparent', backdropFilter: 'none', borderBottom: 0, paddingBottom: 0 }}>
        <div><h1>車輛派單狀態</h1><div className="sub">有未完成整備任務或手動鎖定的車不可派；完成後自動解除</div></div>
      </div>
      <div className="content">
        <div className="notice accent">模擬狀態：尚未與派單系統串接，此頁只反映整備任務與手動鎖定，不會真的擋單。</div>
        <div className="kpis">
          {(['locked', 'review', 'available'] as const).map(k => (
            <button key={k} className={`kpi ${st === k ? 'active' : ''}`} onClick={() => setSt(st === k ? '' : k)}>
              <div className="micro">{ST[k].label}</div>
              <div className={`num ${k === 'locked' && (data?.counts.locked || 0) > 0 ? 'warn' : ''}`}>{data?.counts[k] ?? '—'}</div>
              <div className="sub">{{ locked: '未完成任務或手動鎖定', review: 'AI 標記但尚未人工複核', available: '無待辦整備' }[k]}</div>
            </button>
          ))}
        </div>
        <div className="card">
          <div className="row wrap">
            <input className="input" style={{ width: 200 }} placeholder="搜尋車牌" value={q} onChange={e => setQ(e.target.value)} />
            <span className="spacer" />
            <input className="input" style={{ width: 140 }} placeholder="車牌" value={lockCar} onChange={e => setLockCar(e.target.value)} />
            <input className="input" style={{ width: 220 }} placeholder="鎖定原因（選填）" value={reason} onChange={e => setReason(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') addLock() }} />
            <button className="btn sm" onClick={addLock} disabled={!lockCar.trim()}>🔒 手動鎖定</button>
          </div>
        </div>
        <div className="card" style={{ overflowX: 'auto' }}>
          <table className="table">
            <thead><tr><th>車牌</th><th>狀態</th><th>未完成任務</th><th>資料集</th><th>最近完工</th><th /></tr></thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.car}>
                  <td className="plate">{r.car}</td>
                  <td>
                    <span className={`badge ${ST[r.status].cls}`}>{r.status === 'locked' ? '🔒 ' : ''}{ST[r.status].label}</span>
                    {r.manual_lock && <div className="small faint">手動鎖定{r.lock_reason ? `：${r.lock_reason}` : ''}{r.lock_by ? ` · ${r.lock_by}` : ''} · {rel(r.lock_at)}</div>}
                  </td>
                  <td>
                    {r.open_tasks.length === 0 ? <span className="faint">—</span> : r.open_tasks.map(t => (
                      <button key={t.id} className="row" style={{ gap: 6, padding: '2px 0' }} onClick={() => nav(`/tasks/${t.id}`, { state: { background: loc } })}>
                        <TypeBadge t={t.task_type} /><PriorityBadge p={t.priority} />
                        <span className="small">{t.title}</span>
                        {t.overdue && <span className="sla over">逾時</span>}
                      </button>
                    ))}
                  </td>
                  <td className="small muted">{r.dataset_cases > 0 ? <>{r.dataset_cases} 案{r.claims > 0 && <> · 索賠 {r.claims}</>}{r.unreviewed_flags > 0 && <> · <span style={{ color: '#7A5D00' }}>待複核 {r.unreviewed_flags}</span></>}</> : '—'}</td>
                  <td className="mono small">{r.last_completed_at ? fmt(r.last_completed_at) : '—'}{r.completed_tasks > 0 && <> <span className="faint">（{r.completed_tasks} 次）</span> <button className="btn xs ghost" onClick={() => showBaseline(r.car)}>基準照</button></>}
                    {baseline[r.car] && <div className="row wrap" style={{ gap: 4, marginTop: 4 }}>{baseline[r.car].length === 0 ? <span className="faint">無完工照</span> : baseline[r.car].map(p => <img key={p.id} src={p.url} alt="" style={{ width: 64, height: 48, objectFit: 'cover', borderRadius: 4 }} title={`${p.by || ''} ${fmt(p.at)}`} />)}</div>}</td>
                  <td style={{ textAlign: 'right' }}><button className="btn xs" onClick={() => toggle(r)}>{r.manual_lock ? '🔓 解除' : '🔒 鎖定'}</button></td>
                </tr>
              ))}
              {data && rows.length === 0 && <tr><td colSpan={6} className="empty">沒有符合的車輛</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
