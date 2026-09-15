import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { api } from '../lib/api'
import type { OpsEvent, Task } from '../lib/types'
import { useStore } from '../lib/store-context'
import { EVENT_TXT, zhStatus } from '../lib/labels'
import { rel, slaState, syncClock } from '../lib/time'
import { PriorityBadge, SlaChip, TypeBadge } from '../components/Badges'
import { useToast } from '../components/toast-context'

type Filter = 'action' | 'all' | 'P1' | 'P2' | 'P3' | 'unread' | 'failed' | 'approaching' | 'overdue'
const ACTION_TYPES = new Set(['task_created', 'notify_failed', 'sla_overdue'])

const ICO: Record<string, string> = {
  task_created: '🆕', task_status: '↦', task_assigned: '👤', notify_sent: '🔔', notify_failed: '⚠',
  notify_skipped: '·', sla_overdue: '⏰', note: '✎', fleet_lock: '🔒', fleet_unlock: '🔓',
}

export function Inbox() {
  const { summary, tick, refresh } = useStore()
  const [events, setEvents] = useState<OpsEvent[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [filter, setFilter] = useState<Filter>('action')
  const [loaded, setLoaded] = useState(false)
  const nav = useNavigate()
  const loc = useLocation()
  const toast = useToast()

  const load = useCallback(async () => {
    try {
      const [r, tr] = await Promise.all([api.events({ limit: 200 }), api.tasks()])
      syncClock(r.server_time); setEvents(r.events); setTasks(tr.tasks); setLoaded(true)
    } catch { /* store 會標示離線 */ }
  }, [])
  useEffect(() => { const id = setTimeout(load, 0); return () => clearTimeout(id) }, [load, tick])

  const shown = useMemo(() => events.filter(e => {
    if (filter === 'unread') return !e.is_read
    if (filter === 'failed') return e.type === 'notify_failed'
    if (filter === 'overdue') return e.type === 'sla_overdue'
    if (filter === 'approaching') return false
    if (filter === 'all') return true
    if (filter === 'action') return ACTION_TYPES.has(e.type)
    return e.priority === filter
  }), [events, filter])
  const approaching = useMemo(() => tasks.filter(t => slaState(t).kind === 'soon'), [tasks])

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

  const count = (f: Filter) => f === 'all' ? events.length : f === 'action' ? events.filter(e => ACTION_TYPES.has(e.type)).length : f === 'unread' ? events.filter(e => !e.is_read).length
    : f === 'failed' ? events.filter(e => e.type === 'notify_failed').length
    : f === 'approaching' ? approaching.length
    : f === 'overdue' ? events.filter(e => e.type === 'sla_overdue').length
    : events.filter(e => e.priority === f).length

  return (
    <>
      <div className="topbar" style={{ position: 'static', background: 'transparent', backdropFilter: 'none', borderBottom: 0, paddingBottom: 0 }}>
        <div><h1>通知中心</h1><div className="sub">預設只列需要行動的事：新任務、推播失敗、SLA 逾時；其餘在「全部」</div></div>
        <span className="spacer" />
        <button className="btn sm" onClick={readAll} disabled={!events.some(e => !e.is_read)}>全部標為已讀</button>
      </div>
      <div className="content">
        <div className="kpis">
          <button className={`kpi ${filter === 'action' ? 'active' : ''}`} onClick={() => setFilter('action')}>
            <div className="micro">待處理任務</div><div className="num">{summary?.pending ?? '—'}</div><div className="sub">處理中 {summary?.in_progress ?? '—'} · 今日完成 {summary?.completed_today ?? '—'}</div>
          </button>
          <button className={`kpi ${filter === 'P1' ? 'active' : ''}`} onClick={() => setFilter('P1')}>
            <div className="micro">P1 未開工</div><div className={`num ${(summary?.p1_not_started || 0) > 0 ? 'warn' : ''}`}>{summary?.p1_not_started ?? '—'}</div><div className="sub">即時預警，SLA 5 分鐘</div>
          </button>
          <button className={`kpi ${filter === 'overdue' ? 'active' : ''}`} onClick={() => setFilter('overdue')}>
            <div className="micro">SLA 逾時</div><div className={`num ${(summary?.overdue || 0) > 0 ? 'warn' : ''}`}>{summary?.overdue ?? '—'}</div><div className="sub">待處理且超過開工期限</div>
          </button>
          <button className={`kpi ${filter === 'approaching' ? 'active' : ''}`} onClick={() => setFilter('approaching')}>
            <div className="micro">SLA 即將到期</div><div className={`num ${approaching.length > 0 ? 'warn' : ''}`}>{approaching.length}</div><div className="sub">剩餘時間低於 SLA 的 20%</div>
          </button>
          <button className={`kpi ${filter === 'failed' ? 'active' : ''}`} onClick={() => setFilter('failed')}>
            <div className="micro">推播失敗</div><div className={`num ${(summary?.notify_failed || 0) > 0 ? 'warn' : ''}`}>{summary?.notify_failed ?? '—'}</div><div className="sub">可於任務詳情重發</div>
          </button>
        </div>

        <div className="chips">
          {(['action', 'all', 'unread', 'P1', 'P2', 'P3', 'failed', 'approaching', 'overdue'] as Filter[]).map(f => (
            <button key={f} className={`chip ${filter === f ? 'active' : ''}`} onClick={() => setFilter(f)}>
              {{ action: '需要行動', all: '全部', unread: '未讀', P1: 'P1', P2: 'P2', P3: 'P3', failed: '推播失敗', approaching: '即將逾時', overdue: '逾時' }[f]}
              <span className="n">{count(f)}</span>
            </button>
          ))}
        </div>

        {(filter === 'action' || filter === 'approaching') && approaching.length > 0 && (
          <div className="card" style={{ borderLeft: '4px solid var(--accent)' }}>
            <h2>SLA 即將到期 · 需安排開工</h2>
            <div className="events">
              {approaching.map(t => <button key={t.id} className="ev p2" onClick={() => nav(`/tasks/${t.id}`, { state: { background: loc } })}>
                <span className="stripe" /><div><div className="t1"><span>⏱ 即將逾時</span><span className="plate">{t.car}</span><PriorityBadge p={t.priority} /><TypeBadge t={t.task_type} /></div><div className="t2">{t.title} · {t.assignee_name || '尚未指派'}</div></div><SlaChip task={t} />
              </button>)}
            </div>
          </div>
        )}

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
          {loaded && shown.length === 0 && !(filter === 'approaching' && approaching.length > 0) && (
            <div className="empty card"><b>目前沒有事件</b>案件在監理台確認後，任務與通知結果會出現在這裡</div>
          )}
        </div>
      </div>
    </>
  )
}
