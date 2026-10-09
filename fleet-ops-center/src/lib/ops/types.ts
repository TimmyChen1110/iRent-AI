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
export interface DemoRental { rental_id: string; car: string; vehicle_model: string; status: string | null; analysis: string | null; case_ids: string[] }
export interface Health { server_time: string; demo_mode: boolean; gemini_configured: boolean; demo_cases: { damage: string; cleaning: string }; demo_rental?: DemoRental | null; demo_credentials: DemoCredential[]; channels: Channel[] }

/* ---------- Inspection History（/api/ops/inspections）：iOS App 租約檢查紀錄 ---------- */

export type RentalStatus = 'CREATED' | 'PICKUP_IN_PROGRESS' | 'PICKUP_COMPLETE' | 'RETURN_IN_PROGRESS' | 'RETURN_COMPLETE' | 'ANALYZING' | 'ANALYSIS_COMPLETE' | 'ANALYSIS_FAILED'
export type InspectionResult = 'ISSUES' | 'PASSED' | 'PENDING' | 'ANALYZING' | 'FAILED'
export type ComparisonResult = 'NEW_DAMAGE' | 'EXISTING_DAMAGE' | 'NO_NEW_DAMAGE' | 'UNCOMPARABLE' | 'NO_BASELINE' | 'CLEANING_REQUIRED' | 'CLEAN' | 'UNREADABLE' | 'DUPLICATE_PHOTO'
export interface InspectionCompleteness { required: string[]; received: string[]; missing: string[]; complete: boolean; exterior: { received: number; required: number }; interior: { received: number; required: number }; status: string | null; completed_at: string | null }
export interface InspectionIncidentRef { case_id: string; kind: 'damage' | 'cleaning'; view_angle: string; region: string | null; label: string | null; confidence: number | null; ai_level: Priority | null; review_status?: ReviewStatus; decision?: { decision: string; decided_at: string } | null; tasks?: CaseTaskRef[] }
export interface InspectionRow {
  rental_id: string; vehicle_id: string; plate: string; vehicle_model: string | null; status: RentalStatus
  pickup_at: string | null; return_at: string | null
  pickup: InspectionCompleteness; return: InspectionCompleteness
  result: InspectionResult; issue_count: number; incidents: InspectionIncidentRef[]
  analysis: { source: string | null; error: string | null; started_at: string | null; completed_at: string | null }
  source: 'mobile' | 'demo_seed'; demo: boolean; updated_at: string
}
export interface InspectionPhoto {
  photo_id: string; angle: string; angle_code: string; category: 'exterior' | 'interior'; captured_at: string; uploaded_at: string
  url: string | null; validation_mode: 'coreml' | 'demo' | 'seed'; source: string
  validation: { passed: boolean | null; plate_text: string | null; plate_confidence: number | null; view: string | null; view_confidence: number | null; model_versions: Record<string, string> }
}
export interface InspectionFinding { region?: string | null; label?: string | null; type?: string | null; severity?: string | null; confidence?: number | null; status?: string; reasoning?: string | null; description?: string | null }
export interface InspectionComparison {
  angle: string; angle_code: string; category: 'exterior' | 'interior'
  pickup_photo: InspectionPhoto | null; return_photo: InspectionPhoto | null
  result: ComparisonResult | null; findings: InspectionFinding[]; boxes: Box[]; summary: string | null; case_id: string | null
}
export interface InspectionDetail extends InspectionRow {
  baseline: { source: string; existing_damage: InspectionFinding[]; note?: string; photo_ids?: Record<string, string> } | null
  comparisons: InspectionComparison[]
  interior: { result: ComparisonResult; cleanliness: string | null; confidence: number | null; score: number | null; findings: InspectionFinding[]; summary: string | null } | null
  versions: Record<string, unknown>
  incidents: Array<InspectionIncidentRef & { rental_id: string; car: string; damage_type: string | null; severity: string | null; summary: string | null; findings: InspectionFinding[]; boxes: Box[]; pickup_photo_id: string | null; return_photo_id: string | null; created_at: string }>
}

export interface FleetRow {
  car: string; status: 'rented' | 'locked' | 'review' | 'available'; manual_lock: boolean
  lock_reason: string | null; lock_by: string | null; lock_at: string | null
  open_tasks: Array<{ id: number; task_type: TaskType; status: TaskStatus; priority: Priority | null; title: string; overdue: boolean }>
  completed_tasks: number; last_completed_at: string | null; baseline_count: number
  dataset_cases: number; claims: number; unreviewed_flags: number
  location: CarLocation | null
  /** iOS App 租約帶來的車型與最近租約（沒有租約的資料集車輛為 null） */
  model?: string | null
  last_rental?: { model: string | null; rental_id: string; status: string; pickup_at: string | null; return_at: string | null } | null
  mobile_cases?: number
  /** App 可租車輛才為 true；rentable 與 App 車輛清單同源（後端 rental_sessions.availability） */
  rental_fleet?: boolean
  rentable?: boolean
  rental_state?: { vehicle_id: string; vehicle_status: 'AVAILABLE' | 'RENTED' | 'MAINTENANCE'; session_id: string | null; session_state: string | null; visibility: string | null } | null
}
/** /api/ops/devtools/vehicles：App 可租車輛（demo_vehicles，內部視圖）。座標即 App 地圖顯示位置。 */
export interface DevVehicle {
  vehicle_id: string; plate: string; model: string
  location: { lat: number; lng: number; name: string | null }
  status: 'AVAILABLE' | 'RENTED' | 'MAINTENANCE' | 'PARKED'; rentable: boolean; db_status: string
  /** is_fixture：固定劇本車（車牌為劇本用，可讓給後台 Demo 車；讓出時 status=PARKED） */
  is_demo: boolean; admin_created: boolean; is_fixture: boolean; category: string; visibility: string
  active_session_id: string | null; active_session_state: string | null; hold_reason: string | null
  odometer_km: number; updated_at: string
}
export interface FleetResp { fleet: FleetRow[]; server_time: string; counts: Record<'rented' | 'locked' | 'review' | 'available' | 'rentable', number>; note: string }
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
  /** "vehicle"：可租車輛的實際儲存座標（App 地圖同一組）；未提供＝資料集車輛的站點指派 */
  source?: "vehicle"
}
export interface LocationResp { car: string; location: CarLocation | null; server_time: string }

export type ReviewStatus = 'unreviewed' | 'confirmed_open' | 'confirmed_done' | 'rejected' | 'retake' | 'normal'
export interface CaseDamage { location: string | null; type: string | null; severity: string | null; confidence: number | null; reasoning: string | null; region?: string | null }
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
  /** dataset（評測資料集）或 mobile_inspection（iOS App 租約檢查產生） */
  source?: 'dataset' | 'mobile_inspection'
  rental?: RentalRef | null
}
export interface RentalRef { rental_id: string; pickup_at: string | null; return_at: string | null; vehicle_model: string | null; analysis_source: string | null }
export interface CaseListResp { cases: OpsCase[]; server_time: string; demo_cases: string[] }
export interface CaseDetailResp { case: OpsCase | null; view: CaseView; server_time: string }
