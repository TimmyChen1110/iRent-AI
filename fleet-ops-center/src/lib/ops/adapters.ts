/**
 * 後端資料 → 指揮中心 view model。
 * 車輛狀態只由後端事實推導：未完成任務 / 手動鎖定 → 暫停營運；AI 標記未裁決 → 車損／清潔警示；
 * 低信心 (P2) 未裁決 → 待人工審核；其餘 → 正常。
 */
import type { DamageHotspot, Evidence, Incident, Task as ViewTask, TimelineEvent, Vehicle, VehicleStatus } from "@/types";
import type { FleetRow, OpsCase, Task } from "./types";
import { HOTSPOT_POSITIONS, LOCATION_LABELS } from "@/data/vehicleGeometry";
import { damageSeverity, damageType, locateInteriorIssue, resolveRegion } from "./damageLocator";
import { fmt } from "./time";

export const PRIORITY_MAP = { P1: "high", P2: "medium", P3: "low" } as const;

export function caseKind(c: OpsCase): "damage" | "cleaning" {
  return c.mode === "interior" ? "cleaning" : "damage";
}

export function caseClassification(c: OpsCase): string {
  if (c.mode === "interior") return c.cleanliness === "髒汙" ? "車內髒污" : c.kind || "車內狀況";
  return c.kind || (c.ai_found ? "新增車損" : "車況正常");
}

export function caseLocationText(c: OpsCase): string {
  if (c.mode === "interior") return c.angle || "車內";
  return c.damages[0]?.location || c.angle || "—";
}

/** 案件 → 事件（只有 AI 標記 P1/P2 或已裁決的案件才是「事件」）。 */
export function toIncident(c: OpsCase): Incident | null {
  if (c.review_status === "normal") return null;
  const task = c.tasks.find((t) => t.status !== "cancelled") ?? c.tasks[0] ?? null;
  const status: Incident["status"] =
    c.review_status === "unreviewed" ? "open"
      : c.review_status === "rejected" ? "false-positive"
        : c.review_status === "retake" ? "manual-review"
          : "confirmed";
  return {
    id: c.case_id,
    shortId: c.case_id,
    vehicleId: c.car,
    plate: c.car,
    kind: caseKind(c),
    caseId: c.case_id,
    angle: c.angle,
    taskId: task?.id ?? null,
    reviewStatus: c.review_status,
    pricing: c.pricing,
    aiLevel: c.ai_level,
    classification: caseClassification(c),
    location: caseLocationText(c),
    confidence: c.ai_conf ?? 0,
    priority: PRIORITY_MAP[c.ai_level] ?? "medium",
    detectedAt: c.decision ? fmt(c.decision.decided_at).slice(11) : c.rental?.return_at ? `還車 ${fmt(c.rental.return_at).slice(11)}` : "AI 已判定",
    detectedDate: c.decision ? fmt(c.decision.decided_at).slice(0, 10) : c.rental?.return_at ? fmt(c.rental.return_at).slice(0, 10) : "待裁決",
    source: c.source ?? "dataset",
    rentalId: c.rental?.rental_id ?? null,
    status,
    hotspotId: hotspotIdFor(c, 0),
    summary: c.mode === "interior"
      ? (c.issues.length ? `AI 盤點問題：${c.issues.join("、")}` : "AI 判定車內髒污")
      : c.damages.map((d) => `${d.location || "—"}·${d.type || "—"}`).join("；") || "AI 標記疑似車損",
  };
}

function hotspotIdFor(c: OpsCase, i: number) {
  return `${c.case_id}#${i}`;
}

