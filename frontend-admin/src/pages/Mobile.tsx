import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api } from '../lib/api'
import type { MyTask, TaskAction } from '../lib/types'
import { useStore } from '../lib/store-context'
import { rel, syncClock } from '../lib/time'
import { PriorityBadge, SlaChip, TypeBadge } from '../components/Badges'
import { useToast } from '../components/toast-context'
import { useAuth } from '../lib/auth'

/** 站點整備人員手機版：登入身分 → 我的任務 → 開工 → 拍完工照 → 完工。 */
export function Mobile() {
  const { conn, tick, refresh } = useStore()
  const { user, logout } = useAuth()
  const [tasks, setTasks] = useState<MyTask[]>([])
  const [busy, setBusy] = useState<number | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploadFor, setUploadFor] = useState<number | null>(null)
  const toast = useToast()

  const load = useCallback(async () => {
    try { const r = await api.myTasks(); syncClock(r.server_time); setTasks(r.tasks) } catch { /* offline */ }
  }, [])
  useEffect(() => { const id = setTimeout(load, 0); return () => clearTimeout(id) }, [load, tick])

  const runAction = async (t: MyTask, action: TaskAction) => {
    setBusy(t.id)
    const prev = tasks
    const target = t.action_targets[action]
    if (!target) { toast(t.completion_requirements.message || '目前不能執行這個操作', 'warn'); setBusy(null); return }
    setTasks(l => target === 'completed' ? l.filter(x => x.id !== t.id) : l.map(x => x.id === t.id ? { ...x, status: target } : x))
    try {
      await api.patchTask(t.id, { action }); refresh(); load()
      toast(action === 'claim' ? `✓ 已接下 ${t.car}` : action === 'complete' ? `✓ ${t.car} 完工` : `▶ ${t.car} 開工`)
    } catch (e) { setTasks(prev); toast((e as Error).message, 'warn') } finally { setBusy(null) }
  }
  const pickPhoto = (id: number) => { setUploadFor(id); fileRef.current?.click() }
  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; e.target.value = ''
    if (!f || uploadFor == null) return
    setBusy(uploadFor)
    try { const r = await api.uploadPhoto(uploadFor, f); setTasks(l => l.map(x => x.id === uploadFor ? { ...x, ...r.task, photos: r.photos } : x)); toast('完工照已上傳') }
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
        <button className="btn xs" onClick={logout}>登出</button>
      </div>

      <div className="card row" style={{ gap: 10 }}><span className="micro">登入身分</span><b>{user?.name}</b><span className="badge ok">Station Staff</span></div>

      <>
          <div className="small muted">{tasks.filter(t => t.mine).length} 件指派給我 · {tasks.filter(t => !t.mine).length} 件未指派可接</div>
          <AnimatePresence initial={false}>
            {tasks.map(t => {
              const canFinish = t.allowed_actions.includes('complete')
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
                    {t.mine && t.status === 'pending' && <span className="badge ok">已接單 · 待開工</span>}
                    <span className="spacer" /><SlaChip task={t} />
                  </div>
                  <div className="title" style={{ fontSize: 15 }}>{t.title}</div>
                  <div className="meta"><span>建立 {rel(t.created_at)}</span>{t.status === 'in_progress' && <span className="badge p2">處理中</span>}{t.photos.length > 0 && <span className="badge ok">📷 {t.photos.length}</span>}</div>
                  {expanded && <div className="desc" style={{ marginTop: 4 }}>{t.description}</div>}
                  {t.photos.length > 0 && expanded && (
                    <div className="row wrap" style={{ gap: 6 }}>{t.photos.map(p => <img key={p.id} src={p.url} alt="" style={{ width: 72, height: 54, objectFit: 'cover', borderRadius: 6 }} />)}</div>
                  )}
                  <div className="actions" style={{ marginTop: 6 }}>
                    {t.allowed_actions.includes('claim') && (
                      <button className="btn primary" style={{ flex: 1, padding: '12px 14px', fontSize: 16 }} disabled={busy === t.id} onClick={() => runAction(t, 'claim')}>我來接單</button>
                    )}
                    {t.allowed_actions.includes('start') && (
                      <button className="btn primary" style={{ flex: 1, padding: '12px 14px', fontSize: 16 }} disabled={busy === t.id} onClick={() => runAction(t, 'start')}>▶ 開工</button>
                    )}
                    {t.allowed_actions.includes('upload_photo') && (
                      <>
                        <button className="btn" style={{ flex: 1, padding: '12px 14px', fontSize: 16 }} disabled={busy === t.id} onClick={() => pickPhoto(t.id)}>📷 拍完工照</button>
                        <button className="btn primary" style={{ flex: 1, padding: '12px 14px', fontSize: 16 }} disabled={busy === t.id || !canFinish} title={canFinish ? '' : (t.completion_requirements.message || '')} onClick={() => runAction(t, 'complete')}>✓ 完工</button>
                      </>
                    )}
                  </div>
                  {t.allowed_actions.includes('upload_photo') && !canFinish && <div className="small faint">{t.completion_requirements.message}，照片會成為下次借車的基準照</div>}
                </motion.div>
              )
            })}
          </AnimatePresence>
          {tasks.length === 0 && <div className="empty card"><b>目前沒有任務</b>新任務會自動出現</div>}
      </>
      <div className="small faint" style={{ textAlign: 'center' }}>操作會以 {user?.name} 身分寫入任務歷程{user?.role === 'admin' && <> · <a href="/ops/inbox">管理者介面</a></>}</div>
    </div>
  )
}
