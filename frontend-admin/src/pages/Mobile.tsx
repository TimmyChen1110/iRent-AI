import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { api } from '../lib/api'
import type { MyTask, TaskStatus } from '../lib/types'
import { useStore } from '../lib/store'
import { rel, syncClock } from '../lib/time'
import { PriorityBadge, SlaChip, TypeBadge } from '../components/Badges'
import { useToast } from '../components/Toast'

/** 站點整備人員手機版：選身分 → 我的任務 → 開工 → 拍完工照 → 完工。大按鈕、單欄、不依賴側欄。 */
export function Mobile() {
  const { people, reader, setReader, conn, tick, refresh } = useStore()
  const [tasks, setTasks] = useState<MyTask[]>([])
  const [busy, setBusy] = useState<number | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploadFor, setUploadFor] = useState<number | null>(null)
  const toast = useToast()
  const [params] = useSearchParams()
  // QR 連結可帶 ?as=清潔組%20A 直接預選身分（站點貼 QR 用）
  useEffect(() => { const as = params.get('as'); if (as && !reader) setReader(as) }, [params, reader, setReader])

  const load = useCallback(async () => {
    if (!reader) return
    try { const r = await api.myTasks(); syncClock(r.server_time); setTasks(r.tasks) } catch { /* offline */ }
  }, [reader])
  useEffect(() => { load() }, [load, tick])

  const setStatus = async (t: MyTask, status: TaskStatus) => {
    setBusy(t.id)
    const prev = tasks
    setTasks(l => status === 'completed' ? l.filter(x => x.id !== t.id) : l.map(x => x.id === t.id ? { ...x, status } : x))
    try {
      if (status === 'in_progress' && !t.assignee) await api.patchTask(t.id, { assignee: reader, expected_assignee: '' })   // 防搶單：只有仍未指派才接
      await api.patchTask(t.id, { status }); refresh(); load()
      toast(status === 'completed' ? `✓ ${t.car} 完工` : `▶ ${t.car} 開工`)
    } catch (e) { setTasks(prev); toast((e as Error).message, 'warn') } finally { setBusy(null) }
  }
  const pickPhoto = (id: number) => { setUploadFor(id); fileRef.current?.click() }
  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; e.target.value = ''
    if (!f || uploadFor == null) return
    setBusy(uploadFor)
    try { const r = await api.uploadPhoto(uploadFor, f); setTasks(l => l.map(x => x.id === uploadFor ? { ...x, photos: r.photos } : x)); toast('完工照已上傳') }
    catch (err) { toast((err as Error).message, 'warn') } finally { setBusy(null) }
  }

  return (
    <div style={{ maxWidth: 560, margin: '0 auto', padding: '12px 16px 40px', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 12 }}>
      <input ref={fileRef} type="file" accept="image/*" capture="environment" hidden onChange={onFile} />
      <div className="row">
        <div className="brand" style={{ padding: 0 }}><div className="mark" style={{ background: 'var(--brand)' }}><span style={{ display: 'block', width: 10, height: 10, borderRadius: '50%', background: 'var(--accent)' }} /></div>
          <div><b style={{ fontSize: 16 }}>整備任務</b><small className="faint" style={{ display: 'block', fontSize: 11 }}>站點人員手機版</small></div></div>
        <span className="spacer" />
        <span className={`conn ${conn}`}><i />{conn === 'live' ? '即時' : conn === 'offline' ? '離線' : '同步'}</span>
      </div>

      <label className="card row" style={{ gap: 10 }}>
        <span className="micro">我是</span>
        <select className="select" style={{ flex: 1, minWidth: 0, width: '100%', fontSize: 16 }} value={reader} onChange={e => setReader(e.target.value)}>
          <option value="">請選擇組別</option>
          {people.map(p => <option key={p.id} value={p.name}>{p.name}</option>)}
        </select>
      </label>

      {!reader ? <div className="empty card"><b>先選擇你的組別</b>會列出指派給你與未指派的待處理任務</div> : (
        <>
          <div className="small muted">{tasks.filter(t => t.mine).length} 件指派給我 · {tasks.filter(t => !t.mine).length} 件未指派可接</div>
          <AnimatePresence initial={false}>
            {tasks.map(t => {
              const canFinish = t.status === 'in_progress' && t.photos.length > 0
              const expanded = open === t.id
              return (
                <motion.div key={t.id} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 60 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                  className={`tcard ${(t.priority || 'p2').toLowerCase()}`} style={{ cursor: 'default' }}>
                  <span className="stripe" />
                  <div className="row wrap" onClick={() => setOpen(expanded ? null : t.id)}>
                    <span className="plate" style={{ fontSize: 18 }}>{t.car}</span>
                    <TypeBadge t={t.task_type} /><PriorityBadge p={t.priority} />
                    {!t.mine && <span className="badge soft">未指派</span>}
                    <span className="spacer" /><SlaChip task={t} />
                  </div>
                  <div className="title" style={{ fontSize: 15 }}>{t.title}</div>
                  <div className="meta"><span>建立 {rel(t.created_at)}</span>{t.status === 'in_progress' && <span className="badge p2">處理中</span>}{t.photos.length > 0 && <span className="badge ok">📷 {t.photos.length}</span>}</div>
                  {expanded && <div className="desc" style={{ marginTop: 4 }}>{t.description}</div>}
                  {t.photos.length > 0 && expanded && (
                    <div className="row wrap" style={{ gap: 6 }}>{t.photos.map(p => <img key={p.id} src={p.url} alt="" style={{ width: 72, height: 54, objectFit: 'cover', borderRadius: 6 }} />)}</div>
                  )}
                  <div className="actions" style={{ marginTop: 6 }}>
                    {t.status === 'pending' && (
                      <button className="btn primary" style={{ flex: 1, padding: '12px 14px', fontSize: 16 }} disabled={busy === t.id} onClick={() => setStatus(t, 'in_progress')}>▶ {t.mine ? '開工' : '接單並開工'}</button>
                    )}
                    {t.status === 'in_progress' && (
                      <>
                        <button className="btn" style={{ flex: 1, padding: '12px 14px', fontSize: 16 }} disabled={busy === t.id} onClick={() => pickPhoto(t.id)}>📷 拍完工照</button>
                        <button className="btn primary" style={{ flex: 1, padding: '12px 14px', fontSize: 16 }} disabled={busy === t.id || !canFinish} title={canFinish ? '' : '完工前需至少一張完工照'} onClick={() => setStatus(t, 'completed')}>✓ 完工</button>
                      </>
                    )}
                  </div>
                  {t.status === 'in_progress' && !canFinish && <div className="small faint">完工前需上傳至少一張完工照，照片會成為下次借車的基準照</div>}
                </motion.div>
              )
            })}
          </AnimatePresence>
          {tasks.length === 0 && <div className="empty card"><b>目前沒有任務</b>新任務會自動出現</div>}
        </>
      )}
      <div className="small faint" style={{ textAlign: 'center' }}>身分為自選未驗證 · <a href="/ops/inbox">管理者介面</a></div>
    </div>
  )
}