/** 案件 → 3D 標記（車外每個損傷一個；車內每個問題一個，最多三個）。 */
export function caseHotspots(c: OpsCase): DamageHotspot[] {
  if (c.mode === "interior") {
    if (c.cleanliness !== "髒汙" && c.review_status !== "confirmed_open") return [];
    const issues = c.issues.length ? c.issues.slice(0, 3) : ["車內髒污"];
    return issues.map((issue, i) => {
      const loc = locateInteriorIssue(issue, i);
      return {
        id: hotspotIdFor(c, i), kind: "cleaning", mode: "interior", location: loc, label: LOCATION_LABELS[loc],
        type: "debris", severity: damageSeverity(c.ai_level === "P1" ? "high" : "medium"), confidence: c.ai_conf ?? 0,
        position: HOTSPOT_POSITIONS[loc], title: issue, description: `AI 判定車內「${c.cleanliness || "—"}」${typeof c.score === "number" ? `，整潔分數 ${c.score}/100` : ""}。`,
        incidentId: c.case_id,
      };
    });
  }
  if (!c.ai_found && c.ai_level === "P3") return [];
  const list = c.damages.length ? c.damages : [{ location: null, type: null, severity: null, confidence: c.ai_conf, reasoning: null }];
  return list.map((d, i) => {
    const loc = resolveRegion(d.region, d.location, c.angle);
    return {
      id: hotspotIdFor(c, i), kind: "damage", mode: "exterior", location: loc, label: LOCATION_LABELS[loc],
      type: damageType(d.type), severity: damageSeverity(d.severity), confidence: d.confidence ?? c.ai_conf ?? 0,
      position: HOTSPOT_POSITIONS[loc], title: `${d.location || c.angle}${d.type ? ` · ${d.type}` : ""}`,
      description: d.reasoning || "AI 於還車照偵測到疑似新增損傷。", incidentId: c.case_id,
    };
  });
}

function boxToRegion(b?: { box_2d: number[] }) {
  if (!b) return undefined;
  const [y0, x0, y1, x1] = b.box_2d;
  return { x: x0 / 10, y: y0 / 10, w: (x1 - x0) / 10, h: (y1 - y0) / 10 };
}

export function toViewTask(t: Task): ViewTask {
  const status: ViewTask["status"] = t.status === "pending" ? "assigned" : t.status === "in_progress" ? "in-progress" : t.status === "completed" ? "completed" : "cancelled";
  return {
    id: `#${t.id}`,
    taskId: t.id,
    incidentId: t.case_id,
    vehicleId: t.car || "",
    plate: t.car || "—",
    type: t.task_type === "cleaning" ? "cleaning" : "maintenance",
    title: t.title,
    team: t.assignee_name || "未指派",
    priority: PRIORITY_MAP[t.priority || "P2"],
    status,
    createdAt: fmt(t.created_at),
    eta: t.sla_status === "inactive" ? undefined : fmt(t.sla_due_at),
    assigneeId: t.assignee_id,
    sla: { minutes: t.sla_minutes, dueAt: t.sla_due_at, status: t.sla_status, overdue: t.overdue },
    allowedActions: t.allowed_actions,
    completionMessage: t.completion_requirements.satisfied ? null : t.completion_requirements.message,
    notification: t.notification_status,
    isDemo: Boolean(t.is_demo),
    description: t.description,
  };
}

function deriveStatus(row: FleetRow | undefined, cases: OpsCase[], tasks: Task[]): VehicleStatus {
  if (row?.status === "rented") return "rented";   // 租用中（含還車流程尚未確認還車）優先於其他狀態
  const open = tasks.filter((t) => t.status === "pending" || t.status === "in_progress");
  if (open.length > 0 || row?.manual_lock) return "unavailable";
  const unreviewed = cases.filter((c) => c.review_status === "unreviewed");
  if (unreviewed.some((c) => c.ai_level === "P1" && c.mode === "pair")) return "damage";
  if (unreviewed.some((c) => c.ai_level === "P1" && c.mode === "interior")) return "cleaning";
  if (unreviewed.length > 0 || row?.status === "review") return "pending-review";
  if (tasks.some((t) => t.status === "completed") && cases.some((c) => c.review_status === "confirmed_done")) return "ready";
  return "healthy";
}

