import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { api } from '../lib/api'
import type { Damage, TaskDetail as Detail, TaskStatus } from '../lib/types'
import { useStore } from '../lib/store'
import { fmt, syncClock } from '../lib/time'
import { STATUS_TXT, zhStatus } from '../lib/labels'
import { NotifyBadge, PriorityBadge, SlaChip, TypeBadge } from '../components/Badges'
import { PhotoWithBoxes } from '../components/PhotoWithBoxes'
import { useToast } from '../components/Toast'

const NEXT: Record<string, { status: TaskStatus; label: string; cls: string } | undefined> = {
  pending: { status: 'in_progress', label: '▶ 開始處理', cls: 'primary' },
  in_progress: { status: 'completed', label: '✓ 標記完成', cls: 'primary' },
  completed: { status: 'in_progress', label: '重新開啟', cls: '' },
  cancelled: { status: 'pending', label: '重啟任務', cls: '' },
}

export function TaskDetail({ mode }: { mode: 'sheet' | 'page' }) {
  const { id } = useParams()
  const tid = Number(id)
  const nav = useNavigate()
  const { people, tick, refresh } = useStore()
  const [d, setD] = useState<Detail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [hot, setHot] = useState<number | null>(null)
  const [tab, setTab] = useState<'user' | 'cs' | 'worker'>('cs')
  const toast = useToast()

  const load = useCallback(async () => {
    try { const r = await api.task(tid); syncClock(r.server_time); setD(r); setErr(null) }
    catch (e) { setErr((e as Error).message) }
  }, [tid])
  useEffect(() => { load() }, [load, tick])
  useEffect(() => {
    if (mode !== 'sheet') return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  })

  const close = () => (mode === 'sheet' ? nav(-1) : nav('/board'))

  const act = async (fn: () => Promise<Detail>, okMsg?: string) => {
    setBusy(true)
    try { const r = await fn(); setD(r); refresh(); if (okMsg) toast(okMsg) }
    catch (e) { toast((e as Error).message || '操作失敗', 'warn'); load() }
    finally { setBusy(false) }
  }
  const setStatus = (status: TaskStatus) => {
    if (!d) return
    setD({ ...d, task: { ...d.task, status } })   // 樂觀
    act(() => api.patchTask(tid, { status }))
  }
  const setAssignee = (assignee: string) => {
    if (!d) return
    setD({ ...d, task: { ...d.task, assignee: assignee || null } })
    act(() => api.patchTask(tid, { assignee }))
  }
  const addNote = () => { if (!note.trim()) return; act(() => api.patchTask(tid, { note }), '備註已加入歷程'); setNote('') }
  const retry = () => act(() => api.retryNotify(tid))

  const body = (
    <div className="detail">
      {err && <div className="notice warn">{err}</div>}
      {d && <>
        {/* 摘要 */}
        <div className="section">
          <div className="row wrap" style={{ marginBottom: 10 }}>
            <span className="plate" style={{ fontSize: 20 }}>{d.task.car || '—'}</span>
            <TypeBadge t={d.task.task_type} /><PriorityBadge p={d.task.priority} />
            <span className={`badge ${d.task.status === 'completed' ? 'ok' : d.task.status === 'cancelled' ? 'soft' : d.task.status === 'in_progress' ? 'p2' : 'p1'}`}>{STATUS_TXT[d.task.status]}</span>
            {d.task.is_demo && <span className="badge demo">DEMO</span>}
            <span className="spacer" /><SlaChip task={d.task} />
          </div>
          <div style={{ fontWeight: 800, fontSize: 17, marginBottom: 10 }}>{d.task.title}</div>
          <div className="kv">
            <div><div className="k">負責人</div>
              <select className="select" value={d.task.assignee || ''} disabled={busy || d.task.status === 'completed' || d.task.status === 'cancelled'} onChange={e => setAssignee(e.target.value)}>
                <option value="">未指派</option>
                {people.map(p => <option key={p.id} value={p.name}>{p.name}</option>)}
                {d.task.assignee && !people.some(p => p.name === d.task.assignee) && <option value={d.task.assignee}>{d.task.assignee}</option>}
              </select></div>
            <div><div className="k">建立</div><div className="v mono">{fmt(d.task.created_at)}</div></div>
            <div><div className="k">開工期限</div><div className="v mono">{fmt(d.task.sla_due_at)}</div></div>
            <div><div className="k">完成</div><div className="v mono">{fmt(d.task.resolved_at)}</div></div>
          </div>
          <div className="row wrap" style={{ marginTop: 14 }}>
            {NEXT[d.task.status] && <button className={`btn ${NEXT[d.task.status]!.cls}`} disabled={busy} onClick={() => setStatus(NEXT[d.task.status]!.status)}>{NEXT[d.task.status]!.label}</button>}
            {d.task.status === 'in_progress' && <button className="btn sm ghost" disabled={busy} onClick={() => setStatus('pending')}>退回待處理</button>}
            <span className="spacer" />
            <NotifyBadge s={d.task.notification_status} />
            {d.task.notification_status === 'failed' && <button className="btn sm" disabled={busy} onClick={retry}>重新發送</button>}
          </div>
        </div>

        {/* 證據 */}
        <div className="section">
          <h3>證據 · AI 判定</h3>
          <div className="photos">
            {d.case.mode === 'interior'
              ? <PhotoWithBoxes src={d.case.photos.photo} label="還車車內照" boxes={d.case.boxes} hot={hot} />
              : <>
                <PhotoWithBoxes src={d.case.photos.pickup} label="借車照" />
                <PhotoWithBoxes src={d.case.photos.return} label="還車照" boxes={d.case.boxes} hot={hot} />
              </>}
          </div>
          <div style={{ marginTop: 10 }}>
            {d.case.boxes.length > 0 ? d.case.boxes.map((b, i) => (
              <div key={i} className="dmg" onMouseEnter={() => setHot(i)} onMouseLeave={() => setHot(null)}>
                <div className="l1"><span className="num">{i + 1}</span>{b.label}{b.severity && <span className={`badge ${b.severity === 'high' ? 'warn' : 'soft'}`}>{b.severity}</span>}
                  {typeof b.confidence === 'number' && <span className="mono small faint">信心 {b.confidence}</span>}</div>
                {b.description && <div className="muted">{b.description}</div>}
              </div>
            )) : ((d.case.assessment?.damages as Damage[] | undefined) || []).map((dm, i) => (
              <div key={i} className="dmg"><div className="l1"><span className="num">{i + 1}</span>{dm.location} {dm.type}{dm.severity && <span className="badge soft">{dm.severity}</span>}
                {typeof dm.confidence === 'number' && <span className="mono small faint">信心 {dm.confidence}</span>}</div>
                {dm.reasoning && <div className="muted">{dm.reasoning}</div>}</div>
            ))}
            {d.case.mode === 'interior' && d.case.assessment && (
              <div className="small muted" style={{ marginTop: 6 }}>
                整潔等級 <b>{String(d.case.assessment.level ?? '—')}</b>
                {typeof d.case.assessment.score === 'number' && <> · Cleanliness Score <b className="mono">{d.case.assessment.score}/100</b></>}
                {Array.isArray(d.case.assessment.issues) && d.case.assessment.issues.length > 0 && <> · 問題：{(d.case.assessment.issues as string[]).join('、')}</>}
              </div>
            )}
            {!d.case.mode && <div className="notice">找不到案件快照（案件可能已被移除），任務仍可處理。</div>}
          </div>
          <div className="row wrap" style={{ marginTop: 10 }}>
            <span className="small faint">案件 <span className="mono">{d.case.case_id}</span>{d.case.decision && <> · 人工裁決 {d.case.decision.decision} @ {fmt(d.case.decision.decided_at)}</>}</span>
            <span className="spacer" />
            <a className="btn xs ghost" href="/" target="_blank" rel="noreferrer">在監理台開啟 ↗</a>
          </div>
        </div>

        {/* 任務內容（引用 AI 判定原文） */}
        <div className="section">
          <h3>工作內容</h3>
          <div className="desc">{d.task.description || '—'}</div>
        </div>

        {/* 通知（Phase 2：三對象文案；目前只有 webhook 實發） */}
        <div className="section">
          <h3>通知</h3>
          <div className="tabs" style={{ marginBottom: 10 }}>
            {(['user', 'cs', 'worker'] as const).map(k => <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{{ user: '用戶通知', cs: '客服摘要', worker: '派工單' }[k]}</button>)}
          </div>
          {d.drafts[tab]
            ? <pre className="desc" style={{ margin: 0 }}>{JSON.stringify((d.drafts[tab] as { content: unknown }).content, null, 2)}</pre>
            : <div className="notice">三對象文案生成尚未接上 API（規劃 Phase 2）。目前實際發送的是任務建立 webhook，內容為任務欄位，見上方通知狀態。</div>}
          {d.notification_log.length > 0 && (
            <table className="table" style={{ marginTop: 10 }}>
              <thead><tr><th>時間</th><th>對象</th><th>管道</th><th>結果</th></tr></thead>
              <tbody>{d.notification_log.map(l => <tr key={l.id}><td className="mono small">{fmt(l.at)}</td><td>{l.audience || '—'}</td><td>{l.channel}</td><td>{l.status}</td></tr>)}</tbody>
            </table>
          )}
        </div>

        {/* 歷程 */}
        <div className="section">
          <h3>處理歷程</h3>
          <div className="timeline">
            {d.task.events.map((e, i) => {
              const cls = e.event === 'created' || e.event === 'reopened' ? 'brand' : e.event === 'notify' ? ((e.detail || '').includes('已送出') ? 'ok' : 'warn') : (e.detail || '').includes('completed') ? 'ok' : ''
              return <div key={i} className="tl"><span className={`pt ${cls}`} /><div><span className="when">{fmt(e.at)}</span> · {zhStatus(e.detail || e.event)}</div></div>
            })}
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <input className="input" placeholder="加入備註（寫進處理歷程）" value={note} onChange={e => setNote(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') addNote() }} />
            <button className="btn sm" disabled={busy || !note.trim()} onClick={addNote}>加入</button>
          </div>
        </div>
      </>}
    </div>
  )

  const header = (
    <div className="topbar">
      {mode === 'sheet' && <button className="btn sm" onClick={close} aria-label="關閉">✕</button>}
      <div><h1>任務 #{tid}</h1><div className="sub">{d ? `${d.task.car || ''} · ${d.task.title}` : '載入中…'}</div></div>
      <span className="spacer" />
      {mode === 'page' && <button className="btn sm" onClick={() => nav('/board')}>← 整備看板</button>}
    </div>
  )

  if (mode === 'page') return <>{header}{body}</>
  return (
    <AnimatePresence>
      <motion.div key="bd" className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={close} />
      <motion.aside key="sh" className="sheet" role="dialog" aria-modal="true"
        initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
        transition={{ type: 'spring', stiffness: 380, damping: 36 }}
        drag="x" dragConstraints={{ left: 0, right: 0 }} dragElastic={{ left: 0, right: .5 }}
        onDragEnd={(_, info) => { if (info.offset.x > 120 || info.velocity.x > 600) close() }}>
        {header}{body}
      </motion.aside>
    </AnimatePresence>
  )
}
