import { motion } from 'motion/react'
import type { Task } from '../lib/types'
import { NotifyBadge, PriorityBadge, SlaChip, TypeBadge } from './Badges'
import { initials } from '../lib/reader'
import { rel } from '../lib/time'

interface Props {
  task: Task
  onOpen: (t: Task) => void
  onAdvance?: (t: Task) => void
  onDragStart?: (t: Task) => void
  onDragEnd?: () => void
  dragging?: boolean
}

const NEXT: Record<string, { label: string; cls: string } | undefined> = {
  pending: { label: '▶ 開始處理', cls: 'primary' },
  in_progress: { label: '✓ 標記完成', cls: 'primary' },
}

export function TaskCard({ task: t, onOpen, onAdvance, onDragStart, onDragEnd, dragging }: Props) {
  const next = NEXT[t.status]
  return (
    <motion.div layout layoutId={`task-${t.id}`} transition={{ type: 'spring', stiffness: 420, damping: 32 }}
      className={`tcard ${(t.priority || 'p2').toLowerCase()} ${t.status === 'cancelled' ? 'cancelled' : ''} ${dragging ? 'dragging' : ''}`}
      draggable={!!onDragStart && (t.status === 'pending' || t.status === 'in_progress')}
      onDragStart={() => onDragStart?.(t)} onDragEnd={onDragEnd}
      onClick={() => onOpen(t)} role="button" tabIndex={0}
      onKeyDown={e => { if (e.key === 'Enter') onOpen(t) }}>
      <span className="stripe" />
      <div className="row wrap">
        <span className="plate">{t.car || '—'}</span>
        <TypeBadge t={t.task_type} />
        <PriorityBadge p={t.priority} />
        {t.is_demo && <span className="badge demo">DEMO</span>}
        <span className="spacer" />
        <SlaChip task={t} />
      </div>
      <div className="title">{t.title}</div>
      <div className="meta">
        <span className="row" style={{ gap: 5 }}>
          <span className={`avatar ${t.assignee ? '' : 'none'}`}>{initials(t.assignee)}</span>
          {t.assignee || '未指派'}
        </span>
        <span>建立 {rel(t.created_at)}</span>
        <NotifyBadge s={t.notification_status} />
      </div>
      {next && onAdvance && (
        <div className="actions" onClick={e => e.stopPropagation()}>
          <button className={`btn sm ${next.cls}`} onClick={() => onAdvance(t)}>{next.label}</button>
        </div>
      )}
    </motion.div>
  )
}
