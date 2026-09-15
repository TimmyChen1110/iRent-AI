import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { api } from '../lib/api'
import type { Damage, TaskAction, TaskDetail as Detail, TaskEvent } from '../lib/types'
import { useStore } from '../lib/store-context'
import { fmt, syncClock } from '../lib/time'
import { STATUS_TXT, zhStatus } from '../lib/labels'
import { NotifyBadge, PriorityBadge, SlaChip, TypeBadge } from '../components/Badges'
import { PhotoWithBoxes } from '../components/PhotoWithBoxes'
import { useToast } from '../components/toast-context'
import { DraftsPanel } from '../components/DraftsPanel'

const ACTION_VIEW: Array<{ action: TaskAction; label: string; cls: string }> = [
  { action: 'start', label: '▶ 開始處理', cls: 'primary' },
  { action: 'complete', label: '✓ 標記完成', cls: 'primary' },
  { action: 'reopen', label: '重新開啟', cls: '' },
]

const DECISION_TXT: Record<string, string> = { confirm: '確認異常並建立任務', reject: '駁回 AI 判定', retake: '要求補件' }

function timelineView(e: TaskEvent) {
  const detail = e.detail || ''
  if (e.event === 'created') return { icon: '①', label: 'Task Created', cls: 'brand' }
  if (e.event === 'reopened') return { icon: '↻', label: 'Task Reopened', cls: 'brand' }
  if (e.event === 'assignee') return { icon: '②', label: detail.includes('自動') ? 'Auto Assigned' : 'Assigned / Claimed', cls: 'brand' }
  if (e.event === 'photo') return { icon: '④', label: 'Photo Uploaded', cls: 'brand' }
  if (e.event === 'note') return { icon: '✎', label: 'Note Added', cls: '' }
  if (e.event === 'notify') return { icon: '🔔', label: 'Notification', cls: detail.includes('已送出') ? 'ok' : detail.includes('未設定') ? '' : 'warn' }
  if (detail.includes('→ in_progress')) return { icon: '③', label: 'Started', cls: 'brand' }
  if (detail.includes('→ completed')) return { icon: '⑤', label: 'Completed', cls: 'ok' }
  if (detail.includes('→ pending')) return { icon: '↩', label: 'Returned to Pending', cls: '' }
  if (detail.includes('→ cancelled')) return { icon: '×', label: 'Cancelled', cls: 'warn' }
  return { icon: '·', label: 'Task Updated', cls: '' }
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
  const toast = useToast()

  const load = useCallback(async () => {
    try { const r = await api.task(tid); syncClock(r.server_time); setD(r); setErr(null) }
    catch (e) { setErr((e as Error).message) }
  }, [tid])
  const close = useCallback(() => (mode === 'sheet' ? nav(-1) : nav('/board')), [mode, nav])
  useEffect(() => { const id = setTimeout(load, 0); return () => clearTimeout(id) }, [load, tick])
  useEffect(() => {
    if (mode !== 'sheet') return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  }, [mode, close])

  const act = async (fn: () => Promise<Detail>, okMsg?: string) => {
    setBusy(true)
    try { const r = await fn(); setD(r); refresh(); if (okMsg) toast(okMsg) }
    catch (e) { toast((e as Error).message || '操作失敗', 'warn'); load() }
    finally { setBusy(false) }
  }
  const runAction = (action: TaskAction) => {
    if (!d) return
    const status = d.task.action_targets[action]
    if (!status) return
    setD({ ...d, task: { ...d.task, status } })   // 樂觀
    act(() => api.patchTask(tid, { action }))
  }
  const setAssignee = (value: string) => {
    if (!d) return
    const assigneeId = value ? Number(value) : null
    const person = people.find(p => p.id === assigneeId)
    setD({ ...d, task: { ...d.task, assignee_id: assigneeId, assignee_name: person?.name || null, assignee: person?.name || null } })
    act(() => api.patchTask(tid, { action: 'assign', assignee_id: assigneeId }))
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
              <select className="select" value={d.task.assignee_id ?? (d.task.assignee_name ? 'legacy' : '')} disabled={busy || !d.task.allowed_actions.includes('assign')} onChange={e => setAssignee(e.target.value)}>
                <option value="">未指派</option>
                {people.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                {d.task.assignee_id == null && d.task.assignee_name && <option value="legacy" disabled>{d.task.assignee_name}（需重新指派）</option>}
              </select></div>
            <div><div className="k">任務類型</div><div className="v">{d.task.task_type === 'cleaning' ? '清潔' : '維修'}</div></div>
            <div><div className="k">目前狀態</div><div className="v">{STATUS_TXT[d.task.status]}</div></div>
            <div><div className="k">SLA</div><div className="v">{d.task.sla_minutes} 分鐘內開工</div></div>
            <div><div className="k">建立</div><div className="v mono">{fmt(d.task.created_at)}</div></div>
            <div><div className="k">開工期限</div><div className="v mono">{fmt(d.task.sla_due_at)}</div></div>
            <div><div className="k">完成</div><div className="v mono">{fmt(d.task.resolved_at)}</div></div>
          </div>
          <div className="row wrap" style={{ marginTop: 14 }}>
            {ACTION_VIEW.filter(x => d.task.allowed_actions.includes(x.action)).map(x =>
              <button key={x.action} className={`btn ${x.cls}`} disabled={busy} onClick={() => runAction(x.action)}>{x.label}</button>)}
            {d.task.allowed_actions.includes('return_to_pending') && <button className="btn sm ghost" disabled={busy} onClick={() => runAction('return_to_pending')}>退回待處理</button>}
            {!d.task.completion_requirements.satisfied && <span className="small muted">{d.task.completion_requirements.message}</span>}
            <span className="spacer" />
            <NotifyBadge s={d.task.notification_status} />
            {d.task.notification_status === 'failed' && <button className="btn sm" disabled={busy} onClick={retry}>重新發送</button>}
          </div>
        </div>

        {/* 證據 */}
        <div className="section">
          <h3>證據 · AI 判定</h3>
          <div className="decision-strip">
            <div><span className="micro">AI 判定</span><b>{d.case.mode === 'interior' ? String(d.case.assessment?.level || '無法確認') : d.case.assessment?.new_damage_found ? '發現新增車損' : '未發現新增車損'}</b><span className="small muted">{d.case.ai_level || '未分級'}{typeof d.case.ai_conf === 'number' ? ` · 信心 ${Math.round(d.case.ai_conf * 100)}%` : ''}</span></div>
            <span className="flow-arrow">→</span>
            <div><span className="micro">人工裁決</span><b>{d.case.decision ? (DECISION_TXT[d.case.decision.decision] || d.case.decision.decision) : '尚未裁決'}</b><span className="small muted">{d.case.decision ? fmt(d.case.decision.decided_at) : '等待人工複核'}</span></div>
          </div>
          <div className="photos">
            {d.case.mode === 'interior'
              ? <PhotoWithBoxes src={d.case.photos.photo} label="還車車內照（AI Evidence）" boxes={d.case.boxes} hot={hot} />
              : <>
                <PhotoWithBoxes src={d.case.photos.pickup} label="Before · 借車基準照" />
                <PhotoWithBoxes src={d.case.photos.return} label="After · 還車 AI Evidence" boxes={d.case.boxes} hot={hot} />
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
            <a className="btn xs ghost" href={`/#case=${encodeURIComponent(d.case.case_id)}`} target="_blank" rel="noreferrer">在監理台開啟此案件 ↗</a>
          </div>
        </div>

        {/* 任務內容（引用 AI 判定原文） */}
        <div className="section">
          <h3>工作內容</h3>
          <div className="desc">{d.task.description || '—'}</div>
        </div>

        {/* 通知：三對象文案（依案件快取）→ 編輯 → 發送（webhook 實發；其他管道標示未接入） */}
        <div className="section">
          <h3>通知</h3>
          <DraftsPanel task={d.task} drafts={d.drafts} log={d.notification_log}
            onChange={drafts => setD({ ...d, drafts })}
            onSent={r => { setD({ ...d, task: r.task, notification_log: r.notification_log }); refresh() }} />
        </div>

        {/* 完工照與 baseline feedback（由既有任務及照片資料推導，不新增 schema） */}
        <div className="section">
          <div className="row wrap" style={{ marginBottom: 10 }}><h3 style={{ margin: 0 }}>完工照 · Completion Evidence</h3><span className="spacer" />
            {d.task.status === 'completed' && d.photos.length > 0
              ? <span className="badge ok">✓ Baseline Available</span>
              : d.photos.length > 0 ? <span className="badge accent">完成任務後成為 Baseline</span>
                : <span className="badge soft">尚無完工照</span>}
          </div>
          {d.photos.length > 0 ? <>
            <div className="photos">
              {d.photos.map(p => <div key={p.id} className="photo"><img src={p.url} alt={p.filename} loading="lazy" /><span className="lbl">{p.by || '—'} · {fmt(p.at)}</span></div>)}
            </div>
            <div className="small faint" style={{ marginTop: 6 }}>{d.task.status === 'completed' ? '此照片已可由環節二作為下一次 AI 比對的借車 baseline。' : '照片已保存；任務完成後才會正式出現在 baseline API。'}</div>
          </> : <div className="notice">{d.task.completion_requirements.photo_required ? d.task.completion_requirements.message : '此類任務不強制完工照；仍可由站點手機版上傳，作為下一次借車 baseline。'}</div>}
        </div>

        {/* 歷程 */}
        <div className="section">
          <h3>處理歷程</h3>
          <div className="timeline">
            {d.task.events.map((e, i) => {
              const view = timelineView(e)
              return <div key={i} className="tl"><span className={`pt ${view.cls}`} /><div><div className="tl-title"><span>{view.icon}</span>{view.label}{e.actor_name && <span className="badge soft">{e.actor_name} · {e.actor_role}</span>}</div><div className="small muted">{zhStatus(e.detail || e.event)}</div><span className="when">{fmt(e.at)}</span></div></div>
            })}
            {d.task.status === 'completed' && d.photos.length > 0 && <div className="tl"><span className="pt ok" /><div><div className="tl-title"><span>⑥</span>Baseline Available <span className="badge soft">Derived</span></div><div className="small muted">完工任務的照片已可供下一次 AI 比對使用</div><span className="when">{fmt(d.task.resolved_at)}</span></div></div>}
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