function timelineFor(cases: OpsCase[], tasks: Task[]): TimelineEvent[] {
  const ev: Array<TimelineEvent & { sort: string }> = [];
  // iOS App 租約：取車基準 → 使用者還車 → AI 比對（同一筆租約只放一次）
  const seenRental = new Set<string>();
  for (const c of cases) {
    const r = c.rental;
    if (!r || seenRental.has(r.rental_id)) continue;
    seenRental.add(r.rental_id);
    if (r.pickup_at) ev.push({ id: `pickup-${r.rental_id}`, sort: r.pickup_at, time: fmt(r.pickup_at).slice(11), title: "使用者取車 · 建立車況基準", detail: `${r.rental_id} · 4 外觀 + 1 車內（裝置端 Core ML 防呆）`, kind: "inspection" });
    if (r.return_at) ev.push({ id: `return-${r.rental_id}`, sort: r.return_at, time: fmt(r.return_at).slice(11), title: "使用者還車 · 完成還車拍攝", detail: `${r.rental_id} · 照片上傳後由後端非同步比對`, kind: "return" });
  }
  for (const c of cases) {
    if (c.review_status === "normal") continue;
    ev.push({ id: `ai-${c.case_id}`, sort: c.rental?.return_at ? `${c.rental.return_at}~` : "0000", time: c.rental?.return_at ? fmt(c.rental.return_at).slice(11) : "AI", title: c.mode === "interior" ? "AI 偵測到車內髒污" : "AI 偵測到疑似車損", detail: c.rental ? `${c.case_id} · 取車 vs 還車比對` : `${c.case_id}`, meta: c.ai_conf != null ? `${Math.round(c.ai_conf * 100)}%` : c.ai_level, kind: c.mode === "interior" ? "cleaning" : "damage" });
    if (c.decision) ev.push({ id: `dec-${c.case_id}`, sort: c.decision.decided_at, time: fmt(c.decision.decided_at).slice(11), title: c.decision.decision === "confirm" ? "營運人員確認異常" : c.decision.decision === "reject" ? "營運人員駁回 AI 判定" : "要求補件", detail: c.case_id, kind: c.decision.decision === "confirm" ? "resolved" : "waiting" });
  }
  for (const t of tasks) {
    for (const e of t.events) {
      const d = e.detail || "";
      const kind: TimelineEvent["kind"] = e.event === "created" ? "incident" : d.includes("→ completed") ? "resolved" : d.includes("→ in_progress") ? "task" : e.event === "assignee" ? "task" : e.event === "notify" ? "ai" : "task";
      const title = e.event === "created" ? `建立${t.task_type === "cleaning" ? "清潔" : "維修"}任務 #${t.id}` : e.event === "assignee" ? "指派負責人" : e.event === "photo" ? "上傳完工照" : e.event === "note" ? "備註" : e.event === "notify" ? "通知" : d.includes("→ completed") ? `${t.task_type === "cleaning" ? "清潔" : "維修"}完成` : d.includes("→ in_progress") ? "開始處理" : "任務更新";
      ev.push({ id: `t-${t.id}-${e.at}-${e.event}`, sort: e.at, time: fmt(e.at).slice(11), title, detail: (d || "").replace(/pending/g, "待處理").replace(/in_progress/g, "處理中").replace(/completed/g, "已完成").replace(/cancelled/g, "已取消").slice(0, 80), kind, meta: e.actor_name || undefined });
    }
  }
  ev.sort((a, b) => a.sort.localeCompare(b.sort));
  return ev.map(({ sort: _s, ...rest }) => rest); // eslint-disable-line @typescript-eslint/no-unused-vars
}

