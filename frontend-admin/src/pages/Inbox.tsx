import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { api } from '../lib/api'
import type { OpsEvent } from '../lib/types'
import { useStore } from '../lib/store'
import { EVENT_TXT, zhStatus } from '../lib/labels'
import { rel, syncClock } from '../lib/time'
import { PriorityBadge } from '../components/Badges'
import { useToast } from '../components/Toast'

type Filter = 'all' | 'P1' | 'P2' | 'P3' | 'unread' | 'failed' | 'overdue'

const ICO: Record<string, string> = {
  task_created: '🆕', task_status: '↦', task_assigned: '👤', notify_sent: '🔔', notify_failed: '⚠',
  notify_skipped: '·', sla_overdue: '⏰', note: '✎',
}

export function Inbox() {
  const { summary, tick, refresh } = useStore()
  const [events, setEvents] = useState<OpsEvent[]>([])
  const [filter, setFilter] = useState<Filter>('all')
  const [loaded, setLoaded] = useState(false)
  const nav = useNavigate()
  const loc = useLocation()
  const toast = useToast()

  const load = useCallback(async () => {
    try {
      const r = await api.events({ limit: 200 })
      syncClock(r.server_time); setEvents(r.events); setLoaded(true)
    } catch { /* store 會標示離線 */ }
  }, [])
  useEffect(() => { load() }, [load, tick])

  const shown = useMemo(() => events.filter(e => {
    if (filter === 'unread') return !e.is_read
    if (filter === 'failed') return e.type === 'notify_failed'
    if (filter === 'overdue') return e.type === 'sla_overdue'
    if (filter === 'all') return true
    return e.priority === filter
  }), [events, filter])

  const open = async (e: OpsEvent) => {
    if (!e.is_read) {
      setEvents(l => l.map(x => x.id === e.id ? { ...x, is_read: 1 } : x))   // 樂觀更新
      api.markRead([e.id]).then(refresh).catch(() => {})
    }
    if (e.task_id) nav(`/tasks/${e.task_id}`, { state: { background: loc } })
  }
  const readAll = async () => {
    setEvents(l => l.map(x => ({ ...x, is_read: 1 })))
    try { await api.markRead(null); refresh(); toast('已全部標為已讀') } catch { toast('操作失敗，請重試', 'warn') }
  }

  const count = (f: Filter) => f === 'all' ? events.length : f === 'unread' ? events.filter(e => !e.is_read).length
    : f === 'failed' ? events.filter(e => e.type === 'notify_failed').length
    : f === 'overdue' ? events.filter(e => e.type === 'sla_overdue').length
    : events.filter(e => e.priority === f).length

  return (
    <>
      <div className="topbar" style={{ position: 'static', background: 'transparent', backdropFilter: 'none', borderBottom: 0, paddingBottom: 0 }}>
        <div><h1>通知中心</h1><div className="sub">案件確認、通知結果、SLA 逾時——只列真實發生的事</div></div>
        <span className="spacer" />
        <button className="btn sm" onClick={readAll} disabled={!events.some(e => !e.is_read)}>全部標為已讀</button>
      </div>
      <div className="content">
        <div className="kpis">
          <button className={`kpi ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>
            <div className="micro">待處理任務</div><div className="num">{summary?.pending ?? '—'}</div><div className="sub">處理中 {summary?.in_progress ?? '—'} · 今日完成 {summary?.completed_today ?? '—'}</div>
          </button>
          <button className={`kpi ${filter === 'P1' ? 'active' : ''}`} onClick={() => setFilter('P1')}>
            <div className="micro">P1 未開工</div><div className={`num ${(summary?.p1_not_started || 0) > 0 ? 'warn' : ''}`}>{summary?.p1_not_started ?? '—'}</div><div className="sub">即時預警，SLA 5 分鐘</div>
          </button>
          <button className={`kpi ${filter === 'overdue' ? 'active' : ''}`} onClick={() => setFilter('overdue')}>
            <div className="micro">SLA 逾時</div><div className={`num ${(summary?.overdue || 0) > 0 ? 'warn' : ''}`}>{summary?.overdue ?? '—'}</div><div className="sub">待處理且超過開工期限</div>
          </button>
          <button className={`kpi ${filter === 'failed' ? 'active' : ''}`} onClick={() => setFilter('failed')}>
            <div className="micro">通知失敗</div><div className={`num ${(summary?.notify_failed || 0) > 0 ? 'warn' : ''}`}>{summary?.notify_failed ?? '—'}</div><div className="sub">可於任務詳情重發</div>
          </button>
        </div>

        <div className="chips">
          {(['all', 'unread', 'P1', 'P2', 'P3', 'failed', 'overdue'] as Filter[]).map(f => (
            <button key={f} className={`chip ${filter === f ? 'active' : ''}`} onClick={() => setFilter(f)}>
              {{ all: '全部', unread: '未讀', P1: 'P1', P2: 'P2', P3: 'P3', failed: '通知失敗', overdue: '逾時' }[f]}
              <span className="n">{count(f)}</span>
            </button>
          ))}
        </div>

        <div className="events">
          <AnimatePresence initial={false}>
            {shown.map(e => (
              <motion.button key={e.id} layout initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                className={`ev ${(e.priority || 'p3').toLowerCase()} ${e.is_read ? 'read' : ''}`} onClick={() => open(e)}>
                <span className="stripe" />
                <div style={{ minWidth: 0 }}>
                  <div className="t1">
                    {!e.is_read && <span className="dot" aria-label="未讀" />}
                    <span>{ICO[e.type] || '·'} {EVENT_TXT[e.type] || e.type}</span>
                    {e.car && <span className="plate">{e.car}</span>}
                    <PriorityBadge p={e.priority} />
                    {e.title && <span className="muted" style={{ fontWeight: 600 }}>{e.title}</span>}
                  </div>
                  <div className="t2">{zhStatus(e.detail || e.case_id || '')}</div>
                </div>
                <span className="when" title={e.at}>{rel(e.at)}</span>
              </motion.button>
            ))}
          </AnimatePresence>
          {loaded && shown.length === 0 && (
            <div className="empty card"><b>目前沒有事件</b>案件在監理台確認後，任務與通知結果會出現在這裡</div>
          )}
        </div>
      </div>
    </>
  )
}
