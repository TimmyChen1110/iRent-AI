export type Priority = 'P1' | 'P2' | 'P3'
export type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled'
export type TaskType = 'repair' | 'cleaning'
export type NotifyStatus = 'not_sent' | 'sent' | 'failed' | 'skipped'
export type TaskAction = 'claim' | 'assign' | 'start' | 'complete' | 'return_to_pending' | 'reopen' | 'cancel' | 'upload_photo'
export type Role = 'admin' | 'station'
export interface AuthUser { id: number; username: string; name: string; role: Role; person_id: number | null }

export interface TaskEvent { at: string; event: string; detail: string | null; actor_id: number | null; actor_name: string | null; actor_role: Role | 'system' | null }

export interface Task {
  id: number
  case_id: string
  task_type: TaskType
  car: string | null
  title: string
  description: string | null
  priority: Priority | null
  assignee_id: number | null
  assignee_name: string | null
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
  sla_status: 'normal' | 'approaching' | 'overdue' | 'inactive'
  allowed_actions: TaskAction[]
  action_targets: Partial<Record<TaskAction, TaskStatus>>
  completion_requirements: {
    photo_required: boolean
    photo_count: number
    satisfied: boolean
    message: string | null
  }
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
export interface NotificationLogEntry { id: number; audience: string | null; channel: string; status: string; detail: string | null; at: string; actor_id: number | null; actor_name: string | null; actor_role: Role | 'system' | null }

export interface TaskPhoto { id: number; task_id: number; case_id: string | null; car: string | null; filename: string; by: string | null; actor_id: number | null; actor_role: Role | 'system' | null; at: string; url: string }
export interface TaskDetail {
  task: Task
  case: CaseView
  drafts: Drafts
  notification_log: NotificationLogEntry[]
  photos: TaskPhoto[]
  server_time: string
}
export type MyTask = Task & { photos: TaskPhoto[]; mine: boolean }

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
export interface DemoCredential { username: string; password: string; label: string }
export interface Health { server_time: string; demo_mode: boolean; gemini_configured: boolean; demo_cases: { damage: string; cleaning: string }; demo_credentials: DemoCredential[]; channels: Channel[] }

export interface FleetRow {
  car: string; status: 'locked' | 'review' | 'available'; manual_lock: boolean
  lock_reason: string | null; lock_by: string | null; lock_at: string | null
  open_tasks: Array<{ id: number; task_type: TaskType; status: TaskStatus; priority: Priority | null; title: string; overdue: boolean }>
  completed_tasks: number; last_completed_at: string | null; baseline_count: number
  dataset_cases: number; claims: number; unreviewed_flags: number
  location: CarLocation | null
}
export interface FleetResp { fleet: FleetRow[]; server_time: string; counts: Record<'locked' | 'review' | 'available', number>; note: string }
export interface Insights {
  server_time: string
  uploads: { source: string; photos: number; orders: number; vehicles: number; dates: Record<string, number>; by_hour: number[]; interior_uploaded_orders: number; note: string } | null
  tasks: { total: number; by_type: Record<string, Record<string, number>>; median_minutes_to_start: number | null; median_minutes_to_complete: number | null; n_started: number; n_completed: number }
  car_ranking: Array<{ car: string; repair: number; cleaning: number; claims: number }>
  interior: { 乾淨: number; 普通: number; 髒汙: number; n: number; excluded_unreadable: number }
  agreement: { days: Array<{ day: string; n: number; agreed: number }>; n: number; agreed: number; rate: number | null }
}

/* ---------- 指揮中心新增（/api/ops/stations、/cases、/fleet/{car}/location） ---------- */

export interface Station { id: string; name: string; city: string; district: string; lng: number; lat: number; weight?: number }
export interface City { id: string; name: string; lng: number; lat: number }
export interface StationsResp { cities: City[]; stations: Station[]; server_time: string }
export interface CarLocation {
  station_id: string; station: string; district: string | null; city_id: string | null; city: string | null
  lng: number; lat: number; manual: boolean
}
export interface LocationResp { car: string; location: CarLocation | null; server_time: string }

export type ReviewStatus = 'unreviewed' | 'confirmed_open' | 'confirmed_done' | 'rejected' | 'retake' | 'normal'
export interface CaseDamage { location: string | null; type: string | null; severity: string | null; confidence: number | null; reasoning: string | null }
export interface CaseTaskRef { id: number; case_id: string; task_type: TaskType; status: TaskStatus; priority: Priority | null; assignee: string | null; created_at: string; resolved_at: string | null }
export interface OpsCase {
  case_id: string; car: string; angle: string; mode: 'pair' | 'interior'; kind: string | null
  ai_level: Priority; ai_conf: number | null; ai_found: boolean
  damages: CaseDamage[]; issues: string[]; cleanliness: string | null; score: number | null
  pricing: Record<string, unknown> | null
  photos: { pickup?: string | null; return?: string | null; photo?: string | null }
  truth: string | null
  boxes: Box[]
  decision: { decision: string; decided_at: string } | null
  tasks: CaseTaskRef[]
  location: CarLocation | null
  review_status: ReviewStatus
}
export interface CaseListResp { cases: OpsCase[]; server_time: string; demo_cases: string[] }
export interface CaseDetailResp { case: OpsCase | null; view: CaseView; server_time: string }