/** 一台車的完整 view model。cases / tasks 已依車牌過濾。 */
export function toVehicle(car: string, row: FleetRow | undefined, cases: OpsCase[], tasks: Task[]): Vehicle {
  const pair = cases.filter((c) => c.mode === "pair" && c.review_status !== "normal" && c.review_status !== "rejected");
  const interior = cases.filter((c) => c.mode === "interior" && c.review_status !== "normal" && c.review_status !== "rejected");
  const topPair = pair.find((c) => c.review_status === "unreviewed") ?? pair.find((c) => c.review_status === "confirmed_open") ?? pair[0];
  const topInterior = interior.find((c) => c.review_status === "unreviewed") ?? interior.find((c) => c.review_status === "confirmed_open") ?? interior[0];
  const evidenceCase = topPair ?? cases.find((c) => c.mode === "pair") ?? null;
  const loc = row?.location ?? cases[0]?.location ?? null;
  const open = tasks.filter((t) => t.status === "pending" || t.status === "in_progress");
  const status = deriveStatus(row, cases, tasks);
  const hotspots = [...(topPair ? caseHotspots(topPair) : []), ...(topInterior ? caseHotspots(topInterior) : [])];
  const d0 = topPair?.damages[0];
  const slaDue = open.map((t) => t.sla_due_at).sort()[0];
  const evidence: Evidence = {
    before: evidenceCase?.photos.pickup ?? null,
    after: evidenceCase?.photos.return ?? null,
    interior: topInterior?.photos.photo ?? undefined,
    diffRegion: boxToRegion(evidenceCase?.boxes[0]),
    boxes: evidenceCase?.boxes ?? [],
    summary: topPair ? `AI 於${topPair.angle}還車照偵測到${topPair.damages.map((d) => `${d.location || ""}${d.type || ""}`).join("、") || "疑似新增車損"}。` : "此車目前沒有 AI 標記的車外損傷。",
    interiorSummary: topInterior ? `AI 判定車內「${topInterior.cleanliness}」${topInterior.issues.length ? `：${topInterior.issues.join("、")}` : ""}。` : undefined,
    confidence: topPair?.ai_conf ?? topInterior?.ai_conf ?? 0,
  };
  const latestTask = [...tasks].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const caseRental = cases.find((c) => c.rental)?.rental ?? null;
  const rental = row?.last_rental ?? caseRental;
  const returnedAt = rental?.return_at ?? null;
  return {
    id: car,
    model: row?.model || caseRental?.vehicle_model || "共享車輛",
    plate: car,
    location: loc?.city || "—",
    station: loc?.station || "未指派站點",
    status,
    aiStatus: status === "rented" ? "租用中" : topPair && topPair.review_status === "unreviewed" ? "車損待裁決" : topInterior && topInterior.review_status === "unreviewed" ? "清潔待裁決" : open.length ? "整備中" : "正常",
    lastInspection: cases.length ? `${cases.length} 個 AI 案件` : "無案件",
    lastReturned: returnedAt
      ? { date: fmt(returnedAt).slice(0, 10), time: fmt(returnedAt).slice(11) }
      : { date: latestTask ? fmt(latestTask.created_at).slice(0, 10) : "—", time: latestTask ? fmt(latestTask.created_at).slice(11) : "" },
    rentalId: rental?.rental_id ?? null,
    manualLock: Boolean(row?.manual_lock),
    lockReason: row?.lock_reason ?? null,
    rentable: Boolean(row?.rentable),
    lngLat: loc ? [loc.lng, loc.lat] : null,
    exactLocation: loc?.source === "vehicle",
    city: loc?.city ?? null,
    district: loc?.district ?? null,
    stationId: loc?.station_id ?? null,
    caseIds: cases.filter((c) => c.review_status !== "normal").map((c) => c.case_id),
    openTaskIds: open.map((t) => t.id),
    exterior: topPair
      ? { result: topPair.review_status === "rejected" ? "AI 誤判（已駁回）" : topPair.kind || "疑似新增車損", location: d0?.location || topPair.angle, type: d0?.type || undefined, confidence: topPair.ai_conf ?? 0, severity: damageSeverity(d0?.severity), flagged: topPair.review_status === "unreviewed" || topPair.review_status === "confirmed_open" }
      : { result: "無新增車損", confidence: 0.97, flagged: false },
    interior: topInterior
      ? { cleanliness: topInterior.cleanliness === "髒汙" ? "Dirty" : topInterior.cleanliness === "普通" ? "Acceptable" : "Clean", confidence: topInterior.ai_conf ?? 0, detected: topInterior.issues, recommendation: topInterior.cleanliness === "髒汙" ? "需安排清潔" : "無需處理", flagged: topInterior.review_status === "unreviewed" || topInterior.review_status === "confirmed_open" }
      : { cleanliness: "Clean", confidence: 0.95, detected: [], recommendation: "無需處理", flagged: false },
    hotspots,
    timeline: timelineFor(cases, tasks),
    evidence,
    lifecycle: open.length ? "suspended" : status === "ready" ? "ready" : "available",
    estimatedReady: slaDue ? fmt(slaDue) : undefined,
    baselineCount: row?.baseline_count ?? 0,
    completedTasks: row?.completed_tasks ?? 0,
  };
}
