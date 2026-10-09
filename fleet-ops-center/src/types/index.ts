export type VehicleStatus =
  | "rented"
  | "healthy"
  | "damage"
  | "cleaning"
  | "maintenance"
  | "pending-review"
  | "unavailable"
  | "ready";

/** Where the vehicle is in the return → suspend → recover → available lifecycle. */
export type VehicleLifecycle = "returned" | "suspended" | "ready" | "available";

export type Severity = "low" | "medium" | "high";
export type Priority = "low" | "medium" | "high";

export type DamageType = "scratch" | "dent" | "crack" | "paint" | "stain" | "debris";

export type HotspotLocation =
  | "front-bumper"
  | "rear-bumper"
  | "hood"
  | "roof"
  | "left-front-door"
  | "right-front-door"
  | "left-rear-door"
  | "right-rear-door"
  | "left-front-fender"
  | "right-front-fender"
  | "left-rear-quarter"
  | "right-rear-quarter"
  | "windshield"
  | "interior"
  | "rear-seat"
  | "cup-holder"
  | "driver-seat";

export type TwinMode = "exterior" | "interior";

export type HotspotKind = "damage" | "cleaning";

export interface DamageHotspot {
  id: string;
  kind: HotspotKind;
  /** Which Digital Twin mode renders this hotspot. */
  mode: TwinMode;
  location: HotspotLocation;
  label: string;
  type: DamageType;
  severity: Severity;
  confidence: number;
  position: [number, number, number];
  title: string;
  description: string;
  incidentId?: string;
}

export interface ExteriorInspection {
  result: string;
  location?: string;
  type?: string;
  confidence: number;
  severity?: Severity;
  flagged: boolean;
}

export interface InteriorInspection {
  cleanliness: "Clean" | "Acceptable" | "Dirty";
  confidence: number;
  detected: string[];
  recommendation: string;
  flagged: boolean;
}

export type TimelineKind =
  | "return"
  | "inspection"
  | "damage"
  | "cleaning"
  | "incident"
  | "waiting"
  | "task"
  | "resolved"
  | "ai"
  | "suspended"
  | "available";

export interface TimelineEvent {
  id: string;
  time: string;
  title: string;
  detail?: string;
  kind: TimelineKind;
  meta?: string;
}

export interface DiffRegion {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Evidence {
  before: string | null;
  after: string | null;
  interior?: string;
  diffRegion?: DiffRegion;
  boxes: Array<{ box_2d: number[]; label: string; severity?: string; confidence?: number; description?: string }>;
  summary: string;
  confidence: number;
  interiorSummary?: string;
}

export interface Vehicle {
  id: string;
  model: string;
  plate: string;
  location: string;
  station: string;
  status: VehicleStatus;
  aiStatus: string;
  lastInspection: string;
  lastReturned: { date: string; time: string };
  manualLock: boolean;
  lockReason: string | null;
  /** 使用者現在租得到（與 App 車輛清單同一個判斷：非租用中、無未完成整備任務、未人工鎖定）。 */
  rentable: boolean;
  lngLat: [number, number] | null;
  /** true：lngLat 是車輛實際儲存座標（App 同一組），地圖不做同站散開偏移。 */
  exactLocation?: boolean;
  city: string | null;
  district: string | null;
  stationId: string | null;
  /** 待裁決／已確認的案件 id。 */
  caseIds: string[];
  openTaskIds: number[];
  exterior: ExteriorInspection;
  interior: InteriorInspection;
  hotspots: DamageHotspot[];
  timeline: TimelineEvent[];
  evidence: Evidence;
  lifecycle?: VehicleLifecycle;
  estimatedReady?: string;
  baselineCount: number;
  completedTasks: number;
  /** 最近一筆 iOS App 租約（檢查紀錄入口） */
  rentalId?: string | null;
}

export type IncidentKind = "damage" | "cleaning";
export type IncidentStatus = "open" | "confirmed" | "false-positive" | "manual-review";

export interface Incident {
  id: string;
  shortId: string;
  vehicleId: string;
  plate: string;
  kind: IncidentKind;
  caseId: string;
  angle: string;
  taskId: number | null;
  reviewStatus: "unreviewed" | "confirmed_open" | "confirmed_done" | "rejected" | "retake" | "normal";
  pricing: Record<string, unknown> | null;
  aiLevel: "P1" | "P2" | "P3";
  classification: string;
  location: string;
  confidence: number;
  priority: Priority;
  detectedAt: string;
  detectedDate: string;
  status: IncidentStatus;
  hotspotId?: string;
  summary: string;
  /** dataset（評測資料集）或 mobile_inspection（iOS App 租約檢查） */
  source?: "dataset" | "mobile_inspection";
  rentalId?: string | null;
}

export type TaskType = "inspection" | "cleaning" | "maintenance";
export type TaskStatus = "assigned" | "in-progress" | "scheduled" | "completed" | "cancelled";

export interface Task {
  id: string;
  /** 後端任務 id（數字）。 */
  taskId: number;
  incidentId?: string;
  vehicleId: string;
  plate: string;
  type: TaskType;
  title: string;
  team: string;
  priority: Priority;
  status: TaskStatus;
  createdAt: string;
  scheduledAt?: string;
  eta?: string;
  assigneeId: number | null;
  sla: { minutes: number; dueAt: string; status: "normal" | "approaching" | "overdue" | "inactive"; overdue: boolean };
  allowedActions: string[];
  completionMessage: string | null;
  notification: "not_sent" | "sent" | "failed" | "skipped";
  isDemo: boolean;
  description: string | null;
}

export interface TaskRecommendation {
  action: string;
  type: TaskType;
  priority: Priority;
  team: string;
  reason: string;
  alternativeTeams: string[];
}

export interface KPI {
  id: string;
  label: string;
  value: number;
  trend: number;
  trendLabel: string;
  tone: "neutral" | "positive" | "warning" | "danger" | "info";
}
