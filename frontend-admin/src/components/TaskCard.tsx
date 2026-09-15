import { motion } from 'motion/react'
import type { Task, TaskAction } from '../lib/types'
import { NotifyBadge, PriorityBadge, SlaChip, TypeBadge } from './Badges'
import { initials } from '../lib/display'
import { rel } from '../lib/time'

interface Props {
  task: Task
  onOpen: (t: Task) => void
  onAdvance?: (t: Task, action: TaskAction) => void
  onDragStart?: (t: Task) => void
  onDragEnd?: () => void
  dragging?: boolean
}

const ACTION_VIEW: Partial<Record<TaskAction, { label: string; cls: string }>> = {
  start: { label: '▶ 開始處理', cls: 'primary' },
  complete: { label: '✓ 標記完成', cls: 'primary' },
}

export function TaskCard({ task: t, onOpen, onAdvance, onDragStart, onDragEnd, dragging }: Props) {
  const action = (['start', 'complete'] as TaskAction[]).find(a => t.allowed_actions.includes(a))
  const next = action ? ACTION_VIEW[action] : undefined
  const draggable = Object.values(t.action_targets).some(s => s === 'pending' || s === 'in_progress' || s === 'completed')
  return (
    <motion.div layout layoutId={`task-${t.id}`} transition={{ type: 'spring', stiffness: 420, damping: 32 }}
      className={`tcard ${(t.priority || 'p2').toLowerCase()} ${t.status === 'cancelled' ? 'cancelled' : ''} ${dragging ? 'dragging' : ''}`}
      draggable={!!onDragStart && draggable}
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
          <span className={`avatar ${t.assignee_id ? '' : 'none'}`}>{initials(t.assignee_name)}</span>
          {t.assignee_name || '未指派'}
        </span>
        <span>建立 {rel(t.created_at)}</span>
        <NotifyBadge s={t.notification_status} />
      </div>
      {!t.completion_requirements.satisfied && (
        <div className="small" style={{ color: 'var(--p1)' }}>📷 {t.completion_requirements.message}</div>
      )}
      {next && onAdvance && (
        <div className="actions" onClick={e => e.stopPropagation()}>
          <button className={`btn sm ${next.cls}`} onClick={() => onAdvance(t, action!)}>{next.label}</button>
        </div>
      )}
    </motion.div>
  )
}
