import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { Task, TaskAction, TaskStatus } from '../lib/types'
import { useStore } from '../lib/store-context'
import { syncClock } from '../lib/time'
import { TaskCard } from '../components/TaskCard'
import { useToast } from '../components/toast-context'

const COLS: Array<{ key: 'pending' | 'in_progress' | 'completed'; label: string; color: string }> = [
  { key: 'pending', label: '待處理', color: 'var(--p1)' },
  { key: 'in_progress', label: '處理中', color: 'var(--p2)' },
  { key: 'completed', label: '已完成', color: 'var(--ok)' },
]
export function Board() {
  const { tick, refresh } = useStore()
  const [tasks, setTasks] = useState<Task[]>([])
  const [ftype, setFtype] = useState<'all' | 'repair' | 'cleaning'>('all')
  const [fassignee, setFassignee] = useState('')
  const [onlyOverdue, setOnlyOverdue] = useState(false)
  const [showAllDone, setShowAllDone] = useState(false)
  const [drag, setDrag] = useState<Task | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const nav = useNavigate(); const loc = useLocation(); const toast = useToast()

  const load = useCallback(async () => {
    try { const r = await api.tasks(); syncClock(r.server_time); setTasks(r.tasks) } catch { /* offline */ }
  }, [])
  useEffect(() => { const id = setTimeout(load, 0); return () => clearTimeout(id) }, [load, tick])

  const today = new Date().toISOString().slice(0, 10)
  const grouped = useMemo(() => {
    const g: Record<string, Task[]> = { pending: [], in_progress: [], completed: [] }
    for (const t of tasks) {
      if (ftype !== 'all' && t.task_type !== ftype) continue
      if (fassignee && t.assignee_id !== Number(fassignee)) continue
      if (onlyOverdue && !t.overdue) continue
      const col = t.status === 'cancelled' ? 'completed' : t.status
      if (col === 'completed' && !showAllDone && !(t.resolved_at || t.updated_at || '').startsWith(today)) continue
      g[col].push(t)
    }
    const rank = (t: Task) => (t.is_demo ? 0 : 1) * 100 + ({ P1: 0, P2: 1, P3: 2 }[t.priority || 'P2'] ?? 1) * 10 + (t.overdue ? 0 : 1)
    for (const k of Object.keys(g)) g[k].sort((a, b) => rank(a) - rank(b) || b.created_at.localeCompare(a.created_at))
    return g
  }, [tasks, ftype, fassignee, onlyOverdue, showAllDone, today])

  const runAction = async (t: Task, action: TaskAction) => {
    const status = t.action_targets[action]
    if (!status) { toast(t.completion_requirements.message || '目前不能執行這個操作', 'warn'); return }
    const prev = tasks
    setTasks(l => l.map(x => x.id === t.id ? { ...x, status } : x))   // 樂觀更新：卡片立刻移欄
    try { await api.patchTask(t.id, { action }); refresh(); load() }
    catch (e) { setTasks(prev); toast((e as Error).message || '更新失敗，已還原', 'warn') }
  }
  const move = async (t: Task, status: TaskStatus) => {
    if (t.status === status) return
    const action = (Object.entries(t.action_targets) as Array<[TaskAction, TaskStatus]>).find(([, target]) => target === status)?.[0]
    if (!action) { toast(t.completion_requirements.message || '後端未允許這個狀態變更', 'warn'); return }
    await runAction(t, action)
  }

  const open = (t: Task) => nav(`/tasks/${t.id}`, { state: { background: loc } })
  const assignees = Array.from(new Map(tasks.filter(t => t.assignee_id != null)
    .map(t => [t.assignee_id as number, t.assignee_name || `#${t.assignee_id}`])).entries())

  return (
    <>
      <div className="topbar" style={{ position: 'static', background: 'transparent', backdropFilter: 'none', borderBottom: 0, paddingBottom: 0 }}>
        <div><h1>整備看板</h1><div className="sub">案件確認後自動開單 → 指派 → 處理 → 完成；拖曳卡片或按按鈕推進</div></div>
      </div>
      <div className="content">
        <div className="row wrap">
          <div className="chips">
            {(['all', 'repair', 'cleaning'] as const).map(k => (
              <button key={k} className={`chip ${ftype === k ? 'active' : ''}`} onClick={() => setFtype(k)}>{{ all: '全部', repair: '維修', cleaning: '清潔' }[k]}</button>
            ))}
            <button className={`chip ${onlyOverdue ? 'active' : ''}`} onClick={() => setOnlyOverdue(v => !v)}>只看逾時</button>
          </div>
          <select className="select" value={fassignee} onChange={e => setFassignee(e.target.value)}>
            <option value="">所有負責人</option>
            {assignees.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
          <span className="spacer" />
          <label className="small muted row"><input type="checkbox" checked={showAllDone} onChange={e => setShowAllDone(e.target.checked)} /> 顯示全部已完成</label>
        </div>

        <div className="kanban">
          {COLS.map(c => (
            <div key={c.key} className={`kcol ${over === c.key && drag ? 'over' : ''}`}
              onDragOver={e => { e.preventDefault(); setOver(c.key) }} onDragLeave={() => setOver(null)}
              onDrop={e => { e.preventDefault(); setOver(null); if (drag) move(drag, c.key); setDrag(null) }}>
              <div className="khead"><span className="kdot" style={{ background: c.color }} />{c.label}<span className="cnt">{grouped[c.key].length}</span>
                {c.key === 'completed' && !showAllDone && <span className="faint small" style={{ fontWeight: 500 }}>（今日）</span>}
              </div>
              {grouped[c.key].map(t => (
                <TaskCard key={t.id} task={t} onOpen={open} dragging={drag?.id === t.id}
                  onAdvance={(x, action) => runAction(x, action)}
                  onDragStart={setDrag} onDragEnd={() => { setDrag(null); setOver(null) }} />
              ))}
              {grouped[c.key].length === 0 && <div className="empty">目前沒有任務</div>}
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
