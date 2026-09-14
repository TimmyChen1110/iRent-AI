export type Priority = 'P1' | 'P2' | 'P3'
export type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled'
export type TaskType = 'repair' | 'cleaning'
export type NotifyStatus = 'not_sent' | 'sent' | 'failed' | 'skipped'

export interface TaskEvent { at: string; event: string; detail: string | null }

export interface Task {
  id: number
  case_id: string
  task_type: TaskType
  car: string | null
  title: string
  description: string | null
  priority: Priority | null
  assignee: string | null
  status: TaskStatus
  notification_status: NotifyStatus
  created_at: string
  updated_at: string
  resolved_at: string | null
  events: TaskEvent[]
  // ops_api 加上的欄位
  sla_minutes: number
  sla_due_at: string
  sla_remaining_s: number | null
  overdue: boolean
  is_demo?: boolean
}

export interface Damage {
  location?: string; type?: string; severity?: string; confidence?: number; reasoning?: string
}
export interface Box { box_2d: number[]; label: string; severity?: string; confidence?: number; description?: string }

export interface CaseView {
  case_id: string
  mode: 'pair' | 'interior' | 'chain' | null
  source: string | null
  ai_level: string | null
  ai_conf: number | null
  assessment: Record<string, unknown> | null
  boxes: Box[]
  photos: { pickup?: string | null; return?: string | null; photo?: string | null }
  decision: { decision: string; decided_at: string } | null
}

export type Audience = 'user' | 'cs' | 'worker'
export interface Draft {
  case_id: string; audience: Audience
  content: Record<string, unknown>
  grounding_ok: boolean; grounding_notes: string[]
  model: string | null; generated_at: string | null; edited_at: string | null
}
export type Drafts = Partial<Record<Audience, Draft>>
export interface NotificationLogEntry { id: number; audience: string | null; channel: string; status: string; detail: string | null; at: string }

export interface TaskDetail {
  task: Task
  case: CaseView
  drafts: Drafts
  notification_log: NotificationLogEntry[]
  server_time: string
}

export type EventType = 'task_created' | 'task_status' | 'task_assigned' | 'notify_sent' | 'notify_failed' | 'notify_skipped' | 'sla_overdue' | 'note' | 'fleet_lock' | 'fleet_unlock'
export interface OpsEvent {
  id: number; at: string; type: EventType; task_id: number | null; case_id: string | null
  priority: Priority | null; car: string | null; title: string | null; detail: string | null; is_read: 0 | 1
}

export interface Summary {
  server_time: string; pending: number; in_progress: number; completed_today: number
  p1_not_started: number; overdue: number; notify_failed: number; unread: number
}
export interface Person { id: number; group_name: string; name: string; active: 0 | 1; created_at: string }
export interface Channel { id: string; label: string; configured: boolean; available: boolean; note: string }
export interface Health { server_time: string; demo_mode: boolean; demo_cases: { damage: string; cleaning: string }; channels: Channel[] }

export interface FleetRow {
  car: string; status: 'locked' | 'review' | 'available'; manual_lock: boolean
  lock_reason: string | null; lock_by: string | null; lock_at: string | null
  open_tasks: Array<{ id: number; task_type: TaskType; status: TaskStatus; priority: Priority | null; title: string; overdue: boolean }>
  completed_tasks: number; last_completed_at: string | null
  dataset_cases: number; claims: number; unreviewed_flags: number
}
export interface FleetResp { fleet: FleetRow[]; server_time: string; counts: Record<'locked' | 'review' | 'available', number>; note: string }
export interface Insights {
  server_time: string
  uploads: { source: string; photos: number; orders: number; vehicles: number; dates: Record<string, number>; by_hour: number[]; interior_uploaded_orders: number; note: string } | null
  tasks: { total: number; by_type: Record<string, Record<string, number>>; median_minutes_to_start: number | null; median_minutes_to_complete: number | null; n_started: number; n_completed: number }
  car_ranking: Array<{ car: string; repair: number; cleaning: number; claims: number }>
  interior: { 乾淨: number; 普通: number; 髒汙: number; n: number; excluded_unreadable: number }
}
