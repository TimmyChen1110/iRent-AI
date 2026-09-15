import { useEffect, useState } from 'react'
import type { NotifyStatus, Priority, TaskType } from '../lib/types'
import { NOTIFY_TXT, TYPE_TXT } from '../lib/labels'
import { slaState } from '../lib/time'

export function PriorityBadge({ p }: { p: Priority | null }) {
  const v = p || 'P2'
  return <span className={`badge ${v.toLowerCase()}`}>{v}</span>
}
export function TypeBadge({ t }: { t: TaskType }) {
  return <span className={`badge ${t}`}>{TYPE_TXT[t] || t}</span>
}
export function NotifyBadge({ s }: { s: NotifyStatus }) {
  const cls = s === 'sent' ? 'ok' : s === 'failed' ? 'warn' : 'soft'
  const ico = s === 'sent' ? '🔔' : s === 'failed' ? '⚠' : '·'
  return <span className={`badge ${cls}`}>{ico} {NOTIFY_TXT[s] || s}</span>
}

/** SLA 倒數：每 15 秒自行重算，不用父層重繪。 */
export function SlaChip({ task }: { task: { status: string; sla_due_at: string; sla_minutes: number; sla_status: 'normal' | 'approaching' | 'overdue' | 'inactive'; resolved_at?: string | null } }) {
  const [, tick] = useState(0)
  useEffect(() => { const id = setInterval(() => tick(x => x + 1), 15000); return () => clearInterval(id) }, [])
  if (task.status === 'completed') return <span className="sla done">✓ 完成</span>
  if (task.status !== 'pending') return null
  const s = slaState(task)
  return <span className={`sla ${s.kind === 'over' ? 'over' : s.kind === 'soon' ? 'soon' : ''}`} title={`SLA ${task.sla_minutes} 分鐘內開工`}>
    {s.kind === 'over' ? '⏰ ' : '⏱ '}{s.label}
  </span>
}
